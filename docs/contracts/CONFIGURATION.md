# Configuration

| Name | Type/default/range | Required; owner; failure |
|---|---|---|
| `INTERLOCK_HOST` | string `127.0.0.1` | optional; API; invalid startup fail |
| `INTERLOCK_PORT` | int `8000`, 1..65535 | optional; API |
| `INTERLOCK_FRONTEND_ORIGINS` | CSV `http://localhost:5173` | optional; API; reject unknown origin |
| `INTERLOCK_WS_URL` | URL `ws://localhost:8000/api/v1` | optional; frontend |
| `INTERLOCK_MODE` | `DEMO|LIVE|TEST`, `DEMO` | optional; composition; unknown fail |
| `INTERLOCK_MODEL_PROVIDER` | `fallback|configured`, `fallback` | optional; intelligence |
| `INTERLOCK_MODEL_API_KEY` | secret, no default | required only configured; missing uses fallback in DEMO, fails LIVE |
| `INTERLOCK_TOOL_TIMEOUT_MS` | int `5000`, 100..60000 | optional; tools |
| `INTERLOCK_BRANCH_TOP_K` | int `2`, 0..3 | optional; BranchCache |
| `INTERLOCK_BRANCH_TTL_MS` | int `10000`, 100..60000 | optional; BranchCache |
| `INTERLOCK_SPECULATION_BUDGET` | int cost units `3`, 0..20 | optional; BranchCache |
| `INTERLOCK_FAKE_LATENCY_MS` | int `250`, 0..60000 | optional; fake provider |
| `INTERLOCK_FAULT_MODE` | `none|scenario`, `scenario` in DEMO | optional; harness |
| `INTERLOCK_SESSION_RETENTION_S` | int `3600`, 60..86400 | optional; registry |
| `INTERLOCK_EVENT_RETENTION` | int `10000`, 100..100000 | optional; journal |
| `INTERLOCK_LOG_LEVEL` | `DEBUG|INFO|WARNING|ERROR`, `INFO` | optional; logging |

The `.env.example` exists for the current backend defaults. The LiveKit/FDB-v3 credential, provider, data-path, and seed configuration is not implemented; `VCE-001` and `FDB-002` must define exact validated names and externalize secrets before a reproduction command is advertised. Do not treat the sample backend configuration as sufficient for the official benchmark.

Current `.env.example`:

```dotenv
INTERLOCK_HOST=127.0.0.1
INTERLOCK_PORT=8000
INTERLOCK_FRONTEND_ORIGINS=http://localhost:5173
INTERLOCK_MODE=DEMO
INTERLOCK_MODEL_PROVIDER=fallback
INTERLOCK_TOOL_TIMEOUT_MS=5000
INTERLOCK_BRANCH_TOP_K=2
INTERLOCK_BRANCH_TTL_MS=10000
INTERLOCK_SPECULATION_BUDGET=3
INTERLOCK_FAKE_LATENCY_MS=250
INTERLOCK_FAULT_MODE=scenario
INTERLOCK_SESSION_RETENTION_S=3600
INTERLOCK_EVENT_RETENTION=10000
INTERLOCK_LOG_LEVEL=INFO
```
