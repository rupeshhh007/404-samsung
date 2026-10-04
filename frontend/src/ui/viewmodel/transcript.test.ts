import { describe, it, expect } from 'vitest';
import { mergeTranscript, type UserPromptEntry } from './transcript';
import type { SpeechProjection } from '../../api/types';

function createMockSpeech(overrides: Partial<SpeechProjection> = {}): SpeechProjection {
  return {
    speech_id: 's1',
    act_type: 'RESULT',
    template_id: 'tmpl-1',
    slots: {},
    claim_ids: [],
    requested_certainty: 'CONFIRMED',
    state: 'EMITTED',
    created_by_event_id: 'evt-1',
    schema_version: 1,
    supersedes_speech_id: null,
    rendered_text: 'Confirmed',
    approved_policy_id: 'pol-1',
    approved_through_sequence: 2,
    approved_claim_versions: {},
    heard: true,
    cancellation_pending: false,
    correction_pending: false,
    ...overrides,
  };
}

describe('viewmodel/transcript', () => {
  it('correctly interleaves user prompts and assistant speech by sequence', () => {
    const userPrompts: UserPromptEntry[] = [
      { id: 'u1', text: 'Book 11:00.', acceptedSequence: 1 },
      { id: 'u2', text: 'Actually make it 12:00.', acceptedSequence: 3 },
    ];

    const speechList: SpeechProjection[] = [
      createMockSpeech({
        speech_id: 's1',
        rendered_text: 'Booked 11:00 AM.',
        approved_through_sequence: 2,
      }),
    ];

    const merged = mergeTranscript(userPrompts, speechList);
    expect(merged.length).toBe(3);
    expect(merged[0]?.kind).toBe('user');
    expect(merged[0]?.sequence).toBe(1);
    expect(merged[1]?.kind).toBe('assistant');
    expect(merged[1]?.sequence).toBe(2);
    expect(merged[2]?.kind).toBe('user');
    expect(merged[2]?.sequence).toBe(3);
  });

  it('puts unsequenced/pending user prompt at the end', () => {
    const userPrompts: UserPromptEntry[] = [
      { id: 'u1', text: 'Prompt 1', acceptedSequence: 5 },
      { id: 'u2', text: 'Pending prompt', acceptedSequence: null },
    ];
    const speechList: SpeechProjection[] = [];

    const merged = mergeTranscript(userPrompts, speechList);
    expect(merged.length).toBe(2);
    expect(merged[0]?.id).toBe('u1');
    expect(merged[1]?.id).toBe('u2');
    expect(merged[1]?.sequence).toBeNull();
  });

  it('ignores empty rendered text unless state is BLOCKED', () => {
    const speechList: SpeechProjection[] = [
      createMockSpeech({
        speech_id: 'empty',
        state: 'PROPOSED',
        rendered_text: '',
        approved_through_sequence: 1,
      }),
      createMockSpeech({
        speech_id: 'blocked',
        state: 'BLOCKED',
        rendered_text: null,
        approved_through_sequence: 2,
      }),
    ];

    const merged = mergeTranscript([], speechList);
    expect(merged.length).toBe(1);
    expect(merged[0]?.id).toBe('blocked');
  });
});
