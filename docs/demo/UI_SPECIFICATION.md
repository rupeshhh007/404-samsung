# UI Specification

## Layout

Desktop uses a three-column workbench: left conversation/input, center intent→operation→world pipeline, right evidence/claims/TRUTHLOCK; bottom full-width trace and metrics. Tablet stacks conversation then pipeline then inspectors; mobile uses accessible tabs with persistent divergence banner.

```text
+ Conversation --------+ Consistency pipeline --------+ Evidence / Claims -----+
| frame, transcript    | Intent: desired 12:00        | FRAME-21 → E14         |
| verified messages    | Operation: cancel requested  | Booking claim: pending |
| input / interrupt    | World: 11:00 confirmed       | TRUTHLOCK: blocked     |
+----------------------+-------------------------------+-------------------------+
| DIVERGENCE: 11:00 exists; desired 12:00 | reconciliation 2/5            |
+ Trace timeline ------------------------------------------------------------+
| Metrics (measured / not measured)                                          |
```

Semantic roles: neutral/slate unknown, blue active/read, violet speculative (ANTICIPATE), amber cancellation/pending, red divergence/block, teal reconciliation (ADAPT), green authoritative confirmation (VERIFY). Always pair color with icon/text.

Empty panels explain what will appear. Loading says the exact stage (“Checking availability”). Errors distinguish retry-safe reads, unknown write outcomes, and unresolved mismatches. Consequential strings are those in TRUTHLOCK policy; UI must not paraphrase “confirmed.” Divergence alert states desired and observed values. Reconciliation stepper shows verify/cancel/confirm/book/verify and never marks success early.

The timeline shows sequence, logical time, event, causation, affected intent/operation/effect/claim, and expandable sanitized payload. Metrics show formula labels and “not measured” where absent. Actions: start/reset session, submit text/frame reference, authorize prompted repair, cancel speech, open trace. Keyboard operation, focus restoration, live-region priority for clarification/divergence/final result, and reduced motion are required.
