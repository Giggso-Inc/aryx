"""Mapping one dense, multi-fact sentence to several still-unresolved
attrs at once, split out of `api/ask_api.py` (Phase 6/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline definition.
"""

from __future__ import annotations

from aryx.api.ask_llm.ask_llm_intent_core import _llm_classify_intent_core


def _llm_extract_multi_attr_hints(
    question: str, candidates: list, workspace_id: int,
) -> dict[str, str]:
    """Amendment 17 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): map a
    single dense, multi-fact sentence to several still-unresolved attrs at
    once, instead of asking for each one individually.

    Live-motivating scenario: "...standard subscription for 25 devices at
    25 locations...package of 'Plus'...new solution type" — Tier-1's
    extract_catalog_hints deliberately leaves this unresolved for two
    separate, correct reasons (see engine.py's own docstring): (1) it
    never guesses when the same value ("25") is valid for two sibling
    attrs (devices vs. locations) — it can't use word ADJACENCY to tell
    them apart, only per-attr option membership; (2) single-word values
    ("Plus", "New") fall below its minimum-trust bar. Both are correct,
    safe defaults for a regex — but leave a human-obvious multi-fact
    sentence to be asked back one attr at a time.

    Scoped to ONLY the candidates the caller already determined are
    plausibly mentioned (via `_relevant_intent_candidates(...,
    fallback_to_full=False)`) — never the full pending list, and the
    caller never invokes this at all when fewer than 2 candidates
    genuinely overlap the question, so this never fires on an ordinary
    short reply.

    Same never-guess discipline as every other Tier-2 fallback here: a
    returned variable_name must be one of the given candidates; a
    returned value must be a real option for THAT SPECIFIC attr (checked
    per-attr, not globally — the same collision `extract_catalog_hints`
    itself refuses to resolve must not be waved through here just because
    an LLM is involved). Only "high" confidence mappings are kept — a
    "low" confidence mapping is dropped silently, leaving that one attr
    pending and asked normally next, exactly as if this function had
    never run for it; this function only ever adds resolved facts, it
    never blocks or re-asks anything the caller was already going to do.

    A candidate with no fixed option list (free-text/numeric, e.g.
    Amendment 12's device-count shape) has its stated value trusted as
    typed — the same trust a normal user-typed reply to that same pending
    question already gets elsewhere in this engine; this catalog's own
    `apply_validation_rules` is the real safety net for those, unchanged.

    Returns {variable_name: item_value} for every validated, high-
    confidence mapping (possibly empty; never raises).
    """
    by_vn = {a.variable_name: a for a in candidates}
    attr_lines = []
    for a in candidates:
        opts = ", ".join(
            f"{o.display_name} (code: {o.item_value})"
            if o.item_value.lower() != o.display_name.lower() else o.display_name
            for o in a.options[:40]
        ) if a.options else "(free text/number — no fixed option list)"
        attr_lines.append(f"- {a.variable_name} — \"{a.display_label}\": {opts}")
    sys = (
        "You extract answers to SEVERAL still-open configuration questions "
        "from one customer sentence that may bundle multiple facts "
        "together (e.g. a quantity, a tier, a plan type, all in one "
        "sentence). For each attribute below, decide whether the sentence "
        "clearly states its value. Use word adjacency to tell apart "
        "attributes that could share the same raw value (e.g. \"25 "
        "devices\" vs \"25 locations\" — the number alone doesn't say "
        "which attribute it answers, the nearby word does). Only map an "
        "attribute when its value is unambiguous; when the same number or "
        "word plausibly applies to more than one attribute here, or the "
        "sentence doesn't mention an attribute at all, leave it out "
        "entirely — do not guess, and never invent a value outside the "
        "options given for that attribute."
    )
    user = (
        "STILL-OPEN ATTRIBUTES:\n" + "\n".join(attr_lines) + "\n\n"
        f"CUSTOMER SENTENCE: {question}\n\n"
        'Reply ONLY as JSON: {"mappings": [{"variable_name": "<exact name '
        'from the list>", "value": "<exact option display name or code, '
        'or the stated number/text for a free-text attribute>", '
        '"confidence": "high"|"low"}, ...]} — omit any attribute you are '
        "not confident about rather than including it with low confidence."
    )

    def _validate(parsed: dict) -> dict[str, str]:
        result: dict[str, str] = {}
        for m in (parsed.get("mappings") or []):
            if not isinstance(m, dict) or m.get("confidence") != "high":
                continue
            attr = by_vn.get(m.get("variable_name"))
            if attr is None:
                continue
            val = str(m.get("value") or "").strip()
            if not val:
                continue
            if attr.options:
                match = next(
                    (o for o in attr.options
                     if o.display_name.lower() == val.lower()
                     or o.item_value.lower() == val.lower()),
                    None,
                )
                if match is None:
                    continue
                result[attr.variable_name] = match.item_value
            else:
                result[attr.variable_name] = val
        return result

    return _llm_classify_intent_core(sys, user, workspace_id, _validate) or {}
