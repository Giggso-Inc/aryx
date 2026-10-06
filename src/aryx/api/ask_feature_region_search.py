"""Feature/region product-search route dispatch for `run_ask` (ported from
dev-rv-msi #331, 2026-09-16). `_cpq_engine`, `logger` are read through the
ask_api MODULE object (not imported by name) since ask_api tests patch
several of its own module-level names by dotted path — same convention as
`api/ask_qa/ask_route_qa.py`.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.api.ask_request_models import AskRequest
from aryx.graph.feature_search import search_products_combined
from aryx.log_safe import text_ref
from aryx.raven_log import raven_log


def _format_feature_region_search_answer(
    results: list[dict[str, Any]],
    region: str | None,
    feature_label: str | None,
    feature_value: str | None,
) -> str:
    """Plain-language answer for a feature/region search route -- lists
    matched model names, with a distinct "nothing found" phrasing rather
    than a bare empty list."""
    criteria = []
    if region:
        criteria.append(f"region {region}")
    if feature_label and feature_value:
        criteria.append(f"{feature_label} '{feature_value}'")
    crit_text = " and ".join(criteria) or "your search"

    if not results:
        return f"I couldn't find any products matching {crit_text}."

    models = [str(r.get("model")) for r in results if r.get("model")]
    if len(models) == 1:
        return f"{models[0]} matches {crit_text}."
    return f"{len(models)} products match {crit_text}: {', '.join(models)}."


def _route_feature_region_search(
    req: AskRequest,
    reader: Any,
    region: str | None,
    feature_label: str | None,
    feature_value: str | None,
) -> dict[str, Any]:
    """Deterministic route for a feature/region product-search question --
    see Phase2_DataTable_Schema_Audit.md and search_products_combined()
    (aryx.graph.feature_search). Triggered by detect_feature_region_search's
    narrow regex match in run_ask, NOT by the gateway LLM: this is
    additive to the existing CPQ/QA router, not a competing classification
    path, so it never consumes or affects the gateway's one-LLM-call
    budget for the turn.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    t0 = time.monotonic()
    try:
        results = search_products_combined(
            reader, _cpq_engine, req.workspace_id,
            region=region, feature_label=feature_label, feature_value=feature_value,
            limit=20,
        )
    except Exception as exc:  # noqa: BLE001 -- never let a search error break the turn
        raven_log(
            "WARN", "P3",
            "ask.feature_search.lookup_failed search failed, answered as no matches",
            error_code="ARYX_ASK_FEATURE_SEARCH_FAILED", context={
                "dependency_name": "graph.feature_search", "operation": "search_products_combined",
                "result": "failed", "error_class": type(exc).__name__, "attempt": 1,
                # region/feature_value are regex-extracted straight from the customer's own
                # question (detect_feature_region_search) -- never log them verbatim, same
                # free-text rule this module's siblings follow with text_ref(req.question).
                # feature_label is a fixed constant ("Feature Type"), never customer input.
                "region_ref": text_ref(region), "feature_label": feature_label or "",
                "feature_value_ref": text_ref(feature_value),
            },
        )
        logger.warning(
            "feature_region_search: search_products_combined failed region=%r "
            "feature_label=%r feature_value=%r: %s",
            region, feature_label, feature_value, exc, exc_info=True,
        )
        results = []
    answer = _format_feature_region_search_answer(results, region, feature_label, feature_value)
    return {
        "answer": answer,
        "terms": [],
        "tools_called": ["search_products_combined()"],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "menial_model": "deterministic",
            "answer_model": "deterministic",
        },
        "grounding": None,
        "session_data": req.session_data or {},
        "cpq_payload": {"feature_region_search_results": results},
    }
