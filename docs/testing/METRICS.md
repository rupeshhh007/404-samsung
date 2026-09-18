# Metrics

Metrics are derived from events; no Phase 0 values are claimed.

| Metric | Formula / sources | Window, unit, aggregation / limitation |
|---|---|---|
| invariant violations | count `ProtocolViolationObserved` tagged invariant | session/count; by ID; detection only |
| interruption recovery latency | resolved/surfaced logical time − consequential control acceptance | session/ms p50/p95; excludes unobserved user latency |
| safe-point latency | safe point reached − cancellation requested | operation/ms p50/p95; only applicable policies |
| stale mutations prevented | count fingerprint rejections | session/count; proxy |
| late effects detected | committed effects whose op superseded before observation | session/count |
| duplicate effects prevented | deduped write attempts/callbacks not producing new logical effect | session/count; cannot prove provider internals |
| TRUTHLOCK blocks | `SpeechActBlocked` count by reason | session/count |
| reconciliation success rate | resolved / terminal reconciliation cases | run/ratio; report denominator |
| BranchCache hit rate | promoted / eligible committed candidate matches | run/ratio |
| latency saved | max(0, baseline configured/observed read latency − promotion latency) | hit/ms sum/median; estimate labeled |
| speculative discarded | expired+evicted+invalidated+failed branches and cost | session/count/cost units |
| scenario success rate | passed / executed deterministic scenarios | suite/ratio; not production reliability |

`MetricsSnapshot` is pinned through a sequence. Dashboard displays “not measured” for absent denominators, never zero.
