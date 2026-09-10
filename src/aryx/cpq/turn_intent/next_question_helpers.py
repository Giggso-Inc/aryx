"""Helpers for ``next_question.next_question_prompt``, split off purely
to keep both files under the file-size cap (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). No logic changed --
each function is the exact original inline block, just given a name.
"""

from __future__ import annotations

from aryx.cpq.state import ConfigAttr


def narrow_constrained_item_values(
    attr: ConfigAttr, constrained_item_values: list[str] | None,
) -> list[str] | None:
    """A constraint is a source of truth for VALIDITY, not catalog
    spelling. If it names a legal value with no literal item_value
    match in the real catalog (live-confirmed: productSelectionProduct
    _all's constraint returns 'APX NEXT XE 4G LTE PLUS 5G', which no
    real option equals), discarding the WHOLE constrained set back to
    unconstrained (first attempt at this fix) throws away the
    legitimate, real-matching values too -- live-confirmed regression:
    Product went from a flip-flopping 1-2 option menu to showing all
    325 raw options. Drop only the phantom entries instead, same as
    auto_fill's valid_opts computation -- keep whichever real values
    the constraint did correctly narrow to. Falls back to fully
    unconstrained only if EVERY value was phantom.
    """
    if constrained_item_values is None:
        return None
    real_item_values = {o.item_value for o in attr.options}
    narrowed = set(constrained_item_values) & real_item_values
    return sorted(narrowed) if narrowed else None


def oversized_options_prompt(ctx_prefix: str, label: str, effective_opts: list) -> str:
    """An unconstrained master list (confirmed live: the product
    selector carries the full ~325-model portfolio in every
    catalog, and the country attr ~250 entries) is unusable as
    a numbered menu -- ask for the exact name instead of
    dumping it. Threshold-based and generic: applies to ANY
    oversized attr, no attribute-specific hardcoding. The
    typed reply flows through apply_answer's existing
    exact/display/word-boundary matching unchanged, and the
    explicit "what are the options for X" Q&A path still
    enumerates in full for clients who really want the list.
    "Please provide" (not "type") -- the batched-mode e2e test
    counts question blocks by the "choose one"/"Please provide"
    phrases, and this prompt must stay countable as one block.
    """
    examples = ", ".join(f"*{o.display_name}*" for o in effective_opts[:3])
    return (
        f"{ctx_prefix}**{label}** has "
        f"{len(effective_opts)} available options — too many to "
        f"list here. Please provide the exact name "
        f"(e.g. {examples}), or ask *\"what are the options for "
        f"{label}\"* to see the full list."
    )
