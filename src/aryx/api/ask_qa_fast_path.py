"""Fast-path attribute-options answer and whole-catalog-enumeration
answer, split out of `_handle_cpq_qa` (Phase 8/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to
keep the sibling `ask_handle_cpq_qa.py` under the line cap. Logic
unchanged from the original inline if/elif block. `_cpq_engine` and
several not-yet-split ask_api.py names are read through the ask_api
MODULE object (not imported by name) since ask_api tests patch several
of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_text_helpers import _build_attr_options_text
from aryx.api import ask_attr_text_helpers as _ask_attr_text_helpers_module
from aryx.api import ask_catalog_listing_text as _ask_catalog_listing_text_module
from aryx.api.ask_llm import ask_llm_catalog_enumeration as _ask_llm_catalog_enumeration_module


def _qa_fast_path_or_enumeration(
    req: "Any", session: Any, attrs: list, product_hint: str,
) -> "tuple[str, tuple[int, int, int, int, int, int]] | None":
    """Returns (qa_answer, (p_in, p_out, p_ms, s_in, s_out, s_ms)) when
    either the fast single-attribute-options path or the whole-catalog-
    enumeration path answered the question; None when neither applies,
    in which case the caller falls through to the generic graph search.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    # Fast path: question asks about a specific attribute's available
    # options. Uses attr.options already in memory from BmMenuItem — no
    # graph query, no LLM synthesis, no schema leakage possible.
    _attr_q = _cpq_engine.detect_attr_query(req.question, attrs)
    qa_answer = (
        _build_attr_options_text(req, session, attrs, _attr_q)
        if _attr_q else None
    )
    if qa_answer:
        # docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §8: remember
        # what the customer just asked about so a follow-up bare-value reply
        # ("make it ATT/FirstNet") can be preferred toward THIS attribute
        # even when a sibling attribute genuinely shares the same option value.
        session.last_qa_variables = [_attr_q.variable_name]
        return qa_answer, (0, 0, 0, 0, 0, 0)

    if not (
        attrs
        and any(kw in req.question.lower() for kw in _cpq_engine._OPTIONS_KEYWORDS)
        and _ask_llm_catalog_enumeration_module._llm_detect_catalog_enumeration_query(req.question, req.workspace_id)
    ):
        return None

    # 2026-08-31 fix: "list the attributes in APX Next" style whole-
    # catalog enumeration requests. detect_attr_query above requires
    # naming ONE specific attribute, so it never matches here -- this
    # used to fall straight into the generic graph-search fallback,
    # which is structurally unable to answer it (the name-match "APX
    # Next" resolves to an unrelated dimension/lookup node, never
    # reaching the real ~430 attribute entities regardless of how wide
    # its search limits are set -- confirmed live against the actual
    # FalkorDB graph). Answered instead straight from `attrs` -- the
    # real, complete ConfigAttr list already loaded above for this
    # exact request -- with the LLM used only to phrase/group the
    # answer, never to recall or infer which attributes exist.
    _catalog_prefix = attrs[0].catalog_prefix or ""
    # Human-readable name for the customer-facing text -- catalog_prefix
    # is an internal ingestion identifier, never something to show a
    # customer. Prefer session.product_name (set once a real quote is
    # in progress/complete) then product_hint (the read-only product-
    # mention resolve from _route_qa), falling back to catalog_prefix
    # only when neither is available.
    _catalog_label = session.product_name or product_hint or _catalog_prefix or "this catalog"
    if session.filled:
        # A quote is already in progress/complete -- the real filled
        # state IS the one real path, so answer from it directly (see
        # _build_current_quote_attribute_listing_text's own docstring)
        # instead of the pre-quote, path-agnostic catalog-wide
        # approximation below.
        qa_answer = _ask_attr_text_helpers_module._build_current_quote_attribute_listing_text(
            session, attrs, req.workspace_id, _catalog_prefix, _catalog_label,
        )
    else:
        qa_answer = _ask_catalog_listing_text_module._build_catalog_attribute_listing_text(
            attrs, _catalog_label, req.workspace_id, _catalog_prefix,
        )
    session.last_qa_variables = []
    return qa_answer, (0, 0, 0, 0, 0, 0)
