"""``build_bml_evaluator`` -- the per-catalog BML evaluator factory
(Phase 4 step 6 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Needs nothing from the ``CpqEngine`` instance, so it takes no ``engine``
parameter. ``get_cpq_rdb`` goes through the engine module object rather
than a ``from ... import`` -- ``aryx.cpq.engine.get_cpq_rdb`` is patched
by dotted path in several tests, and a frozen import-time reference would
silently bypass those patches.
"""

from __future__ import annotations

import time

from aryx.config import get_settings
from aryx.cpq import engine as _engine_module
from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.engine import logger


def build_bml_evaluator(
    workspace_id: int, catalog_prefix: str = "", run_id: str = "",
) -> BmlEvaluator:
    """BML evaluator over this workspace's BmFunction scripts.

    catalog_prefix — scopes to one ingested catalog when the workspace
    holds more than one product's XML export (BM-native function ids
    collide across catalogs the same way rule ids do). Also passed to
    the evaluator itself so its process-wide LLM-result cache (see
    bml._SHARED_SCRIPT_CACHE) can't cross-contaminate between catalogs
    or workspaces sharing a colliding function id.

    Tier-2 LLM fallback is gated by settings.bml_use_llm (default
    False) — see that field's docstring for why it's off by default.
    """
    _t0 = time.monotonic()
    logger.info(
        "cpq_step: build_bml_evaluator start workspace_id=%s catalog_prefix=%r",
        workspace_id, catalog_prefix,
    )
    try:
        scripts = _engine_module.get_cpq_rdb().fetch_function_scripts(
            workspace_id, catalog_prefix)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cpq: function script fetch failed", exc_info=True)
        fill_log.log_load_failed("bml_scripts", exc, "SCRIPT_FETCH_FAILED", workspace_id=workspace_id,
                                 catalog_prefix=catalog_prefix)
        scripts = {}
    logger.info(
        "cpq_step: build_bml_evaluator done elapsed_s=%.3f scripts=%d",
        time.monotonic() - _t0, len(scripts),
    )
    fill_log.log_load("bml_evaluator", workspace_id=workspace_id, catalog_prefix=catalog_prefix,
                      script_count=len(scripts), empty=not scripts, use_llm=bool(get_settings().bml_use_llm))
    return BmlEvaluator(
        scripts, use_llm=get_settings().bml_use_llm,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix, run_id=run_id,
    )
