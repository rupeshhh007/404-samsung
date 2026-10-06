"""T-FDB-02: one-command official FDB-v3 orchestration contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from interlock.adapters.fdb_v3 import FdbLiveKitToolBridge, FdbScenarioAdapter


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "reproduce_fdb_v3.sh"


def _write(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _reproduction_python() -> str:
    """Prefer an explicitly configured Python 3.11 reproduction interpreter."""

    configured = os.environ.get("FDB_V3_PYTHON", "").strip()
    return configured or sys.executable


@pytest.fixture
def reproduction(tmp_path: Path) -> dict[str, object]:
    repository = tmp_path / "official-fdb"
    v3 = repository / "v3"
    data = tmp_path / "dataset"
    example = data / "example_01_0123456789abcdef01234567"
    artifacts = tmp_path / "artifacts"
    bin_dir = tmp_path / "bin"

    _write(v3 / "benchmark_data_v2.json", json.dumps({
        "benchmark_name": "stub FDB-v3",
        "scenarios": [{"id": "example_01"}],
    }))
    _write(v3 / "lk_agent_tool.py", "# official agent stub\n")
    _write(v3 / "mock_apis.py", "# official API stub\n")
    _write(example / "input.wav", "stub audio")
    _write(example / "metadata.json", json.dumps({"id": "example_01"}))
    _write(bin_dir / "ffmpeg", "#!/bin/sh\nexit 0\n", executable=True)
    agent = tmp_path / "agent.sh"
    _write(
        agent,
        "#!/bin/sh\ntrap 'exit 0' TERM INT\nwhile :; do sleep 1; done\n",
        executable=True,
    )

    inference = """\
import argparse, json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--provider', required=True)
p.add_argument('--root_dir', required=True)
p.add_argument('--force', action='store_true')
a = p.parse_args()
folders = sorted(path for path in Path(a.root_dir).iterdir() if path.is_dir())
target = folders[0] / f'result_{a.provider}.json'
target.write_text(json.dumps({
    'status': 'completed', 'example_id': 'example_01',
    'actual_tool_calls': [], 'transcript': 'stubbed orchestration output',
    'user_speech_end_rel': 1.0, 'audio_agent_speech_start': 2.0,
}), encoding='utf-8')
print('official inference stub completed')
"""
    _write(v3 / "run_tool_benchmark_all_released.py", inference)
    evaluator = """\
import argparse, json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--benchmark')
p.add_argument('--results-dir')
p.add_argument('--provider')
p.add_argument('--output', required=True)
p.add_argument('--use-llm', action='store_true')
a = p.parse_args()
Path(a.output).write_text(json.dumps({'source': 'official evaluator stub'}), encoding='utf-8')
"""
    for name in ("evaluate_tool_calls.py", "evaluate_pass_rate.py"):
        _write(v3 / name, evaluator)
    _write(v3 / "analyze_tool_latency.py", evaluator)

    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        [
            "git", "-C", str(repository), "-c", "user.name=FDB Test",
            "-c", "user.email=fdb@example.invalid", "commit", "-qm", "fixture",
        ],
        check=True,
    )
    commit = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "FDB_V3_REPO": str(repository),
        "FDB_V3_DATA_DIR": str(data),
        "FDB_V3_PROVIDER": "gpt_realtime",
        "FDB_V3_BENCHMARK_COMMIT": commit,
        "FDB_V3_PYTHON": _reproduction_python(),
        "FDB_V3_REQUIRED_MODULES": "",
        "FDB_V3_AGENT_COMMAND": str(agent),
        "FDB_V3_AGENT_STARTUP_SECONDS": "0.01",
        "FDB_V3_OUTPUT_DIR": str(artifacts),
        "FDB_V3_RUN_ID": "contract-test",
        "FDB_V3_SEED": "17",
        "LIVEKIT_URL": "wss://example.invalid",
        "LIVEKIT_API_KEY": "test-key",
        "LIVEKIT_API_SECRET": "test-secret",
        "OPENAI_API_KEY": "test-provider-key",
    }
    return {
        "env": env,
        "v3": v3,
        "data": data,
        "artifacts": artifacts,
    }


def _run(case: dict[str, object], **changes: str | None) -> subprocess.CompletedProcess[str]:
    env = dict(case["env"])
    for name, value in changes.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    command = [str(SCRIPT)]
    if os.name == "nt":
        bash = shutil.which("bash")
        if bash is None:
            pytest.fail("T-FDB-02 requires Git Bash on Windows to execute the shell contract")
        cygpath = Path(bash).with_name("cygpath.exe")
        if not cygpath.is_file():
            pytest.fail("T-FDB-02 requires Git Bash cygpath for Windows fixture paths")
        for name in (
            "FDB_V3_REPO", "FDB_V3_DATA_DIR", "FDB_V3_PYTHON",
            "FDB_V3_AGENT_COMMAND", "FDB_V3_OUTPUT_DIR",
        ):
            value = env.get(name)
            if value and Path(value).drive:
                env[name] = subprocess.check_output(
                    [str(cygpath), "-u", value], text=True,
                ).strip()
        command = [bash, "scripts/reproduce_fdb_v3.sh"]
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )


def test_reproduction_python_prefers_explicit_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = "/configured/python3.11"
    monkeypatch.setenv("FDB_V3_PYTHON", configured)
    assert _reproduction_python() == configured

    monkeypatch.setenv("FDB_V3_PYTHON", "")
    assert _reproduction_python() == sys.executable


def test_rejects_missing_prerequisite(reproduction: dict[str, object]) -> None:
    result = _run(reproduction, FDB_V3_PYTHON="/missing/python")
    assert result.returncode != 0
    assert "Python executable not found" in result.stderr


def test_rejects_missing_benchmark_dataset(reproduction: dict[str, object]) -> None:
    result = _run(reproduction, FDB_V3_DATA_DIR="/missing/fdb-data")
    assert result.returncode != 0
    assert "benchmark dataset directory not found" in result.stderr


def test_rejects_missing_livekit_configuration(reproduction: dict[str, object]) -> None:
    result = _run(reproduction, LIVEKIT_API_SECRET=None)
    assert result.returncode != 0
    assert "LIVEKIT_API_SECRET is missing" in result.stderr


def test_rejects_zero_example_success(reproduction: dict[str, object]) -> None:
    _write(
        Path(reproduction["v3"]) / "run_tool_benchmark_all_released.py",
        "print('success without results')\n",
    )
    result = _run(reproduction)
    assert result.returncode != 0
    assert "produced zero result files" in result.stderr


def test_propagates_official_evaluator_failure(reproduction: dict[str, object]) -> None:
    _write(
        Path(reproduction["v3"]) / "evaluate_tool_calls.py",
        "raise SystemExit(7)\n",
    )
    result = _run(reproduction)
    assert result.returncode == 7
    assert not (Path(reproduction["artifacts"]) / "provenance.json").exists()


def test_records_provenance_without_fabricated_scores(
    reproduction: dict[str, object],
) -> None:
    result = _run(reproduction)
    assert result.returncode == 0, result.stdout + result.stderr
    artifacts = Path(reproduction["artifacts"])
    provenance = json.loads((artifacts / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["benchmark"]["name"] == "Full-Duplex-Bench v3"
    assert provenance["configuration"]["provider"] == "gpt_realtime"
    assert provenance["configuration"]["seed"] == "17"
    assert provenance["examples"] == {"attempted": 1, "completed": 1}
    assert provenance["benchmark"]["commit"] == reproduction["env"][
        "FDB_V3_BENCHMARK_COMMIT"
    ]
    assert "score" not in json.dumps(provenance).lower()
    for name in (
        "tool_evaluation.json", "pass_rate.json", "latency.json",
        "logs/agent.log", "logs/inference.log",
    ):
        assert (artifacts / name).is_file()
    assert list((artifacts / "raw_results").rglob("result_gpt_realtime.json"))


def test_livekit_model_tool_surface_routes_through_interlock(
    tmp_path: Path,
) -> None:
    """A LiveKit-selected raw tool call crosses the real INTERLOCK tool path."""

    async def case() -> None:
        observed: list[tuple[str, dict[str, object]]] = []

        def execute(name: str, arguments: dict[str, object]) -> dict[str, object]:
            observed.append((name, dict(arguments)))
            return {"available": True, "destination": arguments["destination"]}

        declarations = [
            {
                "type": "function",
                "function": {
                    "name": "search_flights",
                    "description": "Search available flights.",
                    "parameters": {
                        "type": "object",
                        "properties": {"destination": {"type": "string"}},
                        "required": ["destination"],
                    },
                },
                "read_only": True,
            }
        ]
        adapter = FdbScenarioAdapter(
            "fdb-livekit-contract", tools=declarations, tool_executor=execute
        )
        await adapter.start()
        telemetry = tmp_path / "agent_tool_calls.log"
        bridge = FdbLiveKitToolBridge(
            adapter,
            declarations,
            room_name="official-room",
            telemetry_path=telemetry,
        )
        tool = bridge.livekit_tools()[0]
        result = json.loads(await tool._func({"destination": "LHR"}))

        assert result == {"available": True, "destination": "LHR"}
        assert len(observed) == 1
        assert observed[0][0] == "search_flights"
        assert observed[0][1]["destination"] == "LHR"
        assert str(observed[0][1]["idempotency_key"]).startswith("sha256:")
        terminal = [
            event
            for event in adapter.application.events("fdb-livekit-contract")
            if event.event_type == "ToolResultObserved"
        ]
        assert len(terminal) == 1
        recorded = json.loads(telemetry.read_text(encoding="utf-8"))
        assert recorded["room"] == "official-room"
        assert recorded["call"]["function"] == "search_flights"
        assert recorded["call"]["args"] == {"destination": "LHR"}
        await adapter.close()

    import asyncio

    asyncio.run(case())
