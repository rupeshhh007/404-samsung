import React, {
  useCallback,
  useState,
  useRef,
  useEffect,
  useMemo,
  useSyncExternalStore,
  lazy,
  Suspense,
} from 'react';
import {
  HttpApplicationError,
  HttpProtocolError,
  InterlockHttpClient,
} from './api/http';
import type {
  FrontendError,
  ProjectionEventMessage,
  SessionProjection,
} from './api/types';
import { ProjectionSocketClient } from './api/websocket';
import { createProjectionStore } from './state/store';
import { AppShell } from './ui/shell/AppShell';
import type { ActiveView } from './ui/shell/TopBar';
import type { ToastMessage } from './ui/shell/Toasts';
import { IdleScreen } from './ui/idle/IdleScreen';
import { VoiceColumn } from './ui/voice/VoiceColumn';
import { BlackBoxPage } from './ui/blackbox/BlackBoxPage';
import { KitchenSink } from './ui/primitives/KitchenSink';
import { deriveStage } from './ui/viewmodel/stage';
import type { UserPromptEntry } from './ui/viewmodel/transcript';
import { useStageDirector } from './ui/motion/director/useStageDirector';
import type { StoryboardClient } from './dev/storyboard/StoryboardClient';

// Lazy load Storyboard overlay only when flag is set
const StoryboardOverlay =
  import.meta.env.VITE_ENABLE_STORYBOARD === '1'
    ? lazy(() => import('./dev/storyboard/StoryboardOverlay'))
    : null;

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

/**
 * Stage Director bridge component running inside LiveRegionsProvider
 */
const DirectorBridge: React.FC<{
  readonly projection: SessionProjection | null;
  readonly sessionId: string | null;
}> = ({ projection, sessionId }) => {
  useStageDirector(projection, sessionId);
  return null;
};

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

  const [view, setView] = useState<ActiveView>(new URLSearchParams(window.location.search).get('qa') === 'blackbox' ? 'blackbox' : 'console');
  const [actionPending, setActionPending] = useState(false);
  const [toasts, setToasts] = useState<readonly ToastMessage[]>([]);
  const [traceEvents, setTraceEvents] = useState<readonly ProjectionEventMessage[]>([]);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [userPrompts, setUserPrompts] = useState<readonly UserPromptEntry[]>([]);
  const [storyboardClient, setStoryboardClient] = useState<StoryboardClient | null>(null);

  // Derive stage, tension, and layout gap from pure view-model
  const { stage, gapPx, tension } = useMemo(() => {
    return deriveStage(state.projection, state.sessionId, state.connectionStatus);
  }, [state.projection, state.sessionId, state.connectionStatus]);

  // Storyboard gating check
  const isStoryboardActive =
    import.meta.env.VITE_ENABLE_STORYBOARD === '1' &&
    typeof window !== 'undefined' &&
    window.location.search.includes('storyboard=samsung-v1');

  // Check for dev kitchen sink route
  const isKitchenRoute =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('kitchen') === '1';

  // Cleanup websocket on unmount
  useEffect(() => () => socketRef.current?.disconnect(), []);

  // Poll trace history from REST endpoint when sequence advances
  useEffect(() => {
    // If storyboard is driving, do not poll REST
    if (isStoryboardActive && storyboardClient) {
      return;
    }

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

    const activeSessionId = sessionId;
    const generation = traceGenerationRef.current;
    traceLoadingRef.current = true;

    async function loadHistory() {
      setTraceLoading(true);
      setTraceError(null);
      try {
        while (traceCursorRef.current < traceTargetSequenceRef.current) {
          const page = await http.getEvents(activeSessionId, traceCursorRef.current);
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
  }, [http, state.sessionId, state.lastAppliedSequence, isStoryboardActive, storyboardClient]);

  const nextRequestId = useCallback((kind: string) => {
    if (typeof crypto.randomUUID === 'function') {
      return `interlock-ui-${kind}-${crypto.randomUUID()}`;
    }
    requestSequence.current += 1;
    return `interlock-ui-${kind}-${requestSequence.current}`;
  }, []);

  const addToast = useCallback((kind: 'error' | 'warning' | 'info', message: string) => {
    const id = nextRequestId('toast');
    setToasts((prev) => [
      ...prev,
      {
        id,
        kind,
        message,
        onDismiss: () => setToasts((curr) => curr.filter((t) => t.id !== id)),
      },
    ]);
  }, [nextRequestId]);

  // E1: startSession returns Promise<boolean> (true on success)
  const startSession = useCallback(async (): Promise<boolean> => {
    setActionPending(true);
    socketRef.current?.disconnect();
    socketRef.current = null;
    store.reset();
    setTraceEvents([]);
    setUserPrompts([]);

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
      return true;
    } catch (error) {
      const normalized = frontendError(error);
      store.markError(normalized);
      addToast('error', normalized.message);
      return false;
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, store, addToast]);

  const resetSession = useCallback(async () => {
    if (storyboardClient) {
      storyboardClient.jumpTo(0);
      return;
    }

    if (!state.sessionId || !streamUrlRef.current) return;
    setActionPending(true);

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
      addToast('error', normalized.message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, state.sessionId, store, storyboardClient, addToast]);

  // E2: submitText records acceptedSequence on userPrompts
  const submitText = useCallback(async (content: string) => {
    if (!state.sessionId) return;

    const promptId = typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : String(Date.now());
    setUserPrompts((prev) => [
      ...prev,
      { id: promptId, text: content, acceptedSequence: null },
    ]);

    try {
      const res = await http.submitInput(state.sessionId, {
        modality: 'TEXT',
        content,
        client_request_id: nextRequestId('input'),
      });
      setUserPrompts((prev) =>
        prev.map((p) => (p.id === promptId ? { ...p, acceptedSequence: res.sequence } : p)),
      );
    } catch (error) {
      const normalized = frontendError(error);
      setUserPrompts((prev) =>
        prev.map((p) => (p.id === promptId ? { ...p, failed: true } : p)),
      );
      addToast('error', normalized.message);
    }
  }, [http, nextRequestId, state.sessionId, addToast]);

  const cancelSpeech = useCallback(async (speechId: string) => {
    if (!state.sessionId) return;
    setActionPending(true);
    try {
      await http.cancelSpeech(state.sessionId, speechId, {
        client_request_id: nextRequestId('speech-cancel'),
      });
    } catch (error) {
      const normalized = frontendError(error);
      addToast('error', normalized.message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, state.sessionId, addToast]);

  // E3: authorizePlan and authorizeRevision wrappers
  const authorizePlan = useCallback(async (planId: string, decision: 'AUTHORIZE' | 'DENY') => {
    if (!state.sessionId) return;
    setActionPending(true);
    try {
      await http.authorize(state.sessionId, {
        plan_id: planId,
        decision,
        client_request_id: nextRequestId('auth-plan'),
      });
    } catch (error) {
      const normalized = frontendError(error);
      addToast('error', normalized.message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, state.sessionId, addToast]);

  const authorizeRevision = useCallback(async (revisionId: string, decision: 'AUTHORIZE' | 'DENY') => {
    if (!state.sessionId) return;
    setActionPending(true);
    try {
      await http.authorize(state.sessionId, {
        revision_id: revisionId,
        decision,
        client_request_id: nextRequestId('auth-rev'),
      });
    } catch (error) {
      const normalized = frontendError(error);
      addToast('error', normalized.message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, state.sessionId, addToast]);

  // Expose global window.__interlock test helpers
  useEffect(() => {
    (window as unknown as { __interlock?: Record<string, unknown> }).__interlock = {
      startSession,
      resetSession,
      submitText,
      cancelSpeech,
      authorizePlan,
      authorizeRevision,
    };
  }, [startSession, resetSession, submitText, cancelSpeech, authorizePlan, authorizeRevision]);

  // Merge prompts and events if StoryboardClient is driving
  const effectivePrompts = storyboardClient ? storyboardClient.getUserPrompts() : userPrompts;
  const effectiveEvents = storyboardClient ? storyboardClient.getAllEvents() : traceEvents;
  const isScriptedReplay = isStoryboardActive && !!storyboardClient;

  return (
    <AppShell
      view={view}
      onViewChange={setView}
      stage={stage}
      tension={tension}
      connectionStatus={state.connectionStatus}
      sessionId={state.sessionId}
      lastAppliedSequence={state.lastAppliedSequence}
      onNewSession={() => void startSession()}
      onResetDemo={() => void resetSession()}
      actionPending={actionPending}
      isScriptedReplay={isScriptedReplay}
      toasts={toasts}
    >
      <DirectorBridge projection={state.projection} sessionId={state.sessionId} />

      {/* Dev Kitchen Sink route */}
      {isKitchenRoute ? (
        <KitchenSink />
      ) : state.sessionId === null ? (
        /* Idle screen */
        <IdleScreen
          onBeginSession={startSession}
          onHealthCheck={async () => {
            try {
              const res = await http.health();
              return res.status === 'ok';
            } catch {
              return false;
            }
          }}
          baseUrl={http.baseUrl}
        />
      ) : (
        /* Active session views */
        <>
          {view === 'console' ? (
            <VoiceColumn
              stage={stage}
              gapPx={gapPx}
              projection={state.projection}
              userPrompts={effectivePrompts}
              onSendText={submitText}
              onCancelSpeech={cancelSpeech}
              onOpenBlackBox={() => setView('blackbox')}
              actionPending={actionPending}
            />
          ) : (
            /* Black Box forensic replay */
            <BlackBoxPage
              sessionId={state.sessionId}
              liveProjection={state.projection}
              events={effectiveEvents}
              loading={traceLoading}
              error={traceError}
            />
          )}
        </>
      )}

      {/* Storyboard overlay if gated and active */}
      {isStoryboardActive && StoryboardOverlay && (
        <Suspense fallback={null}>
          <StoryboardOverlay
            store={store}
            onClientReady={setStoryboardClient}
          />
        </Suspense>
      )}
    </AppShell>
  );
};

export default App;
