"""Token governor: per-tier budgets with downgrade-on-overflow (P6)."""
from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from typing import MutableMapping

from aryx.broker.specs import TIER_LADDER, Tier

logger = logging.getLogger(__name__)


class TokenGovernor:
    """Tracks token spend per tier and downgrades when a budget is exhausted.

    `spent`/`lock` let a caller inject a cross-process-safe backing store — a
    multiprocessing.Manager().dict() + Manager().Lock() — instead of the
    default plain dict. Needed when one Broker's budget must be shared by
    workers running in separate processes (see doc_discovery.ingest_confirmed,
    which fans concurrent ingest files out to a ProcessPoolExecutor): each
    worker gets its own pickled copy of the TokenGovernor object, but a
    Manager-backed dict/lock pickles as a proxy back to the same manager
    process, so charge() calls from any worker still land in one real
    shared counter instead of each worker starting from an unspent budget.
    """

    def __init__(
        self, budgets: dict[str, int],
        spent: MutableMapping[str, int] | None = None,
        lock: AbstractContextManager | None = None,
    ) -> None:
        """Configure per-tier token budgets (0 or missing means unlimited)."""
        self._budgets = budgets
        self._spent: MutableMapping[str, int] = spent if spent is not None else {}
        self._lock = lock

    @property
    def budgets(self) -> dict[str, int]:
        """Copy of the configured per-tier budgets."""
        return dict(self._budgets)

    def spend_snapshot(self) -> dict[str, int]:
        """Copy of current per-tier spend — for seeding a new governor that
        must start from the same cumulative state."""
        return dict(self._spent)

    def replace_spend(self, spent: dict[str, int]) -> None:
        """Overwrite current spend with an external snapshot.

        Used to fold a cross-process governor's accumulated spend back into
        the original in-process governor once its workers have finished —
        see ingest_confirmed(), which builds a shared governor for a batch
        of concurrent files, then must make the *original* governor (used by
        the last file, run afterward in-process) reflect what the batch
        actually spent.
        """
        self._spent = dict(spent)

    def charge(self, tier: Tier, tokens: int) -> None:
        """Record token spend against a tier.

        Locked when a cross-process lock was supplied — a bare += against a
        Manager dict proxy is a non-atomic read-modify-write over IPC, so two
        processes charging concurrently could lose an update without it.
        """
        if self._lock is not None:
            with self._lock:
                self._spent[tier] = self._spent.get(tier, 0) + tokens
        else:
            self._spent[tier] = self._spent.get(tier, 0) + tokens

    def _exhausted(self, tier: Tier) -> bool:
        """True when a tier has a positive budget and has spent beyond it."""
        budget = self._budgets.get(tier, 0)
        return budget > 0 and self._spent.get(tier, 0) >= budget

    def effective_tier(self, requested: Tier) -> Tier:
        """Return the requested tier, or the next cheaper one if over budget."""
        ladder = TIER_LADDER[TIER_LADDER.index(requested):]
        for tier in ladder:
            if not self._exhausted(tier):
                return tier
        logger.warning("all tiers from %s exhausted; using %s", requested, ladder[-1])
        return ladder[-1]
