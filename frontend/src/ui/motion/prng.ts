/**
 * Seeded PRNG using mulberry32.
 * Seed is parsed from ?seed=<int> query param (default 7) for reproducible animation runs.
 */
function getInitialSeed(): number {
  if (typeof window === 'undefined') return 7;
  try {
    const params = new URLSearchParams(window.location.search);
    const seedParam = params.get('seed');
    if (seedParam !== null) {
      const parsed = parseInt(seedParam, 10);
      if (!Number.isNaN(parsed)) return parsed;
    }
  } catch {
    // Fallback if window.location is unavailable
  }
  return 7;
}

export function createMulberry32(seed = getInitialSeed()): () => number {
  let s = Math.floor(seed);
  return function next(): number {
    s |= 0;
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const prng = createMulberry32();
