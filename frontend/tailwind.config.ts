import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Semantic roles from docs/demo/UI_SPECIFICATION.md:
        // - Neutral / slate: unknown / uninitialized
        // - Blue: active / read
        // - Violet: speculative (ANTICIPATE)
        // - Amber: cancellation / pending
        // - Red: divergence / block
        // - Teal: reconciliation (ADAPT)
        // - Green: authoritative confirmation (VERIFY)
        interlock: {
          dark: '#090d16',
          panel: '#0f172a',
          card: '#1e293b',
          border: '#334155',
          muted: '#64748b',
          text: '#e2e8f0',
          highlight: '#f8fafc',
          // Pillar & semantic colors
          unknown: '#64748b',       // Slate
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
