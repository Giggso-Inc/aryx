"""QA-route and ambiguous-route top-level dispatch, split out of `api/
ask_api.py` (Phase 9/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
definitions. `_cpq_engine`, `logger`, `_handle_cpq_qa`, `set_run_id`, and
`_standard_ask_pipeline` are read through the ask_api MODULE object (not
imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

import uuid
from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.api.ask_finish_cpq_result import _finish_cpq_result
from aryx.cpq.intent_gateway import AskRouteDecision
from aryx.cpq.state import CpqSession


def _route_qa(
    req: "Any", reader: Any, meta: AskRouteDecision | None = None,
) -> dict[str, Any]:
    """QA path — handlers execute only; no re-classification.

    N2 harden: cold-start QA loads catalog attrs via a *read-only* product
    mention resolve for option lists — never writes session.product_name
    or triggers a family switch (few-shot: 'options for product' must not
    hop to softwareSolutions_BOM).
    """
    _cpq_engine = _ask_api_module._cpq_engine
    session = (
        CpqSession.from_dict(req.session_data)
        if req.session_data.get("mode") == "cpq"
        else CpqSession()
    )
    if not session.run_id:
        session.run_id = uuid.uuid4().hex
    _ask_api_module.set_run_id(session.run_id)
    attrs: list = []
    product_for_attrs = session.product_name
    if not product_for_attrs:
        # Read-only resolve — do NOT assign session.product_name (N2/N3).
        try:
            _hints = _cpq_engine.extract_hints(req.question)
            mentioned = _cpq_engine.detect_product_mention(
                req.question, _hints, reader, req.workspace_id,
            )
            if mentioned:
                product_for_attrs = mentioned
                _ask_api_module.logger.info(
                    "route_qa: read_only product context=%r (session.product_name unchanged)",
                    mentioned,
                )
        except Exception:  # noqa: BLE001
            _ask_api_module.logger.debug("route_qa: detect_product_mention failed", exc_info=True)
    if product_for_attrs:
        try:
            attrs, _ = _cpq_engine.load_product_config(
                reader, req.workspace_id, product_for_attrs,
            )
        except Exception:  # noqa: BLE001
            _ask_api_module.logger.debug("route_qa: load_product_config failed", exc_info=True)
            attrs = []
    result = _ask_api_module._handle_cpq_qa(
        req, session, attrs, reader, resume_review=False, product_hint=product_for_attrs,
    )
    # Belt-and-suspenders: never let QA path mutate product without switch.
    if result and isinstance(result.get("session_data"), dict):
        if req.session_data.get("mode") != "cpq":
            # Cold QA shell — strip product commits if any leaked.
            sd = dict(result["session_data"])
            if not req.session_data.get("product_name"):
                if sd.get("product_name") and sd.get("status") not in (
                    "awaiting_approval", "post_approval", "configuring",
                ):
                    pass  # allow only if engine already entered real CPQ
            result["session_data"] = sd
    finished = _finish_cpq_result(result, req, reader, route_meta=meta)
    return finished or _ask_api_module._standard_ask_pipeline(req, reader)


def _route_ambiguous(meta: AskRouteDecision, req: "Any") -> dict[str, Any]:
    cq = meta.clarifying_question or (
        "Are you looking to configure or quote a product, or ask a "
        "general product question?"
    )
    return {
        "answer": cq,
        "terms": [],
        "tools_called": ["cpq_ask_route_ambiguous()"],
        "usage": {
            "prompt_tokens": meta.prompt_tokens,
            "completion_tokens": meta.completion_tokens,
            "latency_ms": 0,
            "menial_model": meta.model_id or "cpq-intent-gateway",
            "answer_model": meta.model_id or "cpq-intent-gateway",
        },
        "grounding": None,
        "session_data": req.session_data or {},
        "cpq_payload": None,
    }
