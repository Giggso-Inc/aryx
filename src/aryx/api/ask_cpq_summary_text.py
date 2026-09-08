"""Structured, headed/bulleted configuration-summary narration, split out
of `api/ask_api.py` (Phase 3/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original
inline definition; the LLM-call/parsing/fallback chain lives in the
sibling `ask_cpq_summary_narrate.py` purely to keep this file under the
line cap. `_cpq_engine` is read through the ask_api MODULE object (not
imported by name) since at least one test replaces the whole singleton
via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from aryx.api.ask_cpq_summary_narrate import _narrate_cpq_summary
from aryx.api.ask_cpq_summary_prompt import _build_summary_narration_user_prompt
from aryx.cpq.state import ConfigAttr


def _cpq_summary_text(
    display_filled: dict[str, str],
    attrs: list[ConfigAttr],
    rule_governed_ids: set[int],
    product_name: str,
    workspace_id: int,
    sources: dict[str, str] | None = None,
    product_quantity: int | None = None,
    filled: dict[str, str] | None = None,
) -> str:
    """Structured, headed/bulleted summary of the filtered configuration.

    filled — optional (default `None`, preserving today's behavior byte-
    for-byte). The raw (non-display) filled dict, used ONLY to compute
    Tier C (`_cpq_engine.mandatory_tier_c_vns`) so the summary's item list
    equals exactly the Mandatory User Input set (docs/CPQ_Beautify_
    Mandatory_Section_Miscategorization_2026_08_19.md) instead of the
    prior, separately-maintained "rule-governed and actively-sourced"
    narrowing. Omitted entirely, this falls back to Tier A/B only.

    Post-generation, summary_guard diffs field-by-field against session
    display state; mismatch regenerates once, then falls back to the raw
    state table (never a hallucinated summary).

    The engine's `categorized_summary_groups` owns ALL filtering (booleans,
    secondary/warranty/product attrs, year durations, rule-governed set,
    "(none)" placeholders) AND the same category grouping (Product Name /
    Service Plan / Quantity & Duration / Associated Options, or however
    many are actually present) the deterministic fallback
    (`render_filled_summary`) uses.

    The "**Category:**" headers are assembled here in CODE, never left to
    the LLM to reproduce verbatim — asking a model to keep exact header
    text on its own line is a request, not a guarantee (confirmed live: it
    silently folded headers into running prose instead of respecting the
    line breaks). The model is only asked for each category's CONTENT — its
    real bulleted/plain-text shape (bullets for every category except
    Associated Options, one plain-text line for that one) — as one segment
    per category separated by a fixed delimiter it cannot plausibly emit as
    part of real prose, so the structure is deterministic while the wording
    stays LLM-narrated. Associated Options is explicitly told to OMIT any
    fact it isn't sure of rather than gesture at it with a vague placeholder
    (e.g. never "plus the usual defaults") — confirmed live to hallucinate
    otherwise. If the reply doesn't split into exactly the expected number
    of segments, or the LLM call fails/returns empty, this falls back to
    `render_filled_summary` — the CPQ flow must never block on, or silently
    mis-format via, the narrator.
    """
    from aryx.api import ask_api as _ask_api_module
    def _finish(text: str) -> str:
        # Live-verified gap, 2026-08-13: this used to unconditionally
        # append "**Quantity:** N" AFTER the whole summary regardless of
        # catalog shape, which always put it last (after Service Plan,
        # Quantity & Duration, Associated Options). Product Quantity is now
        # injected directly into the Product Name category by
        # `categorized_summary_groups`/`render_filled_summary` themselves,
        # so both the LLM-narrated path (`draft`) and the deterministic
        # bullet fallback (`second`) already carry it in the right place
        # by the time they reach a return statement — this helper is only
        # still needed for the LAST-resort `raw_state_table` fallback
        # below, which has no category concept at all (a flat, alphabetized
        # state table) and so still needs the old trailing-append behavior
        # rather than silently dropping the fact.
        if product_quantity is None or not text:
            return text
        return f"{text}\n\n**Quantity:** {product_quantity}"

    _catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    _cpq_engine = _ask_api_module._cpq_engine
    display_order = _cpq_engine.load_layout_display_order(workspace_id, _catalog_prefix)
    _required_vns = _cpq_engine.mandatory_tier_c_vns(filled, workspace_id, _catalog_prefix)
    groups = _cpq_engine.categorized_summary_groups(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources,
        display_order=display_order, product_quantity=product_quantity,
        required_vns=_required_vns)
    if not groups:
        return _finish("")
    # The narrator and its bullet fallback are only ever asked to cover
    # THESE curated (label, value) facts — never the raw display_filled
    # dict, which includes hundreds of internal/technical BM fields
    # (Record Separator, BoolContinue1-4, HTML Update1-3, etc.) neither
    # synthesis path is designed to mention. Validating against raw
    # display_filled instead of this set made the check structurally
    # unsatisfiable for any product with many such fields — a correct
    # summary that (rightly) omits them got discarded every time,
    # falling all the way to raw_state_table(). Live-confirmed against
    # aSTRO25_bom / APX NEXT Single Band (~173 auto-filled fields).
    # Only the STRICT categories (Product Name, Service Plan, Quantity &
    # Duration) are required to be fully covered. The fallback category
    # (Associated Options) is deliberately excluded here — the prompt
    # below explicitly tells the model it may OMIT facts in that one
    # category ("pick whichever subset you can state with total accuracy
    # and simply OMIT the rest"), so requiring every one of its facts to
    # appear contradicts the very permission the prompt grants, and
    # discarded a correct, intentionally-partial narration every time
    # (live-confirmed: aSTRO25_bom / APX NEXT Single Band's Associated
    # Options narration was rejected for omitting Primary Frequency,
    # Keypad Type, Display Type, Knob Type, System Key — all deliberately
    # dropped by design, not missing by error).
    sys = (
        "You summarise product configurations for sales reps in plain, "
        "everyday English — never technical or internal terminology."
    )
    expected_segments = 1 + len(groups)
    user = _build_summary_narration_user_prompt(groups, product_name, expected_segments)
    return _narrate_cpq_summary(
        sys, user, expected_segments, groups, workspace_id,
        display_filled, attrs, rule_governed_ids, sources, product_quantity,
        _required_vns, _finish,
    )
