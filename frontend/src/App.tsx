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
import { SessionBar } from './components/SessionBar';
import { CopilotPage } from './pages/CopilotPage';
import { TracePage } from './pages/TracePage';
import { createProjectionStore } from './state/store';
import { Icons } from './components/Icons';

type View = 'copilot' | 'trace';
type Theme = 'light' | 'dark';

function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem('interlock-theme');
    if (stored === 'light' || stored === 'dark') return stored;
    if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light';
  } catch {
    // Storage and media-query access are optional presentation capabilities.
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

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    try {
      localStorage.setItem('interlock-theme', theme);
    } catch {
      // A blocked storage write does not affect runtime state.
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
    try {
      const reset = await http.resetDemo(state.sessionId, {
        fixture_id: 'samsung-demo-v1',
        client_request_id: nextRequestId('reset'),
      });
      socketRef.current?.disconnect();
      socketRef.current = null;
      store.reset();
      setTraceEvents([]);
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

  return (
    <div className="min-h-screen bg-[#faf8f5] text-stone-800 transition-colors dark:bg-[#12100e] dark:text-stone-200">
      <a href="#main-content" className="skip-link">Skip to main content</a>

      {/* Top Application Header */}
      <header className="app-header">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-stone-900 text-white shadow-sm dark:bg-stone-100 dark:text-stone-900">
              <Icons.ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-base font-bold tracking-wider text-stone-950 dark:text-white">
                  INTERLOCK
                </span>
                <span className="rounded-full bg-stone-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-stone-600 dark:bg-stone-800 dark:text-stone-400 border border-stone-200 dark:border-stone-700">
                  Consistency Runtime
                </span>
              </div>
              <p className="text-[11px] text-stone-500 dark:text-stone-400">
                Interruptible Real-Time Agent Workbench
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <nav aria-label="Primary views" className="view-switcher">
              <button
                type="button"
                className={view === 'copilot' ? 'view-button view-button-active' : 'view-button'}
                aria-current={view === 'copilot' ? 'page' : undefined}
                onClick={() => setView('copilot')}
              >
                Copilot
              </button>
              <button
                type="button"
                className={view === 'trace' ? 'view-button view-button-active' : 'view-button'}
                aria-current={view === 'trace' ? 'page' : undefined}
                onClick={() => setView('trace')}
              >
                Trace
              </button>
            </nav>

            <button
              type="button"
              className="secondary-button inline-flex items-center gap-1.5"
              onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {theme === 'dark' ? (
                <>
                  <Icons.Sun className="h-3.5 w-3.5" />
                  <span className="text-xs">Light</span>
                </>
              ) : (
                <>
                  <Icons.Moon className="h-3.5 w-3.5" />
                  <span className="text-xs">Dark</span>
                </>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="mx-auto w-full max-w-7xl px-4 pt-4">
        <SessionBar
          state={state}
          actionPending={actionPending}
          onStartSession={() => void startSession()}
          onResetSession={() => void resetSession()}
        />
      </div>

      {view === 'copilot' ? (
        <CopilotPage
          state={state}
          actionPending={actionPending}
          actionError={actionError}
          onSubmitText={submitText}
          onCancelSpeech={cancelSpeech}
        />
      ) : (
        <TracePage
          state={state}
          events={traceEvents}
          loading={traceLoading}
          error={traceError}
        />
      )}

      {/* Product Footer */}
      <footer className="mt-8 border-t border-stone-200/80 px-4 py-4 text-center text-xs text-stone-500 dark:border-stone-800/80 dark:text-stone-400">
        <p>Anticipate early · Commit safely · Speak only what reality confirms</p>
      </footer>
    </div>
  );
};

export default App;
