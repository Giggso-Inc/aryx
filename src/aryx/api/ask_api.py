"""Ask API — natural-language questions answered over the knowledge graph.

Flow: extract terms -> deterministic graph retrieval -> synthesise -> verify
grounding. Returns the answer, graph calls, usage, and the grounding record.
"""
from __future__ import annotations

import logging
from typing import Any  # noqa: E402

from fastapi import APIRouter  # noqa: E402

from aryx import llm_runtime
from aryx.api.ask_core_helpers import _validate_workspace
from aryx.api.ask_llm.ask_llm_usage_and_new_request_detect import _apply_real_llm_usage
from aryx.api.ask_request_models import AskRequest, LlmConfigRequest, Turn  # noqa: E402,F401 — Turn re-exported
from aryx.api.ask_run_ask import run_ask
from aryx.api.ask_turn_dispatch import _dispatch_cpq_turn_steps
from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine  # noqa: E402
from aryx.cpq.intent_gateway import (
    AskRouteDecision,
    classify_ask_route,
    classify_intent as gateway_classify_intent,
    hard_off_topic,
    mark_top_level_route_used,
    soft_quote_heuristic,
    top_level_route_used,
)
from aryx.cpq.logging_context import install_run_id_logging, set_run_id
from aryx.cpq.session_guard import (  # noqa: E402
    detect_guided_mode_accept,
    detect_undo,
    enforce_conversational_invariant,
    record_utterance,
)
from aryx.graph.retrieve import all_types, gather, render_context

_cpq_engine = CpqEngine()

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


def _run_cpq_turn(
    req: AskRequest, reader: Any, route_meta: "AskRouteDecision | None" = None,
) -> dict[str, Any]:
    """Execute one turn of the 8-step CPQ guided-configuration conversation.

    Step contract, route_meta, session_data, and the real-usage-reporting
    choke point this is: see docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_
    2026_08_13.md and docs/CPQ_Usage_Reporting_Gap.md.
    """
    llm_runtime.reset_turn_usage()
    result = enforce_conversational_invariant(_run_cpq_turn_inner(req, reader, route_meta))
    _apply_real_llm_usage(result)
    return result


def _run_cpq_turn_inner(
    req: AskRequest, reader: Any, route_meta: "AskRouteDecision | None" = None,
) -> dict[str, Any]:
    """Inner CPQ turn body — see ``_run_cpq_turn`` for the step contract."""
    return _dispatch_cpq_turn_steps(req, reader, route_meta)


def ask_router() -> APIRouter:
    router = APIRouter()

    @router.post("/ask")
    def ask(req: AskRequest) -> dict:
        _validate_workspace(req.workspace_id)
        return run_ask(req)

    @router.get("/llm/config")
    def get_llm_config() -> dict:
        return llm_runtime.status()

    @router.post("/admin/llm/config")
    def set_llm_config(req: LlmConfigRequest) -> dict:
        llm_runtime.set_config(**req.model_dump())
        return llm_runtime.status()

    return router
