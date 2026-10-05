import { describe, it, expect } from 'vitest';
import realP0 from './fixtures/real-p0.json';
import { createProjectionStore } from '../../state/store';
import type { ProjectionEventMessage, SessionProjection } from '../../api/types';
import { StoryboardClient } from './StoryboardClient';

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
  it('does not surface the correction before its observed input event', () => {
    const client = new StoryboardClient(createProjectionStore());
    client.init(11);
    expect(client.getUserPrompts().map((prompt) => prompt.text)).toEqual(['Book 11:00.']);

    client.jumpTo(12);
    expect(client.getUserPrompts().map((prompt) => prompt.text)).toEqual([
      'Book 11:00.',
      'Actually, make it 12:00.',
    ]);
  });

  it('has 31 real P0 events', () => {
    expect(realP0.events.length).toBe(31);
    expect(realP0.session_id).toBe('01a1092a-21be-7e8a-bced-0584da056667');
  });

  it('replays all 31 real P0 events continuously without gaps or errors', () => {
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

    const allEvents = realP0.events as unknown as ProjectionEventMessage[];

    for (const event of allEvents) {
      const result = store.applyEvent(event);
      expect(result).toBe('APPLIED');
    }

    const finalState = store.getState();
    expect(finalState.lastAppliedSequence).toBe(31);
    expect(finalState.error).toBeNull();
    expect(finalState.stale).toBe(false);

    // Verify final state properties for P0 race
    const proj = finalState.projection;
    expect(proj).not.toBeNull();
    expect(proj?.intent?.active_revision?.values.requested_slot).toBe('2030-01-15T12:00:00+05:30');
    expect(proj?.divergences.length).toBe(1);
    expect(proj?.divergences[0].state).toBe('OPEN');
    expect(proj?.speech.length).toBeGreaterThan(0);
  });
});
