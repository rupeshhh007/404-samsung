import React from 'react';
import type { IntentProjection, IntentRevision, JsonObject } from '../api/types';
import { Icons } from './Icons';
import { TechnicalDetails, type DetailItem } from './TechnicalDetails';
import {
  formatGoalType,
  formatSlot,
} from '../utils/formatters';

interface IntentPanelProps {
  readonly intent: IntentProjection | null;
  readonly revision: IntentRevision | null;
}

function maturityTone(maturity: string): string {
  if (maturity === 'COMMITTED') return 'status-success';
  if (maturity === 'PROVISIONAL') return 'status-active';
  if (maturity === 'SUPERSEDED') return 'status-neutral';
  return 'status-neutral';
}

function authTone(auth: string): string {
  if (auth === 'AUTHORIZED') return 'status-active';
  if (auth === 'REQUIRED') return 'status-warning';
  if (auth === 'DENIED' || auth === 'EXPIRED') return 'status-danger';
  return 'status-neutral';
}

export const IntentPanel: React.FC<IntentPanelProps> = ({ intent, revision }) => {
  if (!intent || !revision) {
    return (
      <section className="panel" aria-labelledby="intent-heading">
        <div className="panel-heading">
          <div className="flex items-center gap-2">
            <Icons.GitBranch className="h-4 w-4 text-stone-400 dark:text-stone-500" />
            <div>
              <p className="eyebrow">User Goal</p>
              <h2 id="intent-heading">Active Intent</h2>
            </div>
          </div>
          <span className="status-pill status-neutral">Idle</span>
        </div>
        <div className="empty-state">
          No active goal recorded yet. Submit a message to define desired intent.
        </div>
      </section>
    );
  }

  // Extract desired slot if present in values
  const values = revision.values as JsonObject;
  const slotValue = values.requested_slot ?? values.slot ?? null;
  const formattedSlot = slotValue ? formatSlot(slotValue) : null;

  // Other secondary values
  const otherEntries = Object.entries(values).filter(
    ([k]) => k !== 'requested_slot' && k !== 'slot',
  );

  const techItems: DetailItem[] = [
    { label: 'Revision ID', value: revision.revision_id },
    { label: 'Dependency Fingerprint', value: revision.dependency_fingerprint },
    { label: 'Intent ID', value: intent.intent_id },
    { label: 'Maturity Stage', value: revision.maturity, mono: false },
    { label: 'Raw Goal Type', value: intent.goal_type, mono: true },
  ];

  return (
    <section className="panel" aria-labelledby="intent-heading">
      <div className="panel-heading">
        <div className="flex items-center gap-2">
          <Icons.GitBranch className="h-4 w-4 text-purple-600 dark:text-purple-400" />
          <div>
            <p className="eyebrow">User Goal</p>
            <h2 id="intent-heading">Active Intent</h2>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`status-pill ${maturityTone(revision.maturity)}`}>
            {revision.maturity.toLowerCase()}
          </span>
          <span className={`status-pill ${authTone(revision.authorization)}`}>
            {revision.authorization.toLowerCase()}
          </span>
        </div>
      </div>

      <div className="space-y-3">
        {/* Human-first summary cards */}
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <div className="rounded-lg bg-stone-50/80 p-2.5 dark:bg-stone-950/40 border border-stone-200/60 dark:border-stone-800/60">
            <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500 font-medium">
              Goal
            </span>
            <p className="mt-0.5 text-xs font-semibold text-stone-900 dark:text-stone-100">
              {formatGoalType(intent.goal_type)}
            </p>
          </div>

          <div className="rounded-lg bg-stone-50/80 p-2.5 dark:bg-stone-950/40 border border-stone-200/60 dark:border-stone-800/60">
            <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500 font-medium">
              Target Slot
            </span>
            <p className="mt-0.5 text-xs font-semibold text-stone-900 dark:text-stone-100">
              {formattedSlot ?? 'Not specified'}
            </p>
          </div>
        </div>

        {otherEntries.length > 0 && (
          <div className="rounded-lg bg-stone-50/60 p-2.5 dark:bg-stone-950/30 text-xs">
            <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500 font-medium">
              Additional Parameters
            </span>
            <div className="mt-1 flex flex-wrap gap-2 text-stone-700 dark:text-stone-300">
              {otherEntries.map(([k, v]) => (
                <span key={k} className="inline-flex items-center gap-1">
                  <span className="text-stone-500">{k}:</span>
                  <span className="font-medium">{String(v)}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Progressive Disclosure */}
        <TechnicalDetails title="Protocol identifiers" items={techItems} />
      </div>
    </section>
  );
};
