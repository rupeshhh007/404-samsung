# Reconciliation

The detector compares the active desired fingerprint with authoritative world projection after intent/effect/verification changes. Mismatch creates `DivergenceCase`; duplicates are coalesced by desired/observed identity.

Planning is capability-driven: verify observed state; if obsolete effect is reversible and authorization covers compensation, cancel; verify cancellation; prepare/authorize desired action; commit it; verify final state. Providers that require book-before-cancel may use that order only if their descriptor and authorization explicitly permit it. Automatic repair is forbidden for irreversible/unknown capabilities.

Plan steps carry idempotency keys, retry rules, and base intent revision. A new correction supersedes undispatched steps and triggers replanning from the actual ledger. Compensation failure, denied repair, or unverifiable outcome marks the plan failed and case escalated; UI and speech surface the mismatch. Resolution requires authoritative evidence that observed equals current desired state. Tests: `T-REC-01`, `T-REC-02`, `T-REC-03`, and `T-E2E-02`.

## Implementation contract

- Purpose: detect desired/observed mismatch and produce/execute a safe, capability-bound repair plan.
- Non-responsibilities: privileged tool dispatch, assuming reversibility, hiding divergence, or confirming claims.
- State: reducer owns `DivergenceCase` and `ReconciliationPlan`; executor uses normal operations for each step.
- Inputs: active committed revision/fingerprint, world projection/evidence, descriptor capability hash, authorization scope. Outputs: `DivergenceDetected`, `ReconciliationPlanned`, `ReconciliationAuthorized` or `ReconciliationDenied`, `ReconciliationStepChanged`, `DivergenceResolved`, and standard operation commands.

```text
detect(desired, world):
  normalize comparable center/slot/resource identity
  if equal: resolve an existing case only with authoritative evidence
  else: open/coalesce a case keyed by desired fingerprint + observed effect IDs

plan(case):
  if observed outcome unknown: VERIFY first
  if obsolete effect exists:
    require reversible + compensation descriptor + authorization
    add COMPENSATE_OBSOLETE then VERIFY_COMPENSATION
  require desired action authorization
  add PREPARE_DESIRED, COMMIT_DESIRED, VERIFY_FINAL
```

| Situation | Result |
|---|---|
| capability unknown/irreversible | `ESCALATED`, manual-only; no compensation |
| authorization missing | divergence remains PLANNED, plan remains DRAFT, and exact scope is requested |
| step timeout after dispatch | step/plan unresolved; verify, never skip ahead |
| compensation failure | plan FAILED, case ESCALATED, uncertainty output |
| intent/capability hash changes | plan SUPERSEDED; retain committed steps; redetect/replan |
| interim commit result matches current desired | ledger updates, but an active plan remains RUNNING and case RECONCILING |
| `VERIFY_FINAL` matches current desired and confirms obsolete effects compensated | plan SUCCEEDED; case RESOLVED |

Only one RUNNING plan per divergence is allowed; step idempotency prevents duplicate compensation. Acceptance: `T-REC-01`, `T-REC-02`, `T-REC-03`, `T-E2E-02`, `T-INV-I10-P`, and `T-INV-I10-N`. Owner C; depends on EXE-005, authorization, and descriptor contracts.
