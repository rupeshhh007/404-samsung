import React, { useEffect } from 'react';
import { TopBar, type ActiveView } from './TopBar';
import { Toasts, type ToastMessage } from './Toasts';
import { LiveRegionsProvider } from './LiveRegions';
import type { Stage } from '../viewmodel/stage';
import type { ConnectionStatus } from '../../api/types';

interface AppShellProps {
  readonly view: ActiveView;
  readonly onViewChange: (view: ActiveView) => void;
  readonly stage: Stage;
  readonly tension?: number;
  readonly connectionStatus: ConnectionStatus;
  readonly sessionId: string | null;
  readonly lastAppliedSequence: number;
  readonly onNewSession: () => void;
  readonly onResetDemo: () => void;
  readonly actionPending?: boolean;
  readonly isScriptedReplay?: boolean;
  readonly isScriptedContinuation?: boolean;
  readonly toasts: readonly ToastMessage[];
  readonly children: React.ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({
  view,
  onViewChange,
  stage,
  tension: _tension = 0,
  connectionStatus,
  sessionId,
  lastAppliedSequence,
  onNewSession,
  onResetDemo,
  actionPending = false,
  isScriptedReplay = false,
  isScriptedContinuation = false,
  toasts,
  children,
}) => {
  // Global '/' keyboard shortcut to focus composer when not typing
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement)?.tagName)) {
        e.preventDefault();
        const composer = document.getElementById('interlock-composer-input');
        composer?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <LiveRegionsProvider>
      <div className={`interlock-app ${view === 'blackbox' ? 'interlock-app--blackbox' : 'interlock-app--console'} relative flex min-h-screen flex-col font-sans`}>
        {/* Skip to main content link for screen readers and keyboard users */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-white focus:px-4 focus:py-2 focus:font-mono focus:text-xs focus:font-bold focus:text-black"
        >
          Skip to main content
        </a>

        {/* TopBar navigation */}
        <TopBar
          view={view}
          onViewChange={onViewChange}
          stage={stage}
          connectionStatus={connectionStatus}
          sessionId={sessionId}
          lastAppliedSequence={lastAppliedSequence}
          onNewSession={onNewSession}
          onResetDemo={onResetDemo}
          actionPending={actionPending}
          isScriptedReplay={isScriptedReplay}
          isScriptedContinuation={isScriptedContinuation}
        />

        {/* Main Product Surface */}
        <main id="main-content" className="relative flex flex-1 flex-col">
          {children}
        </main>

        {/* Floating notifications */}
        <Toasts toasts={toasts} />
      </div>
    </LiveRegionsProvider>
  );
};
