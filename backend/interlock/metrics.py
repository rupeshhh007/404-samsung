"""Pure, sequence-pinned base metrics from canonical accepted facts.

Absence means unmeasured. In particular, the event model supplies neither a
BranchCache eligible-match denominator nor a baseline read latency, a scenario
outcome, an audible feedback clock, or an unambiguous interruption/resolution
pair. Those metrics are deliberately not inferred from adjacent events.
"""

from collections import Counter
from collections.abc import Iterable
import math

from interlock.domain.enums import CancellationPolicy, OperationState, RuntimeMode
from interlock.domain.models import EventEnvelope, MetricsSnapshot
from interlock.runtime.reducer import Reducer


def derive_metrics(
    session_id: str,
    events: Iterable[EventEnvelope],
    *,
    through_sequence: int | None = None,
) -> MetricsSnapshot:
    """Derive metrics from a complete, contiguous session prefix, without I/O.

    Re-reduction distinguishes accepted semantic failures from applied facts.
    Truncated retention is not a complete trace and fails explicitly instead
    of silently reporting undercounts. Logical times, never wall time, measure
    the canonical cancellation-request to named-safe-point interval.
    """
    trace = tuple(event.model_copy(deep=True) for event in events)
    if not session_id or any(event.session_id != session_id for event in trace):
        raise ValueError("metrics require one nonempty session identity")
    if tuple(event.sequence for event in trace) != tuple(range(1, len(trace) + 1)):
        raise ValueError("metrics require the complete ordered journal prefix")
    if through_sequence is None:
        through_sequence = trace[-1].sequence if trace else 0
    if type(through_sequence) is not int or through_sequence < 0:
        raise ValueError("through_sequence must be a non-negative integer")
    prefix = tuple(event for event in trace if event.sequence <= through_sequence)
    if tuple(event.sequence for event in prefix) != tuple(range(1, through_sequence + 1)):
        raise ValueError("metrics require the complete ordered journal prefix")
    counters: Counter[str] = Counter()
    requests: dict[str, int] = {}
    samples: list[int] = []
    terminal_cases: dict[str, str] = {}
    state = None
    for event in prefix:
        previous = state
        state, _ = Reducer.reduce(state, event, mode=RuntimeMode.REPLAY)
        if state is None or state.last_sequence != event.sequence:
            raise ValueError("trace cannot be reduced contiguously")
        counters["accepted_events"] += 1
        counters[f"events.{event.event_type}"] += 1
        if event.event_type == "ProtocolViolationObserved":
            counters["protocol_violations"] += 1
            counters[f"protocol_violations.{event.payload['code']}"] += 1
        if event.event_type == "SpeechActBlocked":
            # Do not put free-form block reasons into metric keys.
            sid = event.payload["speech_id"]
            if previous and previous.speech.get(sid) != state.speech.get(sid):
                counters["truthlock_blocks"] += 1
        if event.event_type == "WorldEffectObserved" and previous:
            effect_id = event.payload["effect"]["effect_id"]
            effect = state.effects.get(effect_id)
            if effect is not None and effect_id not in previous.effects:
                op = previous.operations.get(effect.operation_id)
                if effect.state == "COMMITTED" and op and op.state == OperationState.SUPERSEDED:
                    counters["late_effects_detected"] += 1
        if event.event_type == "CancellationRequested" and previous:
            op_id = event.payload["operation_id"]
            op = state.operations.get(op_id)
            if op and op != previous.operations.get(op_id) and op.cancellation_policy == CancellationPolicy.AT_SAFEPOINT:
                requests.setdefault(op_id, event.logical_time)
        if event.event_type == "SafePointReached":
            op_id = event.payload["operation_id"]
            requested = requests.pop(op_id, None)
            if requested is not None and event.payload["name"] == "BEFORE_PROVIDER_DISPATCH":
                delta = event.logical_time - requested
                if delta >= 0:
                    samples.append(delta)
        if previous:
            for case_id, case in state.divergences.items():
                state_val = case.state.value if hasattr(case.state, "value") else str(case.state)
                if state_val in ("RESOLVED", "ESCALATED") and case != previous.divergences.get(case_id):
                    terminal_cases[case_id] = state_val
    durations: dict[str, float] = {}
    gauges: dict[str, float] = {}
    if samples:
        ordered = sorted(samples)
        counters["safe_point_latency_samples"] = len(samples)
        for quantile in (50, 95):
            # Nearest-rank percentile, explicitly deterministic.
            durations[f"safe_point_latency_p{quantile}"] = float(
                ordered[math.ceil(len(ordered) * quantile / 100) - 1]
            )
    if terminal_cases:
        resolved = sum(value == "RESOLVED" for value in terminal_cases.values())
        counters["terminal_reconciliation_cases"] = len(terminal_cases)
        counters["resolved_reconciliation_cases"] = resolved
        gauges["reconciliation_success_rate"] = resolved / len(terminal_cases)
    return MetricsSnapshot(
        session_id=session_id,
        through_sequence=through_sequence,
        counters=dict(sorted(counters.items())),
        durations_ms=durations,
        gauges=gauges,
    )
