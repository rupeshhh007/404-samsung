import type {
  DivergenceProjection,
  EffectProjection,
  IntentProjection,
  IntentRevision,
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
 */
export function extractObservedSlot(
  divergence: DivergenceProjection | null,
  effects: readonly EffectProjection[],
): string | null {
  if (!divergence) return null;
  const observedEffectIds = new Set(divergence.observed_effect_ids);
  const matchedEffects = effects.filter((e) => observedEffectIds.has(e.effect_id));

  for (const effect of matchedEffects) {
    const params = effect.parameters;
    if (typeof params.confirmed_slot === 'string') return params.confirmed_slot;
    if (typeof params.requested_slot === 'string') return params.requested_slot;
    if (typeof params.slot === 'string') return params.slot;
  }

  // If none found in observed effects, check all committed effects
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
