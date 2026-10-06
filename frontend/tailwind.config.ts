import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Night Instrument Tokens
        ink: {
          950: 'var(--ink-950)',
          900: 'var(--ink-900)',
          850: 'var(--ink-850)',
          800: 'var(--ink-800)',
          700: 'var(--ink-700)',
          600: 'var(--ink-600)',
          500: 'var(--ink-500)',
        },
        bone: {
          50: 'var(--bone-50)',
          300: 'var(--bone-300)',
          500: 'var(--bone-500)',
          600: 'var(--bone-600)',
          paper: 'var(--paper)',
          paperInk: 'var(--paper-ink)',
        },
        sig: {
          active: 'var(--sig-active)',
          activeGlow: 'var(--sig-active-glow)',
          activeWash: 'var(--sig-active-wash)',
          spec: 'var(--sig-spec)',
          specGlow: 'var(--sig-spec-glow)',
          specWash: 'var(--sig-spec-wash)',
          pending: 'var(--sig-pending)',
          pendingGlow: 'var(--sig-pending-glow)',
          pendingWash: 'var(--sig-pending-wash)',
          alarm: 'var(--sig-alarm)',
          alarmGlow: 'var(--sig-alarm-glow)',
          alarmWash: 'var(--sig-alarm-wash)',
          adapt: 'var(--sig-adapt)',
          adaptGlow: 'var(--sig-adapt-glow)',
          adaptWash: 'var(--sig-adapt-wash)',
          verify: 'var(--sig-verify)',
          verifyGlow: 'var(--sig-verify-glow)',
          verifyWash: 'var(--sig-verify-wash)',
        },
        // Compatibility alias mapping
        interlock: {
          bgDark: 'var(--ink-950)',
          surfaceDark: 'var(--ink-850)',
          cardDark: 'var(--ink-800)',
          borderDark: 'var(--ink-600)',
          textDark: 'var(--bone-50)',
          textMutedDark: 'var(--bone-500)',
          active: 'var(--sig-active)',
          speculative: 'var(--sig-spec)',
          pending: 'var(--sig-pending)',
          divergence: 'var(--sig-alarm)',
          reconcile: 'var(--sig-adapt)',
          verify: 'var(--sig-verify)',
        },
      },
      fontFamily: {
        display: ['Bricolage Grotesque Variable', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        voice: ['Instrument Serif', 'Georgia', 'serif'],
        mono: ['JetBrains Mono Variable', 'ui-monospace', 'Menlo', 'monospace'],
        sans: ['Bricolage Grotesque Variable', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        none: '0px',
      },
    },
  },
  plugins: [],
};

export default config;
