# Semantic Control

The interpreter receives immutable input evidence and a bounded active-context summary. It consumes `UserInputObserved` or `TranscriptHypothesisObserved` commands and emits `ControlIntentInterpreted` plus optional `IntentRevisionProposed`; deterministic reducer policy applies consequences.

`BACKCHANNEL` changes no task; `CANCEL_SPEECH` stops queued/emitting output only; `CORRECT` revises targeted fields; `ADD_GOAL`/`RETRACT_GOAL` alter goals; `PAUSE` blocks future eligible dispatch but does not undo effects; `RESUME` re-evaluates; `REFER` requests reference resolution; `NEW_TOPIC` supersedes active goals after consequential confidence policy; `CLARIFY` asks without mutation.

Consequential controls below 0.85, multiple plausible targets, or unresolved pronouns become `CLARIFY`. Partial transcripts create provisional proposals only; a final transcript still does not authorize writes. Repeated interruptions serialize and target the latest non-superseded revision unless explicitly anchored. “Stop explaining” is speech cancellation, not booking cancellation. Model failure uses scripted demo patterns or clarification. Tests: T-CTL-01 and T-REF-01.
