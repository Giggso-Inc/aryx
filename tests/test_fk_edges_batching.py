"""Unit tests for link_by_attribute -- verifies the P8 fix: entities are
passed in by the caller instead of being refetched from the store on every
call (see docs/SCALABILITY_BOTTLENECKS.md P8).
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from aryx.pipeline.fk_edges import link_by_attribute


class _FakeEntityStore:
    """Records save_relationships calls; list_entities() must never be called
    by link_by_attribute -- that would mean the refetch bug regressed."""

    def __init__(self) -> None:
        self.saved: list = []
        self.list_entities_calls = 0

    def list_entities(self):
        self.list_entities_calls += 1
        raise AssertionError(
            "link_by_attribute must not call estore.list_entities() -- "
            "entities must be passed in by the caller (P8 fix)"
        )

    def save_relationships(self, rels) -> None:
        self.saved.extend(rels)

    def conflict_aliases(self, target_attr: str) -> dict:
        """No survivorship-merge aliases in these tests -- plain lookup only."""
        return {}


ENTITIES = [
    (1, "Ticket", {"customer_name": "Acme"}),
    (2, "Ticket", {"customer_name": "Globex"}),
    (3, "Customer", {"name": "Acme"}),
    (4, "Customer", {"name": "Globex"}),
    (5, "Customer", {"name": "Initech"}),
]


class TestLinkByAttribute(unittest.TestCase):
    def test_does_not_refetch_entities(self) -> None:
        """The core P8 regression guard: no call to list_entities()."""
        store = _FakeEntityStore()
        link_by_attribute(store, ENTITIES, "Ticket", "customer_name",
                          "Customer", "name", "HAS_TICKET")
        self.assertEqual(store.list_entities_calls, 0)

    def test_matches_by_lowercased_attribute_value(self) -> None:
        store = _FakeEntityStore()
        count = link_by_attribute(store, ENTITIES, "Ticket", "customer_name",
                                  "Customer", "name", "HAS_TICKET")
        self.assertEqual(count, 2)
        self.assertEqual(len(store.saved), 2)

    def test_no_matches_saves_nothing(self) -> None:
        store = _FakeEntityStore()
        count = link_by_attribute(store, ENTITIES, "Ticket", "customer_name",
                                  "Customer", "does_not_exist", "HAS_TICKET")
        self.assertEqual(count, 0)
        self.assertEqual(store.saved, [])

    def test_reused_entities_list_serves_multiple_calls(self) -> None:
        """Simulates the orchestrate.py loop: same entities list, N specs,
        only ever handed to link_by_attribute -- never refetched."""
        store = _FakeEntityStore()
        specs = [
            ("Ticket", "customer_name", "Customer", "name", "HAS_TICKET"),
            ("Ticket", "customer_name", "Customer", "name", "HAS_TICKET_2"),
            ("Ticket", "customer_name", "Customer", "name", "HAS_TICKET_3"),
        ]
        for source_type, source_attr, target_type, target_attr, name in specs:
            link_by_attribute(store, ENTITIES, source_type, source_attr,
                              target_type, target_attr, name)
        self.assertEqual(store.list_entities_calls, 0)
        self.assertEqual(len(store.saved), 6)  # 2 matches x 3 specs


if __name__ == "__main__":
    unittest.main()
