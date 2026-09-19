"""Immutable Evidence Store and Provenance Tracking for INTERLOCK (TRU-001).

Implements the EvidenceStore contract defined in:
- docs/contracts/INTERFACES.md (EvidenceStore.add)
- docs/components/EVIDENCE_AND_PROVENANCE.md
- docs/architecture/INVARIANTS.md (Invariant I8)
- docs/architecture/DOMAIN_MODEL.md (EvidenceRecord)
- docs/delivery/TASK_BACKLOG.md (TRU-001)

Invariant I8:
EvidenceRecord content/provenance is immutable; corrections create new
records/edges. Duplicate insertions of identical records are idempotent;
conflicting insertions with the same evidence_id fail closed.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from interlock.domain.enums import EvidenceSource
from interlock.domain.models import EvidenceRecord


class EvidenceStoreError(Exception):
    """Base exception for all EvidenceStore errors."""


class ConflictingEvidenceError(EvidenceStoreError):
    """Raised when an insertion has an existing evidence_id with conflicting content or metadata.

    Enforces Invariant I8: EvidenceRecord is immutable.
    """

    def __init__(
        self,
        evidence_id: str,
        message: str,
        *,
        existing_record: Optional[EvidenceRecord] = None,
        conflicting_record: Optional[EvidenceRecord] = None,
    ) -> None:
        super().__init__(message)
        self.evidence_id = evidence_id
        self.existing_record = existing_record
        self.conflicting_record = conflicting_record


class EvidenceNotFoundError(EvidenceStoreError):
    """Raised when a required evidence_id is not found in the store."""

    def __init__(self, evidence_id: str, message: Optional[str] = None) -> None:
        msg = message or f"Evidence '{evidence_id}' not found in store"
        super().__init__(msg)
        self.evidence_id = evidence_id


class EvidenceStore:
    """Session-scoped, in-memory immutable Evidence Store.

    Responsibilities:
    1. Preserves source observations (FRAME, AUDIO, USER, TOOL, SYSTEM) and derived interpretations.
    2. Enforces Invariant I8: once recorded, an EvidenceRecord cannot be mutated or overwritten.
    3. Handles idempotent duplicates cleanly: inserting an identical record returns the existing record.
    4. Detects conflicts: inserting a record with an existing ID but different content/hash/provenance
       raises ConflictingEvidenceError without modifying the stored record.
    5. Maintains provenance and derivation DAG: derived evidence records point to parents via derived_from
       without mutating the parent.
    6. Preserves session retention (NFR-008, EVIDENCE_AND_PROVENANCE.md): records remain stored
       for the lifetime of the session until explicit session clear/reset. Stale/expired evidence
       is retained for historical provenance and trace auditing.
    7. Employs defensive deep copying on ingress and egress to preserve immutability in Python.
    """

    def __init__(self, session_id: str) -> None:
        if not session_id or not isinstance(session_id, str):
            raise ValueError("session_id must be a non-empty string")

        self._session_id = session_id
        self._records: Dict[str, EvidenceRecord] = {}
        self._source_index: Dict[EvidenceSource, List[str]] = {}
        self._derived_index: Dict[str, List[str]] = {}

    @property
    def session_id(self) -> str:
        """The session ID this store is scoped to."""
        return self._session_id

    def add(self, record: EvidenceRecord) -> EvidenceRecord:
        """Add an immutable EvidenceRecord to the store.

        Follows the EvidenceStore.add interface contract:
        - If the evidence_id already exists:
          - If the candidate record is identical in content and metadata, return a defensive copy
            of the existing record (idempotent duplicate).
          - If the candidate record differs in content_hash, content_ref, source, authority,
            provenance, or derivation lineage, raise ConflictingEvidenceError. The original
            record remains completely unchanged.
        - If the evidence_id does not exist:
          - Store a defensive copy of the record.
          - Index derivation lineage (derived_from) and source provenance.
          - Retain immutably under session retention.
          - Return a defensive copy of the stored record.
        """
        if not isinstance(record, EvidenceRecord):
            raise TypeError(f"Expected EvidenceRecord, got {type(record).__name__}")

        evidence_id = record.evidence_id

        if evidence_id in self._records:
            existing = self._records[evidence_id]
            if self._is_identical(existing, record):
                return existing.model_copy(deep=True)

            raise ConflictingEvidenceError(
                evidence_id,
                f"Evidence '{evidence_id}' already exists with conflicting content or metadata (Invariant I8)",
                existing_record=existing.model_copy(deep=True),
                conflicting_record=record.model_copy(deep=True),
            )

        # Defensive copy on ingress
        stored = record.model_copy(deep=True)
        self._records[evidence_id] = stored

        # Update secondary indexes
        self._source_index.setdefault(stored.source, []).append(evidence_id)
        if stored.derived_from:
            for parent_id in stored.derived_from:
                self._derived_index.setdefault(parent_id, []).append(evidence_id)

        return stored.model_copy(deep=True)

    def get(self, evidence_id: str) -> Optional[EvidenceRecord]:
        """Retrieve an EvidenceRecord by ID, returning a defensive copy, or None if not found."""
        record = self._records.get(evidence_id)
        if record is None:
            return None
        return record.model_copy(deep=True)

    def get_required(self, evidence_id: str) -> EvidenceRecord:
        """Retrieve an EvidenceRecord by ID, or raise EvidenceNotFoundError if absent."""
        record = self.get(evidence_id)
        if record is None:
            raise EvidenceNotFoundError(
                evidence_id,
                f"Evidence '{evidence_id}' not found in store for session '{self._session_id}'",
            )
        return record

    def has(self, evidence_id: str) -> bool:
        """Check if an evidence record exists in the store."""
        return evidence_id in self._records

    def get_derived(self, parent_evidence_id: str) -> List[EvidenceRecord]:
        """Retrieve all derived evidence records anchored to a parent evidence ID."""
        derived_ids = self._derived_index.get(parent_evidence_id, [])
        results: List[EvidenceRecord] = []
        for eid in derived_ids:
            rec = self._records.get(eid)
            if rec is not None:
                results.append(rec.model_copy(deep=True))
        return results

    def get_by_source(self, source: EvidenceSource) -> List[EvidenceRecord]:
        """Retrieve all evidence records originating from a specific EvidenceSource."""
        ids = self._source_index.get(source, [])
        results: List[EvidenceRecord] = []
        for eid in ids:
            rec = self._records.get(eid)
            if rec is not None:
                results.append(rec.model_copy(deep=True))
        return results

    def all(self) -> List[EvidenceRecord]:
        """Return all stored evidence records in insertion order as defensive copies."""
        return [rec.model_copy(deep=True) for rec in self._records.values()]

    def count(self) -> int:
        """Return the number of evidence records in the store."""
        return len(self._records)

    def clear(self) -> None:
        """Clear all stored evidence and indexes (e.g., on session reset)."""
        self._records.clear()
        self._source_index.clear()
        self._derived_index.clear()

    @staticmethod
    def _is_identical(a: EvidenceRecord, b: EvidenceRecord) -> bool:
        """Compare two EvidenceRecord instances for full canonical model equality."""
        return a.model_dump() == b.model_dump()
