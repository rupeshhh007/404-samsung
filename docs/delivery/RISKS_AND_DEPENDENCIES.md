# Risks and Dependencies

| ID | Category; description | Likelihood / impact | Mitigation / fallback | Owner; requirements |
|---|---|---|---|---|
| R-01 | Concurrency: dispatch/cancel race | High/High | separate states, ledger, deterministic race / surface divergence | C; FR-007, FR-011 |
| R-02 | Provider: ignored cancellation/ambiguous ACK | High/High | confirmation semantics, verify / unknown wording | C; FR-011, FR-012 |
| R-03 | Idempotency: provider lacks keys | Medium/High | no blind write retry / manual verification | C; FR-010 |
| R-04 | LLM invalid/ambiguous output | High/Medium | schemas/confidence/fallback / clarify | B; FR-003 |
| R-05 | External data authority/freshness | Medium/High | rules/expiry / uncertainty | D; FR-014 |
| R-06 | Integration schema drift | Medium/High | canonical owners/gates/contract policy | A; NFR-005 |
| R-07 | Demo timing/nondeterminism | Medium/High | virtual clock/golden trace / scripted trace | A; FR-019 |
| R-08 | Frontend implies success | Medium/High | backend projection/exact text/UI tests | D; FR-015 |
| R-09 | In-memory crash loses facts | Medium/High | disclose, short demo/reset / verify provider manually | A; NFR-008 |
| R-10 | Privacy: media/transcripts in logs | Medium/High | refs/hashes/redaction/retention | A/B; NFR-004, NFR-008 |
| R-11 | Delivery scope overload | High/Medium | gates/cut P2/degraded P1 behavior | all; scope |
| R-12 | Manifest misclassification | Medium/High | trusted allowlist/conservative defaults / disable tool | C; FR-008 |

Unavailable external prerequisites: official Samsung protocol/API/manifests, credentials, error-code meanings, service-center/availability/warranty data, and booking/cancellation/idempotency guarantees. They are not blockers for the local demo; `SAMSUNG_ADAPTER.md`, mock manifests, and simulated fixtures isolate them. A real integration requires supplied specs, credentials, privacy/security review, and contract tests.
