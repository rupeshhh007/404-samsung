# Invariant Test Registry

This file owns all canonical invariant-case IDs. All cases are implemented in the owning module’s unit test file or `backend/tests/concurrency/test_races.py`. Initial state is a valid TEST session with canonical descriptors unless stated otherwise. A positive case passes when the allowed action and state occur; a negative case passes only when the adversarial input is rejected/contained and the forbidden effect/output is absent.

| Invariant / responsible ticket / enforcement / planned file | Positive ID and input → expected result | Negative ID and adversary → expected result |
|---|---|---|
| I1; TST-003; FR-005; reducer fingerprint; `test_intent_graph.py` | `T-INV-I1-P`: current read result → active projection updated | `T-INV-I1-N`: stale read completes after correction → historical evidence only, active projection unchanged |
| I2; TST-004; FR-006, FR-008; ToolRuntime; `test_branch_cache.py` | `T-INV-I2-P`: READ_ONLY/NONE branch → adapter may run | `T-INV-I2-N`: speculative booking → `SPECULATION_FORBIDDEN`, zero adapter calls/effects |
| I3; TST-003; FR-007; SAFEPOINT; `test_safepoint.py` | `T-INV-I3-P`: AT_SAFEPOINT cancel at named point → local cancellation | `T-INV-I3-N`: forced NONCANCELLABLE stop → request recorded, observation continues |
| I4; TST-003; FR-011; effects; `test_effects.py` | `T-INV-I4-P`: current confirmed result → ledger COMMITTED | `T-INV-I4-N`: superseded operation commits late → same COMMITTED retention plus divergence |
| I5; TST-003; FR-010; idempotency; `test_tools.py` | `T-INV-I5-P`: same key/same args retry → one logical effect | `T-INV-I5-N`: duplicate callbacks/retry conflict → no second logical effect; conflict violation/unknown |
| I6; TST-003; FR-015; TRUTHLOCK; `test_truthlock.py` | `T-INV-I6-P`: exact confirmed claim → confirmed template approved | `T-INV-I6-N`: pending/unknown claim → success blocked; no confirmed wording |
| I7; TST-003; FR-003; semantic policy; `test_control.py` | `T-INV-I7-P`: high-confidence correction → revision proposed | `T-INV-I7-N`: low-confidence destructive control → clarification, no mutation/cancel |
| I8; TST-003; FR-013, FR-017; evidence; `test_evidence.py` | `T-INV-I8-P`: new derived interpretation → source and derived records coexist | `T-INV-I8-N`: same ID/different content → violation; original byte/hash unchanged |
| I9; TST-003; FR-014; claims/effects; `test_claims.py` | `T-INV-I9-P`: exact authoritative booking confirmation → claim CONFIRMED | `T-INV-I9-N`: earlier/faster acknowledgement or mismatched slot → desired claim not confirmed |
| I10; TST-004; FR-012; divergence; `test_reconciliation.py` | `T-INV-I10-P`: desired equals verified world → no OPEN case/resolution valid | `T-INV-I10-N`: desired 12 vs world 11 → OPEN or active case visible; cannot hide mismatch |
| I11; TST-003; FR-002, NFR-001; runtime boundary; `test_reducer.py` | `T-INV-I11-P`: reducer event advances state/sequence | `T-INV-I11-N`: worker attempts mutation/out-of-band update → rejected/not observable in state |
| I12; TST-003; NFR-003; replay; `test_reducer.py` | `T-INV-I12-P`: live reduction emits expected dispatch command | `T-INV-I12-N`: same journal in REPLAY → zero external/output dispatch while state matches |
| I13; TST-003; FR-007, FR-012; operation policy; `test_operations.py` | `T-INV-I13-P`: authoritative verify proves absence → OUTCOME_UNKNOWN→FAILED | `T-INV-I13-N`: timeout alone → remains OUTCOME_UNKNOWN; no blind retry/failure claim |
| I14; TST-003; FR-004, FR-009; SAFEPOINT; `test_safepoint.py` | `T-INV-I14-P`: committed active revision + exact authorization → dispatch allowed | `T-INV-I14-N`: provisional/stale/expired authorization → no dispatch/provider call |

Each negative case also runs relevant adversarial ordering: callback before cancellation acknowledgement, duplicate before original processing completes, or correction while reconciliation is running. Requirements covered are FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-009, FR-010, FR-011, FR-012, FR-013, FR-014, FR-015 and NFR-003.

Exact path expansion: every short `test_*.py` name in the table is under `backend/tests/unit/`. `TST-004` owns `T-INV-I2-P`, `T-INV-I2-N`, `T-INV-I10-P`, and `T-INV-I10-N` in `test_branch_cache.py` and `test_reconciliation.py`. `TST-003` owns the other 24 named cases and the concurrency variants in `backend/tests/concurrency/test_races.py`.
