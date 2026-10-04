import { describe, it, expect } from 'vitest';
import realP0 from './fixtures/real-p0.json';
import scriptedContinuation from './fixtures/scripted-continuation.json';
import { createProjectionStore } from '../../state/store';
import type { ProjectionEventMessage, SessionProjection } from '../../api/types';

const INITIAL_PROJECTION: SessionProjection = {
  intent: null,
  operations: [],
  effects: [],
  evidence: [],
  claims: [],
  divergences: [],
  plans: [],
  speech: [],
  metrics: {
    session_id: '01a1092a-21be-7e8a-bced-0584da056667',
    through_sequence: 0,
    counters: {},
    durations_ms: {},
    gauges: {},
  },
};

describe('Storyboard Fixtures and Playback', () => {
  it('has 31 real P0 events and 10 scripted continuation events', () => {
    expect(realP0.events.length).toBe(31);
    expect(scriptedContinuation.events.length).toBe(10);
    expect(realP0.session_id).toBe(scriptedContinuation.session_id);
  });

  it('replays all 41 events continuously without gaps or errors', () => {
    const store = createProjectionStore();
    const sessionId = realP0.session_id;

    // Apply sequence 0 initial snapshot
    const snapResult = store.applySnapshot({
      type: 'snapshot',
      schema_version: 1,
      session_id: sessionId,
      through_sequence: 0,
      projection: INITIAL_PROJECTION,
    });
    expect(snapResult).toBe('SNAPSHOT_REPLACED');

    const allEvents = [
      ...realP0.events,
      ...scriptedContinuation.events,
    ] as unknown as ProjectionEventMessage[];

    for (const event of allEvents) {
      const result = store.applyEvent(event);
      expect(result).toBe('APPLIED');
    }

    const finalState = store.getState();
    expect(finalState.lastAppliedSequence).toBe(41);
    expect(finalState.error).toBeNull();
    expect(finalState.stale).toBe(false);

    // Verify final state properties
    const proj = finalState.projection;
    expect(proj).not.toBeNull();
    expect(proj?.intent?.active_revision?.values.requested_slot).toBe('2030-01-15T12:00:00+05:30');
    expect(proj?.divergences.length).toBe(1);
    expect(proj?.divergences[0].state).toBe('RESOLVED');
    expect(proj?.speech.length).toBeGreaterThan(0);

    // Final speech is exact wording
    const finalSpeech = proj?.speech[proj.speech.length - 1];
    expect(finalSpeech?.rendered_text).toBe('Confirmed — your 12:00 appointment is booked.');
  });
});
