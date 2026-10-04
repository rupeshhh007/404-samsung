import React from 'react';
import type { ConnectionStatus } from '../api/types';
import type { ProjectionStoreState } from '../state/store';
import { Icons } from './Icons';
import { CopyButton } from './CopyButton';
import { shortenId } from '../utils/formatters';

interface SessionBarProps {
  readonly state: ProjectionStoreState;
  readonly actionPending: boolean;
  readonly onStartSession: () => void;
  readonly onResetSession: () => void;
}

const CONNECTION_META: Readonly<
  Record<
    ConnectionStatus,
    { label: string; dotClass: string; badgeClass: string }
  >
> = {
  DISCONNECTED: {
    label: 'Disconnected',
    dotClass: 'bg-stone-400',
    badgeClass: 'border-stone-300 bg-stone-100 text-stone-700 dark:border-stone-800 dark:bg-stone-800 dark:text-stone-300',
  },
  CONNECTING: {
    label: 'Connecting…',
    dotClass: 'bg-amber-400 animate-pulse',
    badgeClass: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-300',
  },
  CONNECTED: {
    label: 'Live Stream',
    dotClass: 'bg-emerald-500 animate-pulse',
    badgeClass: 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-300',
  },
  RECONNECTING: {
    label: 'Reconnecting…',
    dotClass: 'bg-amber-500 animate-pulse',
    badgeClass: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-300',
  },
  ERROR: {
    label: 'Connection Error',
    dotClass: 'bg-rose-500',
    badgeClass: 'border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950/60 dark:text-rose-300',
  },
};

export const SessionBar: React.FC<SessionBarProps> = ({
  state,
  actionPending,
  onStartSession,
  onResetSession,
}) => {
  const hasSession = state.sessionId !== null;
  const conn = CONNECTION_META[state.connectionStatus];

  return (
    <section
      className="flex flex-col justify-between gap-3 rounded-2xl border border-stone-200/90 bg-white/95 p-3.5 shadow-sm transition-colors dark:border-stone-800/80 dark:bg-stone-900/80 sm:flex-row sm:items-center"
      aria-label="Session status and runtime controls"
    >
      {/* Left: Session ID + Connection Indicator */}
      <div className="flex flex-wrap items-center gap-3 min-w-0">
        {/* Connection status pill */}
        <div
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${conn.badgeClass}`}
        >
          <span className={`h-2 w-2 rounded-full ${conn.dotClass}`} aria-hidden="true" />
          <span>{conn.label}</span>
        </div>

        {/* Session ID display with copy */}
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-[11px] font-medium uppercase tracking-wider text-stone-400 dark:text-stone-500">
            Session:
          </span>
          {hasSession ? (
            <div className="inline-flex items-center gap-1 rounded bg-stone-100/90 px-2 py-0.5 text-xs font-mono text-stone-800 dark:bg-stone-800/80 dark:text-stone-200">
              <span title={state.sessionId ?? ''}>{shortenId(state.sessionId, 8, 6)}</span>
              <CopyButton text={state.sessionId ?? ''} label="Copy Session ID" />
            </div>
          ) : (
            <span className="text-xs text-stone-500 dark:text-stone-400 italic">
              No active session
            </span>
          )}
        </div>

        {/* Applied sequence counter */}
        {hasSession && (
          <span className="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] font-mono text-stone-600 dark:border-stone-800 dark:bg-stone-950 dark:text-stone-400">
            Seq #{state.lastAppliedSequence}
          </span>
        )}

        {state.stale && (
          <span className="status-pill status-warning text-[11px]">
            Cached State
          </span>
        )}
      </div>

      {/* Right: Runtime Action Controls */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="primary-button inline-flex items-center gap-1.5 text-xs"
          onClick={onStartSession}
          disabled={actionPending || state.connectionStatus === 'CONNECTING'}
        >
          <Icons.Sparkles className="h-3.5 w-3.5" />
          <span>{actionPending ? 'Initializing…' : hasSession ? 'New Session' : 'Start Session'}</span>
        </button>

        <button
          type="button"
          className="secondary-button inline-flex items-center gap-1.5 text-xs"
          onClick={onResetSession}
          disabled={!hasSession || actionPending}
          title="Reset fake appointment provider and clear session state"
        >
          <Icons.RefreshCw className="h-3.5 w-3.5 opacity-70" />
          <span>Reset Demo</span>
        </button>
      </div>
    </section>
  );
};
