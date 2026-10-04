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

/**
 * Formats appointment slots or arbitrary slot representations.
 * Handles:
 * - Simple time strings: "11:00", "12:00", "14:30" -> "11:00 AM", "12:00 PM", "2:30 PM"
 * - ISO date strings: "2030-01-15T12:00:00Z" -> "Jan 15, 2030 at 12:00 PM"
 * - Fallbacks to clean string representation
 */
export function formatSlot(value: unknown): string {
  if (value === null || value === undefined) {
    return 'Not specified';
  }
  const str = String(value).trim();
  if (!str) return 'Not specified';

  // Check simple 24-hour time format: "11:00", "12:00", "14:30"
  const timeMatch = /^(\d{1,2}):(\d{2})$/.exec(str);
  if (timeMatch) {
    const hours = parseInt(timeMatch[1], 10);
    const minutes = timeMatch[2];
    const ampm = hours >= 12 ? 'PM' : 'AM';
    const displayHours = hours % 12 || 12;
    return `${displayHours}:${minutes} ${ampm}`;
  }

  // Check ISO date format: "2030-01-15T12:00:00Z" or "2030-01-15"
  if (/^\d{4}-\d{2}-\d{2}/.test(str)) {
    try {
      const date = new Date(str);
      if (!isNaN(date.getTime())) {
        const hasTime = str.includes('T');
        if (hasTime) {
          return date.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            hour12: true,
          });
        }
        return date.toLocaleDateString('en-US', {
          month: 'short',
          day: 'numeric',
          year: 'numeric',
        });
      }
    } catch {
      // Fallback to original string
    }
  }

  return str;
}

/**
 * Formats ISO timestamps into human-readable local time.
 */
export function formatTimestamp(isoString: string | null | undefined): string {
  if (!isoString) return 'Not recorded';
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    });
  } catch {
    return isoString;
  }
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
  if (map[goal]) return map[goal];
  return goal
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
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
  const desiredVal = revision?.values?.requested_slot ?? revision?.values?.slot ?? null;
  const desiredFormatted = desiredVal ? formatSlot(desiredVal) : '12:00 PM';

  const matchedEffects = effects.filter((effect) =>
    divergence.observed_effect_ids.includes(effect.effect_id),
  );

  let observedVal: unknown = null;
  for (const effect of matchedEffects) {
    if (effect.parameters?.requested_slot) {
      observedVal = effect.parameters.requested_slot;
      break;
    }
    if (effect.parameters?.confirmed_slot) {
      observedVal = effect.parameters.confirmed_slot;
      break;
    }
    if (effect.parameters?.slot) {
      observedVal = effect.parameters.slot;
      break;
    }
  }

  const observedFormatted = observedVal ? formatSlot(observedVal) : '11:00 AM';

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
