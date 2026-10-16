import { describe, it, expect } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AssistantLine } from './AssistantLine';
import type { SpeechProjection } from '../../api/types';

function mockSpeech(overrides: Partial<SpeechProjection> = {}): SpeechProjection {
  return {
    speech_id: 's1',
    act_type: 'RESULT',
    template_id: 'tmpl-1',
    slots: {},
    claim_ids: ['claim-1'],
    requested_certainty: 'CONFIRMED',
    state: 'EMITTED',
    created_by_event_id: 'evt-1',
    schema_version: 1,
    supersedes_speech_id: null,
    rendered_text: 'Confirmed — your eleven o’clock appointment is booked.',
    approved_policy_id: 'pol-1',
    approved_through_sequence: 5,
    approved_claim_versions: { 'claim-1': 'evt-1' },
    heard: true,
    cancellation_pending: false,
    correction_pending: false,
    ...overrides,
  };
}

describe('AssistantLine truthful verification status', () => {
  it('renders TRUTHLOCK · Verified for confirmed emitted speech heard by user', () => {
    const markup = renderToStaticMarkup(createElement(AssistantLine, {
      speech: mockSpeech({ state: 'EMITTED', heard: true }),
    }));
    expect(markup).toContain('TRUTHLOCK · Verified');
    expect(markup).not.toContain('Cancelled');
    expect(markup).not.toContain('Correction required');
  });

  it('renders Cancelled mid-speech with strikethrough when speech was cancelled', () => {
    const markup = renderToStaticMarkup(createElement(AssistantLine, {
      speech: mockSpeech({ state: 'CANCELLED', heard: true }),
    }));
    expect(markup).toContain('Cancelled mid-speech');
    expect(markup).toContain('line-through');
    expect(markup).not.toContain('TRUTHLOCK · Verified');
  });

  it('renders Cancelled mid-speech when cancellation_pending is true', () => {
    const markup = renderToStaticMarkup(createElement(AssistantLine, {
      speech: mockSpeech({ state: 'EMITTING', cancellation_pending: true, heard: null }),
    }));
    expect(markup).toContain('Cancelled mid-speech');
    expect(markup).not.toContain('TRUTHLOCK · Verified');
  });

  it('renders TRUTHLOCK · Correction required when correction is required', () => {
    const markup = renderToStaticMarkup(createElement(AssistantLine, {
      speech: mockSpeech({ state: 'CORRECTION_REQUIRED', heard: true }),
    }));
    expect(markup).toContain('TRUTHLOCK · Correction required');
    expect(markup).not.toContain('TRUTHLOCK · Verified');
  });

  it('renders TRUTHLOCK · Playing... while emitting or queued', () => {
    const markup = renderToStaticMarkup(createElement(AssistantLine, {
      speech: mockSpeech({ state: 'EMITTING', heard: null }),
    }));
    expect(markup).toContain('TRUTHLOCK · Playing...');
    expect(markup).not.toContain('TRUTHLOCK · Verified');
  });

  it('renders TRUTHLOCK · Not heard when delivery completed unheard', () => {
    const markup = renderToStaticMarkup(createElement(AssistantLine, {
      speech: mockSpeech({ state: 'EMITTED', heard: false }),
    }));
    expect(markup).toContain('TRUTHLOCK · Not heard');
    expect(markup).not.toContain('TRUTHLOCK · Verified');
  });
});
