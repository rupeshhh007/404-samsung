# User Journeys

| Step | User action | Agent / visible UI | Runtime and error behavior | Complete when |
|---|---|---|---|---|
| 1 | Open app | “Start session”; disconnected/empty trace | fetch capability metadata | session can be created |
| 2 | Start | session badge, clean timeline | journal `SessionStarted` | snapshot sequence shown |
| 3 | Supply error frame | preview + “Observed E14 (simulated interpretation)” | immutable frame and derived evidence | provenance visible |
| 4 | Ask for help/center | checking then center cards | BranchCache may supply valid read | sources shown or error retry offered |
| 5 | Ask availability | 11:00/12:00 slots | read-only tool result becomes evidence | freshness shown |
| 6 | Say “Book 11.” | prepared/submitting, never “confirmed” | committed authorized intent; SAFEPOINT dispatch | operation in flight |
| 7 | Interrupt “Actually, make it 12.” | old operation marked cancel requested; desired slot changes | selective invalidation; cancel command | revision 2 active |
| 8 | Observe late 11:00 commit | red/amber divergence banner: “11:00 exists; you requested 12:00” | ledger retains effect; pending success claim contradicted | case open |
| 9 | Allow configured recovery | reconciliation stepper | confirm cancellation then dispatch 12:00 | provider confirms final state |
| 10 | Receive result | “Confirmed — your 12:00 appointment is booked.” | authoritative evidence confirms claim; TRUTHLOCK permits | intent/world/claim agree |
| 11 | Inspect trace | causal timeline and metric values | projection is read-only | relevant event chain visible |

If the LLM is unavailable, deterministic phrase rules handle scripted inputs and the UI labels fallback mode. If compensation fails, the journey ends with an unresolved divergence and instructions to verify manually—never a fabricated confirmation.

## Updated voice/benchmark journey (planned)

The user speaks through LiveKit. Partial hypotheses may prepare interpretation but cannot authorize a consequential write. The agent gives a meaningful safe acknowledgement within the measured few-hundred-millisecond target while model/perception/tool work proceeds asynchronously. A mid-utterance correction or barge-in cancels stale speech promptly, updates only affected intent dependencies, and prevents stale or duplicate writes at SAFEPOINT. A tool receipt permits progress wording only; authoritative confirmation or verified absence determines final wording. The same generic path must handle FDB-v3 chained tools and self-corrections with a fresh session per benchmark scenario. No current runnable adapter verifies this journey.
