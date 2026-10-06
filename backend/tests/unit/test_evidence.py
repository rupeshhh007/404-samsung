"""T-EVD-01, T-INV-I8-P, T-INV-I8-N: immutable evidence lineage."""

from datetime import datetime, timezone

import pytest

from interlock.domain.enums import EvidenceAuthority, EvidenceSource
from interlock.domain.models import EvidenceRecord
from interlock.truth.evidence import ConflictingEvidenceError, EvidenceStore


def _evidence(evidence_id: str, content_hash: str, **extra) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id, source=EvidenceSource.USER, kind="utterance",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        content_ref="input", content_hash=content_hash,
        authority=EvidenceAuthority.NON_AUTHORITATIVE, **extra,
    )


def test_t_evd_01_t_inv_i8_p_source_and_derived_coexist():
    store = EvidenceStore("s")
    source = _evidence("source", "hash-1")
    derived = _evidence("derived", "hash-2", derived_from=["source"])
    store.add(source)
    store.add(derived)
    assert store.count() == 2
    assert store.get_derived("source") == [derived]
    detached = store.get("source")
    detached.content_hash = "tampered"
    assert store.get("source") == source


def test_t_evd_01_t_inv_i8_n_conflict_cannot_replace_original():
    store = EvidenceStore("s")
    source = _evidence("source", "hash-1")
    store.add(source)
    assert store.add(source) == source
    with pytest.raises(ConflictingEvidenceError):
        store.add(_evidence("source", "hash-2"))
    assert store.get("source") == source
