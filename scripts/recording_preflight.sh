#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${INTERLOCK_PREFLIGHT_PYTHON:-$ROOT/.venv/bin/python}"

fail() {
  printf '\n[recording-preflight] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -x "$PYTHON" ]] || fail "Python not found at $PYTHON. Set INTERLOCK_PREFLIGHT_PYTHON."
command -v node >/dev/null 2>&1 || fail "Node.js is required."
command -v npm >/dev/null 2>&1 || fail "npm is required."

printf '\n=== INTERLOCK recording preflight ===\n'
printf 'repo: %s\n' "$ROOT"
printf 'python: %s\n' "$("$PYTHON" --version 2>&1)"
printf 'node: %s\n' "$(node --version)"
printf 'npm: %s\n' "$(npm --version)"

printf '\n[1/7] Critical voice + race contracts\n'
PYTHONPATH=backend "$PYTHON" -m pytest -W error -q \
  backend/tests/contract/test_voice_phrase_flexibility.py \
  backend/tests/contract/test_demo_timeout_override.py \
  backend/tests/contract/test_demo_recording_hardening.py \
  backend/tests/contract/test_livekit.py

printf '\n[2/7] Full backend suite\n'
PYTHONPATH=backend "$PYTHON" -m pytest -W error -q

printf '\n[3/7] Python compile check\n'
"$PYTHON" -m compileall -q backend/interlock backend/tests

printf '\n[4/7] Frontend tests\n'
npm --prefix frontend test

printf '\n[5/7] Frontend typecheck\n'
npm --prefix frontend run typecheck

printf '\n[6/7] Frontend production build\n'
npm --prefix frontend run build

printf '\n[7/7] Repository diff hygiene\n'
git diff --check

cat <<'EOF'

=== AUTOMATED PREFLIGHT PASSED ===

Recommended recording configuration:

  export INTERLOCK_MODE=DEMO
  export INTERLOCK_TOOL_TIMEOUT_MS=15000
  export INTERLOCK_FAKE_LATENCY_MS=0

  export INTERLOCK_VOICE_STT_LANGUAGE='en-IN'
  export INTERLOCK_VOICE_STT_ENDPOINTING_MS=500
  export INTERLOCK_VOICE_STT_UTTERANCE_END_MS=1000
  export INTERLOCK_VOICE_FINAL_COALESCE_MS=700

For the intentional post-provider correction race only:

  export INTERLOCK_TOOL_TIMEOUT_MS=15000
  export INTERLOCK_FAKE_LATENCY_MS=10000

Do not use the 10-second fake delay for ordinary recording takes.
Run docs/demo/RECORDING_DAY.md before the final capture.
EOF
