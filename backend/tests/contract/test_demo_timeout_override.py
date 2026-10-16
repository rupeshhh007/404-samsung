"""Regression coverage for configurable DEMO tool timeouts."""

from __future__ import annotations

from interlock.config import Settings
from interlock.main import create_demo_session_dependencies


class _NullOutput:
    async def emit(
        self, *, session_id: str, speech_id: str, rendered_text: str
    ) -> None:
        del session_id, speech_id, rendered_text

    async def cancel(self, *, session_id: str, speech_id: str) -> None:
        del session_id, speech_id


def test_demo_tool_timeout_setting_overrides_fixture_manifests() -> None:
    settings = Settings(
        _env_file=None,
        INTERLOCK_MODE="DEMO",
        INTERLOCK_TOOL_TIMEOUT_MS=15_000,
    )

    registry, _, _ = create_demo_session_dependencies(
        settings,
        output=_NullOutput(),
    )

    for tool_name in (
        "device.lookup_error",
        "service.find_centers",
        "appointment.availability",
        "appointment.book",
        "appointment.get",
        "appointment.cancel",
    ):
        assert registry.get(tool_name).timeout_ms == 15_000
