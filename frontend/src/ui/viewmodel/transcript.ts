import type { SpeechProjection } from '../../api/types';

export interface UserPromptEntry {
  readonly id: string;
  readonly text: string;
  readonly acceptedSequence: number | null;
  readonly failed?: boolean;
}

export interface UserTranscriptItem {
  readonly kind: 'user';
  readonly id: string;
  readonly text: string;
  readonly sequence: number | null;
  readonly failed: boolean;
}

export interface AssistantTranscriptItem {
  readonly kind: 'assistant';
  readonly id: string;
  readonly speech: SpeechProjection;
  readonly sequence: number | null;
}

export type TranscriptItem = UserTranscriptItem | AssistantTranscriptItem;

interface SortableItem {
  readonly item: TranscriptItem;
  readonly sequence: number | null;
  readonly originalIndex: number;
}

/**
 * Merges user prompts and assistant speech chronologically by journal sequence.
 * Items with known sequence appear first in ascending order.
 * Unsequenced items (e.g. pending user input or unapproved speech) appear at the tail in insertion order.
 */
export function mergeTranscript(
  userPrompts: readonly UserPromptEntry[],
  speechList: readonly SpeechProjection[],
): readonly TranscriptItem[] {
  const sortables: SortableItem[] = [];

  // 1. Map user prompts
  userPrompts.forEach((prompt, index) => {
    sortables.push({
      item: {
        kind: 'user',
        id: prompt.id,
        text: prompt.text,
        sequence: prompt.acceptedSequence,
        failed: prompt.failed ?? false,
      },
      sequence: prompt.acceptedSequence,
      originalIndex: index,
    });
  });

  // 2. Map speech items
  speechList.forEach((speech, index) => {
    // Only include if non-empty rendered text or BLOCKED state
    const hasText = typeof speech.rendered_text === 'string' && speech.rendered_text.trim().length > 0;
    const isBlocked = speech.state === 'BLOCKED';

    if (!hasText && !isBlocked) {
      return;
    }

    sortables.push({
      item: {
        kind: 'assistant',
        id: speech.speech_id,
        speech,
        sequence: speech.approved_through_sequence,
      },
      sequence: speech.approved_through_sequence,
      originalIndex: userPrompts.length + index,
    });
  });

  // 3. Stable sort
  sortables.sort((a, b) => {
    const seqA = a.sequence;
    const seqB = b.sequence;

    if (seqA !== null && seqB !== null) {
      if (seqA !== seqB) return seqA - seqB;
      return a.originalIndex - b.originalIndex;
    }

    if (seqA !== null && seqB === null) return -1;
    if (seqA === null && seqB !== null) return 1;

    return a.originalIndex - b.originalIndex;
  });

  return sortables.map((s) => s.item);
}
