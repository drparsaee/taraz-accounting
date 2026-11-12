"""DB1 source-backed read contracts: real SQLite remains the sole authority.

The adapter is deliberately read-only. This does not install PostgreSQL,
change accounting schema, introduce dual writes, or select a Cloud/Local
financial writer. Finance migration needs separate replay and lease tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from taraz_order_store import TarazOrderStore, _path_ok
from taraz_madar_order_sync import _source_digest


@dataclass(frozen=True)
class VersionedReference:
    source_system: str
    entity_type: str
    entity_id: str
    source_revision: int
    source_digest: str


class VersionedReadRepository(Protocol):
    def read_reference(self, entity_id: str) -> VersionedReference:
        """Read the actual source, refuse absent IDs, preserve exact revision."""


class TarazOrderReadRepository:
    """Adapter of the EXISTING TarazOrderStore, not a parallel source of data."""
    def __init__(self, company_directory):
        self.directory = Path(company_directory)
        _path_ok(self.directory)
        self.store = TarazOrderStore(self.directory)

    def read_reference(self, entity_id):
        record=self.store.get(entity_id)
        return VersionedReference(
            source_system='TARAZ',entity_type='order',
            entity_id=record['id'],source_revision=record['revision'],
            source_digest=_source_digest(record))

    def witness(self, entity_id):
        reference=self.read_reference(entity_id)
        return reference.source_revision,reference.source_digest


class RadarRepositoryNotAvailable:
    """Explicit boundary only; no invented RADAR data or API implementation."""
    def read_reference(self, entity_id):
        raise NotImplementedError('RADAR source and authenticated host not verified')
