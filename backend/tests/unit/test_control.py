"""T-CTL-01, T-INV-I7-P, T-INV-I7-N: trustworthy control proposals."""

import asyncio

from interlock.config import Settings
from interlock.domain.enums import ControlKind
from interlock.intelligence.control import ControlInterpreter, InterpretationRequest


def _interpret(text: str, **updates):
    fields = dict(control_id="control", raw_evidence_id="evidence",
                  text=text, correlation_id="correlation",
                  active_intent_id="intent", context={"correction_field": "time"})
    fields.update(updates)
    return asyncio.run(ControlInterpreter(Settings(_env_file=None)).interpret(
        InterpretationRequest(**fields)))


def test_t_ctl_01_t_inv_i7_p_high_confidence_correction_proposes_delta():
    result = _interpret("Actually make it 12")
    assert result.control.kind == ControlKind.CORRECT
    assert result.control.confidence >= 0.85
    assert result.intent_delta.target_intent_id == "intent"
    assert result.intent_delta.set_fields == {"time": "12"}


def test_t_ctl_01_t_inv_i7_n_ambiguous_cancel_only_clarifies():
    result = _interpret("stop it")
    assert result.control.kind == ControlKind.CLARIFY
    assert result.intent_delta is None
    assert result.control.clarification
