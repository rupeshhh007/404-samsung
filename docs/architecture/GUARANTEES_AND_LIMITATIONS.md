# Guarantees and Limitations

| Area | Local guarantee | Provider-dependent / not guaranteed |
|---|---|---|
| Speculation | explicit read-only/no-effect descriptors only; hard rejection otherwise | provider may misdeclare behavior; allowlisting mitigates |
| Cancellation | policy and safe-point compliance locally | remote commit may cross boundary; ACK meaning is descriptor-specific |
| Idempotency | session logical-action dedupe and duplicate callback suppression | exactly-once remote execution requires provider idempotency |
| Effects | all observed authoritative effects retained | unobserved effects and post-crash callbacks may be lost |
| Claims | certainty cannot exceed registered evidence rule | source itself may be wrong; freshness expires |
| Speech | consequential templates pass TRUTHLOCK | already-heard audio cannot be retracted; correction only |
| Replay | deterministic state reconstruction and no dispatch | memory journal disappears on crash |
| Compensation | only planned/authorized/capability-declared | irreversible effects or provider failure remain divergent |

The deterministic simulator tests these guarantees for scripted providers; that does not certify arbitrary real providers. A timeout after dispatch is unknown, never assumed failed. Process crash loses sessions and cannot discover remote outcomes until a future persistent/versioned implementation adds recovery. INTERLOCK reduces unsupported claims; it does not eliminate all hallucination, guarantee external truth, or make irreversible actions reversible.
