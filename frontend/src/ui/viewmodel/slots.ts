import type {
  DivergenceProjection,
  EffectProjection,
  EffectState,
  EvidenceAuthority,
  IntentProjection,
  IntentRevision,
  OperationProjection,
  ReconciliationPlanProjection,
  SessionProjection,
} from '../../api/types';

export interface ParsedSlot {
  readonly date: string | null;
  readonly time: string | null;
  readonly offset: string | null;
  readonly raw: string;
}

export interface SlotParts {
  readonly numerals: string;
  readonly meridiem: string;
  readonly zone: string | null;
  readonly dateLabel: string | null;
  readonly unknown: boolean;
  readonly formatted: string;
}

const MONTH_NAMES = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/**
 * Parses literal slot strings into date/time/offset parts without using JavaScript Date timezone conversion.
 * Matches:
 * - ISO formats: "YYYY-MM-DDTHH:MM(:SS)?(Z|±HH:MM)?"
 * - Bare date: "YYYY-MM-DD"
 * - Bare time: "HH:MM"
 */
export function parseSlot(value: unknown): ParsedSlot | null {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim();
  if (!raw) return null;

  // Regex matching ISO-like date-time strings:
  // e.g. 2030-01-15T12:00:00+05:30 or 2030-01-15T12:00:00Z or 2030-01-15
  const isoRegex = /^(\d{4}-\d{2}-\d{2})(?:T(\d{1,2}:\d{2})(?::\d{2})?(Z|[+-]\d{2}:\d{2})?)?$/;
  const isoMatch = isoRegex.exec(raw);
  if (isoMatch) {
    return {
      date: isoMatch[1] ?? null,
      time: isoMatch[2] ?? null,
      offset: isoMatch[3] ?? null,
      raw,
    };
  }

  // Bare time format: "11:00", "12:00", "14:30"
  const timeRegex = /^(\d{1,2}:\d{2})$/;
  const timeMatch = timeRegex.exec(raw);
  if (timeMatch) {
    return {
      date: null,
      time: timeMatch[1] ?? null,
      offset: null,
      raw,
    };
  }

  return {
    date: null,
    time: null,
    offset: null,
    raw,
  };
}

/**
 * Compares two slot values semantically without timezone corruption.
 */
export function matchSlots(actual: unknown, desired: unknown): boolean {
  if (actual === desired) return true;
  if (!actual || !desired) return false;
  const pA = parseSlot(actual);
  const pB = parseSlot(desired);
  if (!pA || !pB) return false;
  if (pA.time && pB.time && pA.time === pB.time) {
    if (pA.date && pB.date) {
      return pA.date === pB.date;
    }
    return true;
  }
  return pA.raw === pB.raw;
}

/**
 * Formats slot parts cleanly for the UI without any timezone conversion.
 * Unknown/absent values return { numerals: "—:——", meridiem: "", ... }
 */
export function formatSlotParts(value: unknown): SlotParts {
  const parsed = parseSlot(value);
  if (!parsed || (!parsed.time && !parsed.date && parsed.raw.length === 0)) {
    return {
      numerals: '—:——',
      meridiem: '',
      zone: null,
      dateLabel: null,
      unknown: true,
      formatted: '—',
    };
  }

  // Determine Zone Label
  let zone: string | null = null;
  if (parsed.offset === 'Z') {
    zone = 'UTC';
  } else if (parsed.offset) {
    zone = `UTC${parsed.offset}`;
  }

  // Determine Date Label
  let dateLabel: string | null = null;
  if (parsed.date) {
    const [yearStr, monthStr, dayStr] = parsed.date.split('-');
    const monthIdx = parseInt(monthStr ?? '0', 10) - 1;
    const day = parseInt(dayStr ?? '0', 10);
    const month = MONTH_NAMES[monthIdx] ?? monthStr;
    dateLabel = `${month} ${day}, ${yearStr}`;
  }

  // If time is present, convert 24h -> 12h numerals and meridiem
  if (parsed.time) {
    const [hStr, mStr] = parsed.time.split(':');
    const h = parseInt(hStr ?? '0', 10);
    const meridiem = h >= 12 ? 'PM' : 'AM';
    const displayH = h % 12 || 12;
    const numerals = `${displayH}:${mStr}`;

    const formattedParts: string[] = [];
    if (dateLabel) formattedParts.push(dateLabel);
    formattedParts.push(`${numerals} ${meridiem}`);
    if (zone) formattedParts.push(zone);

    return {
      numerals,
      meridiem,
      zone,
      dateLabel,
      unknown: false,
      formatted: formattedParts.join(' '),
    };
  }

  // If only date is present
  if (dateLabel) {
    return {
      numerals: dateLabel,
      meridiem: '',
      zone,
      dateLabel,
      unknown: false,
      formatted: zone ? `${dateLabel} ${zone}` : dateLabel,
    };
  }

  // Fallback for raw unrecognized string
  return {
    numerals: parsed.raw,
    meridiem: '',
    zone: null,
    dateLabel: null,
    unknown: false,
    formatted: parsed.raw,
  };
}

/**
 * Extracts the desired slot value from the active revision.
 */
export function extractDesiredSlot(
  intent: IntentProjection | null,
  revision: IntentRevision | null,
): string | null {
  if (!revision) return null;
  const values = revision.values;
  if (!values) return null;
  const slotVal = values.requested_slot ?? values.slot;
  return typeof slotVal === 'string' ? slotVal : null;
}

/**
 * Extracts the observed slot value from the divergence and matching effects.
 * Prefers confirmed_slot over requested_slot or slot.
 * Works even when divergence is null (external reality exists independent of divergence).
 */
export function extractObservedSlot(
  divergence: DivergenceProjection | null,
  effects: readonly EffectProjection[],
): string | null {
  if (divergence && divergence.observed_effect_ids && divergence.observed_effect_ids.length > 0) {
    const observedEffectIds = new Set(divergence.observed_effect_ids);
    const matchedEffects = effects.filter((e) => observedEffectIds.has(e.effect_id));

    for (const effect of matchedEffects) {
      const params = effect.parameters;
      if (typeof params.confirmed_slot === 'string') return params.confirmed_slot;
      if (typeof params.requested_slot === 'string') return params.requested_slot;
      if (typeof params.slot === 'string') return params.slot;
    }
  }

  // If none found in divergence observed effects, check all committed effects
  for (const effect of effects) {
    if (effect.state === 'COMMITTED') {
      const params = effect.parameters;
      if (typeof params.confirmed_slot === 'string') return params.confirmed_slot;
      if (typeof params.requested_slot === 'string') return params.requested_slot;
      if (typeof params.slot === 'string') return params.slot;
    }
  }

  return null;
}

export interface ObservedWorld {
  readonly slot: string | null;
  readonly rawSlot: string | null;
  readonly state: EffectState | null;
  readonly authority: EvidenceAuthority | null;
  readonly effectId: string | null;
  readonly divergence: DivergenceProjection | null;
}

/**
 * Pure selector: select active divergence by semantic lifecycle state, never array index.
 */
export function selectActiveDivergence(
  projection: SessionProjection | null,
): DivergenceProjection | null {
  if (!projection || !projection.divergences) return null;
  const active = projection.divergences.find(
    (d) => d.state === 'OPEN' || d.state === 'ESCALATED' || d.state === 'PLANNED' || d.state === 'RECONCILING',
  );
  return active ?? null;
}

/**
 * Pure selector: select active operation by semantic revision linkage and lifecycle state, never array index.
 */
export function selectActiveOperation(
  projection: SessionProjection | null,
): OperationProjection | null {
  if (!projection || !projection.operations || projection.operations.length === 0) return null;
  const ops = projection.operations;
  const activeRevId = projection.intent?.active_revision_id ?? projection.intent?.active_revision?.revision_id;

  // 1. If active revision exists, look for matching operation
  if (activeRevId) {
    const revOps = ops.filter((op) => op.intent_revision_id === activeRevId);
    if (revOps.length > 0) {
      // Prioritize active in-flight states
      const inFlight = revOps.find(
        (op) =>
          !op.speculative &&
          (op.state === 'DISPATCHED' ||
            op.state === 'WAITING' ||
            op.state === 'PREPARING' ||
            op.state === 'READY' ||
            op.state === 'CREATED'),
      );
      if (inFlight) return inFlight;

      // Prioritize non-superseded
      const nonSuperseded = revOps.find((op) => op.state !== 'SUPERSEDED');
      if (nonSuperseded) return nonSuperseded;

      return revOps[0];
    }
  }

  // 2. Look for any in-flight non-speculative operation
  const inFlightAny = ops.find(
    (op) =>
      !op.speculative &&
      (op.state === 'DISPATCHED' ||
        op.state === 'WAITING' ||
        op.state === 'PREPARING' ||
        op.state === 'READY' ||
        op.state === 'CREATED'),
  );
  if (inFlightAny) return inFlightAny;

  // 3. Fallback: find any non-superseded operation
  const nonSuperseded = ops.find((op) => op.state !== 'SUPERSEDED');
  if (nonSuperseded) return nonSuperseded;

  return ops[0] ?? null;
}

/**
 * Pure selector: select active reconciliation plan by state or divergence correlation.
 */
export function selectActivePlan(
  projection: SessionProjection | null,
): ReconciliationPlanProjection | null {
  if (!projection || !projection.plans || projection.plans.length === 0) return null;
  const running = projection.plans.find((p) => p.state === 'AUTHORIZED' || p.state === 'RUNNING');
  if (running) return running;

  const activeDiv = selectActiveDivergence(projection);
  if (activeDiv) {
    const divPlan = projection.plans.find((p) => p.divergence_id === activeDiv.divergence_id);
    if (divPlan) return divPlan;
  }

  return projection.plans.find((p) => p.state !== 'SUPERSEDED') ?? projection.plans[0] ?? null;
}

function extractEffectSlot(effect: EffectProjection): { slot: string | null; rawSlot: string | null } {
  const params = effect.parameters;
  const raw =
    (typeof params.confirmed_slot === 'string' && params.confirmed_slot) ||
    (typeof params.requested_slot === 'string' && params.requested_slot) ||
    (typeof params.slot === 'string' && params.slot) ||
    null;
  if (!raw) return { slot: null, rawSlot: null };
  const parts = formatSlotParts(raw);
  return {
    slot: parts.unknown ? raw : parts.formatted,
    rawSlot: raw,
  };
}

/**
 * Pure selector: selectObservedWorld adhering strictly to Selection Rules A–D:
 * A. If active divergence has observed_effect_ids, find matching effect in projection.effects.
 * B. Else find latest authoritative COMMITTED effect of type appointment.booking.
 * C. Else find any committed effect.
 * D. Else return null fields.
 */
export function selectObservedWorld(projection: SessionProjection | null): ObservedWorld {
  if (!projection) {
    return {
      slot: null,
      rawSlot: null,
      state: null,
      authority: null,
      effectId: null,
      divergence: null,
    };
  }

  const activeDiv = selectActiveDivergence(projection);
  const effects = projection.effects ?? [];
  let selectedEffect: EffectProjection | null = null;

  // Rule A: Active divergence observed effects
  if (activeDiv && activeDiv.observed_effect_ids && activeDiv.observed_effect_ids.length > 0) {
    const ids = new Set(activeDiv.observed_effect_ids);
    const matched = effects.filter((e) => ids.has(e.effect_id));
    if (matched.length > 0) {
      selectedEffect = [...matched].sort((a, b) => (b.observed_at || '').localeCompare(a.observed_at || ''))[0] ?? null;
    }
  }

  // Rule B: Latest authoritative COMMITTED effect of type appointment.booking
  if (!selectedEffect) {
    const authCommitted = effects.filter(
      (e) =>
        e.authority === 'AUTHORITATIVE' &&
        e.state === 'COMMITTED' &&
        (e.effect_type === 'appointment.booking' || e.effect_type === 'appointment_booked'),
    );
    if (authCommitted.length > 0) {
      selectedEffect = [...authCommitted].sort((a, b) => (b.observed_at || '').localeCompare(a.observed_at || ''))[0] ?? null;
    }
  }

  // Rule C: Any committed effect
  if (!selectedEffect) {
    const anyCommitted = effects.filter((e) => e.state === 'COMMITTED');
    if (anyCommitted.length > 0) {
      selectedEffect = [...anyCommitted].sort((a, b) => (b.observed_at || '').localeCompare(a.observed_at || ''))[0] ?? null;
    }
  }

  // Rule D: No effect found
  if (!selectedEffect) {
    return {
      slot: null,
      rawSlot: null,
      state: null,
      authority: null,
      effectId: null,
      divergence: activeDiv,
    };
  }

  const { slot, rawSlot } = extractEffectSlot(selectedEffect);
  return {
    slot,
    rawSlot,
    state: selectedEffect.state,
    authority: selectedEffect.authority,
    effectId: selectedEffect.effect_id,
    divergence: activeDiv,
  };
}
