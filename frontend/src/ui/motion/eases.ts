export const EASES = {
  // cubic-bezier(0.22, 1, 0.36, 1) - default out
  interlock: 'cubic-bezier(0.22, 1, 0.36, 1)',
  // cubic-bezier(0.7, 0, 0.2, 1) - in-out for mechanical moves
  snap: 'cubic-bezier(0.7, 0, 0.2, 1)',
  // back-out with 8% overshoot for the Lock Snap
  lock: 'back.out(1.08)',
} as const;

export const DURATIONS = {
  micro: 0.12,
  ui: 0.24,
  scene: 0.75,
  hero: 1.4,
} as const;
