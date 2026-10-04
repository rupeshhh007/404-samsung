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
 * - ISO date strings: "2030-01-15T12:00:00Z" -> "Jan 15, 2030 at 12:00 PM"
 * - Simple time strings: "12:00", "11:00" -> "12:00 PM", "11:00 AM"
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
 * Formats ISO timestamps into human-readable local time or compact time.
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
 * e.g. "7a8f12c4...e4b9" -> "7a8f...e4b9"
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
  // Convert dot or snake notation: "tool.some_action" -> "Tool: Some Action"
  return name
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Humanizes effect types.
 */
export function formatEffectType(type: string): string {
  const map: Record<string, string> = {
    'appointment.booked': 'Booking Confirmed',
    'appointment.cancelled': 'Booking Cancelled',
    'appointment.rescheduled': 'Booking Rescheduled',
  };
  if (map[type]) return map[type];
  return type
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Humanizes claim predicates.
 */
export function formatPredicate(predicate: string): string {
  const map: Record<string, string> = {
    appointment_booked: 'Appointment Booked',
    slot_available: 'Slot Available',
    identity_verified: 'Identity Verified',
    payment_authorized: 'Payment Authorized',
  };
  if (map[predicate]) return map[predicate];
  return predicate
    .replace(/[._]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Formats goal types into clean action verbs.
 */
export function formatGoalType(goal: string): string {
  const map: Record<string, string> = {
    'appointment.schedule': 'Schedule Appointment',
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
 * Humanizes cancellation states.
 */
export function formatCancellationState(state: string): { label: string; tone: 'neutral' | 'warning' | 'active' | 'success' } {
  switch (state) {
    case 'TOO_LATE':
      return { label: 'Too late (committed)', tone: 'warning' };
    case 'REQUESTED':
      return { label: 'Cancellation requested', tone: 'active' };
    case 'ACKNOWLEDGED':
      return { label: 'Cancelled at safepoint', tone: 'success' };
    case 'REJECTED':
      return { label: 'Cancellation rejected', tone: 'warning' };
    case 'NONE':
    default:
      return { label: 'None', tone: 'neutral' };
  }
}

/**
 * Humanizes operation state and produces clean status information.
 */
export function formatOperationState(state: string): { label: string; tone: 'neutral' | 'active' | 'success' | 'warning' | 'danger' } {
  switch (state) {
    case 'SUCCEEDED':
      return { label: 'Completed', tone: 'success' };
    case 'DISPATCHED':
      return { label: 'Dispatched', tone: 'active' };
    case 'WAITING':
      return { label: 'In flight', tone: 'active' };
    case 'PREPARING':
    case 'READY':
      return { label: 'Preparing', tone: 'neutral' };
    case 'TIMED_OUT':
      return { label: 'Timed out', tone: 'warning' };
    case 'FAILED':
      return { label: 'Failed', tone: 'danger' };
    case 'CANCELLED':
      return { label: 'Cancelled', tone: 'warning' };
    default:
      return { label: state, tone: 'neutral' };
  }
}

/**
 * Humanizes effect state.
 */
export function formatEffectState(state: string): { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' } {
  switch (state) {
    case 'COMMITTED':
      return { label: 'Committed to reality', tone: 'success' };
    case 'IN_FLIGHT':
      return { label: 'In flight', tone: 'warning' };
    case 'OUTCOME_UNKNOWN':
      return { label: 'Outcome uncertain', tone: 'warning' };
    case 'FAILED':
      return { label: 'Failed', tone: 'danger' };
    case 'COMPENSATED':
      return { label: 'Reverted', tone: 'neutral' };
    default:
      return { label: state, tone: 'neutral' };
  }
}

/**
 * Humanizes claim state.
 */
export function formatClaimState(state: string): { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' } {
  switch (state) {
    case 'CONFIRMED':
      return { label: 'Verified', tone: 'success' };
    case 'PENDING':
      return { label: 'Awaiting evidence', tone: 'warning' };
    case 'UNCERTAIN':
      return { label: 'Unverified', tone: 'warning' };
    case 'CONTRADICTED':
      return { label: 'Contradicted', tone: 'danger' };
    case 'SUPERSEDED':
      return { label: 'Superseded', tone: 'neutral' };
    case 'STALE':
      return { label: 'Stale', tone: 'warning' };
    default:
      return { label: state, tone: 'neutral' };
  }
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
  desiredSummary: string;
  observedSummary: string;
} {
  // Extract desired slot from active revision values
  const desiredSlot = revision?.values?.requested_slot ?? revision?.values?.slot ?? null;
  const desiredFormatted = desiredSlot ? formatSlot(desiredSlot) : 'Unspecified slot';

  // Find observed effects matched with this divergence
  const matchedEffects = effects.filter((effect) =>
    divergence.observed_effect_ids.includes(effect.effect_id),
  );

  let observedSlot: unknown = null;
  for (const effect of matchedEffects) {
    if (effect.parameters?.requested_slot) {
      observedSlot = effect.parameters.requested_slot;
      break;
    }
    if (effect.parameters?.slot) {
      observedSlot = effect.parameters.slot;
      break;
    }
  }

  const observedFormatted = observedSlot ? formatSlot(observedSlot) : 'Committed prior effect';

  if (divergence.kind === 'DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT') {
    return {
      headline: 'Intent & World Mismatch',
      explanation: `The user revised their goal to ${desiredFormatted}, but the external provider has already confirmed a booking for ${observedFormatted}.`,
      desiredSummary: `Desired: ${desiredFormatted}`,
      observedSummary: `Observed in world: ${observedFormatted}`,
    };
  }

  return {
    headline: 'State Divergence Detected',
    explanation: 'A discrepancy exists between active intent and observed provider state.',
    desiredSummary: `Desired: ${desiredFormatted}`,
    observedSummary: `Observed: ${observedFormatted}`,
  };
}
