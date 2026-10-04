import type {
  ConnectionStatus,
  FrontendError,
  ProjectionEventMessage,
  SessionProjection,
  SnapshotMessage,
} from '../api/types';
import { applyProjectionDelta, copyProjection } from './projections';

export interface ProjectionStoreState {
  readonly connectionStatus: ConnectionStatus;
  readonly sessionId: string | null;
  readonly projection: SessionProjection | null;
  readonly lastAppliedSequence: number;
  readonly loading: boolean;
  readonly stale: boolean;
  readonly error: FrontendError | null;
}

export type ProjectionApplyResult =
  | 'APPLIED'
  | 'SNAPSHOT_REPLACED'
  | 'DUPLICATE'
  | 'STALE'
  | 'GAP'
  | 'SESSION_MISMATCH'
  | 'INVALID_SEQUENCE';

export type ProjectionStoreListener = (state: ProjectionStoreState) => void;

export interface ProjectionStore {
  getState(): ProjectionStoreState;
  subscribe(listener: ProjectionStoreListener): () => void;
  beginConnection(reconnecting?: boolean): void;
  markConnected(): void;
  markDisconnected(error?: FrontendError): void;
  markError(error: FrontendError): void;
  requireResync(error?: FrontendError): void;
  applySnapshot(message: SnapshotMessage): ProjectionApplyResult;
  applyEvent(message: ProjectionEventMessage): ProjectionApplyResult;
  reset(): void;
}

const INITIAL_STATE: ProjectionStoreState = Object.freeze({
  connectionStatus: 'DISCONNECTED',
  sessionId: null,
  projection: null,
  lastAppliedSequence: 0,
  loading: false,
  stale: false,
  error: null,
});

function protocolError(message: string, recoverable: boolean): FrontendError {
  return {
    kind: 'PROTOCOL',
    message,
    recoverable,
    status: null,
  };
}

export function createProjectionStore(
  initialState: ProjectionStoreState = INITIAL_STATE,
): ProjectionStore {
  let state = Object.freeze({ ...initialState });
  const listeners = new Set<ProjectionStoreListener>();

  function publish(next: ProjectionStoreState): void {
    if (next === state) return;
    state = Object.freeze(next);
    for (const listener of listeners) listener(state);
  }

  return {
    getState(): ProjectionStoreState {
      return state;
    },

    subscribe(listener: ProjectionStoreListener): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    beginConnection(reconnecting = false): void {
      publish({
        ...state,
        connectionStatus: reconnecting ? 'RECONNECTING' : 'CONNECTING',
        loading: state.projection === null,
        error: null,
      });
    },

    markConnected(): void {
      publish({
        ...state,
        connectionStatus: 'CONNECTED',
        loading: state.projection === null,
        stale: false,
        error: null,
      });
    },

    markDisconnected(error?: FrontendError): void {
      publish({
        ...state,
        connectionStatus: 'DISCONNECTED',
        loading: false,
        stale: state.projection !== null,
        error: error ?? null,
      });
    },

    markError(error: FrontendError): void {
      publish({
        ...state,
        connectionStatus: 'ERROR',
        loading: false,
        stale: state.projection !== null,
        error,
      });
    },

    requireResync(error = protocolError('Projection resynchronization is required.', true)): void {
      publish({
        ...state,
        loading: true,
        stale: true,
        error,
      });
    },

    applySnapshot(message: SnapshotMessage): ProjectionApplyResult {
      if (state.sessionId !== null && state.sessionId !== message.session_id) {
        publish({
          ...state,
          error: protocolError('Snapshot belongs to a different session.', false),
        });
        return 'SESSION_MISMATCH';
      }
      if (message.through_sequence < state.lastAppliedSequence) return 'STALE';

      publish({
        connectionStatus: state.connectionStatus,
        sessionId: message.session_id,
        projection: copyProjection(message.projection),
        lastAppliedSequence: message.through_sequence,
        loading: false,
        stale: false,
        error: null,
      });
      return 'SNAPSHOT_REPLACED';
    },

    applyEvent(message: ProjectionEventMessage): ProjectionApplyResult {
      if (state.sessionId !== null && state.sessionId !== message.session_id) {
        publish({
          ...state,
          error: protocolError('Projection event belongs to a different session.', false),
        });
        return 'SESSION_MISMATCH';
      }
      if (message.projection_delta.through_sequence !== message.sequence) {
        publish({
          ...state,
          stale: state.projection !== null,
          error: protocolError('Projection delta is not pinned to its event sequence.', false),
        });
        return 'INVALID_SEQUENCE';
      }
      if (message.sequence < state.lastAppliedSequence) return 'STALE';
      if (message.sequence === state.lastAppliedSequence) return 'DUPLICATE';
      if (state.projection === null || message.sequence !== state.lastAppliedSequence + 1) {
        publish({
          ...state,
          sessionId: state.sessionId ?? message.session_id,
          loading: true,
          stale: true,
          error: protocolError('Projection sequence gap requires an authoritative snapshot.', true),
        });
        return 'GAP';
      }

      const projection = applyProjectionDelta(state.projection, message.projection_delta);
      publish({
        ...state,
        sessionId: message.session_id,
        projection,
        lastAppliedSequence: message.sequence,
        loading: false,
        stale: false,
        error: null,
      });
      return 'APPLIED';
    },

    reset(): void {
      publish(INITIAL_STATE);
    },
  };
}
