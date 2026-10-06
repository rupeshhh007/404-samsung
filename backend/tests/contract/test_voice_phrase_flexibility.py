"""Voice demo phrase flexibility and STT tuning regressions."""

from __future__ import annotations

import pytest

from interlock.adapters.livekit_agent import _browser_stt_options
from interlock.domain.enums import ControlKind
from interlock.main import _demo_spoken_alias
from interlock.providers.fallback import DeterministicFallbackProvider, FallbackContext


@pytest.mark.parametrize(
    ("spoken", "semantic"),
    [
        ("Book twelve please.", "book 12"),
        ("Please book me for twelve.", "book 12"),
        ("Can you schedule it for 12?", "book 12"),
        ("I'd like twelve.", "book 12"),
        ("Can we do twelve?", "book 12"),
        ("Twelve please.", "book 12"),
        ("Book an appointment for noon.", "book 12"),
        ("Give me midday please.", "book 12"),
        ("Mid day please.", "book 12"),
        ("Book eleven in the morning.", "book 11"),
        ("Book twelve in the afternoon.", "book 12"),
        ("Book 12 p m.", "book 12"),
        ("Let's do twelve.", "book 12"),
        ("Go with 12.", "book 12"),
        ("At twelve please.", "book 12"),
        ("Actually book twelve.", "make it 12"),
        ("Actually, book 12 please.", "make it 12"),
        ("Actually make it twelve.", "make it 12"),
        ("Actually, twelve.", "make it 12"),
        ("No, twelve.", "make it 12"),
        ("Sorry, twelve.", "make it 12"),
        ("I meant twelve.", "make it 12"),
        ("Make that twelve.", "make it 12"),
        ("Change the booking to twelve.", "make it 12"),
        ("Change from eleven to twelve.", "make it 12"),
        ("Could you move it to 12:00 please?", "make it 12"),
        ("Move the appointment from eleven to twelve.", "make it 12"),
        ("Switch it to noon.", "make it 12"),
        ("Reschedule for twelve.", "make it 12"),
        ("Twelve instead.", "make it 12"),
        ("Can we do twelve instead?", "make it 12"),
        ("Wait, make it twelve.", "make it 12"),
        ("Set it to twelve.", "make it 12"),
        ("Use 12 instead.", "make it 12"),
        ("Go with noon instead.", "make it 12"),
        ("Put it at 12:00.", "make it 12"),
    ],
)
def test_demo_spoken_alias_accepts_common_stt_variants(
    spoken: str,
    semantic: str,
) -> None:
    assert _demo_spoken_alias(spoken) == semantic


@pytest.mark.parametrize(
    "spoken",
    [
        "Don't book twelve.",
        "Do not book 12.",
        "Actually do not make it twelve.",
    ],
)
def test_demo_spoken_alias_never_turns_negation_into_positive_write(spoken: str) -> None:
    assert _demo_spoken_alias(spoken) not in {"book 12", "make it 12"}


@pytest.mark.parametrize(
    "spoken",
    [
        "Book 12:30.",
        "Book eleven thirty.",
        "Book half past eleven.",
        "Book quarter to twelve.",
        "Book sometime before twelve.",
        "Book after eleven.",
        "Book around twelve.",
        "Maybe book twelve.",
        "Book by twelve.",
        "Book from eleven to twelve.",
    ],
)
def test_demo_spoken_alias_rejects_inexact_or_unsupported_time_requests(spoken: str) -> None:
    assert _demo_spoken_alias(spoken) == "please clarify"


@pytest.mark.parametrize(
    "spoken",
    [
        "Eleven or twelve.",
        "Book eleven or twelve.",
        "Maybe eleven, maybe twelve.",
    ],
)
def test_demo_spoken_alias_keeps_ambiguous_multi_slot_input_unresolved(spoken: str) -> None:
    assert _demo_spoken_alias(spoken) == "please clarify"


def test_fallback_correction_accepts_spoken_number_word() -> None:
    provider = DeterministicFallbackProvider()
    slot = "2030-01-15T12:00:00+05:30"
    result = provider.interpret(
        "actually book twelve",
        FallbackContext(
            active_intent_id="intent-1",
            candidate_target_ids=("intent-1",),
            correction_field="requested_slot",
            value_aliases={"twelve": slot, "12": slot},
        ),
    )

    assert result.kind == ControlKind.CORRECT
    assert result.intent_delta is not None
    assert result.intent_delta.target_intent_id == "intent-1"
    assert result.intent_delta.set_fields == {"requested_slot": slot}


def test_fallback_missing_correction_value_requests_slot_specific_clarification() -> None:
    provider = DeterministicFallbackProvider()
    result = provider.interpret(
        "actually change it",
        FallbackContext(
            active_intent_id="intent-1",
            candidate_target_ids=("intent-1",),
            correction_field="requested_slot",
            value_aliases={"eleven": "11", "twelve": "12"},
        ),
    )

    assert result.kind == ControlKind.CLARIFY
    assert result.intent_delta is None
    assert result.clarification == "Which booking time do you want: eleven or twelve?"


def test_browser_stt_defaults_are_tuned_for_demo_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERLOCK_VOICE_STT_LANGUAGE", raising=False)
    monkeypatch.delenv("INTERLOCK_VOICE_STT_KEYTERMS", raising=False)
    monkeypatch.delenv("INTERLOCK_VOICE_STT_ENDPOINTING_MS", raising=False)
    monkeypatch.delenv("INTERLOCK_VOICE_STT_UTTERANCE_END_MS", raising=False)

    options = _browser_stt_options()

    assert options["language"] == "en-IN"
    assert {"book", "appointment", "eleven", "twelve", "actually"}.issubset(
        set(options["keyterm"])
    )
    assert options["endpointing_ms"] == 500
    assert options["utterance_end_ms"] == 1000
    assert options["interim_results"] is True
    assert options["punctuate"] is True
    assert options["smart_format"] is True
    assert options["numerals"] is True
    assert options["filler_words"] is False


def test_browser_stt_tuning_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERLOCK_VOICE_STT_LANGUAGE", "en-US")
    monkeypatch.setenv(
        "INTERLOCK_VOICE_STT_KEYTERMS",
        "eleven,twelve,service center",
    )

    monkeypatch.setenv("INTERLOCK_VOICE_STT_ENDPOINTING_MS", "650")
    monkeypatch.setenv("INTERLOCK_VOICE_STT_UTTERANCE_END_MS", "1400")

    assert _browser_stt_options() == {
        "language": "en-US",
        "keyterm": ["eleven", "twelve", "service center"],
        "interim_results": True,
        "punctuate": True,
        "smart_format": True,
        "numerals": True,
        "filler_words": False,
        "endpointing_ms": 650,
        "utterance_end_ms": 1400,
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("INTERLOCK_VOICE_STT_ENDPOINTING_MS", "50"),
        ("INTERLOCK_VOICE_STT_ENDPOINTING_MS", "2501"),
        ("INTERLOCK_VOICE_STT_UTTERANCE_END_MS", "500"),
        ("INTERLOCK_VOICE_STT_UTTERANCE_END_MS", "6000"),
    ],
)
def test_browser_stt_rejects_unsafe_timing_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        _browser_stt_options()
