import React, { useState } from 'react';
import { InterlockBridge } from './InterlockBridge';
import { Strands } from './Strands';
import { LedgerOperations } from './LedgerOperations';
import { LedgerClaims } from './LedgerClaims';
import { LedgerReconcile } from './LedgerReconcile';
import { MetricsBar } from './MetricsBar';
import { Eyebrow } from '../primitives/Eyebrow';
import type { Stage } from '../viewmodel/stage';
import type { SessionProjection, ProjectionEventMessage } from '../../api/types';

interface DeckProps {
  readonly stage: Stage;
  readonly gapPx: number;
  readonly projection: SessionProjection | null;
  readonly traceEvents: readonly ProjectionEventMessage[];
  readonly onSelectSequence?: (sequence: number) => void;
  readonly onAuthorizePlan?: (planId: string, decision: 'AUTHORIZE' | 'DENY') => void;
  readonly actionPending?: boolean;
}

export const Deck: React.FC<DeckProps> = ({
  stage,
  gapPx,
  projection,
  traceEvents,
  onSelectSequence,
  onAuthorizePlan,
  actionPending = false,
}) => {
  const [activeLedgerTab, setActiveLedgerTab] = useState<'claims' | 'operations' | 'reconcile'>('claims');

  const operations = projection?.operations ?? [];
  const effects = projection?.effects ?? [];
  const claims = projection?.claims ?? [];
  const evidence = projection?.evidence ?? [];
  const divergences = projection?.divergences ?? [];
  const plans = projection?.plans ?? [];
  const metrics = projection?.metrics ?? null;

  const activeDivergence = divergences.find((d) => d.state === 'OPEN' || d.state === 'ESCALATED') ??
    divergences[divergences.length - 1] ?? null;

  const activePlan = plans[plans.length - 1] ?? null;

  return (
    <section
      aria-label="Consistency Runtime Deck"
      className="flex flex-col h-full space-y-4 overflow-y-auto pr-1 select-none"
    >
      {/* 1. Hero Interlock Bridge */}
      <InterlockBridge
        stage={stage}
        gapPx={gapPx}
        projection={projection}
      />

      {/* 2. Strands Live Journal Recorder */}
      <Strands
        events={traceEvents}
        onSelectSequence={onSelectSequence}
      />

      {/* 3. Multi-Card / Tabbed Ledger */}
      <div className="flex-1 bg-ink-900 border border-ink-600 p-4 space-y-3 flex flex-col min-h-[300px]">
        {/* Ledger Navigation Header */}
        <div className="flex items-center justify-between border-b border-ink-600 pb-2">
          <Eyebrow>RUN-TIME LEDGER // CANONICAL AUDIT</Eyebrow>

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setActiveLedgerTab('claims')}
              className={`px-3 py-1 font-mono text-[10px] uppercase tracking-wider border transition-colors ${
                activeLedgerTab === 'claims'
                  ? 'border-bone-50 bg-bone-50 text-ink-950 font-bold'
                  : 'border-ink-600 text-bone-500 hover:text-bone-50'
              }`}
            >
              Claims ({claims.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveLedgerTab('operations')}
              className={`px-3 py-1 font-mono text-[10px] uppercase tracking-wider border transition-colors ${
                activeLedgerTab === 'operations'
                  ? 'border-bone-50 bg-bone-50 text-ink-950 font-bold'
                  : 'border-ink-600 text-bone-500 hover:text-bone-50'
              }`}
            >
              Operations ({operations.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveLedgerTab('reconcile')}
              className={`px-3 py-1 font-mono text-[10px] uppercase tracking-wider border transition-colors ${
                activeLedgerTab === 'reconcile'
                  ? 'border-sig-adapt bg-sig-adapt text-ink-950 font-bold'
                  : 'border-ink-600 text-bone-500 hover:text-bone-50'
              }`}
            >
              Reconcile {divergences.length > 0 ? `(${divergences.length})` : ''}
            </button>
          </div>
        </div>

        {/* Active Ledger Surface */}
        <div className="flex-1 overflow-y-auto">
          {activeLedgerTab === 'claims' && (
            <LedgerClaims claims={claims} evidence={evidence} />
          )}

          {activeLedgerTab === 'operations' && (
            <LedgerOperations operations={operations} effects={effects} />
          )}

          {activeLedgerTab === 'reconcile' && (
            <LedgerReconcile
              plan={activePlan}
              divergence={activeDivergence}
              onAuthorize={onAuthorizePlan}
              actionPending={actionPending}
            />
          )}
        </div>
      </div>

      {/* 4. Bottom Metrics Audit Bar */}
      <MetricsBar metrics={metrics} />
    </section>
  );
};
