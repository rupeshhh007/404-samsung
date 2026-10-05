import React from 'react';
import { ProvenanceChips } from './ProvenanceChips';
import { SessionMenu } from './SessionMenu';
import type { Stage } from '../viewmodel/stage';
import type { ConnectionStatus } from '../../api/types';

export type ActiveView = 'console' | 'blackbox';

interface TopBarProps {
  readonly view: ActiveView;
  readonly onViewChange: (view: ActiveView) => void;
  readonly stage: Stage;
  readonly connectionStatus: ConnectionStatus;
  readonly sessionId: string | null;
  readonly lastAppliedSequence: number;
  readonly onNewSession: () => void;
  readonly onResetDemo: () => void;
  readonly actionPending?: boolean;
  readonly isScriptedReplay?: boolean;
  readonly isScriptedContinuation?: boolean;
}

export const TopBar: React.FC<TopBarProps> = ({
  view,
  onViewChange,
  stage,
  connectionStatus,
  sessionId,
  lastAppliedSequence,
  onNewSession,
  onResetDemo,
  actionPending = false,
  isScriptedReplay = false,
  isScriptedContinuation = false,
}) => {
  const statusText = connectionStatus === 'CONNECTED' ? 'Live' : connectionStatus.toLowerCase();

  return (
    <header className="editorial-header sticky top-0 z-40 flex w-full select-none items-center justify-between px-5 sm:px-8">
      <button
        type="button"
        onClick={() => onViewChange('console')}
        className="font-display text-[15px] font-extrabold uppercase tracking-[0.18em]"
        aria-current={view === 'console' ? 'page' : undefined}
      >
        INTERLOCK
      </button>

      <div className="flex items-center gap-4">
        {view === 'blackbox' && (
          <span className="hidden font-mono text-[9px] uppercase tracking-[0.14em] opacity-50 sm:inline" title={statusText}>
            {stage.replace('_', ' ')} · #{lastAppliedSequence}
          </span>
        )}
        {view === 'blackbox' && (
          <div className="hidden xl:block">
            <ProvenanceChips
              isScriptedReplay={isScriptedReplay}
              isScriptedContinuation={isScriptedContinuation}
            />
          </div>
        )}
        <button
          type="button"
          onClick={() => onViewChange(view === 'console' ? 'blackbox' : 'console')}
          className="font-mono text-[10px] font-semibold uppercase tracking-[0.12em] underline decoration-transparent underline-offset-4 transition-colors hover:decoration-current"
          aria-current={view === 'blackbox' ? 'page' : undefined}
        >
          {view === 'console' ? 'Black Box ↗' : '← Console'}
        </button>
        {view === 'blackbox' && (
          <SessionMenu
            sessionId={sessionId}
            lastAppliedSequence={lastAppliedSequence}
            onNewSession={onNewSession}
            onResetDemo={onResetDemo}
            actionPending={actionPending}
          />
        )}
      </div>
    </header>
  );
};
