"""Result types and golden-record rebuild for the source-purge transaction.

Split out of `store/source_purge_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aryx.resolution.confidence import SINGLETON_CONFIDENCE
from aryx.resolution.golden import golden_record_with_policy
from aryx.resolution.survivorship import SurvivorshipPolicy


class SourcePurgeBusy(RuntimeError):
    """Raised when ingestion is active in the target workspace."""


@dataclass(frozen=True)
class CatalogUpdate:
    """Datasource catalog mutation committed with the source purge."""

    datasource_id: int
    name: str
    kind: str
    config: dict[str, Any]


@dataclass(frozen=True)
class SurvivorState:
    """Rebuilt golden-record state for one impacted surviving entity."""

    attributes: dict[str, Any]
    confidence: float
    conflicts: list[dict[str, Any]]


def _policy(raw: dict[str, Any] | None) -> SurvivorshipPolicy:
    if raw:
        return SurvivorshipPolicy.from_json(raw)
    return SurvivorshipPolicy(default_strategy="most_complete")


def rebuild_survivor_states(
    rows: list[tuple[int, int, dict[str, Any] | str, str | None, Any]],
    policy_data: dict[str, Any] | None,
) -> dict[int, SurvivorState]:
    """Rebuild impacted entities from their remaining landed records."""
    members_by_entity: dict[int, list[dict[str, Any]]] = {}
    for entity_id, record_id, payload, source_system, cleaned_at in rows:
        if isinstance(payload, str):
            payload = json.loads(payload)
        members_by_entity.setdefault(int(entity_id), []).append({
            "payload": payload or {},
            "record_id": int(record_id),
            "source_system": source_system,
            "cleaned_at": cleaned_at,
        })

    policy = _policy(policy_data)
    states: dict[int, SurvivorState] = {}
    for entity_id, members in members_by_entity.items():
        members.sort(key=lambda member: member["record_id"])
        attributes, _provenance, conflicts = golden_record_with_policy(
            members,
            policy,
        )
        states[entity_id] = SurvivorState(
            attributes=attributes,
            # Purge rebuilds the golden record from surviving members only. The
            # merge-edge evidence that produced the original score is run-scoped
            # and may be deleted by this same transaction, so rebuilt entities
            # get the same honest prior used for singleton/legacy clusters.
            confidence=SINGLETON_CONFIDENCE,
            conflicts=conflicts,
        )
    return states
