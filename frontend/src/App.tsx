import React, {
  useCallback,
  useState,
  useRef,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from 'react';
import {
  HttpApplicationError,
  HttpProtocolError,
  InterlockHttpClient,
} from './api/http';
import type { FrontendError, ProjectionEventMessage } from './api/types';
import { ProjectionSocketClient } from './api/websocket';
import { CopilotPage } from './pages/CopilotPage';
import { TracePage } from './pages/TracePage';
import { createProjectionStore } from './state/store';
import { Icons } from './components/Icons';
import { CopyButton } from './components/CopyButton';
import { shortenId } from './utils/formatters';

type View = 'copilot' | 'trace';
type Theme = 'light' | 'dark';

function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem('interlock-theme');
    if (stored === 'light' || stored === 'dark') return stored;
    if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light';
  } catch {
    // Optional presentation capability
  }
  return 'dark';
}

function frontendError(error: unknown): FrontendError {
  if (error instanceof HttpApplicationError) {
    return {
      kind: 'HTTP',
      message: error.message,
      recoverable: error.status >= 500,
      status: error.status,
    };
  }
  if (error instanceof HttpProtocolError) {
    return {
      kind: 'PROTOCOL',
      message: error.message,
      recoverable: false,
      status: null,
    };
  }
  return {
    kind: 'CONNECTION',
    message: error instanceof Error ? error.message : 'The backend request failed.',
    recoverable: true,
    status: null,
  };
}

function streamUrlForSession(currentUrl: string, sessionId: string): string {
  const parsed = new URL(currentUrl, window.location.href);
  const nextPath = parsed.pathname.replace(
    /\/sessions\/[^/]+\/stream$/,
    `/sessions/${encodeURIComponent(sessionId)}/stream`,
  );
  if (nextPath === parsed.pathname) {
    throw new Error('The backend returned an unsupported WebSocket session URL.');
  }
  parsed.pathname = nextPath;
  parsed.search = '';
  return parsed.toString();
}

export const App: React.FC = () => {
  const store = useMemo(() => createProjectionStore(), []);
  const http = useMemo(() => new InterlockHttpClient(), []);
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  const socketRef = useRef<ProjectionSocketClient | null>(null);
  const streamUrlRef = useRef<string | null>(null);
  const requestSequence = useRef(0);
  const traceSessionRef = useRef<string | null>(null);
  const traceGenerationRef = useRef(0);
  const traceLoadingRef = useRef(false);
  const traceCursorRef = useRef(0);
  const traceTargetSequenceRef = useRef(0);
  const traceEventsRef = useRef<ProjectionEventMessage[]>([]);

  const [view, setView] = useState<View>('copilot');
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [traceEvents, setTraceEvents] = useState<readonly ProjectionEventMessage[]>([]);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [userPrompts, setUserPrompts] = useState<readonly { id: string; text: string; timestamp: number }[]>([]);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    try {
      localStorage.setItem('interlock-theme', theme);
    } catch {
      // Storage write error ignored
    }
  }, [theme]);

  useEffect(() => () => socketRef.current?.disconnect(), []);

  useEffect(() => {
    const sessionId = state.sessionId;
    if (!sessionId) {
      traceGenerationRef.current += 1;
      traceSessionRef.current = null;
      traceLoadingRef.current = false;
      traceCursorRef.current = 0;
      traceTargetSequenceRef.current = 0;
      traceEventsRef.current = [];
      setTraceEvents([]);
      setTraceLoading(false);
      setTraceError(null);
      return;
    }

    if (traceSessionRef.current !== sessionId) {
      traceGenerationRef.current += 1;
      traceSessionRef.current = sessionId;
      traceLoadingRef.current = false;
      traceCursorRef.current = 0;
      traceTargetSequenceRef.current = 0;
      traceEventsRef.current = [];
      setTraceEvents([]);
      setTraceError(null);
    }

    traceTargetSequenceRef.current = Math.max(
      traceTargetSequenceRef.current,
      state.lastAppliedSequence,
    );
    if (traceLoadingRef.current || traceCursorRef.current >= traceTargetSequenceRef.current) {
      return;
    }

    const generation = traceGenerationRef.current;
    traceLoadingRef.current = true;
    async function loadHistory() {
      setTraceLoading(true);
      setTraceError(null);
      try {
        while (traceCursorRef.current < traceTargetSequenceRef.current) {
          const page = await http.getEvents(sessionId, traceCursorRef.current);
          if (traceGenerationRef.current !== generation || traceSessionRef.current !== sessionId) return;
          const next = page.events.filter((event) => event.sequence > traceCursorRef.current);
          if (next.length === 0) break;
          traceEventsRef.current = [...traceEventsRef.current, ...next]
            .sort((left, right) => left.sequence - right.sequence);
          traceCursorRef.current = next[next.length - 1].sequence;
          setTraceEvents(traceEventsRef.current);
          if (!page.has_more && traceCursorRef.current >= traceTargetSequenceRef.current) break;
        }
      } catch (error) {
        if (traceGenerationRef.current === generation && traceSessionRef.current === sessionId) {
          const normalized = frontendError(error);
          setTraceError(`Trace history unavailable: ${normalized.message}`);
        }
      } finally {
        if (traceGenerationRef.current === generation && traceSessionRef.current === sessionId) {
          traceLoadingRef.current = false;
          setTraceLoading(false);
        }
      }
    }
    void loadHistory();
  }, [http, state.sessionId, state.lastAppliedSequence]);

  const nextRequestId = useCallback((kind: string) => {
    if (typeof crypto.randomUUID === 'function') {
      return `interlock-ui-${kind}-${crypto.randomUUID()}`;
    }
    requestSequence.current += 1;
    return `interlock-ui-${kind}-${requestSequence.current}`;
  }, []);

  const startSession = useCallback(async () => {
    setActionPending(true);
    setActionError(null);
    socketRef.current?.disconnect();
    socketRef.current = null;
    store.reset();
    setTraceEvents([]);
    setUserPrompts([]);
    setSessionMenuOpen(false);
    try {
      store.beginConnection();
      const created = await http.createSession({
        mode: 'DEMO',
        client_request_id: nextRequestId('session'),
      });
      const snapshot = await http.getSession(created.session_id);
      store.applySnapshot({
        type: 'snapshot',
        schema_version: 1,
        session_id: snapshot.session_id,
        through_sequence: snapshot.through_sequence,
        projection: snapshot.projection,
      });
      const socket = new ProjectionSocketClient({
        url: created.ws_url,
        sessionId: created.session_id,
        store,
        loadSnapshot: (url) => http.getSnapshotUrl(url),
      });
      streamUrlRef.current = created.ws_url;
      socketRef.current = socket;
      socket.connect();
    } catch (error) {
      const normalized = frontendError(error);
      store.markError(normalized);
      setActionError(normalized.message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, store]);

  const resetSession = useCallback(async () => {
    if (!state.sessionId || !streamUrlRef.current) return;
    setActionPending(true);
    setActionError(null);
    setSessionMenuOpen(false);
    try {
      const reset = await http.resetDemo(state.sessionId, {
        fixture_id: 'samsung-demo-v1',
        client_request_id: nextRequestId('reset'),
      });
      socketRef.current?.disconnect();
      socketRef.current = null;
      store.reset();
      setTraceEvents([]);
      setUserPrompts([]);
      const snapshot = await http.getSession(reset.session_id);
      store.applySnapshot({
        type: 'snapshot',
        schema_version: 1,
        session_id: snapshot.session_id,
        through_sequence: snapshot.through_sequence,
        projection: snapshot.projection,
      });
      const nextStreamUrl = streamUrlForSession(streamUrlRef.current, reset.session_id);
      streamUrlRef.current = nextStreamUrl;
      const socket = new ProjectionSocketClient({
        url: nextStreamUrl,
        sessionId: reset.session_id,
        store,
        loadSnapshot: (url) => http.getSnapshotUrl(url),
      });
      socketRef.current = socket;
      socket.connect();
    } catch (error) {
      const normalized = frontendError(error);
      store.markError(normalized);
      setActionError(normalized.message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, state.sessionId, store]);

  const submitText = useCallback(async (content: string) => {
    if (!state.sessionId) return;
    setActionError(null);

    // Record user prompt in conversational history
    const promptId = typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : String(Date.now());
    setUserPrompts((prev) => [...prev, { id: promptId, text: content, timestamp: Date.now() }]);

    try {
      await http.submitInput(state.sessionId, {
        modality: 'TEXT',
        content,
        client_request_id: nextRequestId('input'),
      });
    } catch (error) {
      setActionError(frontendError(error).message);
    }
  }, [http, nextRequestId, state.sessionId]);

  const cancelSpeech = useCallback(async (speechId: string) => {
    if (!state.sessionId) return;
    setActionPending(true);
    setActionError(null);
    try {
      await http.cancelSpeech(state.sessionId, speechId, {
        client_request_id: nextRequestId('speech-cancel'),
      });
    } catch (error) {
      setActionError(frontendError(error).message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, state.sessionId]);

  useEffect(() => {
    (window as unknown as { __interlock?: Record<string, unknown> }).__interlock = {
      startSession,
      resetSession,
      submitText,
      cancelSpeech,
    };
  }, [startSession, resetSession, submitText, cancelSpeech]);

  const hasSession = state.sessionId !== null;
  const isConnected = state.connectionStatus === 'CONNECTED';
  const isConnecting = state.connectionStatus === 'CONNECTING' || state.connectionStatus === 'RECONNECTING';

  return (
    <div className="min-h-screen bg-[#faf8f5] text-stone-900 transition-colors dark:bg-[#0e0d0c] dark:text-stone-100 flex flex-col font-sans">
      <a href="#main-content" className="sr-only focus:not-sr-only fixed left-3 top-3 z-50 rounded-lg bg-stone-900 px-3 py-2 text-xs font-semibold text-white dark:bg-white dark:text-stone-900">
        Skip to main content
      </a>

      {/* Bauhaus Top Nav: Clean, Minimal, Non-Dominant */}
      <header className="sticky top-0 z-30 border-b border-stone-200/80 bg-white/90 backdrop-blur-md dark:border-stone-800/80 dark:bg-[#0e0d0c]/90 transition-colors">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-4 py-2.5">
          {/* Left: Bauhaus geometric mark + Wordmark */}
          <div className="flex items-center gap-2.5">
            <div className="text-stone-900 dark:text-stone-100 flex items-center">
              <Icons.Mark className="h-5 w-5" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-sm font-bold tracking-widest text-stone-950 dark:text-white uppercase">
                INTERLOCK
              </span>
              <span className="hidden sm:inline font-mono text-[9px] uppercase tracking-[0.22em] text-stone-400 dark:text-stone-500">
                Consistency Runtime
              </span>
            </div>
          </div>

          {/* Center: View Switcher */}
          <nav aria-label="Primary views" className="inline-flex rounded-full border border-stone-200/80 bg-stone-100/70 p-0.5 dark:border-stone-800 dark:bg-stone-900/60">
            <button
              type="button"
              className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${
                view === 'copilot'
                  ? 'bg-white text-stone-950 shadow-sm dark:bg-stone-800 dark:text-white font-semibold'
                  : 'text-stone-600 hover:text-stone-950 dark:text-stone-400 dark:hover:text-stone-100'
              }`}
              aria-current={view === 'copilot' ? 'page' : undefined}
              onClick={() => setView('copilot')}
            >
              Copilot
            </button>
            <button
              type="button"
              className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${
                view === 'trace'
                  ? 'bg-white text-stone-950 shadow-sm dark:bg-stone-800 dark:text-white font-semibold'
                  : 'text-stone-600 hover:text-stone-950 dark:text-stone-400 dark:hover:text-stone-100'
              }`}
              aria-current={view === 'trace' ? 'page' : undefined}
              onClick={() => setView('trace')}
            >
              Trace
            </button>
          </nav>

          {/* Right: Status Indicator, Session Popover, and Theme */}
          <div className="flex items-center gap-2 relative">
            {/* Subtle Connection Indicator */}
            <div
              className="flex items-center gap-1.5 px-1.5 py-0.5 text-xs text-stone-500"
              title={`Connection status: ${state.connectionStatus}`}
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  isConnected
                    ? 'bg-emerald-500'
                    : isConnecting
                    ? 'bg-amber-500 animate-pulse'
                    : 'bg-stone-300 dark:bg-stone-700'
                }`}
                aria-hidden="true"
              />
            </div>

            {/* Session Controller Button / Popover */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setSessionMenuOpen((o) => !o)}
                className="inline-flex items-center gap-1 rounded-lg border border-stone-200/80 bg-stone-50/70 px-2 py-1 text-[11px] font-mono text-stone-700 hover:bg-stone-100 dark:border-stone-800 dark:bg-stone-900/60 dark:text-stone-300 dark:hover:bg-stone-800 transition-colors"
                aria-expanded={sessionMenuOpen}
              >
                <span>{hasSession ? shortenId(state.sessionId, 4, 3) : 'No session'}</span>
                <Icons.ChevronDown className="h-3 w-3 opacity-60" />
              </button>

              {sessionMenuOpen && (
                <div className="absolute right-0 top-full mt-1.5 w-60 rounded-xl border border-stone-200/90 bg-white p-3 shadow-lg dark:border-stone-800 dark:bg-stone-900 z-50 space-y-2 text-xs">
                  <div className="border-b border-stone-100 pb-2 dark:border-stone-800">
                    <p className="text-[10px] uppercase tracking-wider text-stone-400 font-mono">
                      Session Details
                    </p>
                    {hasSession ? (
                      <div className="mt-1 flex items-center justify-between font-mono text-[11px]">
                        <span className="truncate">{state.sessionId}</span>
                        <CopyButton text={state.sessionId ?? ''} label="Copy Session ID" />
                      </div>
                    ) : (
                      <p className="text-stone-500 italic mt-0.5">No active session</p>
                    )}
                    {hasSession && (
                      <p className="text-[10px] font-mono text-stone-400 mt-1">
                        Applied Sequence: #{state.lastAppliedSequence}
                      </p>
                    )}
                  </div>

                  <div className="flex flex-col gap-1.5 pt-1">
                    <button
                      type="button"
                      onClick={() => void startSession()}
                      disabled={actionPending}
                      className="w-full rounded-lg bg-stone-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-stone-800 dark:bg-stone-100 dark:text-stone-900 dark:hover:bg-white text-center"
                    >
                      {hasSession ? 'New Session' : 'Start Session'}
                    </button>
                    {hasSession && (
                      <button
                        type="button"
                        onClick={() => void resetSession()}
                        disabled={actionPending}
                        className="w-full rounded-lg border border-stone-200 px-3 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-50 dark:border-stone-800 dark:text-stone-300 dark:hover:bg-stone-800 text-center"
                      >
                        Reset Demo State
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Theme Toggle */}
            <button
              type="button"
              className="rounded-lg p-1.5 text-stone-500 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100 transition-colors"
              onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {theme === 'dark' ? (
                <Icons.Sun className="h-4 w-4" />
              ) : (
                <Icons.Moon className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Primary Canvas */}
      <div className="flex-1">
        {view === 'copilot' ? (
          <CopilotPage
            state={state}
            actionPending={actionPending}
            actionError={actionError}
            onStartSession={() => void startSession()}
            onSubmitText={submitText}
            onCancelSpeech={cancelSpeech}
            userPrompts={userPrompts}
          />
        ) : (
          <TracePage
            state={state}
            events={traceEvents}
            loading={traceLoading}
            error={traceError}
          />
        )}
      </div>
    </div>
  );
};

export default App;
