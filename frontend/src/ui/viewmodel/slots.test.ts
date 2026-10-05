import { describe, it, expect } from 'vitest';
import { parseSlot, formatSlotParts, selectObservedWorld } from './slots';

describe('viewmodel/slots', () => {
  it('parses and formats 2030-01-15T11:00:00+05:30 with explicit offset without zone shifting', () => {
    const parts = formatSlotParts('2030-01-15T11:00:00+05:30');
    expect(parts.numerals).toBe('11:00');
    expect(parts.meridiem).toBe('AM');
    expect(parts.zone).toBe('UTC+05:30');
    expect(parts.dateLabel).toBe('Jan 15, 2030');
    expect(parts.unknown).toBe(false);
  });

  it('parses and formats 2030-01-15T12:00:00+05:30 identically', () => {
    const parts = formatSlotParts('2030-01-15T12:00:00+05:30');
    expect(parts.numerals).toBe('12:00');
    expect(parts.meridiem).toBe('PM');
    expect(parts.zone).toBe('UTC+05:30');
    expect(parts.dateLabel).toBe('Jan 15, 2030');
  });

  it('parses and formats ISO string with Z offset as UTC', () => {
    const parts = formatSlotParts('2030-01-15T05:30:00Z');
    expect(parts.numerals).toBe('5:30');
    expect(parts.meridiem).toBe('AM');
    expect(parts.zone).toBe('UTC');
    expect(parts.dateLabel).toBe('Jan 15, 2030');
  });

  it('parses bare 24-hour time 14:30', () => {
    const parts = formatSlotParts('14:30');
    expect(parts.numerals).toBe('2:30');
    expect(parts.meridiem).toBe('PM');
    expect(parts.zone).toBeNull();
    expect(parts.dateLabel).toBeNull();
  });

  it('handles null and undefined gracefully as unknown', () => {
    const partsNull = formatSlotParts(null);
    expect(partsNull.unknown).toBe(true);
    expect(partsNull.numerals).toBe('—:——');
    expect(partsNull.formatted).toBe('—');

    const partsUndefined = formatSlotParts(undefined);
    expect(partsUndefined.unknown).toBe(true);
    expect(partsUndefined.numerals).toBe('—:——');
  });

  it('handles invalid/garbage strings safely', () => {
    const parts = formatSlotParts('not-a-date');
    expect(parts.unknown).toBe(false);
    expect(parts.numerals).toBe('not-a-date');
  });

  describe('selectObservedWorld', () => {
    const createMockEffect = (overrides = {}) => ({
      effect_id: 'eff-1',
      logical_action_id: 'act-1',
      operation_id: 'op-1',
      provider_effect_id: 'p-1',
      effect_type: 'appointment.booking',
      subject: {},
      parameters: { confirmed_slot: '2030-01-15T11:00:00+05:30' },
      state: 'COMMITTED' as const,
      observed_at: '2030-01-15T10:00:00Z',
      authority: 'AUTHORITATIVE' as const,
      evidence_ids: ['ev-1'],
      schema_version: 1 as const,
      supersedes_effect_id: null,
      ...overrides,
    });

    it('selects observed reality when NO divergence exists (Rule B)', () => {
      const projection = {
        intent: null,
        operations: [],
        effects: [createMockEffect()],
        evidence: [],
        claims: [],
        divergences: [],
        plans: [],
        speech: [],
        metrics: { session_id: 's1', through_sequence: 1, counters: {}, durations_ms: {}, gauges: {} },
      };
      const world = selectObservedWorld(projection);
      expect(world.slot).toBe('Jan 15, 2030 11:00 AM UTC+05:30');
      expect(world.rawSlot).toBe('2030-01-15T11:00:00+05:30');
      expect(world.state).toBe('COMMITTED');
      expect(world.authority).toBe('AUTHORITATIVE');
      expect(world.divergence).toBeNull();
    });

    it('selects divergence observed effect when active divergence exists (Rule A)', () => {
      const effect1 = createMockEffect({
        effect_id: 'eff-1',
        parameters: { confirmed_slot: '2030-01-15T11:00:00+05:30' },
        observed_at: '2030-01-15T10:00:00Z',
      });
      const effect2 = createMockEffect({
        effect_id: 'eff-2',
        parameters: { confirmed_slot: '2030-01-15T12:00:00+05:30' },
        observed_at: '2030-01-15T10:05:00Z',
      });
      const projection = {
        intent: null,
        operations: [],
        effects: [effect1, effect2],
        evidence: [],
        claims: [],
        divergences: [
          {
            divergence_id: 'div-1',
            desired_fingerprint: 'fp-1',
            observed_effect_ids: ['eff-1'],
            kind: 'DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT',
            state: 'OPEN' as const,
            detected_by_event_id: 'e1',
            authorization_required: true,
            schema_version: 1 as const,
          },
        ],
        plans: [],
        speech: [],
        metrics: { session_id: 's1', through_sequence: 1, counters: {}, durations_ms: {}, gauges: {} },
      };
      const world = selectObservedWorld(projection);
      expect(world.rawSlot).toBe('2030-01-15T11:00:00+05:30');
      expect(world.effectId).toBe('eff-1');
      expect(world.divergence?.state).toBe('OPEN');
    });

    it('returns null fields when no effects are present (Rule D)', () => {
      const projection = {
        intent: null,
        operations: [],
        effects: [],
        evidence: [],
        claims: [],
        divergences: [],
        plans: [],
        speech: [],
        metrics: { session_id: 's1', through_sequence: 1, counters: {}, durations_ms: {}, gauges: {} },
      };
      const world = selectObservedWorld(projection);
      expect(world.slot).toBeNull();
      expect(world.rawSlot).toBeNull();
      expect(world.state).toBeNull();
      expect(world.authority).toBeNull();
      expect(world.effectId).toBeNull();
    });

    it('correctly reports non-committed effect when selected', () => {
      const inFlightEffect = createMockEffect({
        state: 'IN_FLIGHT' as const,
        parameters: { requested_slot: '2030-01-15T11:00:00+05:30' },
      });
      const projection = {
        intent: null,
        operations: [],
        effects: [inFlightEffect],
        evidence: [],
        claims: [],
        divergences: [
          {
            divergence_id: 'div-1',
            desired_fingerprint: 'fp-1',
            observed_effect_ids: ['eff-1'],
            kind: 'SLOT_MISMATCH',
            state: 'OPEN' as const,
            detected_by_event_id: 'e1',
            authorization_required: false,
            schema_version: 1 as const,
          },
        ],
        plans: [],
        speech: [],
        metrics: { session_id: 's1', through_sequence: 1, counters: {}, durations_ms: {}, gauges: {} },
      };
      const world = selectObservedWorld(projection);
      expect(world.state).toBe('IN_FLIGHT');
      expect(world.rawSlot).toBe('2030-01-15T11:00:00+05:30');
    });

    it('orders by observed_at descending, NOT array index or ID lexicographic order', () => {
      // eff-99 was observed EARLIER (10:00) but has higher string ID
      const earlier = createMockEffect({
        effect_id: 'eff-99',
        observed_at: '2030-01-15T10:00:00Z',
        parameters: { confirmed_slot: '2030-01-15T11:00:00+05:30' },
      });
      // eff-01 was observed LATER (11:00) but has lower string ID
      const later = createMockEffect({
        effect_id: 'eff-01',
        observed_at: '2030-01-15T11:00:00Z',
        parameters: { confirmed_slot: '2030-01-15T12:00:00+05:30' },
      });

      // Array has eff-99 after eff-01
      const projection = {
        intent: null,
        operations: [],
        effects: [later, earlier],
        evidence: [],
        claims: [],
        divergences: [],
        plans: [],
        speech: [],
        metrics: { session_id: 's1', through_sequence: 1, counters: {}, durations_ms: {}, gauges: {} },
      };
      const world = selectObservedWorld(projection);
      // Must pick the later effect (eff-01 at 12:00)
      expect(world.effectId).toBe('eff-01');
      expect(world.rawSlot).toBe('2030-01-15T12:00:00+05:30');
    });
  });
});
