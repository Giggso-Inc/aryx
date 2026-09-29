""""Show me the configuration"/"recap" response builder, split out of
`api/ask_api.py` (Phase 3/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original
inline definition. `_cpq_engine`, `logger`, and `_persist_cpq_history`
are read through the ask_api MODULE object (not imported by name) since
ask_api tests patch several of its own module-level names by dotted
path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_response_building.ask_cpq_summary_text import _cpq_summary_text


def _build_show_summary_response(
    req: "Any", session: Any, reader: Any,
) -> dict[str, Any] | None:
    """"Give me the final summary now" / "show me the configuration" /
    "recap" — re-render the current configuration, whether or not it's
    actually complete yet. Returns None if the underlying catalog load
    fails or nothing is filled at all (never crash a turn on this).

    Live-verified gap, 2026-08-13: this phrasing had no dedicated
    handling at all. The LLM-first classifier has no category for "show
    it again" so it defaulted to OUT_OF_SCOPE; separately, a shorter
    phrasing like "give the configuration" could coincidentally
    word-match a real catalog attribute whose own label contains
    "configuration" (e.g. "Configuration Type"), hijacking the turn into
    a change-target prompt for that unrelated attribute. Checked and
    handled here, deterministically, before either of those paths runs.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    try:
        attrs, _ = _cpq_engine.load_product_config(
            reader, req.workspace_id, session.product_name,
        )
    except Exception as exc:  # noqa: BLE001 — never crash a turn on this gate
        _ask_api_module.logger.debug(
            "cpq show-summary: load_product_config failed: %r", exc,
        )
        return None
    if not attrs or not session.display_filled:
        return None
    # Live-verified bug, 2026-08-13: load_product_config's second return
    # value is the RESOLVED PRODUCT NAME (its own docstring says so), not
    # a catalog_prefix -- using it as catalog_prefix below made
    # load_hiding_rules/load_recommendation_and_constraint_rules load the
    # WRONG (or empty) rule set, which zeroed out rule_governed_ids and
    # silently emptied the summary every time, always falling back to the
    # bare "Quantity → N" line even once the config was complete. Same
    # pattern _handle_approval/_build_json_preview_response already use.
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    # Never intercept a literal, exact answer to the currently pending
    # question just because it happens to contain a trigger word (e.g. a
    # real option named "Custom Configuration") — an exact case-
    # insensitive match against the pending attr's own option text always
    # wins over this heuristic.
    if session.pending_variables:
        _pending_attr = next(
            (a for a in attrs if a.variable_name == session.pending_variables[0]), None,
        )
        if _pending_attr is not None:
            _q_norm = req.question.strip().lower()
            for _opt in _pending_attr.options:
                if _q_norm in (_opt.display_name.strip().lower(), _opt.item_value.strip().lower()):
                    return None
    hiding_rules = _cpq_engine.load_hiding_rules(
        req.workspace_id, catalog_prefix, session.product_name)
    rec_rules, con_rules = _cpq_engine.load_recommendation_and_constraint_rules(
        req.workspace_id, catalog_prefix)
    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    hidden_vns = _cpq_engine.apply_hiding_rules(
        attrs, session.filled, hiding_rules, bml_eval, filled_multi=session.filled_multi,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix)[2]
    visible_attrs = [a for a in attrs if a.variable_name not in hidden_vns]
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    summary = _cpq_summary_text(
        session.display_filled, attrs, rule_ids,
        session.product_name, req.workspace_id, sources=session.filled_source,
        product_quantity=session.product_quantity, filled=session.filled,
        # docs/CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3 — same
        # applicability signal build_payload's JSON preview uses (see
        # ask_attach_share_flags._attach_share_flags).
        product_anchor_hint=session.product_anchor_question,
    )
    if not summary:
        return None
    if session.pending_variables:
        _next = next(
            (a for a in visible_attrs if a.variable_name == session.pending_variables[0]),
            None,
        )
        _still_need = f" I still need **{_next.display_label}** to finish." if _next else ""
        answer = (
            f"Here's your configuration so far for **{session.product_name}**.\n\n"
            f"{summary}\n\n"
            f"{_still_need}".strip()
        )
    else:
        answer = (
            f"Configuration complete for **{session.product_name}**.\n\n"
            f"{summary}\n\n"
            f"Click **JSON** below to see the full payload, say **confirm** "
            f"to submit, or describe any changes."
        )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_show_summary()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
