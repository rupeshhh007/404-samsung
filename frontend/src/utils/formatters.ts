/**
 * Presentation formatters for the INTERLOCK product interface.
 *
 * Transforms internal protocol values, raw IDs, and machine enums into
 * human-readable, high-signal presentation copy while preserving
 * underlying semantic truth.
 */

import type {
  DivergenceProjection,
  EffectProjection,
  IntentProjection,
  IntentRevision,
} from '../api/types';
import {
  formatSlotParts,
  extractDesiredSlot,
  extractObservedSlot,
} from '../ui/viewmodel/slots';

/**
 * Formats appointment slots or arbitrary slot representations.
 * Preserves literal wall-clock time and timezone offset without local Date conversion.
 */
export function formatSlot(value: unknown): string {
  const parts = formatSlotParts(value);
  return parts.formatted;
}

/**
 * Formats ISO timestamps into human-readable representation.
 */
export function formatTimestamp(isoString: string | null | undefined): string {
  if (!isoString) return 'Not recorded';
  const parts = formatSlotParts(isoString);
  if (!parts.unknown && parts.formatted !== '—') {
    return parts.formatted;
  }
  return isoString;
}

/**
 * Truncates long UUIDs or hashes to clean display strings.
 * e.g. "01a1084d-58bb-79a3-8fcb-8d0efbeb5b68" -> "01a1...5b68"
 */
export function shortenId(id: string | null | undefined, head = 6, tail = 4): string {
  if (!id) return '—';
  if (id.length <= head + tail + 3) return id;
  return `${id.slice(0, head)}…${id.slice(-tail)}`;
}

/**
 * Humanizes tool and operation names.
 */
export function formatToolName(name: string): string {
  const map: Record<string, string> = {
    'appointment.book': 'Book Appointment',
    'appointment.cancel': 'Cancel Appointment',
    'appointment.reschedule': 'Reschedule Appointment',
    'calendar.check': 'Check Availability',
    'samsung.book': 'Book Samsung Appointment',
  };
  if (map[name]) return map[name];
  return name
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Formats goal types into clean action verbs.
 */
export function formatGoalType(goal: string): string {
  const map: Record<string, string> = {
    'appointment.schedule': 'Book Appointment',
    'appointment.reschedule': 'Reschedule Appointment',
    'appointment.cancel': 'Cancel Appointment',
    'inquiry': 'General Inquiry',
  };
  return map[goal] ?? goal.replace(/[._]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Humanizes cancellation state into clean display info.
 */
export function formatCancellationState(state: string): { label: string } {
  switch (state) {
    case 'TOO_LATE':
      return { label: 'Cancellation too late (already committed)' };
    case 'REQUESTED':
      return { label: 'Cancellation requested' };
    case 'ACKNOWLEDGED':
      return { label: 'Cancelled at safepoint' };
    case 'REJECTED':
      return { label: 'Cancellation rejected' };
    case 'NONE':
    default:
      return { label: 'None' };
  }
}

/**
 * Humanizes canonical event names for the Trace timeline.
 */
export function humanizeEventName(eventType: string): string {
  const map: Record<string, string> = {
    SessionStarted: 'Session Initialized',
    InputAccepted: 'User Input Accepted',
    IntentRevisionCommitted: 'Intent Committed',
    IntentAuthorizationChanged: 'Authorization Updated',
    ToolDispatchRequested: 'Tool Operation Dispatched',
    ToolResultObserved: 'Tool Result Received',
    WorldEffectObserved: 'World Effect Observed',
    DivergenceDetected: 'Reality Divergence Detected',
    SpeechEmissionStarted: 'Assistant Speech Started',
    SpeechEmissionCompleted: 'Assistant Speech Completed',
    SpeechCancelled: 'Assistant Speech Cancelled',
    CancellationRequested: 'Cancellation Requested',
    CancellationAcknowledged: 'Cancellation Acknowledged',
    DemoFaultConfigured: 'Fault Injected',
  };
  return map[eventType] ?? eventType.replace(/([A-Z])/g, ' $1').trim();
}

/**
 * Produces a clear, plain-English explanation for an active divergence.
 * Never invents fallback slot strings when missing.
 */
export function explainDivergence(
  divergence: DivergenceProjection,
  intent: IntentProjection | null,
  revision: IntentRevision | null,
  effects: readonly EffectProjection[],
): {
  headline: string;
  explanation: string;
  desiredSlot: string;
  observedSlot: string;
} {
  const rawDesired = extractDesiredSlot(intent, revision);
  const desiredFormatted = rawDesired ? formatSlot(rawDesired) : '—';

  const rawObserved = extractObservedSlot(divergence, effects);
  const observedFormatted = rawObserved ? formatSlot(rawObserved) : '—';

  if (divergence.kind === 'DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT') {
    return {
      headline: 'REALITY MISMATCH',
      explanation: 'The previous booking completed before cancellation could take effect. The external calendar contains a different slot than requested.',
      desiredSlot: desiredFormatted,
      observedSlot: observedFormatted,
    };
  }

  return {
    headline: 'REALITY MISMATCH',
    explanation: 'A discrepancy exists between your active goal and the external confirmed reality.',
    desiredSlot: desiredFormatted,
    observedSlot: observedFormatted,
  };
}
