import React from 'react';
import { motion } from 'motion/react';
import { Led, type LedStatus } from '../primitives/Led';
import { Hairline } from '../primitives/Hairline';
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
  // Connection LED mapping
  let ledStatus: LedStatus = 'idle';
  let ledPulse = false;
  let statusText = 'Idle';

  if (connectionStatus === 'CONNECTED') {
    ledStatus = 'verify';
    statusText = 'Connected to Runtime';
  } else if (connectionStatus === 'CONNECTING' || connectionStatus === 'RECONNECTING') {
    ledStatus = 'pending';
    ledPulse = true;
    statusText = 'Connecting to Runtime';
  } else {
    ledStatus = 'alarm';
    statusText = 'Disconnected';
  }

  const isDiverged = stage === 'DIVERGED';
  const isResolved = stage === 'RESOLVED';

  return (
    <header className="sticky top-0 z-40 w-full h-16 bg-ink-950/80 backdrop-blur-md border-b border-ink-600 flex items-center justify-between px-6 select-none">
      {/* Left: Brand Mark + Wordmark */}
      <div className="flex items-center gap-3">
        {/* Animated Mark */}
        <div
          className="relative w-7 h-7 flex items-center justify-center flex-shrink-0 cursor-pointer"
          title="INTERLOCK Consistency Runtime"
        >
          {/* Square */}
          <div
            className={`absolute w-3.5 h-3.5 border-2 border-bone-50 transition-all duration-300 ${
              isDiverged ? '-translate-x-1 border-sig-alarm' : 'translate-x-0'
            }`}
            style={{ left: 2, top: 2 }}
          />
          {/* Circle */}
          <div
            className={`absolute w-3.5 h-3.5 rounded-full border-2 border-bone-50 transition-all duration-300 ${
              isDiverged ? 'translate-x-1 border-sig-alarm' : 'translate-x-0'
            } ${isResolved ? 'border-sig-verify' : ''}`}
            style={{ right: 2, bottom: 2 }}
          />
        </div>

        {/* Wordmark */}
        <div className="flex items-baseline gap-2.5">
          <span className="font-display font-extrabold text-lg tracking-[0.08em] uppercase text-bone-50">
            INTERLOCK
          </span>
          <span className="hidden min-[1100px]:inline font-mono text-[10px] tracking-[0.16em] uppercase text-bone-500">
            CONSISTENCY RUNTIME
          </span>
        </div>
      </div>

      {/* Centre: Segmented View Control */}
      <nav aria-label="Primary views" className="flex items-center p-1 bg-ink-900 border border-ink-600">
        <button
          type="button"
          onClick={() => onViewChange('console')}
          aria-current={view === 'console' ? 'page' : undefined}
          className={`relative px-4 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors z-10 ${
            view === 'console' ? 'text-bone-50 font-semibold' : 'text-bone-500 hover:text-bone-300'
          }`}
        >
          {view === 'console' && (
            <motion.div
              layoutId="topbar-view-indicator"
              className="absolute inset-0 bg-ink-800 border border-ink-600 -z-10"
              transition={{ type: 'spring', stiffness: 400, damping: 30 }}
            />
          )}
          Console
        </button>

        <button
          type="button"
          onClick={() => onViewChange('blackbox')}
          aria-current={view === 'blackbox' ? 'page' : undefined}
          className={`relative px-4 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors z-10 ${
            view === 'blackbox' ? 'text-bone-50 font-semibold' : 'text-bone-500 hover:text-bone-300'
          }`}
        >
          {view === 'blackbox' && (
            <motion.div
              layoutId="topbar-view-indicator"
              className="absolute inset-0 bg-ink-800 border border-ink-600 -z-10"
              transition={{ type: 'spring', stiffness: 400, damping: 30 }}
            />
          )}
          Black Box
        </button>
      </nav>

      {/* Right: Provenance, Connection Status, Session Menu */}
      <div className="flex items-center gap-3">
        <ProvenanceChips
          isScriptedReplay={isScriptedReplay}
          isScriptedContinuation={isScriptedContinuation}
        />

        {/* Connection status indicator */}
        <div
          className="flex items-center gap-1.5 px-2 h-7 border border-ink-600 bg-ink-900"
          title={statusText}
        >
          <Led status={ledStatus} pulse={ledPulse} size={7} aria-label={statusText} />
          <span className="hidden sm:inline font-mono text-[10px] uppercase text-bone-500">
            {connectionStatus === 'CONNECTED' ? 'LIVE' : connectionStatus}
          </span>
        </div>

        <Hairline vertical className="h-4" />

        {/* Session Pill & Menu */}
        <SessionMenu
          sessionId={sessionId}
          lastAppliedSequence={lastAppliedSequence}
          onNewSession={onNewSession}
          onResetDemo={onResetDemo}
          actionPending={actionPending}
        />
      </div>
    </header>
  );
};
