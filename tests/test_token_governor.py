"""Unit coverage for TokenGovernor's cross-process-safe spend tracking.

Added alongside the fix that moved doc_discovery.ingest_confirmed()'s
concurrent tabular-file batch from a ThreadPoolExecutor to a
ProcessPoolExecutor (GIL contention on CPU-bound land+resolve work). Passing
a Broker across a process boundary pickles an independent copy of its
TokenGovernor, so a bare dict `_spent` counter would silently stop being
shared — each worker would start unspent, letting the per-job token budget
be exceeded by up to `ingest_workers`x. These tests cover the injectable
spent/lock, snapshot, and replace_spend methods that make sharing it across
processes (via a multiprocessing.Manager) possible.
"""
from __future__ import annotations

from aryx.broker.governor import TokenGovernor


def test_charge_without_shared_state_behaves_as_before():
    gov = TokenGovernor({"cheap": 100})
    gov.charge("cheap", 40)
    gov.charge("cheap", 40)
    assert gov.spend_snapshot() == {"cheap": 80}
    assert gov.effective_tier("cheap") == "cheap"
    gov.charge("cheap", 40)
    assert gov.effective_tier("cheap") != "cheap"  # budget exhausted, downgraded


def test_budgets_property_returns_a_copy_not_the_live_dict():
    original = {"cheap": 100}
    gov = TokenGovernor(original)
    snapshot = gov.budgets
    snapshot["cheap"] = 0
    assert gov.budgets == {"cheap": 100}  # mutating the copy didn't affect the governor


def test_charge_with_injected_spent_mapping_writes_through():
    shared_spent: dict[str, int] = {}
    gov = TokenGovernor({"cheap": 100}, spent=shared_spent)
    gov.charge("cheap", 25)
    assert shared_spent == {"cheap": 25}  # the caller's own mapping was updated in place


def test_replace_spend_overwrites_rather_than_adds():
    gov = TokenGovernor({"cheap": 100})
    gov.charge("cheap", 10)
    gov.replace_spend({"cheap": 70})
    assert gov.spend_snapshot() == {"cheap": 70}


def test_spend_snapshot_seeds_a_second_governor_starting_from_the_same_state():
    """Mirrors ingest_confirmed(): a fresh (e.g. Manager-backed) governor is
    seeded from the original's current spend, not from zero."""
    original = TokenGovernor({"cheap": 100})
    original.charge("cheap", 30)

    seeded = TokenGovernor({"cheap": 100}, spent=dict(original.spend_snapshot()))
    assert seeded.spend_snapshot() == {"cheap": 30}
    seeded.charge("cheap", 10)
    assert seeded.spend_snapshot() == {"cheap": 40}
    assert original.spend_snapshot() == {"cheap": 30}  # independent copies, as expected pre-merge
