"""Shared segment-delimiter constant and the narrator-LLM user-prompt
builder for `_cpq_summary_text`, split out of `api/ask_api.py` (Phase 3/
11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md) purely to keep the sibling `ask_cpq_summary_text.py`/`ask_cpq_
summary_narrate.py` under the line cap. Logic unchanged from the
original inline definition.
"""

from __future__ import annotations

from aryx.cpq.engine import SUMMARY_FALLBACK_CATEGORY

# Segments the LLM is asked to separate its reply by — one lead-in
# sentence + one narration segment per category, code-assembled with the
# real "**Category**" headers afterwards. Distinctive enough that real
# narration text won't produce it by accident. Both sibling files import
# this same constant — single source of truth.
_CPQ_SEGMENT_DELIM = "@@@"


def _build_summary_narration_user_prompt(
    groups: list, product_name: str, expected_segments: int,
) -> str:
    """Builds the user prompt `_cpq_summary_text` sends the narrator LLM —
    split out purely to keep `ask_cpq_summary_text.py` under the line cap.
    """
    config_text = "\n\n".join(
        f"{category}:\n"
        + "\n".join(f"- {label}: {value}" for label, value in pairs)
        for category, pairs in groups
    )
    return (
        f"Describe this {product_name or 'product'} configuration for a sales "
        f"rep. Reply with EXACTLY {expected_segments} segments separated by "
        f"the literal token {_CPQ_SEGMENT_DELIM} (nothing else on the "
        f"delimiter's line) — never merge two segments together, never add "
        "or omit a segment, never include this instruction or the token "
        "anywhere except as a separator.\n\n"
        "Segment 1: one direct sentence, e.g. 'Your configuration is complete.'\n"
        + "\n".join(
            (
                f"Segment {i + 2}: the {category} facts below as short markdown "
                "bullets '- **Label** → value', one bullet per fact, using "
                "plain-English labels instead of raw variable names."
                if category != SUMMARY_FALLBACK_CATEGORY
                else (
                    f"Segment {i + 2}: ONE short plain-text line narrating the "
                    f"{category} facts below (not a bulleted list, not "
                    "'label: value' pairs) — you do not need to mention every "
                    "fact in this category; pick whichever subset you can "
                    "state with total accuracy and simply OMIT the rest. Never "
                    "paraphrase, generalise, or invent a placeholder for a "
                    "fact you are dropping (e.g. never write anything like "
                    "'plus the usual defaults') — an omitted fact must be "
                    "invisible, not gestured at."
                )
            )
            for i, (category, _pairs) in enumerate(groups)
        ) + "\n\n"
        "Use ONLY the exact facts below; if you are not certain a name or "
        "value is precisely what you are about to write, leave it out "
        "rather than guess or approximate it.\n\nCONFIGURATION:\n" + config_text
    )
