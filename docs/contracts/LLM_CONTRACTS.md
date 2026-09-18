# Runtime LLM Contracts

The provider abstraction accepts a task name, versioned prompt, JSON input, output schema, timeout, and correlation ID; it returns validated JSON or a typed failure. Runtime models may propose controls, deltas, branches, and temporal anchors. They may not mutate state, dispatch tools, authorize actions, create authoritative evidence, or confirm effects.

## Prompt templates

`CONTROL_V1`: “Classify the utterance using only ControlKind values. Identify explicit targets. Set consequential true if execution/intent may change. Return `{kind,confidence,consequential,target_refs,clarification}`. Do not execute or assert outcomes.”

`DELTA_V1`: “Given the active goal schema and evidence, return `{target_intent_id,set_fields,unset_fields,add_goals,retract_goals,confidence}`. Preserve unspecified fields; do not infer authorization.”

`BRANCH_V1`: “Return at most K likely next deltas with confidence and eligible read-only tool names from the supplied descriptors. Never include a descriptor not explicitly READ_ONLY/NONE.”

`REFERENCE_V1`: “Resolve a temporal phrase against supplied evidence metadata only. Return `{candidate_evidence_ids,confidence,reason}`; do not rewrite evidence.”

JSON is strict: extra fields rejected, confidence 0..1, IDs must be supplied candidates. One retry is allowed only for format repair, not timeout. Invalid/timeout/unavailable invokes deterministic scripted phrase rules in demo mode; otherwise `CLARIFY` or no branch. Consequential controls below `CONTROL_CONSEQUENTIAL_THRESHOLD` (default 0.85) clarify. Prompt/version/input digest and validation outcome are traced without secret/raw-image leakage.

Development coding agents are unrelated to this runtime interface; see [AI Usage](../agents/AI_USAGE.md).
