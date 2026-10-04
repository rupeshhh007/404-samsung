# Integrated Demo Scenario

Labels: UI and presenter must distinguish **REAL runtime logic**, **SIMULATED provider/data**, **SCRIPTED fault/timing**, and **MODEL-ASSISTED** interpretation (or fallback).

| Step | Exact user / agent text | Backend, events, state and UI assertions |
|---:|---|---|
| 1 | Upload `frame-21`; agent: “I observed error E14 in the supplied demo frame.” | evidence source FRAME + derived interpretation; provenance card; simulated badge |
| 2 | — | BranchCache predicts center/manual reads; `BranchPredicted`; only read tools; ANTICIPATE panel |
| 3 | “Find a service center.” | promote valid branch or read; center `ctr-01`; cache hit/miss visible |
| 4 | “What appointments are available?” | availability read; evidence shows 11/12 and freshness |
| 5 | At 0 ms: “Book 11:00.” | committed+authorized revision; prepare/safe point/dispatch through the fake provider |
| 6 | Before the scripted response: “Actually, make it 12:00.” | correction commits; 11 operation cancellation requested; UI desired=12 |
| 7 | After `INTERLOCK_FAKE_LATENCY_MS` | simulated provider has committed 11 and returns it despite cancellation; late result/effect retained |
| 8 | Agent: “I can’t yet verify whether the booking completed.” | canonical P0 checkpoint: world=11, desired=12, divergence OPEN, 12 claim PENDING, exact TRUTHLOCK-approved uncertainty output |
| 9 | 1200–1880 ms | plan verify→cancel 11→confirm cancel→prepare/book 12→verify; stepper updates |
| 10 | At 1900 ms, agent: “Confirmed — your 12:00 appointment is booked.” | apt-11 compensated, apt-12 committed, exact center/requested/confirmed-slot evidence confirms claim, divergence RESOLVED |
| 11 | Open trace | causal chain and metrics shown; no invented measured values |

EXT-001 stops after step 8 with an unresolved warning and no success claim.
Steps 9–10 are the planned EXE-006/TST-004/UI-005 continuation, not implemented
or demonstrated by this P0 composition. The fallback interpreter is the
expected credential-free path.
