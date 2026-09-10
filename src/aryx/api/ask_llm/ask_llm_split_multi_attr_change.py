"""LLM-first check for a compound multi-attribute change request, split
out of `api/ask_api.py` (Phase 6/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline definition.
"""

from __future__ import annotations

from aryx.api.ask_llm.ask_llm_intent_core import _llm_classify_intent_core
from aryx.api.ask_catalog.ask_relevant_intent_candidates import _relevant_intent_candidates


def _llm_split_multi_attr_change_request(
    question: str, attrs: list, workspace_id: int,
    last_qa_variables: list[str] | None = None,
) -> list[str] | None:
    """LLM-first check: does this message set 2+ genuinely DIFFERENT
    attributes' values at once (docs/config_consistency_issues_2026-07-30.md
    Issue 12)?

    Mirrors _llm_split_multi_attr_options_query's already-working pattern,
    but for changes rather than options-questions. classify_intent's
    GatewayIntentResult schema has exactly ONE variable_name/value_ref
    slot — it structurally cannot represent two separate target+value
    pairs, so a genuine two-change compound ("Add Frequency Bands as VHF
    and Wireless Carrier as ATT/FirstNet") always collapsed to that
    gateway's own "ambiguous" category (or an inconsistent single-target
    guess), regardless of how well-formed the message was.
    _llm_split_compound_change_and_question already splits a CHANGE +
    QUESTION compound; this covers the CHANGE + CHANGE case its own
    docstring assumed (incorrectly — confirmed live) was "already handled
    by CHANGE_REQUESTS_MULTI": that category only ever corroborates a
    single already-resolved variable_name, it never applies a second one.

    last_qa_variables — the attributes the customer's immediately
    preceding turn discussed (e.g. a compound options query just listed
    both). Passed as context so the LLM recognizes "Add Frequency Bands
    as VHF and Wireless Carrier as ATT/FirstNet" as directly continuing
    that same topic, not a fresh, unrelated request — the same
    conversational-recency signal build_candidate_bundles/_mutating_agrees
    already use elsewhere, applied here to help produce a correct split
    in the first place rather than only correcting a result after the
    fact.

    Each returned string is a self-contained "change X to Y" style
    request, resolved the same way the sibling change+question splitter's
    own change_text already is (`detect_change_request`) — no new
    resolution machinery, this only adds the missing split step. Returns
    None when fewer than 2 real candidates overlap, or when the LLM's own
    judgment says this isn't genuinely a multi-attribute change — caller
    falls through to the existing single-target gateway path unchanged.
    """
    candidates = _relevant_intent_candidates(question, attrs, fallback_to_full=False)
    if len(candidates) < 2:
        return None
    catalog_lines = "\n".join(
        f"- \"{a.display_label}\" (variable_name={a.variable_name})"
        for a in candidates
    )
    recency_line = ""
    if last_qa_variables:
        _recent_labels = [
            a.display_label for a in attrs if a.variable_name in last_qa_variables
        ]
        if _recent_labels:
            recency_line = (
                "\nThe customer's immediately preceding message already "
                "discussed: " + ", ".join(_recent_labels) + " — a follow-up "
                "naming these same attributes with values is very likely "
                "setting both of them, not a fresh ambiguous request.\n"
            )
    sys = (
        "A customer sent a message to a product-configuration assistant "
        "trying to SET the value of one or more attributes. Determine "
        "whether the message sets TWO OR MORE genuinely DIFFERENT "
        "attributes from the CANDIDATE list below in one message — not a "
        "single attribute change, and not a change combined with a "
        "separate question (that is handled elsewhere). If it sets 2+ "
        "different attributes, split it into that many self-contained "
        "change requests, each phrased as \"change <attribute> to "
        "<value>\" using the customer's own words for the attribute and "
        "value. Never invent an attribute or value that isn't named in "
        "the message."
    )
    user = (
        f"CANDIDATE ATTRIBUTES:\n{catalog_lines}\n"
        f"{recency_line}\n"
        f"MESSAGE: {question}\n\n"
        'Reply ONLY as JSON: {"is_multi_change": true|false, '
        '"changes": ["<change request 1>", "<change request 2>", ...]}'
    )

    def _validate(parsed: dict) -> list[str] | None:
        if not parsed.get("is_multi_change"):
            return None
        raw_cs = parsed.get("changes") or []
        cs = [c.strip() for c in raw_cs if isinstance(c, str) and c.strip()]
        return cs if len(cs) >= 2 else None

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)
