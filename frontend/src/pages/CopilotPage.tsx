import type { ProjectionStoreState } from '../state/store';
import {
  selectActiveIntent,
  selectActiveRevision,
  selectClaims,
  selectDivergences,
  selectOperations,
  selectPlans,
  selectSpeech,
} from '../state/projections';
import { ClaimPanel } from '../components/ClaimPanel';
import { DivergenceAlert } from '../components/DivergenceAlert';
import { InputPanel } from '../components/InputPanel';
import { IntentPanel } from '../components/IntentPanel';
import { OperationPanel } from '../components/OperationPanel';
import { TruthBanner } from '../components/TruthBanner';
import { WorldPanel } from '../components/WorldPanel';

interface CopilotPageProps {
  readonly state: ProjectionStoreState;
  readonly actionPending: boolean;
  readonly actionError: string | null;
  readonly onSubmitText: (content: string) => Promise<void>;
  readonly onCancelSpeech: (speechId: string) => Promise<void>;
}

export function CopilotPage({
  state,
  actionPending,
  actionError,
  onSubmitText,
  onCancelSpeech,
}: CopilotPageProps) {
  const projection = state.projection;
  const intent = projection ? selectActiveIntent(projection) : null;
  const revision = projection ? selectActiveRevision(projection) : null;
  const operations = projection ? selectOperations(projection) : [];
  const claims = projection ? selectClaims(projection) : [];
  const speech = projection ? selectSpeech(projection) : [];
  const divergences = projection ? selectDivergences(projection) : [];
  const plans = projection ? selectPlans(projection) : [];
  const effects = projection?.effects ?? [];
  const evidence = projection?.evidence ?? [];

  const awaitingFirstProjection = state.loading && projection === null;

  return (
    <main id="main-content" className="mx-auto w-full max-w-7xl space-y-4 px-4 py-4">
      {/* Top feedback notifications */}
      {(state.error || actionError) && (
        <div className="error-message" role="alert">
          {actionError ?? state.error?.message}
        </div>
      )}

      {awaitingFirstProjection && (
        <div className="loading-message" role="status">
          Connecting to INTERLOCK runtime and awaiting first authoritative projection…
        </div>
      )}

      {!awaitingFirstProjection && projection === null && (
        <div className="empty-state text-center py-6" role="status">
          <p className="font-medium text-stone-800 dark:text-stone-200">
            Welcome to the INTERLOCK consistency runtime.
          </p>
          <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
            Click <strong>Start Session</strong> above to begin multimodal input interpretation and reality tracking.
          </p>
        </div>
      )}

      {/* Asymmetric Two-Column Product Layout */}
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-12">
        {/* Left Column: Primary Interaction & Verified Output (5 cols on lg) */}
        <div className="space-y-4 lg:col-span-5">
          {/* TRUTHLOCK Speech Gate */}
          <TruthBanner speech={speech} />

          {/* Conversation Input & Speech Feed */}
          <InputPanel
            speech={speech}
            sessionAvailable={state.sessionId !== null}
            actionPending={actionPending}
            onSubmitText={onSubmitText}
            onCancelSpeech={onCancelSpeech}
          />
        </div>

        {/* Right Column: State of Reality Workbench (7 cols on lg) */}
        <div className="space-y-4 lg:col-span-7">
          {/* Reality Alignment / Divergence Monitor */}
          <DivergenceAlert
            divergences={divergences}
            plans={plans}
            intent={intent}
            revision={revision}
            effects={effects}
          />

          {/* 1. What the user wants: Intent Card */}
          <IntentPanel intent={intent} revision={revision} />

          {/* 2. What the system is doing: Operations Card */}
          <OperationPanel operations={operations} />

          {/* 3. What the real world says: Observed World Card */}
          <WorldPanel effects={effects} />

          {/* 4. Claims & Evidence */}
          <ClaimPanel claims={claims} evidence={evidence} />
        </div>
      </div>
    </main>
  );
}
