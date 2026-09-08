"""Missing-Data-Table detection for hiding rules, split out of `cpq/
engine.py`'s module-level scope (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md -- module-level constant/helper extraction, done
purely to shrink engine.py further). Re-exported from `aryx.cpq.engine`
(see the import there) so every existing `from aryx.cpq.engine import
<name>` caller/test keeps working unchanged. Logic unchanged from the
original inline definitions.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.cpq import engine as _engine_module
from aryx.cpq.engine import logger

# CANDIDATE registry of data tables known to be missing from AT LEAST ONE
# ingested workspace historically (not attribute names -- a hiding rule
# anywhere, for any attribute, that structurally depends on one of these
# tables can never resolve THERE, so auto_fill warns and skips rather than
# asking forever). Extend this tuple if another candidate-missing table
# surfaces; never hardcode which attributes are affected -- that's derived
# generically from which hiding rules reference the table.
#
# 2026-08-18 (Raven PR #211 review, finding #4): this was briefly emptied
# to `()` on a single-workspace verification (workspace 93 -- 511
# UserGroupMapping rows confirmed ingested there). Cross-workspace check
# (docs/CPQ_MULTISELECT_AUTOFILL_AND_COUNTRY_CONFIGDATA_PLAN_2026_08_18.md)
# found UserGroupMapping ingested ONLY for workspace 93 -- 16 other live
# workspaces (1, 27, 28, 29, 31, 38, 51, 61, 63, 64, 73, 85, 88, 90, 91, 92)
# have ZERO UserGroupMapping rows. Emptying this constant globally would
# have silently defeated Group 1's skip for every one of those workspaces --
# `dHSAssetTagLabel_astro`/`cBPQRCode_astro`/`fedQRCode_astro` would blind-
# pick a wrong value there instead of correctly staying skipped. Fixed
# properly instead: this list is now just the CANDIDATE names to check --
# `_hiding_rule_needs_missing_data_table` verifies actual ingestion PER
# WORKSPACE (live query, cached) rather than assuming one workspace's
# ingestion status applies globally.
_KNOWN_MISSING_DATA_TABLES = ("UserGroupMapping",)

# workspace_id -> {table_name.lower(): is_ingested_bool}, short-TTL so a
# newly-completed ingestion run is picked up without a process restart,
# same convention as this file's other per-workspace caches (_DT_CACHE,
# _LAYOUT_*_CACHE).
_TABLE_INGESTED_CACHE: dict[int, dict[str, bool]] = {}
_TABLE_INGESTED_CACHE_TTL_SECONDS = 300.0
_TABLE_INGESTED_CACHE_TS: dict[int, float] = {}


def _table_ingested_for_workspace(table_name: str, workspace_id: int | None) -> bool:
    """True if `table_name` has at least one real ingested entity in
    `workspace_id`. `workspace_id=None` (no workspace context available,
    e.g. an offline/unit-test caller) conservatively returns False -- same
    "assume missing, never assume present" default `_KNOWN_MISSING_DATA_
    TABLES` always used before this was workspace-scoped."""
    if workspace_id is None:
        return False
    key = table_name.lower()
    now = time.monotonic()
    cached_ts = _TABLE_INGESTED_CACHE_TS.get(workspace_id, 0.0)
    if now - cached_ts >= _TABLE_INGESTED_CACHE_TTL_SECONDS:
        _TABLE_INGESTED_CACHE.pop(workspace_id, None)
    per_ws = _TABLE_INGESTED_CACHE.setdefault(workspace_id, {})
    if key in per_ws:
        return per_ws[key]
    try:
        rows = _engine_module.get_cpq_rdb().fetch_entities_by_type(workspace_id, table_name)
        ingested = bool(rows)
    except Exception:
        logger.debug(
            "cpq: table-ingestion check failed for %r ws=%s -- assuming "
            "not ingested (never assume present on a lookup failure)",
            table_name, workspace_id, exc_info=True,
        )
        ingested = False
    per_ws[key] = ingested
    _TABLE_INGESTED_CACHE_TS[workspace_id] = now
    return ingested


def _hiding_rule_needs_missing_data_table(
    rule: Any, workspace_id: int | None = None,
) -> bool:
    """True if `rule`'s script (declarative or condition-script form)
    references a data table that is NOT ingested for `workspace_id` -- see
    `_KNOWN_MISSING_DATA_TABLES` for the candidate list and
    `_table_ingested_for_workspace` for the per-workspace check. Such a
    rule can never resolve to a real hide/show outcome in THIS workspace,
    so its target should never be silently asked about forever here --
    even though the exact same table may be genuinely ingested (and this
    same rule shape genuinely resolvable) in a different workspace.

    `workspace_id=None` (no caller passes it) preserves the original,
    fully conservative behavior: every candidate table is treated as
    missing everywhere, identical to today's behavior for any caller that
    doesn't supply a workspace.
    """
    script = (rule.script or "") + (getattr(rule, "condition_script", None) or "")
    if not script:
        return False
    script_lower = script.lower()
    return any(
        table.lower() in script_lower
        and not _table_ingested_for_workspace(table, workspace_id)
        for table in _KNOWN_MISSING_DATA_TABLES
    )
