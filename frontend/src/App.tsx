import React, { useState, useRef } from 'react';

// Semantic Status Badge Helper
interface BadgeProps {
  roleType: 'neutral' | 'blue' | 'violet' | 'amber' | 'red' | 'teal' | 'green';
  text: string;
}

const SemanticBadge: React.FC<BadgeProps> = ({ roleType, text }) => {
  const styles = {
    neutral: 'bg-slate-800/90 text-slate-300 border-slate-700',
    blue: 'bg-blue-950/80 text-blue-300 border-blue-700',
    violet: 'bg-purple-950/80 text-purple-300 border-purple-700',
    amber: 'bg-amber-950/80 text-amber-300 border-amber-700',
    red: 'bg-rose-950/80 text-rose-300 border-rose-700',
    teal: 'bg-teal-950/80 text-teal-300 border-teal-700',
    green: 'bg-emerald-950/80 text-emerald-300 border-emerald-700',
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
    <svg className="w-4 h-4 text-rose-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
    </svg>
  ),
  Check: () => (
    <svg className="w-4 h-4 text-emerald-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
    </svg>
  ),
  Clock: () => (
    <svg className="w-4 h-4 text-amber-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
    </svg>
  ),
  Branch: () => (
    <svg className="w-4 h-4 text-purple-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M7 3a2 2 0 00-2 2v2a2 2 0 002 2h1a1 1 0 011 1v2a2 2 0 102 0V9.83A3.001 3.001 0 0010 4.17V5a2 2 0 00-2-2H7zm4 10a1 1 0 11-2 0 1 1 0 012 0z" clipRule="evenodd" />
    </svg>
  ),
  Shield: () => (
    <svg className="w-4 h-4 text-slate-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path fillRule="evenodd" d="M10 1.944A11.954 11.954 0 012.166 5C2.056 5.649 2 6.319 2 7c0 5.225 3.34 9.67 8 11.317C14.66 16.67 18 12.225 18 7c0-.682-.057-1.35-.166-2.001A11.954 11.954 0 0110 1.944z" clipRule="evenodd" />
    </svg>
  ),
  NeutralDot: () => (
    <svg className="w-4 h-4 text-slate-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
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

export const App: React.FC = () => {
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
    <div className="min-h-screen bg-[#090d16] text-slate-200 flex flex-col font-sans">
      {/* 1. Header Region */}
      <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur px-4 py-3 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xl font-bold tracking-wider text-slate-100 font-mono">
                INTERLOCK
              </span>
              <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800/80 font-mono">
                Runtime Shell
              </span>
            </div>
            <span className="hidden md:inline text-xs text-slate-400 border-l border-slate-700 pl-3">
              Consistency runtime for interruptible multimodal agents
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto justify-between sm:justify-end">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-mono">Session:</span>
              <SemanticBadge roleType="neutral" text="No active session" />
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-mono">Connection:</span>
              <SemanticBadge roleType="neutral" text="Backend not connected" />
            </div>

            <div className="flex items-center gap-1.5 ml-2">
              <button
                type="button"
                disabled
                aria-disabled="true"
                title="Backend HTTP API integration required (UI-002 prerequisite)"
                className="px-3 py-1 text-xs font-medium rounded bg-slate-800 text-slate-400 border border-slate-700 cursor-not-allowed opacity-60 focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:outline-none"
              >
                Start Session
              </button>
              <button
                type="button"
                disabled
                aria-disabled="true"
                title="Backend HTTP API integration required (UI-002 prerequisite)"
                className="px-2.5 py-1 text-xs font-medium rounded bg-slate-800 text-slate-400 border border-slate-700 cursor-not-allowed opacity-60 focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:outline-none"
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
        className="border-b border-slate-800 bg-slate-900/60 px-4 py-2.5"
      >
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <SemanticBadge roleType="neutral" text="DIVERGENCE MONITOR" />
            <span className="text-xs font-medium text-slate-300">
              Divergence not evaluated
            </span>
            <span className="text-xs text-slate-400 hidden lg:inline">
              — Backend not connected; intent and world state not evaluated.
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400 font-mono">
            <span>Reconciliation:</span>
            <span className="text-slate-300">Not evaluated</span>
          </div>
        </div>
      </section>

      {/* 3. Mobile Tab Navigation (< md screens) */}
      <nav
        role="tablist"
        aria-label="Workbench views"
        onKeyDown={handleTabKeyDown}
        className="md:hidden border-b border-slate-800 bg-slate-900/40 px-2 py-1.5 flex gap-1 overflow-x-auto"
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
              className={`px-3 py-1 text-xs font-medium rounded-md whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:outline-none ${
                isSelected
                  ? 'bg-blue-900/50 text-blue-200 border border-blue-700'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
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
            className={`flex flex-col gap-4 rounded-lg ${
              activeTab !== 'conversation' ? 'hidden md:flex' : 'flex'
            }`}
          >
            <div className="border border-slate-800 rounded-lg bg-slate-900/50 p-4 flex-1 flex flex-col">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
                <div>
                  <h2 className="text-sm font-semibold text-slate-100 tracking-wide">
                    Conversation & Input
                  </h2>
                  <p className="text-xs text-slate-400">
                    USER INTENT: What the user currently wants
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="AWAITING SESSION" />
              </div>

              {/* Multimodal Preview & Transcript Empty State */}
              <div className="flex-1 flex flex-col items-center justify-center p-6 border border-dashed border-slate-800 rounded-md bg-slate-950/40 text-center min-h-[220px]">
                <div className="w-10 h-10 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center mb-3">
                  <Icons.Shield />
                </div>
                <h3 className="text-xs font-semibold text-slate-300 mb-1">
                  No active conversation
                </h3>
                <p className="text-xs text-slate-400 max-w-xs">
                  Start a session to begin multimodal input interpretation, frame tracking, and hypothesis streaming.
                </p>
              </div>

              {/* Input Area (Honest Disabled State) */}
              <div className="mt-4 pt-3 border-t border-slate-800">
                <label htmlFor="user-input" className="sr-only">
                  User message input
                </label>
                <div className="flex gap-2">
                  <input
                    id="user-input"
                    type="text"
                    disabled
                    placeholder="Input unavailable until session starts (UI-002)..."
                    className="flex-1 bg-slate-950 border border-slate-800 rounded px-3 py-1.5 text-xs text-slate-400 placeholder:text-slate-400 cursor-not-allowed opacity-60 focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:outline-none"
                  />
                  <button
                    type="button"
                    disabled
                    aria-disabled="true"
                    className="px-3 py-1.5 text-xs font-medium rounded bg-slate-800 text-slate-400 border border-slate-700 cursor-not-allowed opacity-60 focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:outline-none"
                  >
                    Send
                  </button>
                </div>
                <p className="text-[11px] text-slate-400 mt-1.5">
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
            className={`flex flex-col gap-4 rounded-lg ${
              activeTab !== 'pipeline' ? 'hidden md:flex' : 'flex'
            }`}
          >
            <div className="border border-slate-800 rounded-lg bg-slate-900/50 p-4 flex-1 flex flex-col">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
                <div>
                  <h2 className="text-sm font-semibold text-slate-100 tracking-wide">
                    Consistency Pipeline
                  </h2>
                  <p className="text-xs text-slate-400">
                    OPERATION VS. WORLD: Execution state vs. reality
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="IDLE" />
              </div>

              <div className="space-y-3 flex-1">
                {/* 1. Desired Intent */}
                <div className="p-3 rounded-md bg-slate-950/60 border border-slate-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
                      <Icons.Branch />
                      1. INTENT (Desired Goal)
                    </span>
                    <SemanticBadge roleType="neutral" text="Not evaluated" />
                  </div>
                  <p className="text-xs text-slate-400">
                    No intent recorded.
                  </p>
                  <p className="text-[11px] text-slate-400 mt-1 font-mono">
                    Revision: None · Authorization: Not evaluated
                  </p>
                </div>

                {/* 2. Operation / SAFEPOINT */}
                <div className="p-3 rounded-md bg-slate-950/60 border border-slate-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
                      <Icons.Clock />
                      2. OPERATION (Local Execution)
                    </span>
                    <SemanticBadge roleType="neutral" text="Not evaluated" />
                  </div>
                  <p className="text-xs text-slate-400">
                    No operation recorded.
                  </p>
                  <p className="text-[11px] text-slate-400 mt-1 font-mono">
                    State: None · Cancellation: None · Fingerprint: Not available
                  </p>
                </div>

                {/* 3. World Ledger Effect */}
                <div className="p-3 rounded-md bg-slate-950/60 border border-slate-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
                      <Icons.NeutralDot />
                      3. WORLD EFFECT (Observed Reality)
                    </span>
                    <SemanticBadge roleType="neutral" text="Not evaluated" />
                  </div>
                  <p className="text-xs text-slate-400">
                    No observed world effect.
                  </p>
                  <p className="text-[11px] text-slate-400 mt-1 font-mono">
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
            className={`flex flex-col gap-4 rounded-lg ${
              activeTab !== 'truth' ? 'hidden md:flex' : 'flex'
            }`}
          >
            <div className="border border-slate-800 rounded-lg bg-slate-900/50 p-4 flex-1 flex flex-col">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
                <div>
                  <h2 className="text-sm font-semibold text-slate-100 tracking-wide">
                    Evidence & TRUTHLOCK
                  </h2>
                  <p className="text-xs text-slate-400">
                    TRUTH GATE: What supports belief and what can be claimed
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="Not evaluated" />
              </div>

              <div className="space-y-3 flex-1">
                {/* Evidence Store */}
                <div className="p-3 rounded-md bg-slate-950/60 border border-slate-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-slate-300">
                      Evidence Store & Provenance
                    </span>
                    <SemanticBadge roleType="neutral" text="No records" />
                  </div>
                  <p className="text-xs text-slate-400">
                    No evidence recorded.
                  </p>
                  <p className="text-[11px] text-slate-400 mt-1">
                    Immutable records with source provenance and SHA-256 integrity hashes.
                  </p>
                </div>

                {/* Claim Graph */}
                <div className="p-3 rounded-md bg-slate-950/60 border border-slate-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-slate-300">
                      Claim Graph Evaluation
                    </span>
                    <SemanticBadge roleType="neutral" text="No claims" />
                  </div>
                  <p className="text-xs text-slate-400">
                    No claims available.
                  </p>
                  <p className="text-[11px] text-slate-400 mt-1">
                    Acknowledgement is not confirmation. Claims require authoritative evidence.
                  </p>
                </div>

                {/* TRUTHLOCK Gate */}
                <div className="p-3 rounded-md bg-slate-950/60 border border-slate-800">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
                      <Icons.NeutralDot />
                      TRUTHLOCK Speech Gate
                    </span>
                    <SemanticBadge roleType="neutral" text="Not evaluated" />
                  </div>
                  <p className="text-xs text-slate-300">
                    No verified statement available.
                  </p>
                  <p className="text-[11px] text-slate-400 mt-1">
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
          className={`flex flex-col gap-4 rounded-lg ${
            activeTab !== 'trace' ? 'hidden md:flex' : 'flex'
          }`}
        >
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Trace Timeline (2 Columns on Desktop) */}
            <div className="lg:col-span-2 border border-slate-800 rounded-lg bg-slate-900/50 p-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-100 tracking-wide">
                    Trace Timeline
                  </h2>
                  <p className="text-xs text-slate-400">
                    Ordered Event Journal & Causal Traceability
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="No events" />
              </div>

              <div className="border border-dashed border-slate-800 rounded p-6 bg-slate-950/40 text-center">
                <p className="text-xs text-slate-400 font-mono">
                  No events received.
                </p>
                <p className="text-[11px] text-slate-400 mt-1">
                  Ordered event journal entries and causation trees will render here when a session begins.
                </p>
              </div>
            </div>

            {/* Metrics Inspector (1 Column on Desktop) */}
            <div className="border border-slate-800 rounded-lg bg-slate-900/50 p-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-100 tracking-wide">
                    Operational Metrics
                  </h2>
                  <p className="text-xs text-slate-400">
                    Runtime Invariant & Latency Telemetry
                  </p>
                </div>
                <SemanticBadge roleType="neutral" text="Not measured" />
              </div>

              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                  <dt className="text-slate-400 text-[11px]">Reducer p95</dt>
                  <dd className="text-slate-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                  <dt className="text-slate-400 text-[11px]">Invalidations</dt>
                  <dd className="text-slate-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                  <dt className="text-slate-400 text-[11px]">Divergences</dt>
                  <dd className="text-slate-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                  <dt className="text-slate-400 text-[11px]">SAFEPOINT Latency</dt>
                  <dd className="text-slate-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                  <dt className="text-slate-400 text-[11px]">Truth Blocks</dt>
                  <dd className="text-slate-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
                <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80">
                  <dt className="text-slate-400 text-[11px]">Replay Violations</dt>
                  <dd className="text-slate-300 font-mono font-medium mt-0.5">Not measured</dd>
                </div>
              </dl>
            </div>
          </div>
        </section>
      </main>

      {/* 6. Footer Information */}
      <footer className="border-t border-slate-800 bg-slate-950/80 px-4 py-2.5 text-center text-[11px] text-slate-400">
        <p>
          INTERLOCK UI-001 Shell · Anticipate early · Commit safely · Speak only what reality confirms
        </p>
      </footer>
    </div>
  );
};

export default App;
