"""LLM-first check for a whole-catalog "list the attributes" style
question, split out of `api/ask_api.py` (Phase 6/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline definition.
"""

from __future__ import annotations

from aryx.api.ask_llm.ask_llm_intent_core import _llm_classify_intent_core


def _llm_detect_catalog_enumeration_query(question: str, workspace_id: int) -> bool:
    """LLM-first check: is this asking to LIST/ENUMERATE a whole category of
    catalog attributes (e.g. "list the attributes in APX Next", "what
    attributes does this catalog have"), as opposed to a question about one
    specific attribute's options/value?

    Live-confirmed gap (2026-08-31): a pre-quote "list the attributes in
    APX Next" question fell through detect_attr_query (which requires
    naming one SPECIFIC attribute) into the generic open-domain graph
    search — which itself turned out to be structurally unable to answer
    this class of question at all (see the analysis this fix is based on):
    _extract_terms/gather's name-substring match for "APX Next" resolves
    to an unrelated Dimension:Updatedby lookup node, not the product/
    catalog itself, so even widening the search's limits could never reach
    the real ~430 ApxnextConfigdataBmConfigAttr entities from that anchor.
    The correct data source for "list the attributes" was already sitting
    in memory the whole time (`attrs`, loaded by load_product_config for
    every QA call) -- this function only decides WHETHER a question wants
    that whole-list treatment; _build_catalog_attribute_listing_text does
    the actual answering, straight from `attrs`, never from the graph.

    Gated behind the same cheap _OPTIONS_KEYWORDS pre-check the sibling
    multi-attribute-options split already uses (ask_api.py, `if any(kw in
    req.question.lower() for kw in _cpq_engine._OPTIONS_KEYWORDS)`) --
    "list" is already a member of that set, so the common single-attribute
    case never pays this extra LLM call; only when a cheap keyword hints
    at listing/options language does the LLM get asked to judge intent.
    """
    sys = (
        "A customer asked a product-configuration assistant a question "
        "about a CPQ catalog. Determine whether the question is asking to "
        "LIST or ENUMERATE a whole CATEGORY of things (e.g. 'list the "
        "attributes', 'what attributes does this have', 'show me all the "
        "options this catalog configures') -- as opposed to asking about "
        "ONE specific, named attribute's value or options (e.g. 'what are "
        "the wireless carrier options'), which is a different, already-"
        "handled case. Only answer true for a genuine whole-category "
        "listing request."
    )
    user = (
        f"MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"is_catalog_enumeration": true|false}'
    )

    def _validate(parsed: dict) -> bool | None:
        return bool(parsed.get("is_catalog_enumeration"))

    result = _llm_classify_intent_core(sys, user, workspace_id, _validate, role="menial")
    return bool(result)
