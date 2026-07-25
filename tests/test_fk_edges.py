"""link_by_attribute: exact-match FK linking, including survivorship-merge aliasing.

A merged entity keeps one winning value for a disputed attribute and records
the rest in aryx_attribute_conflict.losing_values. Anything that referenced
one of those losing values by exact match must still resolve to the entity
that absorbed it — conflict_aliases() is what makes that possible.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aryx.pipeline.fk_edges import link_by_attribute


def test_links_on_exact_current_value_match() -> None:
    """Baseline: source's FK value matches target's current attribute value."""
    estore = MagicMock()
    estore.list_entities.return_value = [
        (1, "Customer", {"id": "C1"}),
        (2, "Ticket", {"customer_id": "C1"}),
    ]
    estore.conflict_aliases.return_value = {}

    n = link_by_attribute(estore, "Ticket", "customer_id", "Customer", "id", "CUSTOMER_HAS_TICKET")

    assert n == 1
    saved = estore.save_relationships.call_args[0][0]
    assert saved[0].source_entity_id == 1
    assert saved[0].target_entity_id == 2


def test_links_via_conflict_alias_when_target_value_was_merged_away() -> None:
    """A merged entity's discarded ('losing') id must still resolve for FK linking."""
    estore = MagicMock()
    estore.list_entities.return_value = [
        (38854, "Assoc", {"id": "18722402376"}),  # merge winner
        (25249, "Prop", {"assoc_id": "18722402377"}),  # FK points at the loser
    ]
    estore.conflict_aliases.return_value = {"18722402377": 38854}

    n = link_by_attribute(estore, "Prop", "assoc_id", "Assoc", "id", "ASSOC_HAS_PROP")

    assert n == 1
    saved = estore.save_relationships.call_args[0][0]
    assert saved[0].source_entity_id == 38854
    assert saved[0].target_entity_id == 25249


def test_conflict_alias_ignored_when_entity_is_not_target_type() -> None:
    """An alias pointing at an entity of a *different* type must not be used —
    aryx_attribute_conflict has no type column, so this filter is load-bearing."""
    estore = MagicMock()
    estore.list_entities.return_value = [
        (1, "OtherType", {"id": "X"}),
        (2, "Prop", {"assoc_id": "X"}),
    ]
    # Alias points at entity 1, which is NOT an "Assoc" — must not link.
    estore.conflict_aliases.return_value = {"x": 1}

    n = link_by_attribute(estore, "Prop", "assoc_id", "Assoc", "id", "ASSOC_HAS_PROP")

    assert n == 0
    estore.save_relationships.assert_not_called()


def test_no_duplicate_when_alias_matches_an_existing_target() -> None:
    """If the current winning value AND an alias both map to the same entity,
    don't double-link the same target id under one key."""
    estore = MagicMock()
    estore.list_entities.return_value = [
        (1, "Assoc", {"id": "same-value"}),
        (2, "Prop", {"assoc_id": "same-value"}),
    ]
    estore.conflict_aliases.return_value = {"same-value": 1}

    n = link_by_attribute(estore, "Prop", "assoc_id", "Assoc", "id", "ASSOC_HAS_PROP")

    assert n == 1


def test_links_across_leading_zero_format_mismatch() -> None:
    """A numeric-looking code stored as '007' in one source and 7 (or '7') in
    another must still join — this is the exact format mismatch that used to
    silently produce zero edges (isolated nodes) with no error, since the
    prior exact-match-after-lower() join treated '007' and '7' as unrelated."""
    estore = MagicMock()
    estore.list_entities.return_value = [
        (1, "Material", {"code": "7"}),
        (2, "Transaction", {"material_code": "007"}),
    ]
    estore.conflict_aliases.return_value = {}

    n = link_by_attribute(estore, "Transaction", "material_code", "Material", "code", "MATERIAL_HAS_TRANSACTION")

    assert n == 1


def test_links_across_case_and_whitespace_mismatch() -> None:
    estore = MagicMock()
    estore.list_entities.return_value = [
        (1, "State", {"code": "AE"}),
        (2, "Record", {"state_code": "  ae  "}),
    ]
    estore.conflict_aliases.return_value = {}

    n = link_by_attribute(estore, "Record", "state_code", "State", "code", "STATE_HAS_RECORD")

    assert n == 1


# ── Defense-in-depth selectivity cap ─────────────────────────────────────────
# Regression coverage for a real incident: a shared low-cardinality category
# column ("Matl Group") produced 1,529,548 relationship rows from one FK
# spec and stalled ingestion for hours. dynamic_fk's Stage 1 fanout guard is
# meant to catch this before a spec ever reaches here, but link_by_attribute
# must never trust that upstream guard alone — ANY spec (column-name- or
# dynamic-detected) that turns out non-selective must abort loudly rather
# than silently writing an unbounded number of rows.

def _many_to_many_estore(group_count: int, rows_per_group: int) -> MagicMock:
    """Build an estore where `group_count` shared category values each have
    `rows_per_group` entities on BOTH the source and target side — a
    classic non-selective join key."""
    entities = []
    tid = 0
    for g in range(group_count):
        for _ in range(rows_per_group):
            entities.append((tid, "Target", {"code": f"G{g}"}))
            tid += 1
    for g in range(group_count):
        for _ in range(rows_per_group):
            entities.append((tid, "Source", {"ref": f"G{g}"}))
            tid += 1
    estore = MagicMock()
    estore.list_entities.return_value = entities
    estore.conflict_aliases.return_value = {}
    return estore


def test_aborts_and_saves_nothing_when_relationship_count_exceeds_cap() -> None:
    # 5 groups x 20 rows each side -> 20*20*5 = 2000 potential relationships.
    estore = _many_to_many_estore(group_count=5, rows_per_group=20)
    with patch("aryx.pipeline.fk_edges.get_settings",
               return_value=SimpleNamespace(max_relationships_per_fk_spec=100)):
        n = link_by_attribute(estore, "Source", "ref", "Target", "code", "TARGET_HAS_SOURCE")
    assert n == 0
    estore.save_relationships.assert_not_called()


def test_stays_under_cap_saves_normally() -> None:
    # 2 groups x 3 rows each side -> 3*3*2 = 18 relationships, under a 100 cap.
    estore = _many_to_many_estore(group_count=2, rows_per_group=3)
    with patch("aryx.pipeline.fk_edges.get_settings",
               return_value=SimpleNamespace(max_relationships_per_fk_spec=100)):
        n = link_by_attribute(estore, "Source", "ref", "Target", "code", "TARGET_HAS_SOURCE")
    assert n == 18
    estore.save_relationships.assert_called_once()
