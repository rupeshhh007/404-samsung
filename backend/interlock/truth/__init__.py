"""Truth and epistemic governance module for INTERLOCK.

Owns EvidenceStore (TRU-001), ClaimGraph (TRU-002), TRUTHLOCK (TRU-003),
and SpeechAct output lifecycle (TRU-004).
"""

from interlock.truth.evidence import (
    ConflictingEvidenceError,
    EvidenceNotFoundError,
    EvidenceStore,
    EvidenceStoreError,
)

__all__ = [
    "ConflictingEvidenceError",
    "EvidenceNotFoundError",
    "EvidenceStore",
    "EvidenceStoreError",
]
