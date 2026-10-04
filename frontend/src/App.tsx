import React, {
  useCallback,
  useState,
  useRef,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from 'react';
import {
  HttpApplicationError,
  HttpProtocolError,
  InterlockHttpClient,
} from './api/http';
import type { FrontendError, ProjectionEventMessage } from './api/types';
import { ProjectionSocketClient } from './api/websocket';
import { SessionBar } from './components/SessionBar';
import { CopilotPage } from './pages/CopilotPage';
import { TracePage } from './pages/TracePage';
import { createProjectionStore } from './state/store';

// Semantic Status Badge Helper
interface BadgeProps {
  roleType: 'neutral' | 'blue' | 'violet' | 'amber' | 'red' | 'teal' | 'green';
  text: string;
}

const SemanticBadge: React.FC<BadgeProps> = ({ roleType, text }) => {
  const styles = {
    neutral: 'bg-stone-200/80 text-stone-700 border-stone-300 dark:bg-stone-800/90 dark:text-stone-300 dark:border-stone-700',
    blue: 'bg-blue-100/90 text-blue-800 border-blue-300 dark:bg-blue-950/80 dark:text-blue-300 dark:border-blue-700',
    violet: 'bg-purple-100/90 text-purple-800 border-purple-300 dark:bg-purple-950/80 dark:text-purple-300 dark:border-purple-700',
    amber: 'bg-amber-100/90 text-amber-800 border-amber-300 dark:bg-amber-950/80 dark:text-amber-300 dark:border-amber-700',
    red: 'bg-rose-100/90 text-rose-800 border-rose-300 dark:bg-rose-950/80 dark:text-rose-300 dark:border-rose-700',
    teal: 'bg-teal-100/90 text-teal-800 border-teal-300 dark:bg-teal-950/80 dark:text-teal-300 dark:border-teal-700',
    green: 'bg-emerald-100/90 text-emerald-800 border-emerald-300 dark:bg-emerald-950/80 dark:text-emerald-300 dark:border-emerald-700',
  }[roleType];

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${styles}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" aria-hidden="true" />
      <span>{text}</span>
    </span>
  );
};

// Icons (Inline SVG for accessibility and zero extra dependencies)
const Icons = {
  Alert: () => (
    <svg className="w-4 h-4 text-rose-600 dark:text-rose-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
    </svg>
  ),
  Check: () => (
    <svg className="w-4 h-4 text-emerald-600 dark:text-emerald-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
    </svg>
  ),
  Clock: () => (
    <svg className="w-4 h-4 text-amber-600 dark:text-amber-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
    </svg>
  ),
  Branch: () => (
    <svg className="w-4 h-4 text-purple-600 dark:text-purple-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M7 3a2 2 0 00-2 2v2a2 2 0 002 2h1a1 1 0 011 1v2a2 2 0 102 0V9.83A3.001 3.001 0 0010 4.17V5a2 2 0 00-2-2H7zm4 10a1 1 0 11-2 0 1 1 0 012 0z" clipRule="evenodd" />
    </svg>
  ),
  Shield: () => (
    <svg className="w-4 h-4 text-stone-500 dark:text-stone-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M10 1.944A11.954 11.954 0 012.166 5C2.056 5.649 2 6.319 2 7c0 5.225 3.34 9.67 8 11.317C14.66 16.67 18 12.225 18 7c0-.682-.057-1.35-.166-2.001A11.954 11.954 0 0110 1.944z" clipRule="evenodd" />
    </svg>
  ),
  NeutralDot: () => (
    <svg className="w-4 h-4 text-stone-500 dark:text-stone-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <circle cx="10" cy="10" r="4" />
    </svg>
  ),
};

type TabId = 'conversation' | 'pipeline' | 'truth' | 'trace';

interface TabDefinition {
  id: TabId;
  label: string;
}

const TABS: TabDefinition[] = [
  { id: 'conversation', label: '1. Intent & Input' },
  { id: 'pipeline', label: '2. Pipeline' },
  { id: 'truth', label: '3. Evidence & Truth' },
  { id: 'trace', label: '4. Trace & Metrics' },
];

const LegacyShell: React.FC = () => {
  // Theme state: initialized from localStorage -> prefers-color-scheme -> default 'dark'
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    try {
      const stored = localStorage.getItem('interlock-theme');
      if (stored === 'light' || stored === 'dark') return stored;
      if (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
        return 'light';
      }
    } catch {
      // Safe fallback if localStorage is blocked
    }
    return 'dark';
  });

  useEffect(() => {
    try {
      const root = document.documentElement;
      if (theme === 'dark') {
        root.classList.add('dark');
      } else {
        root.classList.remove('dark');
      }
      localStorage.setItem('interlock-theme', theme);
    } catch {
      // Safe fallback
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  // Local presentation state for responsive tabs on mobile (< md screens)
  // Does not simulate or hold authoritative backend state
  const [activeTab, setActiveTab] = useState<TabId>('conversation');
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Roving tabindex and accessible keyboard navigation (WAI-ARIA tabs pattern)
  const handleTabKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const currentIndex = TABS.findIndex((t) => t.id === activeTab);
    if (currentIndex === -1) return;

    let nextIndex: number | null = null;

    if (e.key === 'ArrowRight') {
      // Navigate right, wrap to first tab
      nextIndex = (currentIndex + 1) % TABS.length;
    } else if (e.key === 'ArrowLeft') {
      // Navigate left, wrap to last tab
      nextIndex = (currentIndex - 1 + TABS.length) % TABS.length;
    } else if (e.key === 'Home') {
      // Jump to first tab
      nextIndex = 0;
    } else if (e.key === 'End') {
      // Jump to last tab
      nextIndex = TABS.length - 1;
    }

    if (nextIndex !== null) {
      e.preventDefault();
      const nextTab = TABS[nextIndex];
      setActiveTab(nextTab.id);
      tabRefs.current[nextIndex]?.focus();
    }
  };

  return (
    <div className="min-h-screen bg-[#faf8f5] dark:bg-[#12100e] text-stone-800 dark:text-stone-200 flex flex-col font-sans transition-colors duration-150">
      {/* 1. Header Region */}
      <header className="border-b border-stone-200 dark:border-stone-800 bg-white/90 dark:bg-stone-900/90 backdrop-blur px-4 py-3 sticky top-0 z-30 transition-colors">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xl font-bold tracking-wider text-stone-900 dark:text-stone-100 font-mono">
                INTERLOCK
              </span>
              <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-950/70 text-amber-900 dark:text-amber-300 border border-amber-300 dark:border-amber-800/80 font-mono">
                Runtime Shell
              </span>
            </div>
            <span className="hidden md:inline text-xs text-stone-500 dark:text-stone-400 border-l border-stone-300 dark:border-stone-700 pl-3">
              Consistency runtime for interruptible multimodal agents
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto justify-between sm:justify-end">
            <div className="flex items-center gap-2">
              <span className="text-xs text-stone-500 dark:text-stone-400 font-mono">Session:</span>
              <SemanticBadge roleType="neutral" text="No active session" />
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-stone-500 dark:text-stone-400 font-mono">Connection:</span>
              <SemanticBadge roleType="neutral" text="Backend not connected" />
            </div>

            <div className="flex items-center gap-1.5 ml-2">
              {/* Theme Toggle Button */}
              <button
                type="button"
                onClick={toggleTheme}
                aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
                className="px-2.5 py-1 text-xs font-medium rounded-md bg-stone-100 hover:bg-stone-200 dark:bg-stone-800 dark:hover:bg-stone-700 text-stone-700 dark:text-stone-300 border border-stone-300 dark:border-stone-700 transition-colors focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 focus-visible:outline-none flex items-center gap-1.5"
              >
                <span aria-hidden="true">{theme === 'dark' ? '☀️' : '🌙'}</span>
                <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
              </button>

              <button
                type="button"
                disabled
                aria-disabled="true"
                title="Backend HTTP API integration required (UI-002 prerequisite)"
                className="px-3 py-1 text-xs font-medium rounded bg-stone-100 dark:bg-stone-800 text-stone-400 dark:text-stone-500 border border-stone-300 dark:border-stone-700 cursor-not-allowed opacity-60 focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 focus-visible:outline-none"
              >
                Start Session
              </button>
              <button
                type="button"
                disabled
                aria-disabled="true"
                title="Backend HTTP API integration required (UI-002 prerequisite)"
                className="px-2.5 py-1 text-xs font-medium rounded bg-stone-100 dark:bg-stone-800 text-stone-400 dark:text-stone-500 border border-stone-300 dark:border-stone-700 cursor-not-allowed opacity-60 focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 focus-visible:outline-none"
              >
                Reset
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* 2. Divergence Banner Region (Persistent across all screen sizes) */}
      <section
        aria-label="Divergence Status"
        className="border-b border-stone-200 dark:border-stone-800 bg-stone-100/70 dark:bg-stone-900/60 px-4 py-2.5 transition-colors"
      >
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <SemanticBadge roleType="neutral" text="DIVERGENCE MONITOR" />
            <span className="text-xs font-medium text-stone-800 dark:text-stone-300">
              Divergence not evaluated
            </span>
            <span className="text-xs text-stone-500 dark:text-stone-400 hidden lg:inline">
              — Backend not connected; intent and world state not evaluated.
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs text-stone-500 dark:text-stone-400 font-mono">
            <span>Reconciliation:</span>
            <span className="text-stone-700 dark:text-stone-300">Not evaluated</span>
          </div>
        </div>
      </section>

      {/* 3. Mobile Tab Navigation (< md screens) */}
      <nav
        role="tablist"
        aria-label="Workbench views"
        onKeyDown={handleTabKeyDown}
        className="md:hidden border-b border-stone-200 dark:border-stone-800 bg-stone-100/50 dark:bg-stone-900/40 px-2 py-1.5 flex gap-1 overflow-x-auto transition-colors"
      >
        {TABS.map((tab, idx) => {
          const isSelected = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              ref={(el) => {
                tabRefs.current[idx] = el;
              }}
              role="tab"
              type="button"
              id={`tab-${tab.id}`}
              aria-selected={isSelected}
              aria-controls={`panel-${tab.id}`}
              tabIndex={isSelected ? 0 : -1}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1 text-xs font-medium rounded-md whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 focus-visible:outline-none ${
                isSelected
                  ? 'bg-amber-100 text-amber-900 border border-amber-300 dark:bg-stone-800 dark:text-stone-100 dark:border-stone-600'
                  : 'text-stone-600 hover:text-stone-900 hover:bg-stone-200/60 dark:text-stone-400 dark:hover:text-stone-200 dark:hover:bg-stone-800/50 border border-transparent'
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>

      {/* 4. Main Workbench (Desktop 3-Column / Tablet Stack / Mobile Tabs) */}
      <main className="max-w-7xl mx-auto w-full p-4 flex-1 flex flex-col gap-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* COLUMN 1: USER INTENT & CONVERSATION */}
          <section
            id="panel-conversation"
            role="tabpanel"
            aria-labelledby="tab-conversation"
            tabIndex={0}
            className={`flex flex-col gap-4 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 ${
              activeTab !== 'conversation' ? 'hidden md:flex' : 'flex'
            }`}
          >
            <div className="border border-stone-200 dark:border-stone-800 rounded-lg bg-white/90 dark:bg-stone-900/50 p-4 flex-1 flex flex-col shadow-sm dark:shadow-none transition-colors">
              <div className="flex items-center justify-between pb-3 border-b border-stone-200 dark:border-stone-800 mb-4">
                <div>
                  <h2 className="text-sm font-semibold text-stone-900 dark:text-stone-100 tracking-wide">
                    Conversation & Input
                  </h2>
                  <p className="text-xs text-stone-500 dark:text-stone-400">
                    USER INTENT: What the user currently wants
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="AWAITING SESSION" />
              </div>

              {/* Multimodal Preview & Transcript Empty State */}
              <div className="flex-1 flex flex-col items-center justify-center p-6 border border-dashed border-stone-300 dark:border-stone-800 rounded-md bg-stone-50/70 dark:bg-stone-950/40 text-center min-h-[220px]">
                <div className="w-10 h-10 rounded-full bg-stone-100 dark:bg-stone-900 border border-stone-200 dark:border-stone-800 flex items-center justify-center mb-3">
                  <Icons.Shield />
                </div>
                <h3 className="text-xs font-semibold text-stone-800 dark:text-stone-300 mb-1">
                  No active conversation
                </h3>
                <p className="text-xs text-stone-500 dark:text-stone-400 max-w-xs">
                  Start a session to begin multimodal input interpretation, frame tracking, and hypothesis streaming.
                </p>
              </div>

              {/* Input Area (Honest Disabled State) */}
              <div className="mt-4 pt-3 border-t border-stone-200 dark:border-stone-800">
                <label htmlFor="user-input" className="sr-only">
                  User message input
                </label>
                <div className="flex gap-2">
                  <input
                    id="user-input"
                    type="text"
                    disabled
                    placeholder="Input unavailable until session starts (UI-002)..."
                    className="flex-1 bg-stone-50 dark:bg-stone-950 border border-stone-300 dark:border-stone-800 rounded px-3 py-1.5 text-xs text-stone-700 dark:text-stone-300 placeholder:text-stone-400 dark:placeholder:text-stone-500 cursor-not-allowed opacity-75 focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 focus-visible:outline-none"
                  />
                  <button
                    type="button"
                    disabled
                    aria-disabled="true"
                    className="px-3 py-1.5 text-xs font-medium rounded bg-stone-100 dark:bg-stone-800 text-stone-400 dark:text-stone-500 border border-stone-300 dark:border-stone-700 cursor-not-allowed opacity-60 focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 focus-visible:outline-none"
                  >
                    Send
                  </button>
                </div>
                <p className="text-[11px] text-stone-500 dark:text-stone-400 mt-1.5">
                  Backend HTTP API commands will be connected under ticket UI-002.
                </p>
              </div>
            </div>
          </section>

          {/* COLUMN 2: CONSISTENCY PIPELINE */}
          <section
            id="panel-pipeline"
            role="tabpanel"
            aria-labelledby="tab-pipeline"
            tabIndex={0}
            className={`flex flex-col gap-4 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 ${
              activeTab !== 'pipeline' ? 'hidden md:flex' : 'flex'
            }`}
          >
            <div className="border border-stone-200 dark:border-stone-800 rounded-lg bg-white/90 dark:bg-stone-900/50 p-4 flex-1 flex flex-col shadow-sm dark:shadow-none transition-colors">
              <div className="flex items-center justify-between pb-3 border-b border-stone-200 dark:border-stone-800 mb-4">
                <div>
                  <h2 className="text-sm font-semibold text-stone-900 dark:text-stone-100 tracking-wide">
                    Consistency Pipeline
                  </h2>
                  <p className="text-xs text-stone-500 dark:text-stone-400">
                    OPERATION VS. WORLD: Execution state vs. reality
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="IDLE" />
              </div>

              <div className="space-y-3 flex-1">
                {/* 1. Desired Intent */}
                <div className="p-3 rounded-md bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-stone-800 dark:text-stone-300 flex items-center gap-1.5">
                      <Icons.Branch />
                      1. INTENT (Desired Goal)
                    </span>
                    <SemanticBadge roleType="neutral" text="Not evaluated" />
                  </div>
                  <p className="text-xs text-stone-600 dark:text-stone-400">
                    No intent recorded.
                  </p>
                  <p className="text-[11px] text-stone-500 dark:text-stone-400 mt-1 font-mono">
                    Revision: None · Authorization: Not evaluated
                  </p>
                </div>

                {/* 2. Operation / SAFEPOINT */}
                <div className="p-3 rounded-md bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-stone-800 dark:text-stone-300 flex items-center gap-1.5">
                      <Icons.Clock />
                      2. OPERATION (Local Execution)
                    </span>
                    <SemanticBadge roleType="neutral" text="Not evaluated" />
                  </div>
                  <p className="text-xs text-stone-600 dark:text-stone-400">
                    No operation recorded.
                  </p>
                  <p className="text-[11px] text-stone-500 dark:text-stone-400 mt-1 font-mono">
                    State: None · Cancellation: None · Fingerprint: Not available
                  </p>
                </div>

                {/* 3. World Ledger Effect */}
                <div className="p-3 rounded-md bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-stone-800 dark:text-stone-300 flex items-center gap-1.5">
                      <Icons.NeutralDot />
                      3. WORLD EFFECT (Observed Reality)
                    </span>
                    <SemanticBadge roleType="neutral" text="Not evaluated" />
                  </div>
                  <p className="text-xs text-stone-600 dark:text-stone-400">
                    No observed world effect.
                  </p>
                  <p className="text-[11px] text-stone-500 dark:text-stone-400 mt-1 font-mono">
                    Append-only ledger. Confirmed effects persist across intent changes.
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* COLUMN 3: EVIDENCE, CLAIMS & TRUTHLOCK */}
          <section
            id="panel-truth"
            role="tabpanel"
            aria-labelledby="tab-truth"
            tabIndex={0}
            className={`flex flex-col gap-4 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 ${
              activeTab !== 'truth' ? 'hidden md:flex' : 'flex'
            }`}
          >
            <div className="border border-stone-200 dark:border-stone-800 rounded-lg bg-white/90 dark:bg-stone-900/50 p-4 flex-1 flex flex-col shadow-sm dark:shadow-none transition-colors">
              <div className="flex items-center justify-between pb-3 border-b border-stone-200 dark:border-stone-800 mb-4">
                <div>
                  <h2 className="text-sm font-semibold text-stone-900 dark:text-stone-100 tracking-wide">
                    Evidence & TRUTHLOCK
                  </h2>
                  <p className="text-xs text-stone-500 dark:text-stone-400">
                    TRUTH GATE: What supports belief and what can be claimed
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="Not evaluated" />
              </div>

              <div className="space-y-3 flex-1">
                {/* Evidence Store */}
                <div className="p-3 rounded-md bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-stone-800 dark:text-stone-300">
                      Evidence Store & Provenance
                    </span>
                    <SemanticBadge roleType="neutral" text="No records" />
                  </div>
                  <p className="text-xs text-stone-600 dark:text-stone-400">
                    No evidence recorded.
                  </p>
                  <p className="text-[11px] text-stone-500 dark:text-stone-400 mt-1">
                    Immutable records with source provenance and SHA-256 integrity hashes.
                  </p>
                </div>

                {/* Claim Graph */}
                <div className="p-3 rounded-md bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-stone-800 dark:text-stone-300">
                      Claim Graph Evaluation
                    </span>
                    <SemanticBadge roleType="neutral" text="No claims" />
                  </div>
                  <p className="text-xs text-stone-600 dark:text-stone-400">
                    No claims available.
                  </p>
                  <p className="text-[11px] text-stone-500 dark:text-stone-400 mt-1">
                    Acknowledgement is not confirmation. Claims require authoritative evidence.
                  </p>
                </div>

                {/* TRUTHLOCK Gate */}
                <div className="p-3 rounded-md bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-stone-800 dark:text-stone-300 flex items-center gap-1.5">
                      <Icons.NeutralDot />
                      TRUTHLOCK Speech Gate
                    </span>
                    <SemanticBadge roleType="neutral" text="Not evaluated" />
                  </div>
                  <p className="text-xs text-stone-700 dark:text-stone-300">
                    No verified statement available.
                  </p>
                  <p className="text-[11px] text-stone-500 dark:text-stone-400 mt-1">
                    Consequential language gated by ClaimGraph evidence. Unverified claims cannot be spoken.
                  </p>
                </div>
              </div>
            </div>
          </section>
        </div>

        {/* 5. Bottom Region: Trace Timeline and Metrics */}
        <section
          id="panel-trace"
          role="tabpanel"
          aria-labelledby="tab-trace"
          tabIndex={0}
          className={`flex flex-col gap-4 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:focus-visible:ring-sky-400 ${
            activeTab !== 'trace' ? 'hidden md:flex' : 'flex'
          }`}
        >
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Trace Timeline (2 Columns on Desktop) */}
            <div className="lg:col-span-2 border border-stone-200 dark:border-stone-800 rounded-lg bg-white/90 dark:bg-stone-900/50 p-4 shadow-sm dark:shadow-none transition-colors">
              <div className="flex items-center justify-between pb-3 border-b border-stone-200 dark:border-stone-800 mb-3">
                <div>
                  <h2 className="text-sm font-semibold text-stone-900 dark:text-stone-100 tracking-wide">
                    Trace Timeline
                  </h2>
                  <p className="text-xs text-stone-500 dark:text-stone-400">
                    Ordered Event Journal & Causal Traceability
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="No events" />
              </div>

              <div className="border border-dashed border-stone-300 dark:border-stone-800 rounded p-6 bg-stone-50/70 dark:bg-stone-950/40 text-center">
                <p className="text-xs text-stone-600 dark:text-stone-400 font-mono">
                  No events received.
                </p>
                <p className="text-[11px] text-stone-500 dark:text-stone-400 mt-1">
                  Ordered event journal entries and causation trees will render here when a session begins.
                </p>
              </div>
            </div>

            {/* Metrics Inspector (1 Column on Desktop) */}
            <div className="border border-stone-200 dark:border-stone-800 rounded-lg bg-white/90 dark:bg-stone-900/50 p-4 shadow-sm dark:shadow-none transition-colors">
              <div className="flex items-center justify-between pb-3 border-b border-stone-200 dark:border-stone-800 mb-3">
                <div>
                  <h2 className="text-sm font-semibold text-stone-900 dark:text-stone-100 tracking-wide">
                    Operational Metrics
                  </h2>
                  <p className="text-xs text-stone-500 dark:text-stone-400">
                    Runtime Invariant & Latency Telemetry
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="Not measured" />
              </div>

              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2 rounded bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800/80">
                  <dt className="text-stone-500 dark:text-stone-400 text-[11px]">Reducer p95</dt>
                  <dd className="text-stone-800 dark:text-stone-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800/80">
                  <dt className="text-stone-500 dark:text-stone-400 text-[11px]">Invalidations</dt>
                  <dd className="text-stone-800 dark:text-stone-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800/80">
                  <dt className="text-stone-500 dark:text-stone-400 text-[11px]">Divergences</dt>
                  <dd className="text-stone-800 dark:text-stone-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800/80">
                  <dt className="text-stone-500 dark:text-stone-400 text-[11px]">SAFEPOINT Latency</dt>
                  <dd className="text-stone-800 dark:text-stone-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800/80">
                  <dt className="text-stone-500 dark:text-stone-400 text-[11px]">Truth Blocks</dt>
                  <dd className="text-stone-800 dark:text-stone-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-stone-50/90 dark:bg-stone-950/60 border border-stone-200 dark:border-stone-800/80">
                  <dt className="text-stone-500 dark:text-stone-400 text-[11px]">Replay Violations</dt>
                  <dd className="text-stone-800 dark:text-stone-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
              </dl>
            </div>
          </div>
        </section>
      </main>

      {/* 6. Footer Information */}
      <footer className="border-t border-stone-200 dark:border-stone-800 bg-stone-100/90 dark:bg-stone-950/80 px-4 py-2.5 text-center text-[11px] text-stone-500 dark:text-stone-400 transition-colors">
        <p>
          INTERLOCK UI-001 Shell · Anticipate early · Commit safely · Speak only what reality confirms
        </p>
      </footer>
    </div>
  );
};

type View = 'copilot' | 'trace';
type Theme = 'light' | 'dark';

function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem('interlock-theme');
    if (stored === 'light' || stored === 'dark') return stored;
    if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light';
  } catch {
    // Storage and media-query access are optional presentation capabilities.
  }
  return 'dark';
}

function frontendError(error: unknown): FrontendError {
  if (error instanceof HttpApplicationError) {
    return {
      kind: 'HTTP',
      message: error.message,
      recoverable: error.status >= 500,
      status: error.status,
    };
  }
  if (error instanceof HttpProtocolError) {
    return {
      kind: 'PROTOCOL',
      message: error.message,
      recoverable: false,
      status: null,
    };
  }
  return {
    kind: 'CONNECTION',
    message: error instanceof Error ? error.message : 'The backend request failed.',
    recoverable: true,
    status: null,
  };
}

export const App: React.FC = () => {
  const store = useMemo(() => createProjectionStore(), []);
  const http = useMemo(() => new InterlockHttpClient(), []);
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  const socketRef = useRef<ProjectionSocketClient | null>(null);
  const requestSequence = useRef(0);

  const [view, setView] = useState<View>('copilot');
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [traceEvents, setTraceEvents] = useState<readonly ProjectionEventMessage[]>([]);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    try {
      localStorage.setItem('interlock-theme', theme);
    } catch {
      // A blocked storage write does not affect runtime state.
    }
  }, [theme]);

  useEffect(() => () => socketRef.current?.disconnect(), []);

  useEffect(() => {
    const sessionId = state.sessionId;
    if (!sessionId) {
      setTraceEvents([]);
      setTraceLoading(false);
      setTraceError(null);
      return;
    }

    let cancelled = false;
    async function loadHistory() {
      setTraceLoading(true);
      setTraceError(null);
      try {
        const collected: ProjectionEventMessage[] = [];
        let afterSequence = 0;
        let hasMore = true;
        while (hasMore) {
          const page = await http.getEvents(sessionId, afterSequence);
          if (cancelled) return;
          const next = page.events.filter((event) => event.sequence > afterSequence);
          collected.push(...next);
          if (next.length === 0) break;
          afterSequence = next[next.length - 1].sequence;
          hasMore = page.has_more;
        }
        if (!cancelled) {
          setTraceEvents([...collected].sort((left, right) => left.sequence - right.sequence));
        }
      } catch (error) {
        if (!cancelled) {
          const normalized = frontendError(error);
          setTraceError(`Trace history unavailable: ${normalized.message}`);
        }
      } finally {
        if (!cancelled) setTraceLoading(false);
      }
    }
    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [http, state.sessionId, state.lastAppliedSequence]);

  const nextRequestId = useCallback((kind: string) => {
    requestSequence.current += 1;
    return `interlock-ui-${kind}-${requestSequence.current}`;
  }, []);

  const startSession = useCallback(async () => {
    setActionPending(true);
    setActionError(null);
    socketRef.current?.disconnect();
    socketRef.current = null;
    store.reset();
    setTraceEvents([]);
    try {
      store.beginConnection();
      const created = await http.createSession({
        mode: 'DEMO',
        client_request_id: nextRequestId('session'),
      });
      const snapshot = await http.getSession(created.session_id);
      store.applySnapshot({
        type: 'snapshot',
        schema_version: 1,
        session_id: snapshot.session_id,
        through_sequence: snapshot.through_sequence,
        projection: snapshot.projection,
      });
      const socket = new ProjectionSocketClient({
        url: created.ws_url,
        sessionId: created.session_id,
        store,
        loadSnapshot: (url) => http.getSnapshotUrl(url),
      });
      socketRef.current = socket;
      socket.connect();
    } catch (error) {
      const normalized = frontendError(error);
      store.markError(normalized);
      setActionError(normalized.message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, store]);

  const submitText = useCallback(async (content: string) => {
    if (!state.sessionId) return;
    setActionPending(true);
    setActionError(null);
    try {
      await http.submitInput(state.sessionId, {
        modality: 'TEXT',
        content,
        client_request_id: nextRequestId('input'),
      });
    } catch (error) {
      setActionError(frontendError(error).message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, state.sessionId]);

  const cancelSpeech = useCallback(async (speechId: string) => {
    if (!state.sessionId) return;
    setActionPending(true);
    setActionError(null);
    try {
      await http.cancelSpeech(state.sessionId, speechId, {
        client_request_id: nextRequestId('speech-cancel'),
      });
    } catch (error) {
      setActionError(frontendError(error).message);
    } finally {
      setActionPending(false);
    }
  }, [http, nextRequestId, state.sessionId]);

  return (
    <div className="min-h-screen bg-[#faf8f5] text-stone-800 transition-colors dark:bg-[#12100e] dark:text-stone-200">
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <header className="app-header">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <p className="font-mono text-xl font-bold tracking-wider text-stone-950 dark:text-white">INTERLOCK</p>
            <p className="text-xs text-stone-500 dark:text-stone-400">Consistency runtime workbench</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <nav aria-label="Primary views" className="view-switcher">
              <button
                type="button"
                className={view === 'copilot' ? 'view-button view-button-active' : 'view-button'}
                aria-current={view === 'copilot' ? 'page' : undefined}
                onClick={() => setView('copilot')}
              >
                Copilot
              </button>
              <button
                type="button"
                className={view === 'trace' ? 'view-button view-button-active' : 'view-button'}
                aria-current={view === 'trace' ? 'page' : undefined}
                onClick={() => setView('trace')}
              >
                Trace
              </button>
            </nav>
            <button
              type="button"
              className="secondary-button"
              onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {theme === 'dark' ? 'Light theme' : 'Dark theme'}
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-7xl px-4 pt-4">
        <SessionBar state={state} actionPending={actionPending} onStartSession={() => void startSession()} />
      </div>

      {view === 'copilot' ? (
        <CopilotPage
          state={state}
          actionPending={actionPending}
          actionError={actionError}
          onSubmitText={submitText}
          onCancelSpeech={cancelSpeech}
        />
      ) : (
        <TracePage
          state={state}
          events={traceEvents}
          loading={traceLoading}
          error={traceError}
        />
      )}

      <footer className="border-t border-stone-200 px-4 py-3 text-center text-xs text-stone-500 dark:border-stone-800 dark:text-stone-400">
        Anticipate early · Commit safely · Speak only what reality confirms
      </footer>
    </div>
  );
};

void LegacyShell;

export default App;
