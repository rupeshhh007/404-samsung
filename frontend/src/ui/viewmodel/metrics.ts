import type { MetricsProjection } from '../../api/types';

export interface MetricItem {
  readonly key: string;
  readonly label: string;
  readonly value: string; // formatted string e.g. "1" or "not measured"
  readonly formula?: string;
  readonly rawValue: number | null;
}

const METRIC_LABELS: Record<string, { label: string; formula: string }> = {
  accepted_events: {
    label: 'Accepted Events',
    formula: 'count(Accepted journal events)',
  },
  truthlock_blocks: {
    label: 'TRUTHLOCK Blocks',
    formula: 'count(Speech blocked by truth check)',
  },
  late_effects_detected: {
    label: 'Late Effects Detected',
    formula: 'count(World effects observed after interruption)',
  },
  terminal_reconciliation_cases: {
    label: 'Terminal Reconciliations',
    formula: 'count(Terminal reconciliation cases)',
  },
  resolved_reconciliation_cases: {
    label: 'Resolved Reconciliations',
    formula: 'count(Divergence resolution events)',
  },
  safe_point_latency_samples: {
    label: 'Safepoint Latency Samples',
    formula: 'count(Safepoint reached)',
  },
  protocol_violations: {
    label: 'Protocol Violations',
    formula: 'count(Protocol violations)',
  },
};

export function formatMetricsViewModel(metrics: MetricsProjection | null): {
  readonly items: readonly MetricItem[];
  readonly throughSequence: number;
  readonly hasData: boolean;
} {
  if (!metrics) {
    return {
      items: [],
      throughSequence: 0,
      hasData: false,
    };
  }

  const counters = metrics.counters ?? {};
  const hasData = Object.keys(counters).length > 0;

  // Build items for primary metrics
  const primaryKeys = [
    'late_effects_detected',
    'truthlock_blocks',
    'resolved_reconciliation_cases',
    'accepted_events',
  ];

  const items: MetricItem[] = primaryKeys.map((key) => {
    const meta = METRIC_LABELS[key];
    const raw = counters[key];
    const value = raw !== undefined && raw !== null ? String(raw) : 'not measured';

    return {
      key,
      label: meta?.label ?? key,
      value,
      formula: meta?.formula,
      rawValue: raw ?? null,
    };
  });

  return {
    items,
    throughSequence: metrics.through_sequence ?? 0,
    hasData,
  };
}
