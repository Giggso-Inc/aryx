"""LLM fallback for remove/change intent, split out of `api/ask_api.py`
(Phase 6/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline
definition. `logger` is read through the ask_api MODULE object (not
imported by name) for consistency with the rest of this decomposition.
"""

from __future__ import annotations

import json
from typing import Any

from aryx.llm import llm_runtime
from aryx.api.ask_catalog.ask_relevant_intent_candidates import (
    _LLM_INTENT_ATTRS_CAP_HARD,
    _relevant_intent_candidates,
)


def _llm_classify_change_intent(
    question: str, attrs: list, session: Any, workspace_id: int,
) -> "tuple[dict[str, str] | None, int, int]":
    """LLM fallback for remove/change intent, tried only after every regex
    detector (detect_multi_select_removal, detect_change_request(s_multi))
    found nothing. Reuses the existing menial-tier model already wired for
    term extraction (`_extract_terms`) — no new model config. Classify-only:
    it never synthesizes prose, only picks {intent, variable_name, value}.

    Same never-guess discipline as the regex path: any attribute name the
    model returns that isn't one of the attrs actually present in the
    current session is discarded. Live-verified finding (2026-07-22): two
    real attrs in this catalog share the display_label "Mounting Type"
    (mountType_viSoln, single, vs. mountingTypeArray_viSoln, multi) — the
    label alone isn't enough to disambiguate, so the prompt keys on
    variable_name + select_type + the attr's real option list, and the
    returned value is re-validated against that specific attr's own
    options before being trusted (a "remove" against a single-select attr,
    or a value not in the target attr's option set, is discarded).
    """
    from aryx.api import ask_api as _ask_api_module
    filled_candidates = [
        a for a in attrs
        if a.variable_name in session.filled or a.variable_name in session.filled_multi
    ]
    if not filled_candidates:
        return None, 0, 0
    # Relevance-score BEFORE capping — a catalog with dozens of filled
    # attrs (promotions, accessories, etc.) can push the actually-relevant
    # attr past a fixed positional cap if capped by catalog order first.
    # Live-verified bug (2026-07-22): capping to the first 40 filled attrs
    # by catalog order cut mountingTypeArray_viSoln out entirely before
    # relevance scoring ever saw it, because dozens of unrelated
    # promotion/accessory attrs came first in attrs' catalog order.
    candidates = _relevant_intent_candidates(
        question, filled_candidates[:_LLM_INTENT_ATTRS_CAP_HARD])
    by_vn = {a.variable_name: a for a in candidates}
    catalog_lines = []
    for a in candidates:
        current = session.filled_multi.get(a.variable_name) or session.filled.get(a.variable_name)
        opts = ", ".join(o.display_name for o in a.options[:15]) if a.options else "(free text)"
        catalog_lines.append(
            f"- {a.variable_name} [{a.select_type}] ({a.display_label}): "
            f"current={current!r}; options=[{opts}]"
        )
    sys = (
        "You classify a user's message about an in-progress product configuration. "
        "Decide if they want to REMOVE an already-selected option from a [multi] "
        "attribute, or CHANGE a [single] attribute's value. Attributes can share the "
        "same display label but are different fields — pick by variable_name, "
        "select_type, and which one's current value or options actually match what "
        "the user is talking about. Only use attribute names from the list given — "
        "never invent one. If neither intent clearly applies, or you're unsure which "
        "of two similarly-labeled attrs is meant, say none."
    )
    user = (
        "ATTRIBUTES (variable_name [select_type] (label): current=...; options=[...]):\n"
        + "\n".join(catalog_lines) +
        f"\n\nUSER MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"intent": "remove"|"change"|"none", '
        '"variable_name": "<exact name from list, or empty>", '
        '"value": "<option text or new value, or empty>"}'
    )
    def _validate(parsed: dict) -> dict[str, str] | None:
        intent = parsed.get("intent")
        vn = parsed.get("variable_name") or ""
        value = parsed.get("value") or ""
        if intent not in ("remove", "change") or not vn:
            return None
        # "remove" genuinely needs a value (which option to remove) — but
        # "change" with an empty value is a real, distinct outcome (the
        # attribute WAS identified, just with no new value stated), not a
        # failed classification — the caller routes it to a "which value
        # would you like?" follow-up instead of discarding the match
        # entirely (2026-07-28 fix, live-verified: "change the hardware
        # type" correctly named hWVersion_astro with value="", previously
        # thrown away here).
        if intent == "remove" and not value:
            return None
        attr = by_vn.get(vn)
        if attr is None:
            _ask_api_module.logger.debug(
                "llm intent fallback: model named vn %r not in candidates %r",
                vn, list(by_vn),
            )
            return None
        if intent == "remove" and attr.select_type != "multi":
            _ask_api_module.logger.debug(
                "llm intent fallback: rejected remove on non-multi attr %r", vn,
            )
            return None
        if value and attr.options:
            valid_values = {o.display_name.lower() for o in attr.options} | {
                o.item_value.lower() for o in attr.options
            }
            if value.lower() not in valid_values:
                _ask_api_module.logger.debug(
                    "llm intent fallback: value %r not a real option for %r", value, vn,
                )
                return None
        return {"intent": intent, "variable_name": vn, "value": value}

    # Inlines _llm_classify_intent_core's call+parse shape rather than
    # reusing it directly (2026-07-28): that shared helper's other 4 call
    # sites return a bare bool/dict and never attach token usage to a
    # user-visible response, so changing its signature to a 3-tuple would
    # force pointless unpacking on all of them. This is the one caller
    # whose result DOES reach a response with hardcoded "cpq-engine, 0
    # tokens" usage (via the "change" + empty-value branch below) — same
    # live-confirmed gap _llm_classify_intent_universal already fixed for
    # the Phase 2 path.
    try:
        text, _it, _ot = llm_runtime.chat("menial", sys, user, workspace_id=workspace_id)
        s, e = text.find("{"), text.rfind("}")
        parsed = json.loads(text[s:e + 1])
    except Exception as exc:  # noqa: BLE001 — fallback must never crash the turn
        _ask_api_module.logger.debug("llm intent fallback: llm call or parse failed: %r", exc)
        return None, 0, 0
    return _validate(parsed), _it, _ot
