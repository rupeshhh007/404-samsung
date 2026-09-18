# Tool Descriptor Contract

```json
{
  "tool_name":"appointment.book","manifest_version":1,
  "argument_schema":{"type":"object","additionalProperties":false,"required":["center_id","requested_slot","idempotency_key"],"properties":{"center_id":{"type":"string","minLength":1},"requested_slot":{"type":"string","format":"date-time"},"idempotency_key":{"type":"string","minLength":1}}},
  "result_schema":{"oneOf":[
    {"type":"object","additionalProperties":false,"required":["phase","status","provider_request_id","center_id","requested_slot"],"properties":{"phase":{"const":"ACKNOWLEDGEMENT"},"status":{"const":"REQUEST_RECEIVED"},"provider_request_id":{"type":"string"},"center_id":{"type":"string"},"requested_slot":{"type":"string","format":"date-time"}}},
    {"type":"object","additionalProperties":false,"required":["phase","status","provider_request_id","provider_booking_id","center_id","requested_slot","confirmed_slot"],"properties":{"phase":{"const":"FINAL"},"status":{"const":"BOOKING_CONFIRMED"},"provider_request_id":{"type":"string"},"provider_booking_id":{"type":"string"},"center_id":{"type":"string"},"requested_slot":{"type":"string","format":"date-time"},"confirmed_slot":{"type":"string","format":"date-time"}}},
    {"type":"object","additionalProperties":false,"required":["phase","status","provider_request_id","error"],"properties":{"phase":{"const":"FINAL"},"status":{"const":"BOOKING_FAILED"},"provider_request_id":{"type":"string"},"error":{"type":"object","additionalProperties":false,"required":["code","message","retryable"],"properties":{"code":{"type":"string"},"message":{"type":"string"},"retryable":{"type":"boolean"}}}}},
    {"type":"object","additionalProperties":false,"required":["phase","status","provider_request_id"],"properties":{"phase":{"const":"FINAL"},"status":{"const":"OUTCOME_UNKNOWN"},"provider_request_id":{"type":"string"}}}
  ]},
  "effect_classification":"EXTERNAL_STATE_CHANGE","action_type":"REVERSIBLE",
  "cancellation_policy":"AT_SAFEPOINT","safe_points":["BEFORE_PROVIDER_DISPATCH"],"timeout_ms":5000,
  "retry_policy":{"max_attempts":1,"retry_on":[]},
  "idempotency":{"supported":true,"scope":"PROVIDER","key_field":"idempotency_key"},
  "compensation":{"supported":true,"tool_name":"appointment.cancel","requires_authorization":true},
  "confirmation_semantics":{"acknowledgement":"REQUEST_RECEIVED","commit":"BOOKING_CONFIRMED","unknown":"OUTCOME_UNKNOWN","authoritative_fields":["provider_request_id","provider_booking_id","center_id","requested_slot","confirmed_slot"]}
}
```

Normalization verifies schemas, bounds timeout, resolves referenced compensation tools, and hashes the capability set. Missing/unknown effect becomes `UNKNOWN`, action `IRREVERSIBLE`, cancellation `NONCANCELLABLE`, retries zero, idempotency false, compensation false; registration may allow manual invocation but never speculation/automatic retry/repair.

ToolRuntime authorizes speculation only when action is `READ_ONLY`, effect classification `NONE`, and descriptor registration is trusted. Tool name and HTTP method are irrelevant. Results are schema-validated and interpreted using confirmation semantics: receipt is evidence of receipt, never commit. Manifest changes invalidate cached branches and active reconciliation plans by capability hash.

The local `appointment.cancel` descriptor requires `provider_booking_id`, `center_id`, and `idempotency_key`. Its confirmed result requires `CANCELLATION_CONFIRMED`, `provider_request_id`, the same booking and center IDs, and `cancelled_at`. `appointment.get` is the authoritative read used after unknown booking/cancellation outcomes. These are simulated internal contracts; the Samsung adapter must translate verified external semantics when available.
