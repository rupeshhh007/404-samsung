#!/usr/bin/env bash
set -euo pipefail

readonly EXPECTED_FDB_COMMIT="3e799c45a045256f47d5f1c9cda90157e2d2ec9e"
readonly EXPECTED_LIVEKIT_AGENTS_VERSION="1.8.4"
readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "FDB-002 ERROR: $*" >&2
  exit 1
}

require_value() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "required configuration $name is missing"
}

require_value FDB_V3_REPO
require_value FDB_V3_DATA_DIR
require_value FDB_V3_PROVIDER

case "$FDB_V3_PROVIDER" in
  gpt_realtime|azure_openai) PROVIDER_MODULE="livekit.plugins.openai" ;;
  grok) PROVIDER_MODULE="livekit.plugins.xai" ;;
  gemini2_5|gemini3_1) PROVIDER_MODULE="livekit.plugins.google" ;;
  ultravox) PROVIDER_MODULE="livekit.plugins.ultravox" ;;
  *) fail "unsupported FDB_V3_PROVIDER: $FDB_V3_PROVIDER" ;;
esac

PYTHON_BIN="${FDB_V3_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
[[ -x "$PYTHON_BIN" ]] || fail "Python executable not found: $PYTHON_BIN"
command -v git >/dev/null 2>&1 || fail "git is required"
command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg is required"

"$PYTHON_BIN" - <<'PY' || exit 1
import sys
if sys.version_info[:2] != (3, 11):
    raise SystemExit("FDB-002 ERROR: Python 3.11 is required")
PY

REQUIRED_MODULES="${FDB_V3_REQUIRED_MODULES-livekit.agents,$PROVIDER_MODULE,numpy,dotenv,nemo.collections.asr,pydub,openai}"
"$PYTHON_BIN" - "$REQUIRED_MODULES" "$EXPECTED_LIVEKIT_AGENTS_VERSION" <<'PY' || exit 1
import importlib.util
from importlib.metadata import PackageNotFoundError, version
import sys

modules = [item for item in sys.argv[1].split(",") if item]
missing = [name for name in modules if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("FDB-002 ERROR: missing Python modules: " + ", ".join(missing))
try:
    installed = version("livekit-agents")
except PackageNotFoundError as exc:
    raise SystemExit("FDB-002 ERROR: livekit-agents is not installed") from exc
if installed != sys.argv[2]:
    raise SystemExit(
        f"FDB-002 ERROR: livekit-agents {sys.argv[2]} is required; found {installed}"
    )
PY

FDB_REPO="$(cd "$FDB_V3_REPO" 2>/dev/null && pwd)" || fail "benchmark repository not found: $FDB_V3_REPO"
FDB_DIR="$FDB_REPO/v3"
[[ -d "$FDB_REPO/.git" ]] || fail "FDB_V3_REPO must be an official git checkout"
BENCHMARK_COMMIT="$(git -C "$FDB_REPO" rev-parse HEAD)" || fail "cannot resolve benchmark commit"
PINNED_COMMIT="${FDB_V3_BENCHMARK_COMMIT:-$EXPECTED_FDB_COMMIT}"
[[ "$BENCHMARK_COMMIT" == "$PINNED_COMMIT" ]] || fail \
  "benchmark commit mismatch: expected $PINNED_COMMIT, found $BENCHMARK_COMMIT"

for relative in \
  benchmark_data_v2.json \
  lk_agent_tool.py \
  mock_apis.py \
  run_tool_benchmark_all_released.py \
  evaluate_tool_calls.py \
  evaluate_pass_rate.py \
  analyze_tool_latency.py; do
  [[ -s "$FDB_DIR/$relative" ]] || fail "official benchmark file missing: v3/$relative"
done

DATA_DIR="$(cd "$FDB_V3_DATA_DIR" 2>/dev/null && pwd)" || fail \
  "benchmark dataset directory not found: $FDB_V3_DATA_DIR"
DATASET_EXAMPLES="$("$PYTHON_BIN" - "$DATA_DIR" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
pattern = re.compile(r"^.+_[0-9a-f]{24}$")
examples = sorted(path for path in root.iterdir() if path.is_dir() and pattern.match(path.name))
with_audio = [path for path in examples if (path / "input.wav").is_file()]
if not with_audio:
    raise SystemExit("FDB-002 ERROR: benchmark dataset contains zero official input.wav examples")
missing = [str(path) for path in with_audio if not (path / "metadata.json").is_file()]
if missing:
    raise SystemExit(
        "FDB-002 ERROR: benchmark example is missing metadata.json: " + ", ".join(missing)
    )
print(len(with_audio))
PY
)"

require_value LIVEKIT_URL
require_value LIVEKIT_API_KEY
require_value LIVEKIT_API_SECRET
require_value OPENAI_API_KEY
case "$FDB_V3_PROVIDER" in
  gpt_realtime) require_value OPENAI_API_KEY ;;
  grok) require_value XAI_API_KEY ;;
  gemini2_5|gemini3_1) require_value GOOGLE_API_KEY ;;
  ultravox) require_value ULTRAVOX_API_KEY ;;
  azure_openai)
    require_value AZURE_OPENAI_API_KEY
    require_value AZURE_OPENAI_ENDPOINT
    require_value AZURE_OPENAI_DEPLOYMENT
    ;;
esac

RUN_ID="${FDB_V3_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
ARTIFACT_DIR="${FDB_V3_OUTPUT_DIR:-$PROJECT_ROOT/artifacts/fdb-v3/$RUN_ID}"
mkdir -p "$ARTIFACT_DIR/logs" "$ARTIFACT_DIR/raw_results"
ARTIFACT_DIR="$(cd "$ARTIFACT_DIR" && pwd)"
SEED="${FDB_V3_SEED:-0}"
export PYTHONHASHSEED="$SEED"
export LK_PROVIDER="$FDB_V3_PROVIDER"
export FDB_V3_LATENCY_PROFILE="${FDB_V3_LATENCY_PROFILE:-instant}"

AGENT_PID=""
cleanup() {
  if [[ -n "$AGENT_PID" ]] && kill -0 "$AGENT_PID" 2>/dev/null; then
    kill "$AGENT_PID" 2>/dev/null || true
    wait "$AGENT_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ -n "${FDB_V3_AGENT_COMMAND:-}" ]]; then
  [[ -x "$FDB_V3_AGENT_COMMAND" ]] || fail "FDB_V3_AGENT_COMMAND is not executable"
  "$FDB_V3_AGENT_COMMAND" >"$ARTIFACT_DIR/logs/agent.log" 2>&1 &
else
  PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON_BIN" -m interlock.adapters.fdb_v3 \
    benchmark-agent --fdb-v3-dir "$FDB_DIR" start \
    >"$ARTIFACT_DIR/logs/agent.log" 2>&1 &
fi
AGENT_PID="$!"
sleep "${FDB_V3_AGENT_STARTUP_SECONDS:-8}"
kill -0 "$AGENT_PID" 2>/dev/null || {
  wait "$AGENT_PID" || true
  fail "INTERLOCK LiveKit/FDB agent exited during startup; see logs/agent.log"
}

(
  cd "$FDB_DIR"
  "$PYTHON_BIN" run_tool_benchmark_all_released.py \
    --provider "$FDB_V3_PROVIDER" \
    --root_dir "$DATA_DIR" \
    --force
) 2>&1 | tee "$ARTIFACT_DIR/logs/inference.log"

read -r RESULT_FILES COMPLETED < <(
  "$PYTHON_BIN" - "$DATA_DIR" "$FDB_V3_PROVIDER" "$ARTIFACT_DIR/raw_results" <<'PY'
import json
from pathlib import Path
import shutil
import sys

data_dir = Path(sys.argv[1])
provider = sys.argv[2]
destination = Path(sys.argv[3])
files = sorted(data_dir.rglob(f"result_{provider}.json"))
completed = 0
for source in files:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FDB-002 ERROR: invalid evaluator result {source}: {exc}") from exc
    if payload.get("status") == "completed":
        completed += 1
    target_dir = destination / source.parent.name
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target_dir / source.name)
print(len(files), completed)
PY
)
ATTEMPTED="$DATASET_EXAMPLES"
[[ "$RESULT_FILES" -gt 0 ]] || fail "inference reported success but produced zero result files"
[[ "$COMPLETED" -gt 0 ]] || fail "inference completed zero benchmark examples"

USE_LLM_JUDGE="${FDB_V3_USE_LLM_JUDGE:-0}"
if [[ "$USE_LLM_JUDGE" != "0" && "$USE_LLM_JUDGE" != "1" ]]; then
  fail "FDB_V3_USE_LLM_JUDGE must be 0 or 1"
fi

run_evaluator() {
  local script="$1"
  local output="$2"
  local log="$3"
  local -a command=(
    "$PYTHON_BIN" "$FDB_DIR/$script"
    --benchmark "$FDB_DIR/benchmark_data_v2.json"
    --results-dir "$DATA_DIR"
    --provider "$FDB_V3_PROVIDER"
    --output "$ARTIFACT_DIR/$output"
  )
  if [[ "$USE_LLM_JUDGE" == "1" ]]; then
    command+=(--use-llm)
  fi
  "${command[@]}" 2>&1 | tee "$ARTIFACT_DIR/logs/$log"
}

run_evaluator evaluate_tool_calls.py tool_evaluation.json tool_evaluation.log
run_evaluator evaluate_pass_rate.py pass_rate.json pass_rate.log

"$PYTHON_BIN" "$FDB_DIR/analyze_tool_latency.py" \
  --results-dir "$DATA_DIR" \
  --provider "$FDB_V3_PROVIDER" \
  --output "$ARTIFACT_DIR/latency.json" \
  2>&1 | tee "$ARTIFACT_DIR/logs/latency.log"

for artifact in tool_evaluation.json pass_rate.json latency.json; do
  [[ -s "$ARTIFACT_DIR/$artifact" ]] || fail "expected evaluator artifact is absent: $artifact"
done

INTERLOCK_COMMIT="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"
LIVEKIT_VERSION="$($PYTHON_BIN -c 'from importlib.metadata import version; print(version("livekit-agents"))')"
"$PYTHON_BIN" - \
  "$ARTIFACT_DIR/provenance.json" "$BENCHMARK_COMMIT" "$INTERLOCK_COMMIT" \
  "$FDB_V3_PROVIDER" "$SEED" "$ATTEMPTED" "$COMPLETED" "$ARTIFACT_DIR" \
  "$DATA_DIR" "$LIVEKIT_VERSION" "$USE_LLM_JUDGE" \
  "$FDB_V3_LATENCY_PROFILE" <<'PY'
import datetime
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import sys

(
    output, benchmark_commit, interlock_commit, provider, seed,
    attempted, completed, artifacts, data_dir, livekit_version, use_llm,
    latency_profile,
) = sys.argv[1:]
root = Path(artifacts)
dependencies = {}
for package in (
    "livekit-agents", "numpy", "python-dotenv", "pydub", "openai",
    "nemo-toolkit", "ffmpeg-python",
):
    try:
        dependencies[package] = version(package)
    except PackageNotFoundError:
        dependencies[package] = None
provenance = {
    "schema_version": 1,
    "benchmark": {
        "name": "Full-Duplex-Bench v3",
        "repository": "https://github.com/DanielLin94144/Full-Duplex-Bench",
        "commit": benchmark_commit,
    },
    "interlock_commit": interlock_commit,
    "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "python_version": platform.python_version(),
    "livekit_agents_version": livekit_version,
    "dependency_versions": dependencies,
    "configuration": {
        "provider": provider,
        "seed": seed,
        "latency_profile": latency_profile,
        "llm_judge_enabled": use_llm == "1",
        "dataset_path": data_dir,
    },
    "examples": {"attempted": int(attempted), "completed": int(completed)},
    "artifacts": {
        "root": str(root),
        "agent_log": str(root / "logs" / "agent.log"),
        "inference_log": str(root / "logs" / "inference.log"),
        "tool_evaluation": str(root / "tool_evaluation.json"),
        "pass_rate": str(root / "pass_rate.json"),
        "latency": str(root / "latency.json"),
        "raw_results": str(root / "raw_results"),
    },
}
Path(output).write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "FDB-v3 reproduction completed: $COMPLETED/$ATTEMPTED examples"
echo "Artifacts: $ARTIFACT_DIR"
