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
        // Semantic roles from docs/demo/UI_SPECIFICATION.md:
        // - Neutral / warm-neutral: unknown / uninitialized
        // - Blue: active / read
        // - Violet: speculative (ANTICIPATE)
        // - Amber: cancellation / pending
        // - Red: divergence / block
        // - Teal: reconciliation (ADAPT)
        // - Green: authoritative confirmation (VERIFY)
        interlock: {
          // Warm foundation surfaces
          bgLight: '#faf8f5',
          bgDark: '#12100e',
          surfaceLight: '#ffffff',
          surfaceDark: '#1c1917',
          cardLight: '#f5f3ef',
          cardDark: '#292524',
          borderLight: '#e7e5e4',
          borderDark: '#38332e',
          textLight: '#1c1917',
          textDark: '#f5f5f4',
          textMutedLight: '#78716c',
          textMutedDark: '#a8a29e',

          // Preserved canonical semantic colors
          unknown: '#78716c',       // Warm stone neutral
          active: '#3b82f6',        // Blue
          speculative: '#a855f7',   // Violet (ANTICIPATE)
          pending: '#f59e0b',       // Amber
          cancellation: '#d97706',  // Amber
          divergence: '#ef4444',    // Red
          block: '#dc2626',         // Red
          reconcile: '#14b8a6',     // Teal (ADAPT)
          verify: '#10b981',        // Green (VERIFY)
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        sans: ['system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
};

export default config;
