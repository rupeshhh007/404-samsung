# Requirements

Acceptance tests are canonical in [Test Strategy](../testing/TEST_STRATEGY.md).

| ID | Requirement and rationale | Pri | Dependencies | Owner | Acceptance / tests |
|---|---|---:|---|---|---|
| FR-001 | Journal every accepted fact with unique ID and monotonic session sequence; enables deterministic reduction. | P0 | — | Runtime | duplicates do not reduce twice; T-JRN-01 |
| FR-002 | Only the serialized reducer mutates authoritative `SessionState`; prevents races. | P0 | FR-001 | Runtime | concurrent inputs yield deterministic state; T-RED-01 |
| FR-003 | Classify the ten `ControlKind` values; low-confidence consequential control becomes `CLARIFY`. | P0 | FR-001 | Intelligence | threshold behavior; T-CTL-01 |
| FR-004 | Track provisional/committed intent separately from action authorization. | P0/P1 | FR-003 | Intelligence | provisional write is blocked; T-INT-01 |
| FR-005 | Invalidate operations by changed dependency fingerprints, not global revision alone. | P0 | FR-004 | Intelligence | warranty survives time correction; T-INT-02 |
| FR-006 | Speculate only with validated read-only descriptors, top-K/budget/TTL bounds. | P1 | FR-005, FR-008 | Intelligence | attempted speculative write rejected; T-BRC-01 |
| FR-007 | Track operation, cancellation, and effect states as orthogonal dimensions. | P0 | FR-002 | Execution | race transitions match state machines; T-SAF-01 |
| FR-008 | Normalize dynamic manifests conservatively; unknown effects cannot speculate or auto-retry writes. | P0 | — | Execution | unknown manifest is safe-denied; T-TOL-01 |
| FR-009 | Require authorization and a valid dependency fingerprint immediately before consequential dispatch. | P0 | FR-004, FR-007 | Execution | stale dispatch prevented; T-SAF-02 |
| FR-010 | Derive stable logical-action/idempotency keys and deduplicate requests/callbacks within session. | P0 | FR-008 | Execution | duplicates make one ledger effect; T-IDM-01 |
| FR-011 | Record authoritative late effects even for superseded operations. | P0 | FR-001, FR-007 | Execution | late 11:00 effect retained; T-WLD-01 |
| FR-012 | Detect desired/observed divergence and surface or reconcile under provider capability and authorization. | P0/P1 | FR-011 | Execution | mismatch case and plan; T-REC-01 |
| FR-013 | Store immutable evidence with provenance; interpretations create derived records. | P0 | FR-001 | Intelligence | mutation rejected; T-EVD-01 |
| FR-014 | Maintain claim states and evidence requirements; acknowledgement is not confirmation. | P0 | FR-011, FR-013 | Truth | booking claim pending until confirmation; T-CLM-01 |
| FR-015 | Gate consequential `SpeechAct` certainty; controlled rendering cannot upgrade it. | P0 | FR-014 | Truth | unsupported success blocked; T-TRU-01 |
| FR-016 | If emitted speech becomes false, enqueue an explicit evidence-supported correction. | P0 | FR-015 | Truth | heard audio remains recorded; T-SPK-01 |
| FR-017 | Resolve temporal frame/audio references without rewriting evidence. | P1 | FR-013 | Intelligence | “before this” anchors prior frame; T-REF-01 |
| FR-018 | Provide HTTP commands, ordered WebSocket projections, snapshots, and sequence-based resync. | P0 | FR-001 | Runtime | reconnect catches gap; T-WS-01 |
| FR-019 | Deterministically simulate latency, failures, ignored cancel, late/duplicate callbacks, races, unknown outcome, and compensation. | P0 | FR-007 | Runtime | golden scenarios repeat identically; T-SCN-01 |
| FR-020 | Provide a complete local Samsung-shaped adapter and never label it official. | P0 | FR-008 | Runtime | no credentials required; T-ADP-01 |
| FR-021 | Run as a voice-native LiveKit Agents session: ingest partial/final transcripts and interruptions, cancel speech independently, and emit safe meaningful progress while reasoning/tools continue asynchronously. | P0 | FR-003, FR-015, FR-016 | Runtime/Truth | T-VOICE-01; no partial instruction can dispatch a write or produce a false completion |
| FR-022 | Expose FDB-v3's generic tool-call protocol through a fresh INTERLOCK session per scenario without scenario-specific rules or cross-scenario state. | P0 | FR-021, FR-010 | Execution/Runtime | T-FDB-01, T-ISO-01; selection/arguments/chains remain generic and valid |
| FR-023 | Demonstrate one additional working end-to-end extension use case beyond FDB-v3; simulated Samsung booking may qualify only when actually executable and honestly labeled. | P0 | FR-021, FR-011, FR-015 | All | T-EXT-01; recorded demo proves interruption, world truth, and safe speech |
| NFR-001 | Preserve single-writer safety under concurrent async work. | P0 | FR-002 | Runtime | stress/property suite; T-CON-01 |
| NFR-002 | Measure interruption recovery, safe-point, cache, reconciliation, and truth-gate metrics without invented results. | P1 | FR-019 | Truth | formula/event audit; T-MET-01 |
| NFR-003 | Replay is deterministic and dispatches no external command. | P0 | FR-001 | Runtime | replay equality/no call; T-RPL-01 |
| NFR-004 | Validate all untrusted inputs, manifests, model outputs, and provider results at boundaries. | P0 | — | All | malformed data rejected safely; T-SEC-01 |
| NFR-005 | Remain a modular monolith with domain logic independent of Samsung fixtures. | P0 | — | All | dependency audit; T-ARC-01 |
| NFR-006 | Operate without LLM or Samsung credentials using deterministic interpreters and fake provider. | P0 | FR-019, FR-020 | All | offline demo; T-OFF-01 |
| NFR-007 | Expose causal traceability from user input through event, operation, effect, evidence, claim, and output. | P0 | FR-001 | All | trace correlation audit; T-OBS-01 |
| NFR-008 | Use in-memory retention with explicit process-loss limitations and privacy-safe logs. | P0 | — | Runtime | restart limitation/UI notice; T-RET-01 |
| NFR-009 | Provide a one-command FDB-v3 reproduction path that validates prerequisites, pins dependency/config versions and seeds, fails nonzero on missing data/credentials/empty results, and records result/log provenance without hardcoded answers. | P0 | FR-022 | Runtime/Delivery | T-FDB-02; clean-machine rerun instructions and generated artifacts |
| NFR-010 | Measure voice acknowledgement, interruption-to-cancellation, tool-selection/argument accuracy, strict pass rate, and latency from real traces; never invent values. | P0 | FR-021, FR-022 | Runtime/Delivery | T-VOICE-01, T-FDB-02; report denominators and absent measurements explicitly |

Provisional engineering target: p95 reducer processing below 20 ms on the demo machine, measured from journal acceptance to command publication. It is not a competition requirement and excludes model/tool latency.
