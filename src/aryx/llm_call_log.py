"""Best-effort persistence of LLM call metadata for aryx_llm_call.

Split out of `llm.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _log_llm_call(tier: str, model: str, provider: str,
                  in_tok: int, out_tok: int, ms: int,
                  workspace_id: int = 1) -> None:
    """Best-effort persist to aryx_llm_call; no-op if DB unavailable."""
    try:
        from aryx.config import get_settings    # noqa: PLC0415
        from aryx.queries import load           # noqa: PLC0415
        from aryx.store.pool import get_pool    # noqa: PLC0415
        dsn = get_settings().effective_dsn()
        with get_pool(dsn).connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("insert_llm_call"),
                            (workspace_id, tier, model, provider,
                             in_tok, out_tok, ms, "pipeline", None))
    except Exception:  # noqa: BLE001
        logger.debug("llm call log write failed", exc_info=True)
