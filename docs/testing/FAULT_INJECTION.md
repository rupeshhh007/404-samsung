# Fault Injection

| Fault type | Configuration | Fake-provider behavior | Required runtime result |
|---|---|---|---|
| `LATENCY` | `delay_ms` | schedules result later | no state race |
| `FAILURE` | `code, before_dispatch` | typed failure | safe fail or unknown per boundary |
| `TIMEOUT` | `after_dispatch` | no timely result | unknown if crossed boundary |
| `IGNORE_CANCELLATION` | operation match | ACK scope may be local; call continues | late result admitted |
| `LATE_RESULT` | `delay_ms` | result after supersession/timeout | ledger/verification processing |
| `COMMIT_BEFORE_CANCEL` | commit/cancel logical times | commits first | cancel too late + effect |
| `DUPLICATE_CALLBACK` | `count, identical` | repeats result | dedupe; conflict unknown |
| `DUPLICATE_RETRY` | provider idempotency flag | sees same/different key | one effect when supported |
| `UNKNOWN_OUTCOME` | after dispatch | withholds commit fact | verification required |
| `COMPENSATION_FAILURE` | error code | cancel fails | divergence escalated |

Fault activation is test/demo-only and journaled before its effect. Exact demo: `IGNORE_CANCELLATION` for `op-book-11`, commit at logical 900 ms, callback at 1100 ms after correction. Assertions are defined in golden traces; faults never modify reducer state directly.
