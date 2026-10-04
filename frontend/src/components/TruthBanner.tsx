import React from 'react';
import type { SpeechProjection } from '../api/types';
import { Icons } from './Icons';
import { TechnicalDetails, type DetailItem } from './TechnicalDetails';

interface TruthBannerProps {
  readonly speech: readonly SpeechProjection[];
}

function speechTone(item: SpeechProjection): string {
  if (item.state === 'BLOCKED' || item.state === 'CORRECTION_REQUIRED') return 'status-danger';
  if (item.state === 'EMITTING' || item.state === 'QUEUED') return 'status-active';
  if (item.state === 'EMITTED' && item.heard === true) return 'status-success';
  if (item.state === 'EMITTED' && item.heard === false) return 'status-neutral';
  if (item.state === 'CANCELLED') return 'status-warning';
  return 'status-neutral';
}

function deliveryLabel(item: SpeechProjection): string {
  if (item.heard === true) return 'Delivered & Heard';
  if (item.heard === false) return 'Console Text Output';
  return 'Delivery Pending';
}

export const TruthBanner: React.FC<TruthBannerProps> = ({ speech }) => {
  const latest = speech.length > 0 ? speech[speech.length - 1] : null;

  return (
    <section className="panel" aria-labelledby="truth-heading" aria-live="polite">
      <div className="panel-heading">
        <div className="flex items-center gap-2">
          <Icons.ShieldCheck className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
          <div>
            <p className="eyebrow">TRUTHLOCK Gate</p>
            <h2 id="truth-heading">Speech Verification</h2>
          </div>
        </div>
        {latest ? (
          <span className={`status-pill ${speechTone(latest)}`}>
            {latest.state.toLowerCase()}
          </span>
        ) : (
          <span className="status-pill status-neutral">Idle</span>
        )}
      </div>

      {!latest ? (
        <div className="empty-state">
          No assistant response evaluated yet. TRUTHLOCK guarantees the assistant never claims an effect that has not been confirmed by real-world evidence.
        </div>
      ) : (
        <div className="space-y-3">
          {/* Prominent Assistant Speech Quote */}
          <div className="rounded-xl border border-stone-200/90 bg-stone-50/80 p-4 shadow-sm dark:border-stone-800/80 dark:bg-stone-950/60">
            <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500 font-medium">
              <span>Verified Utterance</span>
              <span className="font-mono">{latest.act_type}</span>
            </div>
            <p className="mt-2 text-sm font-medium leading-relaxed text-stone-900 dark:text-stone-100">
              "{latest.rendered_text ?? 'Controlled text is pending verification.'}"
            </p>
          </div>

          {/* Verification Attributes */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500">
                Certainty
              </span>
              <span className="mt-0.5 font-medium text-stone-800 dark:text-stone-200">
                {latest.requested_certainty}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500">
                Delivery
              </span>
              <span className="mt-0.5 font-medium text-stone-800 dark:text-stone-200">
                {deliveryLabel(latest)}
              </span>
            </div>
          </div>

          {latest.correction_pending && (
            <div className="rounded-md border border-rose-200 bg-rose-50/80 p-2 text-xs text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-200">
              Correction required: speech gated due to mismatch with current truth.
            </div>
          )}

          {/* Progressive disclosure for technical identifiers */}
          <TechnicalDetails
            title="Speech gate policy"
            items={[
              { label: 'Speech ID', value: latest.speech_id },
              { label: 'Policy ID', value: latest.approved_policy_id ?? 'Not approved' },
              { label: 'Act Type', value: latest.act_type, mono: false },
              {
                label: 'Superseded Speech',
                value: latest.supersedes_speech_id ?? 'None',
              },
            ]}
          />
        </div>
      )}
    </section>
  );
};
