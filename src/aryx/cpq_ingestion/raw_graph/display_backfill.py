"""Pure planner for scripts/backfill_cpq_display_names.py.

Workspaces confirmed through the raw-graph CPQ XML path before the
locale-wrapper fold (``value_wrapper.py``) have their display names stranded
in separate wrapper entities (``label`` / ``bm_name`` / ``name``) linked to the
owning entity by ``CONTAINS``. This computes, from rows already read out of
the DB, what the fold + display-field rules WOULD have produced at ingest:
the new attributes per changed entity and the wrapper entities that become
redundant. No I/O -- the script does the reading and writing.

Same rules as ingestion (one implementation, ``value_wrapper``):
- a tag is a wrapper tag only if every entity of it is value-only, has no
  children of its own, and at least one carries a locale key;
- the value lands on each parent under the wrapper's tag, accumulating;
- ``promote_display_fields`` then fills ``name`` / ``display_label``.

Unlike the raw graph, a resolved wrapper entity can be SHARED by many
parents (identical label text merges at resolve -- 1,635 ``label`` records
became 47 entities on workspace 1126), so values are pushed along every
CONTAINS edge, and a wrapper with no parent at all is left alone.

See docs/ingestion/CPQ_XML_DISPLAY_NAMES_PLAN_2026-10-05.md §4.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from aryx.cpq_ingestion.raw_graph.value_wrapper import (
    accumulate,
    has_locale_key,
    is_value_only,
    promote_display_fields,
    wrapper_value,
)


@dataclass
class BackfillPlan:
    """What the backfill would change for one workspace."""

    updates: dict[int, dict[str, Any]] = field(default_factory=dict)
    wrapper_entity_ids: list[int] = field(default_factory=list)
    wrapper_tags: list[str] = field(default_factory=list)


def _wrapper_tags(
    entities: dict[int, dict[str, Any]], tag_of: dict[int, str], has_children: set[int],
) -> set[str]:
    """Tags whose every entity is a childless, value-only locale wrapper."""
    ids_by_tag: dict[str, list[int]] = defaultdict(list)
    for eid, tag in tag_of.items():
        if eid in entities:
            ids_by_tag[tag].append(eid)
    return {
        tag for tag, ids in ids_by_tag.items()
        if all(is_value_only(entities[i]) and i not in has_children for i in ids)
        and any(has_locale_key(entities[i]) for i in ids)
    }


def plan_display_backfill(
    entities: dict[int, dict[str, Any]],
    tag_of: dict[int, str],
    contains: list[tuple[int, int]],
) -> BackfillPlan:
    """Plan the fold + display-field backfill for one workspace.

    entities: entity id -> attributes. tag_of: entity id -> raw XML tag
    (``aryx_landed_record.source_dataset`` of its members). contains:
    (parent id, child id) CONTAINS relationships. Inputs are not mutated.
    """
    has_children = {src for src, _tgt in contains}
    tags = _wrapper_tags(entities, tag_of, has_children)
    wrapper_ids = {eid for eid, tag in tag_of.items() if tag in tags and eid in entities}

    working: dict[int, dict[str, Any]] = {}
    folded_wrappers: set[int] = set()
    for parent, child in contains:
        if child not in wrapper_ids or parent in wrapper_ids or parent not in entities:
            continue
        props = working.setdefault(parent, copy.deepcopy(entities[parent]))
        accumulate(props, tag_of[child], wrapper_value(entities[child]))
        folded_wrappers.add(child)

    plan = BackfillPlan(wrapper_tags=sorted(tags))
    for eid, attrs in entities.items():
        if eid in wrapper_ids:
            continue
        props = working.get(eid) or copy.deepcopy(attrs)
        promote_display_fields(props)
        if props != attrs:
            plan.updates[eid] = props
    plan.wrapper_entity_ids = sorted(folded_wrappers)
    return plan


def types_fully_removed(ontology_type_of: dict[int, str], removed_ids: list[int]) -> list[str]:
    """Ontology types left with zero entities once ``removed_ids`` are deleted.

    Their ``aryx_ontology_type`` rows would otherwise linger as empty "ghost"
    types in the Ontology tab (same concern PR #435's backfill handles).
    """
    removed = set(removed_ids)
    if not removed:
        return []
    candidate_types = {ontology_type_of[i] for i in removed if i in ontology_type_of}
    surviving = {t for eid, t in ontology_type_of.items() if eid not in removed}
    return sorted(candidate_types - surviving)
