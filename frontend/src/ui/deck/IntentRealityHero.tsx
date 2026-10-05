import React, { useMemo } from 'react';
import {
  formatSlotParts,
  extractDesiredSlot,
  selectObservedWorld,
  selectActiveOperation,
} from '../viewmodel/slots';
import type { Stage } from '../viewmodel/stage';
import type { SessionProjection } from '../../api/types';

interface IntentRealityHeroProps {
  readonly stage: Stage;
  readonly gapPx: number;
  readonly projection: SessionProjection | null;
  readonly onOpenBlackBox?: () => void;
}

function stateCopy(
  stage: Stage,
  isDiverged: boolean,
  isAligned: boolean,
  isTooLate: boolean,
): { label: string; note: string } {
  if (isDiverged) {
    return {
      label: 'Mismatch · Open',
      note: isTooLate ? 'Cancellation arrived too late.' : 'Reality differs from the active intent.',
    };
  }
  if (isAligned) return { label: 'Aligned · Verified', note: 'Intent and authoritative reality agree.' };
  if (stage === 'EXECUTING') return { label: 'In flight', note: 'The current action has not produced authoritative reality yet.' };
  if (stage === 'FAILED') return { label: 'Action failed', note: 'No successful external effect is implied.' };
  if (stage === 'UNKNOWN') return { label: 'Outcome unknown', note: 'The external outcome cannot yet be stated.' };
  if (stage === 'CANCEL_RACE') return { label: 'Cancellation pending', note: 'The operation boundary is still being resolved.' };
  if (stage === 'RECONCILING') return { label: 'Reconciling', note: 'A repair plan is in progress.' };
  if (stage === 'RESOLVED') return { label: 'Resolved · Verified', note: 'The recorded divergence is resolved.' };
  if (stage === 'STALE') return { label: 'State stale', note: 'Reconnect to obtain current authoritative state.' };
  return { label: 'Not yet observed', note: 'No authoritative external effect is recorded.' };
}

export const IntentRealityHero: React.FC<IntentRealityHeroProps> = ({
  stage,
  gapPx: _gapPx,
  projection,
}) => {
  const intent = projection?.intent ?? null;
  const revision = intent?.active_revision ?? null;
  const observed = useMemo(() => selectObservedWorld(projection), [projection]);
  const activeOperation = useMemo(() => selectActiveOperation(projection), [projection]);
  const rawDesired = useMemo(() => extractDesiredSlot(intent, revision), [intent, revision]);
  const desired = useMemo(() => formatSlotParts(rawDesired), [rawDesired]);
  const reality = useMemo(() => formatSlotParts(observed.rawSlot), [observed.rawSlot]);

  const hasObservedSlot = observed.slot !== null && !reality.unknown;
  const isDiverged = stage === 'DIVERGED';
  const isAligned = stage === 'ALIGNED';
  const status = stateCopy(
    stage,
    isDiverged,
    isAligned,
    activeOperation?.cancellation_state === 'TOO_LATE',
  );

  return (
    <section
      aria-label="Intent and authoritative reality"
      className={`intent-reality intent-reality--${stage.toLowerCase()} ${isDiverged ? 'intent-reality--diverged' : ''}`}
    >
      <div className="intent-reality__heading">
        <span className="editorial-kicker">Intent — Reality</span>
        <span className="editorial-kicker">Authoritative state</span>
      </div>

      <div className="intent-reality__labels" aria-hidden="true">
        <span>Desired</span>
        <span />
        <span>Reality</span>
      </div>

      <div className="intent-reality__values">
        <div className="intent-reality__value">
          {desired.unknown ? '—' : desired.numerals}
          {desired.meridiem && <span className="intent-reality__meridiem">{desired.meridiem}</span>}
        </div>

        <div className="intent-reality__connector" aria-hidden="true">
          {isDiverged && <span className="intent-reality__break">≠</span>}
        </div>

        <div className="intent-reality__value intent-reality__value--reality">
          {hasObservedSlot ? reality.numerals : '—'}
          {hasObservedSlot && reality.meridiem && (
            <span className="intent-reality__meridiem">{reality.meridiem}</span>
          )}
        </div>
      </div>

      <div className="intent-reality__status">
        <span className="editorial-state">{status.label}</span>
        <span className="intent-reality__note">{status.note}</span>
      </div>
    </section>
  );
};
