"""Unit coverage for Broker.governor / Broker.with_governor().

Added alongside the fix that shares a Broker's token budget across a
ProcessPoolExecutor (see doc_discovery.ingest_confirmed /
_run_non_last_batch): with_governor() is how a cross-process-safe governor
gets swapped into the broker handed to worker processes, without losing the
broker's registry/secrets/embed config.
"""
from __future__ import annotations

from aryx.broker import Broker
from aryx.broker.governor import TokenGovernor
from aryx.broker.registry import Registry
from aryx.broker.secrets import EnvSecretProvider


def _broker(governor: TokenGovernor) -> Broker:
    return Broker(Registry(), governor, EnvSecretProvider(), {"model": "nomic-embed-text"})


def test_governor_property_returns_the_brokers_own_governor():
    governor = TokenGovernor({"cheap": 100})
    broker = _broker(governor)
    assert broker.governor is governor


def test_with_governor_swaps_governor_but_keeps_everything_else():
    original_governor = TokenGovernor({"cheap": 100})
    broker = _broker(original_governor)

    new_governor = TokenGovernor({"cheap": 999})
    swapped = broker.with_governor(new_governor)

    assert swapped is not broker  # a new Broker, not a mutation
    assert swapped.governor is new_governor
    assert broker.governor is original_governor  # original untouched
    assert swapped.embed_model_id == broker.embed_model_id  # embed config carried over
    assert swapped.secrets is broker.secrets  # secrets carried over


def test_with_governor_charges_land_on_the_new_governor_not_the_old_one():
    old_governor = TokenGovernor({"cheap": 100})
    broker = _broker(old_governor)

    new_governor = TokenGovernor({"cheap": 100})
    swapped = broker.with_governor(new_governor)

    swapped.charge("cheap", 40)

    assert new_governor.spend_snapshot() == {"cheap": 40}
    assert old_governor.spend_snapshot() == {}
