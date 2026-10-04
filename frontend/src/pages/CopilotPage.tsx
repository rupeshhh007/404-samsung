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
    <main id="main-content" className="mx-auto w-full max-w-7xl space-y-4 px-4 py-5">
      {(state.error || actionError) && (
        <div className="error-message" role="alert">
          {actionError ?? state.error?.message}
        </div>
      )}

      {awaitingFirstProjection && (
        <div className="loading-message" role="status">
          Connecting and awaiting the first authoritative projection…
        </div>
      )}

      {!awaitingFirstProjection && projection === null && (
        <div className="empty-state" role="status">
          Start a session to load authoritative intent, operation, world, claim, and speech projections.
        </div>
      )}

      <DivergenceAlert divergences={divergences} plans={plans} />

      <div className="workbench-grid">
        <InputPanel
          speech={speech}
          sessionAvailable={state.sessionId !== null}
          actionPending={actionPending}
          onSubmitText={onSubmitText}
          onCancelSpeech={onCancelSpeech}
        />

        <div className="space-y-4">
          <IntentPanel intent={intent} revision={revision} />
          <OperationPanel operations={operations} />
          <WorldPanel effects={effects} />
        </div>

        <div className="space-y-4">
          <ClaimPanel claims={claims} evidence={evidence} />
          <TruthBanner speech={speech} />
        </div>
      </div>
    </main>
  );
}
