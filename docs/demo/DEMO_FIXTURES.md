# Demo Fixtures

All values are **SIMULATED**, stable, and not representations of Samsung services.

```json
{
  "fixture_id":"samsung-demo-v1",
  "device":{"device_id":"dev-galaxy-demo-01","label":"Galaxy Demo Device","model":"SIM-GX1"},
  "frames":[
    {"evidence_id":"frame-21","content_ref":"fixture://frames/error-e14.png","observed_error":"E14","captured_at":"2030-01-15T05:30:00Z"},
    {"evidence_id":"frame-38","content_ref":"fixture://frames/error-e17.png","observed_error":"E17","captured_at":"2030-01-15T05:31:00Z"}
  ],
  "centers":[{"center_id":"ctr-01","name":"Demo Service Center A","timezone":"Asia/Kolkata"}],
  "availability":{"ctr-01":["2030-01-15T11:00:00+05:30","2030-01-15T12:00:00+05:30"]},
  "warranty":{"device_id":"dev-galaxy-demo-01","status":"ACTIVE_SIMULATED","through":"2030-12-31"},
  "appointments":{
    "obsolete":{"provider_request_id":"req-11","provider_booking_id":"apt-11","center_id":"ctr-01","requested_slot":"2030-01-15T11:00:00+05:30","confirmed_slot":"2030-01-15T11:00:00+05:30"},
    "desired":{"provider_request_id":"req-12","provider_booking_id":"apt-12","center_id":"ctr-01","requested_slot":"2030-01-15T12:00:00+05:30","confirmed_slot":"2030-01-15T12:00:00+05:30"}
  },
  "results":{"book_status":"BOOKING_CONFIRMED","cancel_status":"CANCELLATION_CONFIRMED"},
  "fault":{"id":"ignore-cancel-11","type":"IGNORE_CANCELLATION","commit_at_ms":900,"callback_at_ms":1100},
  "initial_provider_state":{"bookings":[]},
  "final_provider_state":{"bookings":[{"provider_booking_id":"apt-12","center_id":"ctr-01","confirmed_slot":"2030-01-15T12:00:00+05:30","status":"BOOKING_CONFIRMED"}],"cancelled":[{"provider_booking_id":"apt-11","center_id":"ctr-01","status":"CANCELLATION_CONFIRMED"}]}
}
```

Error meanings are intentionally not specified; the demo shows provenance/temporal reference, not real diagnostics. Reset restores empty bookings, idempotency registry, virtual clock 0, fault plan, and session state.
