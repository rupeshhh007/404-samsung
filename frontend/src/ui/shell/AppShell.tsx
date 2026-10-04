import React, { useEffect, Suspense, lazy } from 'react';
import { TopBar, type ActiveView } from './TopBar';
import { Toasts, type ToastMessage } from './Toasts';
import { LiveRegionsProvider } from './LiveRegions';
import type { Stage } from '../viewmodel/stage';
import type { ConnectionStatus } from '../../api/types';

// Lazy load WebGL background shader
const StrandField = lazy(() => import('../gl/StrandField'));

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
  tension = 0,
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
      <div className="relative min-h-screen bg-ink-950 text-bone-50 flex flex-col font-sans selection:bg-ink-700 selection:text-bone-50">
        {/* Skip to main content link for screen readers and keyboard users */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-50 focus:px-4 focus:py-2 focus:bg-bone-50 focus:text-ink-950 focus:font-mono focus:text-xs focus:font-bold focus:slab-shadow"
        >
          Skip to main content
        </a>

        {/* WebGL StrandField background layer */}
        <Suspense fallback={null}>
          <StrandField tension={tension} />
        </Suspense>

        {/* 3% Film grain overlay */}
        <div className="grain-overlay" aria-hidden="true" />

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
        <main id="main-content" className="relative z-10 flex-1 flex flex-col">
          {children}
        </main>

        {/* Floating notifications */}
        <Toasts toasts={toasts} />
      </div>
    </LiveRegionsProvider>
  );
};
