"""End-to-end proof that a Manager-backed TokenGovernor actually shares
spend across real OS processes — not just across in-process objects.

Unlike test_token_governor.py (plain-dict unit tests), this spawns a real
ProcessPoolExecutor and confirms charge() calls made inside worker
processes are visible from the parent afterward. This is the exact
mechanism doc_discovery.ingest_confirmed() relies on so a per-job LLM token
budget stays enforced across `ingest_workers` concurrent worker processes
instead of each one starting from an unspent copy.
"""
from __future__ import annotations

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor

from aryx.broker import Broker
from aryx.broker.governor import TokenGovernor
from aryx.broker.registry import Registry
from aryx.broker.secrets import EnvSecretProvider


def _charge_in_worker(broker: Broker, tier: str, tokens: int) -> None:
    """Module-level (picklable) worker body — spawn requires importable targets."""
    broker.charge(tier, tokens)


def _make_broker(governor: TokenGovernor) -> Broker:
    return Broker(Registry(), governor, EnvSecretProvider(), {})


def test_charge_from_multiple_worker_processes_lands_in_one_shared_counter():
    with mp.Manager() as manager:
        shared_governor = TokenGovernor(
            {"cheap": 1_000_000},
            spent=manager.dict(),
            lock=manager.Lock(),
        )
        shared_broker = _make_broker(shared_governor)

        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=3, mp_context=ctx) as pool:
            futures = [
                pool.submit(_charge_in_worker, shared_broker, "cheap", 100)
                for _ in range(9)  # 3 workers x 3 charges each
            ]
            for fut in futures:
                fut.result(timeout=30)

        # If each worker had its own unshared copy of the governor (the bug
        # this fix closes), the parent's view would show 0 — every charge
        # would have landed in a private copy that vanished with its
        # process. Seeing the true total here proves the charges were
        # routed through the Manager to one real shared counter.
        assert shared_governor.spend_snapshot() == {"cheap": 900}


def test_replace_spend_folds_batch_total_back_into_original_governor():
    """Mirrors ingest_confirmed()'s exact sequence: charge from workers
    against a shared governor, then fold the result back into the
    original in-process governor before the next (non-parallel) step."""
    original = TokenGovernor({"cheap": 1_000_000})
    original.charge("cheap", 50)  # spend from an earlier, non-parallel stage

    with mp.Manager() as manager:
        shared_governor = TokenGovernor(
            original.budgets,
            spent=manager.dict(original.spend_snapshot()),
            lock=manager.Lock(),
        )
        shared_broker = _make_broker(shared_governor)

        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=2, mp_context=ctx) as pool:
            futures = [
                pool.submit(_charge_in_worker, shared_broker, "cheap", 30)
                for _ in range(2)
            ]
            for fut in futures:
                fut.result(timeout=30)

        original.replace_spend(dict(shared_governor.spend_snapshot()))

    # 50 (pre-existing) + 30 + 30 (from the two worker processes) = 110 —
    # not 60 (which double-merge would produce) and not 0 (which no merge,
    # or the original silent-loss bug, would produce).
    assert original.spend_snapshot() == {"cheap": 110}
