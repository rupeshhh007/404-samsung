import type { OperationProjection } from '../api/types';

interface OperationPanelProps {
  readonly operations: readonly OperationProjection[];
}

function operationTone(operation: OperationProjection): string {
  if (operation.effect_state === 'COMMITTED' || operation.state === 'SUCCEEDED') return 'status-success';
  if (operation.effect_state === 'OUTCOME_UNKNOWN' || operation.state === 'TIMED_OUT') return 'status-warning';
  if (operation.state === 'FAILED') return 'status-danger';
  if (operation.state === 'DISPATCHED' || operation.state === 'WAITING') return 'status-active';
  return 'status-neutral';
}

export function OperationPanel({ operations }: OperationPanelProps) {
  const ordered = [...operations].sort((left, right) => left.operation_id.localeCompare(right.operation_id));

  return (
    <section className="panel" aria-labelledby="operation-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Operations</p>
          <h2 id="operation-heading">Execution lifecycle</h2>
        </div>
        <span className="status-pill status-neutral">{operations.length} projected</span>
      </div>

      {ordered.length === 0 ? (
        <div className="empty-state">No operation is currently projected. This does not imply completion.</div>
      ) : (
        <ul className="space-y-2">
          {ordered.map((operation) => (
            <li key={operation.operation_id} className="data-card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{operation.tool_name}</span>
                <span className={`status-pill ${operationTone(operation)}`}>{operation.state}</span>
              </div>
              <dl className="mt-2 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
                <div><dt>Effect</dt><dd>{operation.effect_state}</dd></div>
                <div><dt>Cancellation</dt><dd>{operation.cancellation_state}</dd></div>
                <div><dt>Action</dt><dd>{operation.action_type}</dd></div>
                <div><dt>Policy</dt><dd>{operation.cancellation_policy}</dd></div>
              </dl>
              <p className="mono-wrap mt-2 text-xs text-stone-500 dark:text-stone-400">
                {operation.operation_id}
              </p>
              {operation.error && (
                <p className="mt-2 text-xs text-rose-700 dark:text-rose-300">
                  {operation.error.code}: {operation.error.message}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
