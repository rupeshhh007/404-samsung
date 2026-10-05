"""T-MET-01: metrics derive only from complete accepted event prefixes."""

from datetime import datetime, timezone

import pytest

from interlock.domain.enums import EventSource
from interlock.domain.models import EventEnvelope
from interlock.metrics import derive_metrics


def _start(sequence: int = 1) -> EventEnvelope:
    return EventEnvelope(
        event_id="start", session_id="s", sequence=sequence,
        event_type="SessionStarted", source=EventSource.SYSTEM,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        logical_time=0, payload={"mode": "TEST"},
    )


def test_t_met_01_count_and_no_invented_denominators():
    result = derive_metrics("s", [_start()])
    assert result.through_sequence == 1
    assert result.counters["accepted_events"] == 1
    assert result.counters["events.SessionStarted"] == 1
    assert result.durations_ms == {}
    assert result.gauges == {}


def test_t_met_01_reject_truncated_or_gapped_trace():
    with pytest.raises(ValueError, match="complete ordered"):
        derive_metrics("s", [_start(sequence=2)])
