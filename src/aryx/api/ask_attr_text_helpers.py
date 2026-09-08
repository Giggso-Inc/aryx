"""Attribute-options and current-quote-listing text builders, split out
of `ask_api.py` (final sweep, Phase 11/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). `_build_attr_options_
text` was factored out of `_handle_cpq_qa`'s single-attr fast path
(docs/config_consistency_issues_2026-07-30.md issue 3) so the same
constrained-options logic can answer more than one attribute in one
turn. `_build_current_quote_attribute_listing_text` answers "list the
attributes" once a quote is already in progress by reading the REAL
filled state — no layout approximation needed, since the customer's own
actual answers already ARE the one real path. `_resolve_split_change_
text` resolves one self-contained "change X to Y" fragment scoped to
`last_qa_variables` first (a strictly smaller, more precise search than
either generic catalog-wide detector — docs/config_consistency_issues_
2026-07-30.md Issue 12), falling back to the generic detector only when
that scope doesn't cover the fragment. Logic unchanged from the original
inline definitions. `_cpq_engine` is read through the ask_api module
object (not imported by name) since at least one test replaces the
whole singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any



def _build_attr_options_text(
    req: "Any", session: Any, attrs: list, attr_q: Any,
) -> str | None:
    """Build "The available options for X are: ..." text for one already-
    resolved attribute, constrained to the currently-active allowed set.
    Returns None when the attribute has no presentable options at all.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _presentable = [o for o in attr_q.options if o.display_name.strip()]
    if not _presentable:
        return None
    _qa_catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    _, _qa_con_rules = _cpq_engine.load_recommendation_and_constraint_rules(
        req.workspace_id, _qa_catalog_prefix)
    _qa_bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, _qa_catalog_prefix)
    _qa_constrained = _cpq_engine.apply_constraint_rules(
        attrs, _qa_con_rules, session.filled, _qa_bml_eval, filled_multi=session.filled_multi)
    _qa_allowed = _qa_constrained.get(attr_q.entity_id)
    if _qa_allowed is not None:
        _presentable = [o for o in _presentable if o.item_value in _qa_allowed]
    _numbered = "\n".join(
        f"{i + 1}. {o.display_name}" for i, o in enumerate(_presentable)
    )
    return (
        f"The available options for **{_cpq_engine.disambiguated_label(attr_q, attrs)}** "
        f"are:\n\n{_numbered}"
    )


def _build_current_quote_attribute_listing_text(
    session: Any, attrs: list, workspace_id: int, catalog_prefix: str, product_name: str,
) -> str:
    """Answer "list the attributes" when a quote is already in progress
    or complete by reading the REAL filled state, via the exact same
    `build_payload(..., scope_required_and_edited=True)` the JSON-preview
    button already uses — so this list is always exactly the keys that
    JSON preview shows, never a second, driftable approximation of it.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    layout_order = _cpq_engine.load_layout_display_order(workspace_id, catalog_prefix)
    payload = _cpq_engine.build_payload(
        session.filled, session.filled_source, session.filled_multi, attrs,
        display_order=layout_order, product_quantity=session.product_quantity,
        scope_required_and_edited=True,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix,
    )
    config_data = payload.get("configData", {})
    attr_by_vn = {a.variable_name: a for a in attrs}
    seen: set[str] = set()
    labels: list[str] = []
    for vn in config_data:
        attr = attr_by_vn.get(vn)
        label = attr.display_label if attr else vn
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    if not labels:
        return f"Your **{product_name}** quote doesn't have any confirmed attributes yet."
    lines = "\n".join(f"- {label}" for label in labels)
    return (
        f"Here are the attributes currently confirmed in your **{product_name}** "
        f"quote ({len(labels)} items):\n\n{lines}"
    )


def _resolve_split_change_text(
    text: str, attrs: list, filled: dict, filled_multi: dict,
    last_qa_variables: list[str] | None = None,
) -> tuple[Any, str] | None:
    """Resolve one self-contained "change X to Y" fragment from
    _llm_split_multi_attr_change_request to (attr, new_value_hint).
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    text_lower = text.lower()
    preferred = [a for a in attrs if a.variable_name in (last_qa_variables or [])]
    for a in preferred:
        label_l = (a.display_label or "").lower()
        if label_l and label_l in text_lower:
            for opt in sorted(
                a.options, key=lambda o: -len(o.display_name or o.item_value or ""),
            ):
                if (
                    (opt.display_name or "").lower() in text_lower
                    or (opt.item_value or "").lower() in text_lower
                ):
                    return a, opt.item_value
    return _cpq_engine.detect_change_request(text, attrs, filled, filled_multi)
