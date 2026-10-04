import { isProjectionEventMessage, isSessionProjection } from './http';
import type {
  FrontendError,
  ProjectionEventMessage,
  ResyncRequiredMessage,
  SessionSnapshotResponse,
  SnapshotMessage,
  WebSocketClientMessage,
  WebSocketServerMessage,
} from './types';
import type { ProjectionApplyResult, ProjectionStore } from '../state/store';

interface SocketMessageEvent {
  readonly data: unknown;
}

interface SocketCloseEvent {
  readonly code: number;
  readonly reason: string;
}

export interface WebSocketLike {
  readonly readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: SocketMessageEvent) => void) | null;
  onerror: (() => void) | null;
  onclose: ((event: SocketCloseEvent) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export type WebSocketFactory = (url: string) => WebSocketLike;

export interface ReconnectPolicy {
  readonly maxAttempts: number;
  readonly baseDelayMs: number;
  readonly maxDelayMs: number;
}

export interface ProjectionSocketOptions {
  readonly url: string;
  readonly sessionId: string;
  readonly store: ProjectionStore;
  readonly loadSnapshot: (snapshotUrl: string) => Promise<SessionSnapshotResponse>;
  readonly socketFactory?: WebSocketFactory;
  readonly reconnect?: Partial<ReconnectPolicy>;
  readonly schedule?: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout>;
  readonly cancelSchedule?: (handle: ReturnType<typeof setTimeout>) => void;
}

const DEFAULT_RECONNECT: ReconnectPolicy = {
  maxAttempts: 5,
  baseDelayMs: 500,
  maxDelayMs: 5_000,
};

const SOCKET_CONNECTING = 0;
const SOCKET_OPEN = 1;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function hasOnlyKeys(record: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedKeys = new Set(allowed);
  return Object.keys(record).every((key) => allowedKeys.has(key));
}

function isStringArray(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function isRecordArray(value: unknown): value is readonly Record<string, unknown>[] {
  return Array.isArray(value) && value.every(isRecord);
}

function isChangedProjection(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const allowed = [
    'intent',
    'operations',
    'effects',
    'evidence',
    'claims',
    'divergences',
    'plans',
    'speech',
    'metrics',
  ];
  if (!hasOnlyKeys(value, allowed)) return false;
  if ('intent' in value && value.intent !== null && !isRecord(value.intent)) return false;
  for (const key of allowed.slice(1, 8)) {
    if (key in value && !isRecordArray(value[key])) return false;
  }
  if ('metrics' in value && !isRecord(value.metrics)) return false;
  return true;
}

function isRemovedProjection(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const allowed = [
    'intent',
    'operations',
    'effects',
    'evidence',
    'claims',
    'divergences',
    'plans',
    'speech',
  ];
  return hasOnlyKeys(value, allowed) && Object.values(value).every(isStringArray);
}

function parseJson(value: unknown): unknown {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

export function parseWebSocketMessage(value: unknown): WebSocketServerMessage | null {
  const parsed = parseJson(value);
  if (!isRecord(parsed) || typeof parsed.type !== 'string') return null;

  if (parsed.type === 'snapshot') {
    if (
      !hasOnlyKeys(parsed, [
        'type',
        'schema_version',
        'session_id',
        'through_sequence',
        'projection',
      ]) ||
      parsed.schema_version !== 1 ||
      typeof parsed.session_id !== 'string' ||
      !isNonNegativeInteger(parsed.through_sequence) ||
      !isSessionProjection(parsed.projection) ||
      parsed.projection.metrics.through_sequence !== parsed.through_sequence
    ) {
      return null;
    }
    return parsed as unknown as SnapshotMessage;
  }

  if (parsed.type === 'event') {
    if (
      !hasOnlyKeys(parsed, [
        'type',
        'schema_version',
        'session_id',
        'sequence',
        'event_type',
        'projection_delta',
        'trace',
      ]) ||
      !isProjectionEventMessage(parsed) ||
      !isChangedProjection(parsed.projection_delta.changed) ||
      !isRemovedProjection(parsed.projection_delta.removed)
    ) {
      return null;
    }
    return parsed as unknown as ProjectionEventMessage;
  }

  if (parsed.type === 'resync_required') {
    if (
      !hasOnlyKeys(parsed, ['type', 'reason', 'snapshot_url']) ||
      parsed.reason !== 'GAP_OR_EXPIRED' ||
      typeof parsed.snapshot_url !== 'string'
    ) {
      return null;
    }
    return parsed as unknown as ResyncRequiredMessage;
  }

  if (parsed.type === 'error') {
    if (
      !hasOnlyKeys(parsed, ['type', 'code', 'recoverable']) ||
      typeof parsed.code !== 'string' ||
      typeof parsed.recoverable !== 'boolean'
    ) {
      return null;
    }
    return parsed as unknown as WebSocketServerMessage;
  }

  if (parsed.type === 'closing') {
    const common =
      typeof parsed.reason === 'string' && isNonNegativeInteger(parsed.through_sequence);
    const shutdown =
      common &&
      parsed.reason === 'SHUTDOWN' &&
      hasOnlyKeys(parsed, ['type', 'reason', 'through_sequence']);
    const sessionClosing =
      common &&
      parsed.schema_version === 1 &&
      typeof parsed.session_id === 'string' &&
      hasOnlyKeys(parsed, [
        'type',
        'schema_version',
        'session_id',
        'through_sequence',
        'reason',
      ]);
    return shutdown || sessionClosing ? (parsed as unknown as WebSocketServerMessage) : null;
  }

  return null;
}

function appendAfterSequence(url: string, sequence: number): string {
  const absolute = /^[a-z][a-z\d+.-]*:\/\//i.test(url);
  const parsed = new URL(url, 'ws://interlock.invalid');
  parsed.searchParams.set('after_sequence', String(sequence));
  return absolute ? parsed.toString() : `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

function connectionError(message: string, recoverable: boolean): FrontendError {
  return { kind: 'CONNECTION', message, recoverable, status: null };
}

function protocolError(message: string, recoverable: boolean): FrontendError {
  return { kind: 'PROTOCOL', message, recoverable, status: null };
}

export class ProjectionSocketClient {
  private readonly options: ProjectionSocketOptions;
  private readonly policy: ReconnectPolicy;
  private readonly factory: WebSocketFactory;
  private readonly scheduleValue: NonNullable<ProjectionSocketOptions['schedule']>;
  private readonly cancelScheduleValue: NonNullable<ProjectionSocketOptions['cancelSchedule']>;
  private socket: WebSocketLike | null = null;
  private reconnectHandle: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private manuallyClosed = false;
  private suppressReconnect = false;
  private resyncPromise: Promise<void> | null = null;

  constructor(options: ProjectionSocketOptions) {
    this.options = options;
    this.policy = { ...DEFAULT_RECONNECT, ...options.reconnect };
    if (
      !Number.isInteger(this.policy.maxAttempts) ||
      this.policy.maxAttempts < 0 ||
      this.policy.baseDelayMs < 0 ||
      this.policy.maxDelayMs < this.policy.baseDelayMs
    ) {
      throw new TypeError('Reconnect policy is invalid.');
    }
    this.factory =
      options.socketFactory ?? ((url) => new WebSocket(url) as unknown as WebSocketLike);
    this.scheduleValue = options.schedule ?? ((callback, delay) => setTimeout(callback, delay));
    this.cancelScheduleValue = options.cancelSchedule ?? ((handle) => clearTimeout(handle));
  }

  connect(): void {
    if (
      this.socket &&
      (this.socket.readyState === SOCKET_CONNECTING || this.socket.readyState === SOCKET_OPEN)
    ) {
      return;
    }
    this.manuallyClosed = false;
    this.suppressReconnect = false;
    this.openSocket(false);
  }

  disconnect(code = 1000, reason = 'client disconnect'): void {
    this.manuallyClosed = true;
    this.suppressReconnect = true;
    this.clearReconnect();
    const socket = this.socket;
    this.socket = null;
    if (socket && (socket.readyState === SOCKET_CONNECTING || socket.readyState === SOCKET_OPEN)) {
      socket.close(code, reason);
    }
    this.options.store.markDisconnected();
  }

  ping(nonce: string): boolean {
    return this.send({ type: 'ping', nonce });
  }

  private openSocket(reconnecting: boolean): void {
    this.options.store.beginConnection(reconnecting);
    const state = this.options.store.getState();
    const url = reconnecting
      ? appendAfterSequence(this.options.url, state.lastAppliedSequence)
      : this.options.url;
    let socket: WebSocketLike;
    try {
      socket = this.factory(url);
    } catch {
      this.scheduleReconnect(connectionError('WebSocket construction failed.', true));
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.options.store.markConnected();
    };
    socket.onmessage = (event) => {
      if (this.socket !== socket) return;
      this.handleMessage(event.data);
    };
    socket.onerror = () => {
      if (this.socket !== socket) return;
      this.options.store.markError(connectionError('WebSocket transport error.', true));
    };
    socket.onclose = (event) => {
      if (this.socket === socket) this.socket = null;
      if (this.manuallyClosed || this.suppressReconnect) {
        this.options.store.markDisconnected(this.options.store.getState().error ?? undefined);
        return;
      }
      this.scheduleReconnect(
        connectionError(
          `WebSocket disconnected${event.code ? ` (${event.code})` : ''}${
            event.reason ? `: ${event.reason}` : '.'
          }`,
          true,
        ),
      );
    };
  }

  private handleMessage(raw: unknown): void {
    const message = parseWebSocketMessage(raw);
    if (message === null) {
      this.protocolFailure('Malformed or unsupported WebSocket message.');
      return;
    }

    if ('session_id' in message && message.session_id !== this.options.sessionId) {
      this.protocolFailure('WebSocket message belongs to a different session.');
      return;
    }

    switch (message.type) {
      case 'snapshot': {
        const result = this.options.store.applySnapshot(message);
        if (result === 'SESSION_MISMATCH') {
          this.protocolFailure('Snapshot session mismatch.');
          return;
        }
        this.reconnectAttempts = 0;
        this.acknowledge();
        return;
      }
      case 'event': {
        const result = this.options.store.applyEvent(message);
        if (result === 'GAP') {
          void this.resync(`/api/v1/sessions/${encodeURIComponent(this.options.sessionId)}`);
          return;
        }
        if (result === 'SESSION_MISMATCH' || result === 'INVALID_SEQUENCE') {
          this.protocolFailure('Invalid projection event sequence or session.');
          return;
        }
        this.reconnectAttempts = 0;
        this.acknowledge();
        return;
      }
      case 'resync_required':
        void this.resync(message.snapshot_url);
        return;
      case 'error':
        this.options.store.markError(
          protocolError(`WebSocket server error: ${message.code}`, message.recoverable),
        );
        if (!message.recoverable) this.closeForPolicy('non-recoverable server error');
        return;
      case 'closing':
        this.suppressReconnect = true;
        this.options.store.markDisconnected(
          connectionError(`WebSocket stream closed: ${message.reason}`, false),
        );
        return;
    }
  }

  private async resync(snapshotUrl: string): Promise<void> {
    if (this.resyncPromise) return this.resyncPromise;
    this.options.store.requireResync({
      kind: 'RESYNC',
      message: 'Loading an authoritative snapshot after a projection gap.',
      recoverable: true,
      status: null,
    });
    this.resyncPromise = (async () => {
      try {
        const response = await this.options.loadSnapshot(snapshotUrl);
        const result = this.options.store.applySnapshot({
          type: 'snapshot',
          schema_version: 1,
          session_id: response.session_id,
          through_sequence: response.through_sequence,
          projection: response.projection,
        });
        if (result === 'SESSION_MISMATCH' || result === 'STALE') {
          throw new Error('Snapshot could not restore the current session sequence.');
        }
        this.reconnectAttempts = 0;
        this.restartAfterResync();
      } catch (error) {
        this.options.store.markError({
          kind: 'RESYNC',
          message: error instanceof Error ? error.message : 'Projection resynchronization failed.',
          recoverable: true,
          status: null,
        });
        this.socket?.close(1012, 'resync failed');
      } finally {
        this.resyncPromise = null;
      }
    })();
    return this.resyncPromise;
  }

  private acknowledge(): void {
    this.send({
      type: 'ack',
      through_sequence: this.options.store.getState().lastAppliedSequence,
    });
  }

  private send(message: WebSocketClientMessage): boolean {
    if (!this.socket || this.socket.readyState !== SOCKET_OPEN) return false;
    this.socket.send(JSON.stringify(message));
    return true;
  }

  private protocolFailure(message: string): void {
    this.options.store.markError(protocolError(message, false));
    this.closeForPolicy('invalid server message');
  }

  private closeForPolicy(reason: string): void {
    this.suppressReconnect = true;
    this.socket?.close(1008, reason);
  }

  private restartAfterResync(): void {
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      if (socket.readyState === SOCKET_CONNECTING || socket.readyState === SOCKET_OPEN) {
        socket.close(1012, 'resync complete');
      }
    }
    if (!this.manuallyClosed && !this.suppressReconnect) this.openSocket(true);
  }

  private scheduleReconnect(error: FrontendError): void {
    if (this.manuallyClosed || this.suppressReconnect) return;
    if (this.reconnectAttempts >= this.policy.maxAttempts) {
      this.options.store.markError({ ...error, recoverable: false });
      return;
    }
    this.options.store.markDisconnected(error);
    this.options.store.beginConnection(true);
    const delay = Math.min(
      this.policy.maxDelayMs,
      this.policy.baseDelayMs * 2 ** this.reconnectAttempts,
    );
    this.reconnectAttempts += 1;
    this.clearReconnect();
    this.reconnectHandle = this.scheduleValue(() => {
      this.reconnectHandle = null;
      this.openSocket(true);
    }, delay);
  }

  private clearReconnect(): void {
    if (this.reconnectHandle === null) return;
    this.cancelScheduleValue(this.reconnectHandle);
    this.reconnectHandle = null;
  }
}
