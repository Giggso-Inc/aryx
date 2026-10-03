"""Applying a confirmed country change and building the response, split
out of `api/ask_api.py` (Phase 3/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline definition; the country/region-derived-attr re-
derivation and re-validation logic lives in the sibling `ask_country_
change_revalidate.py` purely to keep this file under the line cap.
`_persist_cpq_history` is read through the ask_api MODULE object (not
imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_country_change_revalidate import (
    _rederive_and_revalidate_for_country_change,
)
from aryx.cpq.engine import DECISION_REQUIRED_KEYS, variable_name_words
from aryx.raven_log import raven_log


def _build_country_change_response(
    req: "Any", session: Any, new_country: str, reader: Any = None,
) -> dict[str, Any]:
    """Apply a confirmed country change (or report a no-op when it already
    matches) and build the response. Factored out of the mid-turn
    country-change gate (Issue 7, docs/CPQ_QUANTITY_COUNTRY_SUMMARY_
    FIXES_2026_08_13.md) so the LLM-first dispatcher's COUNTRY_CHANGE
    branch (§8 Phase 4) shares the exact same logic.

    ISSUE-004 (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_17.md):
    the display-only update below (`session.country = new_country`) used to
    be the entire function — it never touched `session.filled`'s
    country-mirror attrs (CRM_BILL_COUNTRY/CRM_SHIP_COUNTRY/
    ultimateDestinationCountry/packageRegion), which stayed frozen at
    whatever the INITIAL quote load derived, even across repeated confirmed
    changes (live-confirmed: "change country to Germany" then "...to
    Canada" left `ultimateDestinationCountry` reading "US"). `auto_fill`'s
    own "never override an already-filled value" contract
    (`engine.py:6908`) means simply re-calling it with the new country does
    nothing unless these 4 mirror keys are cleared first, so that's done
    below before the re-derivation. `reader` is accepted (both call sites
    already have it in scope — `_dispatch_intent_result`'s own param at
    `ask_api.py:4806`, `_run_cpq_turn_inner`'s own param at
    `ask_api.py:7047`) purely so this function can independently reload
    `session.product_name`'s catalog via `load_product_config`, since
    neither call site is guaranteed to already hold attrs/rules loaded for
    THIS session's product at the point it detects a country change.
    """
    if session.country and session.country.strip().lower() == new_country.strip().lower():
        answer = f"Country is already set to **{session.country}** — no change made."
        raven_log("DEBUG", "P4", "ask.response.country_change no-op country unchanged", context={
            "selected_option": "no_op", "available_options": ["no_op", "apply_change"],
            "reason_code": "COUNTRY_ALREADY_SET", "turn": getattr(session, "turn", None),
            "run_id": getattr(session, "run_id", None), "answer_len": len(answer)})
    else:
        session.country = new_country
        answer = f"Country → {session.country}"
        # Clear every frozen country/region-derived attr so the
        # re-derivation below isn't blocked by auto_fill's "already
        # filled -> never override" rule. Originally hardcoded to just
        # CRM_BILL_COUNTRY/CRM_SHIP_COUNTRY/ultimateDestinationCountry/
        # packageRegion, but live-verified that's incomplete: packageRegion
        # is itself cascade-filled from whichever sibling attr matches the
        # "region" decision-key fragment (engine.py:8577,
        # `_DECISION_REQUIRED_KEYS`) — e.g. modelSelectionRegion_astro,
        # which stayed at its stale value since it was never cleared, so
        # packageRegion kept re-copying the OLD region every time (US->
        # Germany left packageRegion="NA" instead of moving to EMEA).
        # Reusing the same "this is a country/region-shaped attr" signal
        # this engine already uses elsewhere, instead of hardcoding one
        # more catalog-specific name that the next catalog would miss too.
        #
        # PR #205 review fix (Medium finding #5): the original version
        # used a raw substring test (`"region" in vn.lower()`), which
        # would also match a hypothetical unrelated attr like
        # "RegionalDiscountCode" (contains "region" as a substring) and
        # silently clear a correct, unrelated answer. Split each
        # variable_name into its real camelCase/underscore word segments
        # (`variable_name_words`, the same helper detect_attr_query
        # already uses for word-level attribute matching) and require an
        # EXACT segment match instead — "RegionalDiscountCode" splits to
        # ["regional", "discount", "code"], and "regional" != "region", so
        # it correctly does NOT match, while "modelSelectionRegion_astro"
        # splits to [..., "region", "astro"] and correctly does.
        _cleared_vns: list[str] = []
        for _mirror_vn in list(session.filled.keys()):
            _vn_words = set(variable_name_words(_mirror_vn))
            if _vn_words & DECISION_REQUIRED_KEYS:
                session.filled.pop(_mirror_vn, None)
                session.display_filled.pop(_mirror_vn, None)
                session.filled_source.pop(_mirror_vn, None)
                _cleared_vns.append(_mirror_vn)
        raven_log("INFO", "P4", "ask.response.country_change applied new country", context={
            "selected_option": "apply_change", "available_options": ["no_op", "apply_change"],
            "reason_code": "COUNTRY_CHANGED", "turn": getattr(session, "turn", None),
            "run_id": getattr(session, "run_id", None), "new_country": new_country,
            "cleared_mirror_count": len(_cleared_vns), "cleared_mirror_vns": _cleared_vns[:20],
            "reader_present": reader is not None})
        _rederive_and_revalidate_for_country_change(req, session, new_country, reader)
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_country_change()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
