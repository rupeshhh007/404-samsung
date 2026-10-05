"""T-TOL-01/T-SEC-01: trusted descriptors default conservatively."""

import pytest

from interlock.domain.enums import ActionType, CancellationPolicy, EffectClassification
from interlock.execution.descriptors import ToolRegistry
from interlock.testing.fixtures import load_tool_manifests


def test_t_tol_01_all_canonical_manifests_register_and_detach():
    manifests = load_tool_manifests()
    registry = ToolRegistry()
    for manifest in manifests:
        descriptor = registry.register(manifest)
        assert registry.get(descriptor.tool_name) == descriptor
        assert registry.capability_hash(descriptor.tool_name).startswith("sha256:")
    assert len(manifests) == 6


def test_t_sec_01_missing_safety_declarations_fail_conservative():
    raw = load_tool_manifests()[0].copy()
    for field in ("effect_classification", "action_type", "cancellation_policy"):
        raw.pop(field)
    descriptor = ToolRegistry().register(raw)
    assert descriptor.effect_classification == EffectClassification.UNKNOWN
    assert descriptor.action_type == ActionType.IRREVERSIBLE
    assert descriptor.cancellation_policy == CancellationPolicy.NONCANCELLABLE


def test_t_sec_01_manifest_unknown_field_is_rejected():
    raw = load_tool_manifests()[0].copy()
    raw["authorization_override"] = True
    with pytest.raises(ValueError):
        ToolRegistry().register(raw)
