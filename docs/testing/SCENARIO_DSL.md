# Deterministic Scenario DSL

Virtual time is an integer number of milliseconds from session start. `at_ms` and `advance_to` are absolute, never relative. Time cannot move backward. Advancing to `T` executes all scheduled items with time ≤ `T`, ordered by `(scheduled_time, declaration_index)`, and drains reducer-generated zero-delay work before an assertion. Inputs are journal facts, tool scripts match logical operation properties, faults alter fake-provider behavior, and checkpoints assert events/state/world/claims/speech at a precise logical time.

```json
{
  "schema_version": 1,
  "scenario_id": "late-effect-reconcile",
  "fixture": "samsung-demo-v1",
  "initial_state": {"session_id": "demo", "mode": "TEST"},
  "tools": {
    "appointment.book": [
      {
        "match": {"args.requested_slot": "2030-01-15T11:00:00+05:30"},
        "acknowledge_at_ms": 100,
        "acknowledgement": {"phase": "ACKNOWLEDGEMENT", "status": "REQUEST_RECEIVED", "provider_request_id": "req-11", "center_id": "ctr-01", "requested_slot": "2030-01-15T11:00:00+05:30"},
        "commit_at_ms": 900,
        "callback_at_ms": 1100,
        "result": {"phase": "FINAL", "status": "BOOKING_CONFIRMED", "provider_request_id": "req-11", "provider_booking_id": "apt-11", "center_id": "ctr-01", "requested_slot": "2030-01-15T11:00:00+05:30", "confirmed_slot": "2030-01-15T11:00:00+05:30"}
      },
      {
        "match": {"args.requested_slot": "2030-01-15T12:00:00+05:30"},
        "acknowledge_at_ms": 1700,
        "acknowledgement": {"phase": "ACKNOWLEDGEMENT", "status": "REQUEST_RECEIVED", "provider_request_id": "req-12", "center_id": "ctr-01", "requested_slot": "2030-01-15T12:00:00+05:30"},
        "callback_at_ms": 1850,
        "result": {"phase": "FINAL", "status": "BOOKING_CONFIRMED", "provider_request_id": "req-12", "provider_booking_id": "apt-12", "center_id": "ctr-01", "requested_slot": "2030-01-15T12:00:00+05:30", "confirmed_slot": "2030-01-15T12:00:00+05:30"}
      }
    ],
    "appointment.get": [
      {"match": {"provider_booking_id": "apt-11"}, "callback_at_ms": 1250, "result": {"phase": "FINAL", "status": "BOOKING_CONFIRMED", "provider_request_id": "req-get-11", "provider_booking_id": "apt-11", "center_id": "ctr-01", "requested_slot": "2030-01-15T11:00:00+05:30", "confirmed_slot": "2030-01-15T11:00:00+05:30"}},
      {"match": {"provider_booking_id": "apt-12"}, "callback_at_ms": 1880, "result": {"phase": "FINAL", "status": "BOOKING_CONFIRMED", "provider_request_id": "req-get-12", "provider_booking_id": "apt-12", "center_id": "ctr-01", "requested_slot": "2030-01-15T12:00:00+05:30", "confirmed_slot": "2030-01-15T12:00:00+05:30"}}
    ],
    "appointment.cancel": [
      {"match": {"provider_booking_id": "apt-11"}, "callback_at_ms": 1500, "result": {"status": "CANCELLATION_CONFIRMED", "provider_request_id": "req-cancel-11", "provider_booking_id": "apt-11", "center_id": "ctr-01", "cancelled_at": "2030-01-15T05:30:01.500Z"}}
    ]
  },
  "faults": [{"id": "ignore-cancel-11", "type": "IGNORE_CANCELLATION", "match": {"operation_id": "op-book-11"}}],
  "steps": [
    {"input": {"at_ms": 0, "text": "Book 11.", "final": true, "authorize": true}},
    {"input": {"at_ms": 200, "text": "Actually, make it 12.", "final": true, "authorize": true}},
    {"advance_to": 1100},
    {"assert": {"state": {"active_slot": "12:00", "divergences.open": 1}, "world": {"contains_booking": "apt-11"}, "claims": {"booking_12": "PENDING"}, "speech_absent": ["Confirmed — your 12:00 appointment is booked."]}},
    {"advance_to": 2000}
  ],
  "expect": {
    "events_in_order": ["IntentRevisionCommitted", "CancellationRequested", "ToolResultObserved", "WorldEffectObserved", "DivergenceDetected", "ReconciliationPlanned", "ReconciliationAuthorized", "DivergenceResolved", "SpeechActApproved"],
    "state": {"active_slot": "12:00", "divergences.resolved": 1, "reconciliation_plans.succeeded": 1},
    "world": {"confirmed_booking": "apt-12", "compensated_booking": "apt-11"},
    "claims": {"booking_12": "CONFIRMED"},
    "speech_last": "Confirmed — your 12:00 appointment is booked."
  }
}
```

The example is JSON and therefore valid YAML 1.2 for the planned `.yaml` scenario files. The 1100 ms assertion is the canonical intermediate divergence checkpoint. The final expectation is evaluated at 2000 ms, after the golden trace resolves at 1900 ms. DSL validation rejects unknown match paths/events, wall-clock sleeps, relative/retrograde time, incomplete expectations, and non-deterministic random faults. Optional seeded data generation must record its seed.
