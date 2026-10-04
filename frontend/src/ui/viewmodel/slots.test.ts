import { describe, it, expect } from 'vitest';
import { parseSlot, formatSlotParts } from './slots';

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
});
