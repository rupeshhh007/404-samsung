import type { SpeechProjection } from '../api/types';

interface TruthBannerProps {
  readonly speech: readonly SpeechProjection[];
}

function speechTone(item: SpeechProjection): string {
  if (item.state === 'BLOCKED' || item.state === 'CORRECTION_REQUIRED') return 'status-danger';
  if (item.state === 'EMITTING' || item.state === 'QUEUED') return 'status-active';
  if (item.state === 'EMITTED' && item.heard === true) return 'status-success';
  if (item.state === 'CANCELLED' || item.heard === false) return 'status-warning';
  return 'status-neutral';
}

function deliveryLabel(item: SpeechProjection): string {
  if (item.heard === true) return 'Heard';
  if (item.heard === false) return 'Not heard';
  return 'Delivery not reported';
}

export function TruthBanner({ speech }: TruthBannerProps) {
  const latest = speech.length > 0 ? speech[speech.length - 1] : null;

  return (
    <section className="panel" aria-labelledby="truth-heading" aria-live="polite">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">TRUTHLOCK</p>
          <h2 id="truth-heading">Speech gate</h2>
        </div>
        {latest ? (
          <span className={`status-pill ${speechTone(latest)}`}>{latest.state}</span>
        ) : (
          <span className="status-pill status-neutral">Not evaluated</span>
        )}
      </div>

      {!latest ? (
        <div className="empty-state">No speech decision is projected.</div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-stone-700 dark:text-stone-200">
            {latest.rendered_text ?? 'Controlled text is not available.'}
          </p>
          <dl className="definition-grid">
            <div><dt>Act</dt><dd>{latest.act_type}</dd></div>
            <div><dt>Requested certainty</dt><dd>{latest.requested_certainty}</dd></div>
            <div><dt>Delivery</dt><dd>{deliveryLabel(latest)}</dd></div>
            <div><dt>Policy</dt><dd>{latest.approved_policy_id ?? 'Not approved'}</dd></div>
          </dl>
          {latest.correction_pending && (
            <p className="rounded-md border border-rose-300 bg-rose-50 p-2 text-xs text-rose-800 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
              Correction pending according to the canonical speech projection.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
