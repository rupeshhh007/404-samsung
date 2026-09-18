# Integrated Demo Scenario

Labels: UI and presenter must distinguish **REAL runtime logic**, **SIMULATED provider/data**, **SCRIPTED fault/timing**, and **MODEL-ASSISTED** interpretation (or fallback).

| Step | Exact user / agent text | Backend, events, state and UI assertions |
|---:|---|---|
| 1 | Upload `frame-21`; agent: “I observed error E14 in the supplied demo frame.” | evidence source FRAME + derived interpretation; provenance card; simulated badge |
| 2 | — | BranchCache predicts center/manual reads; `BranchPredicted`; only read tools; ANTICIPATE panel |
| 3 | “Find a service center.” | promote valid branch or read; center `ctr-01`; cache hit/miss visible |
| 4 | “What appointments are available?” | availability read; evidence shows 11/12 and freshness |
| 5 | At 0 ms: “Book 11.” | committed+authorized revision; prepare/safe point/dispatch; agent: “I’m submitting the 11:00 booking.” |
| 6 | At 200 ms: “Actually, make it 12.” | correction, 11 op superseded, cancel requested; UI desired=12, operation cancellation pending |
| 7 | At 900/1100 ms | scripted provider commits then returns apt-11 despite cancellation; late result/effect retained |
| 8 | At 1100 ms, agent: “An 11:00 booking exists, but you requested 12:00. I’m reconciling it.” | canonical intermediate checkpoint: divergence OPEN, 12 claim PENDING, confirmed-12 speech blocked |
| 9 | 1200–1880 ms | plan verify→cancel 11→confirm cancel→prepare/book 12→verify; stepper updates |
| 10 | At 1900 ms, agent: “Confirmed — your 12:00 appointment is booked.” | apt-11 compensated, apt-12 committed, exact center/requested/confirmed-slot evidence confirms claim, divergence RESOLVED |
| 11 | Open trace | causal chain and metrics shown; no invented measured values |

If the model is unavailable, scripted phrases produce the same events and display `Fallback interpreter`. If reconciliation is disabled/fails, stop after step 8 with an unresolved warning and no success claim.
