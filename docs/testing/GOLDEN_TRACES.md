# Golden Traces

Abbreviations: `I` active intent slot, `O` operation, `W` world, `C` claim, `TL` TRUTHLOCK.

| Trace | Ordered distinguishing facts | Final assertion |
|---|---|---|
| G-01 Normal booking | input 12 → revision/authorize → prepare → dispatch/accept → result → effect 12 → claim confirmed → speech approved | W=12; confirmed output |
| G-02 Correction before commit | book 11 → prepare → correct 12 → invalidate/cancel → book 12 → effect/claim | no W=11 |
| G-03 Correction after commit | effect 11 → correct 12 → divergence | W=11, I=12, no false success |
| G-04 Late reconciliation | sequence below | final W=12; old effect compensated |
| G-05 Unknown outcome | dispatch → timeout(after) → unknown → verification pending | uncertainty output; no retry/success |
| G-06 Failed compensation | divergence → plan → cancel failure → escalated | W=11, I=12, warning |

## G-04 primary trace

| t/seq | Event | I | O / W | C / TL / output | Assertion |
|---:|---|---|---|---|---|
| 0/10 | `IntentRevisionCommitted` 11 | 11 | book11 READY / — | proposed / pending | authorized |
| 100/12 | `ToolDispatchAccepted` | 11 | WAITING/IN_FLIGHT | pending / “submitting” | boundary crossed |
| 200/14 | correction revision committed | 12 | book11 SUPERSEDED, cancel REQUESTED | 11 claim stale | selective invalidation |
| 300/15 | `CancellationAcknowledged` local | 12 | ACK / IN_FLIGHT | no confirmation | ACK limited |
| 900/16 | provider commits (scheduled) | 12 | stale / external 11 | — | fault |
| 1100/17-18 | result + `WorldEffectObserved` | 12 | effect apt-11 COMMITTED | 12 pending | late retained |
| 1100/19 | `DivergenceDetected` | 12 | W=11 | TL permits mismatch notice | open case |
| 1200/20 | plan authorized | 12 | verify/cancel/verify/book/verify | — | capability-bound |
| 1250/22 | obsolete booking verified | 12 | apt-11 COMMITTED | divergence remains open | verify before compensate |
| 1500/24 | cancel confirmed | 12 | apt-11 COMPENSATED | cancellation confirmed | exact booking/center matched |
| 1850/27 | book12 result observed | 12 | apt-12 COMMITTED | claim awaits final verification | exact result retained |
| 1880/28 | final booking verified | 12 | apt-12 COMMITTED | claim confirmed | center/requested/confirmed slot exact |
| 1900/29-30 | resolved + speech approved | 12 | W=12 | TL confirmed / final text | all agree |

Unexpected event order, a missing effect, or success before seq 28 fails the golden test.

Canonical checkpoints: at 1100 ms the case is OPEN, apt-11 is COMMITTED, the 12:00 claim is PENDING, and confirmed-12 speech is absent. At 2000 ms the case is RESOLVED, apt-11 is COMPENSATED, apt-12 is COMMITTED, the 12:00 claim is CONFIRMED, and the final controlled sentence is last. These checkpoints are normative for `late_reconcile.yaml` and `T-E2E-02`.
