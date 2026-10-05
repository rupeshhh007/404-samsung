"""T-RED-01, T-RPL-01, T-INV-I11-P, T-INV-I11-N,
T-INV-I12-P, T-INV-I12-N: pure reducer and replay.
"""

from datetime import datetime, timezone

from interlock.domain.enums import EventSource, RuntimeMode
from interlock.domain.models import EventEnvelope
from interlock.runtime.reducer import Reducer


def _event(sequence: int, kind: str, payload: dict) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"event-{sequence}", session_id="s", sequence=sequence,
        event_type=kind, source=EventSource.SYSTEM,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        logical_time=sequence, payload=payload,
    )


def test_t_red_01_t_inv_i11_p_next_event_advances_only_via_reducer():
    started = _event(1, "SessionStarted", {"mode": "TEST"})
    state, commands = Reducer.reduce(None, started)
    assert state.last_sequence == 1
    assert [command.command_type for command in commands] == ["PublishProjection"]
    input_event = _event(2, "UserInputObserved", {
        "evidence_id": "e", "modality": "TEXT", "content_ref": "hello",
    })
    state, commands = Reducer.reduce(state, input_event)
    assert state.last_sequence == 2
    assert any(command.command_type == "InterpretInput" for command in commands)


def test_t_red_01_t_inv_i11_n_sequence_gap_and_detached_worker_copy():
    state, _ = Reducer.reduce(None, _event(1, "SessionStarted", {"mode": "TEST"}))
    worker_copy = state.model_copy(deep=True)
    worker_copy.paused = True
    assert state.paused is False
    result, commands = Reducer.reduce(state, _event(3, "UserInputObserved", {
        "evidence_id": "e", "modality": "TEXT", "content_ref": "hello",
    }))
    assert result == state
    assert any(command.command_type == "RecordProtocolViolation" for command in commands)


def test_t_rpl_01_t_inv_i12_p_t_inv_i12_n_same_state_zero_replay_commands():
    events = [
        _event(1, "SessionStarted", {"mode": "TEST"}),
        _event(2, "UserInputObserved", {
            "evidence_id": "e", "modality": "TEXT", "content_ref": "hello",
        }),
    ]
    live = replay = None
    live_commands = []
    replay_commands = []
    for event in events:
        live, commands = Reducer.reduce(live, event)
        live_commands.extend(commands)
        replay, commands = Reducer.reduce(replay, event, mode=RuntimeMode.REPLAY)
        replay_commands.extend(commands)
    assert live == replay
    assert any(command.command_type == "InterpretInput" for command in live_commands)
    assert replay_commands == []
