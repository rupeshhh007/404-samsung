import { useMemo } from 'react';
import { applyProjectionDelta } from '../../state/projections';
import type { ProjectionEventMessage, SessionProjection } from '../../api/types';

export function createEmptyProjection(sessionId: string): SessionProjection {
  return {
    intent: null,
    operations: [],
    effects: [],
    evidence: [],
    claims: [],
    divergences: [],
    plans: [],
    speech: [],
    metrics: {
      session_id: sessionId,
      through_sequence: 0,
      counters: {},
      durations_ms: {},
      gauges: {},
    },
  };
}

export interface TimeTravelState {
  readonly projectionsBySequence: ReadonlyMap<number, SessionProjection>;
  readonly isHistoryIncomplete: boolean;
  readonly maxSequence: number;
}

export function useTimeTravel(
  sessionId: string | null,
  events: readonly ProjectionEventMessage[],
): TimeTravelState {
  return useMemo(() => {
    if (!sessionId || events.length === 0) {
      return {
        projectionsBySequence: new Map(),
        isHistoryIncomplete: false,
        maxSequence: 0,
      };
    }

    // Sort events strictly by sequence
    const sorted = [...events].sort((a, b) => a.sequence - b.sequence);

    // If first event is not sequence 1, history is incomplete
    const isHistoryIncomplete = (sorted[0]?.sequence ?? 1) > 1;

    const projectionsMap = new Map<number, SessionProjection>();
    let current = createEmptyProjection(sessionId);

    for (const evt of sorted) {
      current = applyProjectionDelta(current, evt.projection_delta);
      projectionsMap.set(evt.sequence, current);
    }

    const maxSequence = sorted[sorted.length - 1]?.sequence ?? 0;

    return {
      projectionsBySequence: projectionsMap,
      isHistoryIncomplete,
      maxSequence,
    };
  }, [sessionId, events]);
}
