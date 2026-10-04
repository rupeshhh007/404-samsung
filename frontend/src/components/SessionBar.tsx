import type { ConnectionStatus } from '../api/types';
import type { ProjectionStoreState } from '../state/store';

interface SessionBarProps {
  readonly state: ProjectionStoreState;
  readonly actionPending: boolean;
  readonly onStartSession: () => void;
  readonly onResetSession: () => void;
}

const CONNECTION_LABELS: Readonly<Record<ConnectionStatus, string>> = {
  DISCONNECTED: 'Disconnected',
  CONNECTING: 'Connecting',
  CONNECTED: 'Connected',
  RECONNECTING: 'Reconnecting',
  ERROR: 'Connection error',
};

function connectionTone(status: ConnectionStatus): string {
  if (status === 'CONNECTED') return 'status-success';
  if (status === 'CONNECTING' || status === 'RECONNECTING') return 'status-active';
  if (status === 'ERROR') return 'status-danger';
  return 'status-neutral';
}

export function SessionBar({
  state,
  actionPending,
  onStartSession,
  onResetSession,
}: SessionBarProps) {
  const hasSession = state.sessionId !== null;

  return (
    <section className="session-bar" aria-label="Session and connection status">
      <div className="min-w-0">
        <p className="eyebrow">Session</p>
        <p className="mono-wrap text-sm font-medium text-stone-800 dark:text-stone-100">
          {state.sessionId ?? 'No active session'}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        <span className={`status-pill ${connectionTone(state.connectionStatus)}`}>
          {CONNECTION_LABELS[state.connectionStatus]}
        </span>
        {state.stale && <span className="status-pill status-warning">Last-known data</span>}
        <span className="status-pill status-neutral">
          Sequence {state.lastAppliedSequence || '—'}
        </span>
        <button
          type="button"
          className="primary-button"
          onClick={onStartSession}
          disabled={actionPending || state.connectionStatus === 'CONNECTING'}
        >
          {actionPending ? 'Starting…' : hasSession ? 'Start new session' : 'Start session'}
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={onResetSession}
          disabled={!hasSession || actionPending}
        >
          Reset demo
        </button>
      </div>
    </section>
  );
}
