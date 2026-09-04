"""Runtime-swappable LLM config for Ask.

The Settings panel can change provider/model/key live (no restart). Ask calls
chat(role, ...) and this module builds the right single-model Broker on the fly,
reusing aryx.llm's provider routing. V1 holds config in process memory; V2 will
source secrets from AWS via the existing AwsSecretProvider.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), the live
config state and turn-usage tracking (`reset_turn_usage`/`get_turn_usage`/
`_RuntimeSecrets`/`_broker_for`/`set_config`/`status`) moved to
`llm_runtime_state.py` (zero patch risk). `_log_call`/`chat` stay here as
a deliberate exception: `complete_text` is directly whitebox-patched
(`aryx.llm_runtime.complete_text`) by `tests/test_llm_runtime_turn_usage.py`
and `get_settings`/`get_pool`/`load` are directly patched by
`tests/test_llm_runtime_log_call_dsn.py`, both called only from these two
functions.
"""
from __future__ import annotations

import logging
import time

from aryx.cpq.logging_context import get_run_id
from aryx.config import get_settings
from aryx.llm import complete_text
from aryx.llm_runtime_state import (
    _broker_for,
    _KEY_REF,
    _RuntimeSecrets,
    _state,
    _turn_usage,
    get_turn_usage,
    reset_turn_usage,
    set_config,
    status,
)
from aryx.queries import load
from aryx.store.pool import get_pool

__all__ = [
    "_KEY_REF",
    "_RuntimeSecrets",
    "chat",
    "get_turn_usage",
    "reset_turn_usage",
    "set_config",
    "status",
]

logger = logging.getLogger(__name__)


def _log_call(role: str, model: str, pt: int, ct: int, ms: int, err: str,
              workspace_id: int = 1) -> None:
    """Best-effort persist to aryx_llm_call (no-op if DB unavailable).

    Uses get_settings().effective_dsn(), not a raw os.environ read -- the
    latter (ARYX_RDB_DSN specifically) bypassed the Settings/effective_dsn()
    machinery entirely, so on an OCI deployment where ops sets
    ARYX_OCI_ADB_DSN/ARYX_DB_USER/ARYX_DB_PASSWORD per convention and never
    sets ARYX_RDB_DSN, this silently no-opped on every single call -- every
    LLM call's usage/audit record was lost, exactly the gap this choke
    point exists to close (found by post-merge review).
    """
    try:
        dsn = get_settings().effective_dsn()
    except Exception:  # noqa: BLE001 — e.g. ARYX_OCI_ADB_DSN unset; stay best-effort
        return
    if not dsn:
        return
    try:
        with get_pool(dsn).connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("insert_llm_call"),
                            (workspace_id, role, model, _state["provider"],
                             pt, ct, ms, "ask", err or None))
    except Exception:  # noqa: BLE001
        logger.debug("llm call log write failed", exc_info=True)


def chat(role: str, system: str, user: str,
         workspace_id: int = 1) -> tuple[str, int, int]:
    """Run a completion for 'menial' or 'answer' using the configured model."""
    model = _state["menial_model"] if role == "menial" else _state["answer_model"]
    start = time.monotonic()
    # Log BEFORE the network call, not just after -- this is the single
    # choke point every LLM call in the codebase goes through (BML Tier-2
    # script evaluation, every ask_api.py `_llm_*` classifier, general Ask
    # synthesis), so a silent hang anywhere in here previously produced
    # zero log output until (if ever) complete_text returned. Mirrors the
    # same before/after fix already applied to cpq.intent_gateway._pinned_chat.
    logger.info(
        "cpq_llm_runtime_start: role=%s model=%s run_id=%s",
        role, model, get_run_id() or "-",
    )
    text, pt, ct = complete_text(_broker_for(model), "cheap", system, user, think=False)
    ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "cpq_llm_runtime: role=%s model=%s run_id=%s tokens=(%d,%d) elapsed_s=%.3f",
        role, model, get_run_id() or "-", pt, ct, ms / 1000.0,
    )
    _log_call(role, model, pt, ct, ms, "", workspace_id=workspace_id)
    turn_usage = _turn_usage.get()
    if turn_usage is not None:
        turn_usage["prompt_tokens"] += pt
        turn_usage["completion_tokens"] += ct
        turn_usage["latency_ms"] += ms
        turn_usage["calls"] += 1
        turn_usage["models"].add(model)
    return text, pt, ct
