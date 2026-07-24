"""link_by_attribute: exact-match FK linking, including survivorship-merge aliasing.

A merged entity keeps one winning value for a disputed attribute and records
the rest in aryx_attribute_conflict.losing_values. Anything that referenced
one of those losing values by exact match must still resolve to the entity
that absorbed it — conflict_aliases() is what makes that possible.
"""
from __future__ import annotations

from unittest.mock import MagicMock

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
