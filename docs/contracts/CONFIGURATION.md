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
| `INTERLOCK_TOOL_TIMEOUT_MS` | int `5000`, 100..60000 | optional; tools; in DEMO this overrides fixture-manifest timeouts so manual delayed-provider tests can safely use values above 5000 ms |
| `INTERLOCK_BRANCH_TOP_K` | int `2`, 0..3 | optional; BranchCache |
| `INTERLOCK_BRANCH_TTL_MS` | int `10000`, 100..60000 | optional; BranchCache |
| `INTERLOCK_SPECULATION_BUDGET` | int cost units `3`, 0..20 | optional; BranchCache |
| `INTERLOCK_FAKE_LATENCY_MS` | int `250`, 0..60000 | optional; fake provider |
| `INTERLOCK_FAULT_MODE` | `none|scenario`, `scenario` in DEMO | optional; harness |
| `INTERLOCK_SESSION_RETENTION_S` | int `3600`, 60..86400 | optional; registry |
| `INTERLOCK_EVENT_RETENTION` | int `10000`, 100..100000 | optional; journal |
| `INTERLOCK_LOG_LEVEL` | `DEBUG|INFO|WARNING|ERROR`, `INFO` | optional; logging |
| `FDB_V3_REPO` | path to official FDB checkout | required by FDB-002; missing/wrong commit fails before launch |
| `FDB_V3_DATA_DIR` | path to released FDB-v3 example directories | required by FDB-002; zero/malformed examples fail |
| `FDB_V3_PROVIDER` | `gpt_realtime|grok|gemini2_5|gemini3_1|ultravox|azure_openai` | required by FDB-002; unsupported provider fails |
| `FDB_V3_PYTHON` | path to a real Python 3.11 executable; project `.venv/bin/python` fallback in the reproduction script | optional selector; when the main pytest process uses another Python version, set this explicitly so T-FDB-02 delegates to Python 3.11 |
| `FDB_V3_BENCHMARK_COMMIT` | git SHA; default `3e799c45a045256f47d5f1c9cda90157e2d2ec9e` | optional explicit benchmark pin override |
| `FDB_V3_SEED` | integer-like string `0` | optional; exported as `PYTHONHASHSEED` and recorded in provenance |
| `FDB_V3_LATENCY_PROFILE` | official MockAPI latency profile, `instant` | optional; FDB provider fixture |
| `FDB_V3_USE_LLM_JUDGE` | `0|1`, `0` | optional; invalid value fails |
| `FDB_V3_RUN_ID` | nonempty run label; UTC timestamp | optional; default artifact directory component |
| `FDB_V3_OUTPUT_DIR` | writable path, `artifacts/fdb-v3/<run id>` | optional; evaluator artifacts and provenance |
| `LIVEKIT_URL` | secret-bearing service URL | required by VCE-001/FDB-002; missing fails |
| `LIVEKIT_API_KEY` | secret, no default | required by VCE-001/FDB-002; missing fails |
| `LIVEKIT_API_SECRET` | secret, no default | required by VCE-001/FDB-002; missing fails |
| `INTERLOCK_VOICE_WORKER_SECRET` | separate random secret, at least 32 characters, no default | required by browser voice backend and worker; never returned or journaled |
| `INTERLOCK_VOICE_BACKEND_WS_URL` | internal WebSocket base ending `/api/v1`, no default (for example `ws://127.0.0.1:8000/api/v1`) | required by browser voice worker; use `wss://` across hosts; worker appends `/internal/voice/{session_id}/transport` |
| `DEEPGRAM_API_KEY` | secret, no default | required by browser voice worker for Nova-3 STT |
| `CARTESIA_API_KEY` | secret, no default | required by browser voice worker for Sonic-3 TTS |
| `INTERLOCK_VOICE_TTS_VOICE_ID` | provider-specific voice ID, no default | required by browser voice worker; select a valid Cartesia voice externally |
| `INTERLOCK_VOICE_STT_MODEL` | model ID, default `nova-3` | optional browser voice worker override |
| `INTERLOCK_VOICE_STT_LANGUAGE` | Deepgram language, default `en-IN` | optional browser voice tuning; change for a different speaker locale |
| `INTERLOCK_VOICE_STT_KEYTERMS` | comma-separated terms; balanced 11/12 booking and correction phrases by default | optional Nova-3 keyterm bias for demo-critical vocabulary; does not bypass semantic validation |
| `INTERLOCK_VOICE_STT_ENDPOINTING_MS` | int `500`, 100..2000 | optional Deepgram silence window; longer than provider defaults so a short pause in “actually … book twelve” is less likely to split the utterance |
| `INTERLOCK_VOICE_STT_UTTERANCE_END_MS` | int `1000`, 1000..5000 | optional Deepgram utterance-end window; requires interim results and complements endpointing |
| `INTERLOCK_VOICE_FINAL_COALESCE_MS` | int `700`, 100..2000 | optional worker-side grace window that joins multiple Deepgram `is_final=true` segments from one VAD turn before sending one authoritative final transcript to the backend |
| `INTERLOCK_VOICE_TTS_MODEL` | model ID, default `sonic-3` | optional browser voice worker override |
| `VITE_INTERLOCK_API_URL` | browser-visible HTTP base ending `/api/v1`; default `/api/v1` | set to backend URL when running the Vite frontend separately |
| `OPENAI_API_KEY` | secret, no default | required by the official latency evaluator and GPT provider |
| `XAI_API_KEY` | secret, no default | required only for `grok` |
| `GOOGLE_API_KEY` | secret, no default | required only for Gemini providers |
| `ULTRAVOX_API_KEY` | secret, no default | required only for `ultravox` |
| `AZURE_OPENAI_API_KEY` | secret, no default | required only for `azure_openai` |
| `AZURE_OPENAI_ENDPOINT` | URL, no default | required only for `azure_openai` |
| `AZURE_OPENAI_DEPLOYMENT` | string, no default | required only for `azure_openai` |

For manual DEMO race testing, keep `INTERLOCK_TOOL_TIMEOUT_MS` comfortably above `INTERLOCK_FAKE_LATENCY_MS` (for example `15000` with a `10000` ms fake delay) so the delayed provider result is observed instead of being converted into a timeout. FDB-002 still requires Python 3.11 exactly; if the main test runner uses another supported Python version, set `FDB_V3_PYTHON` to an installed real Python 3.11 executable. The test harness preserves that explicit choice and falls back to the pytest interpreter only when no override is supplied. The `.env.example` contains only non-benchmark backend defaults. Benchmark credentials remain external and must never be committed. `scripts/reproduce_fdb_v3.sh` validates the variables above before launch and records non-secret configuration plus resolved dependency versions in `provenance.json`.

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
