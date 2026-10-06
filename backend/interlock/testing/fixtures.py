"""Strict, deterministic loaders for the local appointment demo fixtures."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from interlock.execution.descriptors import ToolRegistry


ProviderOutcome = Literal["ACKNOWLEDGED", "SUCCEEDED", "FAILED", "UNKNOWN"]
_TOOLS = frozenset({
    "device.lookup_error", "service.find_centers", "appointment.availability",
    "appointment.book", "appointment.get", "appointment.cancel",
})
_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


class _FixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FakeCenter(_FixtureModel):
    center_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    timezone: str = Field(min_length=1)


class FakeDiagnostic(_FixtureModel):
    device_id: str = Field(min_length=1)
    error_code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    center_ids: tuple[str, ...]


class FakeBooking(_FixtureModel):
    booking_id: str = Field(min_length=1)
    center_id: str = Field(min_length=1)
    requested_slot: str = Field(min_length=1)
    confirmed_slot: str = Field(min_length=1)
    cancelled_at: str | None = None

    @field_validator("requested_slot", "confirmed_slot", "cancelled_at")
    @classmethod
    def _valid_time(cls, value: str | None) -> str | None:
        if value is not None:
            _parse_rfc3339(value)
        return value


class FakeProviderFixture(_FixtureModel):
    """Complete immutable seed for one isolated fake-provider instance."""

    schema_version: Literal[1]
    fixture_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    centers: tuple[FakeCenter, ...]
    diagnostics: tuple[FakeDiagnostic, ...]
    availability: dict[str, tuple[str, ...]]
    booking_identities: dict[str, dict[str, str]]
    initial_bookings: tuple[FakeBooking, ...]
    cancelled_at: str = Field(min_length=1)
    default_outcomes: dict[str, tuple[ProviderOutcome, ...]]

    @model_validator(mode="after")
    def _validate_semantics(self) -> "FakeProviderFixture":
        if "SIMULATED" not in self.label.upper():
            raise ValueError("fixture label must explicitly identify simulated data")
        center_ids = [center.center_id for center in self.centers]
        if not center_ids or len(center_ids) != len(set(center_ids)):
            raise ValueError("centers must have unique identities")
        if frozenset(self.availability) != frozenset(center_ids):
            raise ValueError("availability must cover exactly the declared centers")
        if frozenset(self.booking_identities) != frozenset(center_ids):
            raise ValueError("booking identities must cover exactly the declared centers")
        diagnostic_keys = [(item.device_id, item.error_code) for item in self.diagnostics]
        if not diagnostic_keys or len(diagnostic_keys) != len(set(diagnostic_keys)):
            raise ValueError("diagnostic identities must be unique and nonempty")
        for item in self.diagnostics:
            if len(item.center_ids) != len(set(item.center_ids)) or any(
                center_id not in center_ids for center_id in item.center_ids
            ):
                raise ValueError("diagnostic center references must be unique and known")
        booking_ids: list[str] = []
        for center_id, slots in self.availability.items():
            if len(slots) != len(set(slots)):
                raise ValueError("availability slots must be unique")
            for slot in slots:
                _parse_rfc3339(slot)
            identities = self.booking_identities[center_id]
            if frozenset(identities) != frozenset(slots):
                raise ValueError("booking identities must cover exactly the available slots")
            if any(not isinstance(identity, str) or not identity for identity in identities.values()):
                raise ValueError("booking identities must be nonempty text")
            booking_ids.extend(identities.values())
        initial_booking_ids = [booking.booking_id for booking in self.initial_bookings]
        if len(initial_booking_ids) != len(set(initial_booking_ids)):
            raise ValueError("initial booking identities must be unique")
        if len(booking_ids) != len(set(booking_ids)):
            raise ValueError("planned booking identities must be unique")
        if set(booking_ids).intersection(initial_booking_ids):
            raise ValueError("planned and initial booking identities must be distinct")
        if any(booking.center_id not in center_ids for booking in self.initial_bookings):
            raise ValueError("initial booking references an unknown center")
        _parse_rfc3339(self.cancelled_at)
        if frozenset(self.default_outcomes) != _TOOLS:
            raise ValueError("default outcomes must cover exactly the six supported tools")
        if any(not outcomes for outcomes in self.default_outcomes.values()):
            raise ValueError("each tool requires at least one deterministic outcome")
        if any(
            "ACKNOWLEDGED" in outcomes and tool != "appointment.book"
            for tool, outcomes in self.default_outcomes.items()
        ):
            raise ValueError("only appointment.book supports acknowledgement")
        return self


def load_demo_fixture(path: Path | None = None) -> FakeProviderFixture:
    """Load and strictly validate a detached fake-provider seed."""

    raw = _load_json(path or (_FIXTURE_ROOT / "demo.json"))
    # JSON arrays are the wire representation of immutable tuple fields.  The
    # model still forbids extras and validates every scalar/semantic constraint.
    return FakeProviderFixture.model_validate(raw).model_copy(deep=True)


def load_tool_manifests(path: Path | None = None) -> tuple[dict[str, Any], ...]:
    """Load manifests and validate them through the canonical registry boundary."""

    raw = _load_json(path or (_FIXTURE_ROOT / "manifests.json"))
    if not isinstance(raw, dict) or frozenset(raw) != {"schema_version", "manifests"}:
        raise ValueError("manifest fixture must contain only schema_version and manifests")
    if raw["schema_version"] != 1 or type(raw["schema_version"]) is not int:
        raise ValueError("manifest fixture schema_version must equal 1")
    manifests = raw["manifests"]
    if not isinstance(manifests, list) or not manifests:
        raise ValueError("manifest fixture must contain a nonempty manifest list")
    if any(not isinstance(manifest, dict) for manifest in manifests):
        raise ValueError("each manifest must be an object")
    registry = ToolRegistry()
    for manifest in manifests:
        registry.register(manifest)
    names = [manifest.get("tool_name") for manifest in manifests]
    if frozenset(names) != _TOOLS or len(names) != len(set(names)):
        raise ValueError("manifest fixture must define each appointment tool exactly once")
    return tuple(deepcopy(manifest) for manifest in manifests)


def register_tool_manifests(registry: ToolRegistry, path: Path | None = None) -> None:
    """Register the canonical fake manifests in dependency-safe file order."""

    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    for manifest in load_tool_manifests(path):
        registry.register(manifest)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("fixture is unavailable or invalid JSON") from exc


def _parse_rfc3339(value: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("fixture time must be nonempty RFC3339 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("fixture time must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError("fixture time must include an offset")
    return parsed


__all__ = [
    "FakeBooking",
    "FakeCenter",
    "FakeDiagnostic",
    "FakeProviderFixture",
    "ProviderOutcome",
    "load_demo_fixture",
    "load_tool_manifests",
    "register_tool_manifests",
]
