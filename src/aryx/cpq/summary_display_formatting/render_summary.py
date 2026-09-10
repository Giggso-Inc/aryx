"""The deterministic, no-LLM categorized summary renderer (Phase 4 step
10 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Pure presentation over `categorized_summary_groups`: it owns only the
heading text and the per-category bullet-vs-one-line choice, never any
filtering or classification of its own.

`categorized_summary_groups` is reached back through the passed-in
`engine` instance, and `_SUMMARY_FALLBACK_CATEGORY` off the engine
MODULE object, so the original ``self.<name>`` / bare-global lookups
(and any patch of them) resolve at call time exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aryx.cpq import engine as _engine_module

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def render_filled_summary(
    engine: Any,
    display_filled: dict[str, str],
    attrs: list["ConfigAttr"] | None = None,
    rule_governed_ids: set[int] | None = None,
    sources: dict[str, str] | None = None,
    product_quantity: int | None = None,
    required_vns: frozenset[str] | None = None,
) -> str:
    """Deterministic, categorized summary of what has been auto-filled.

    Groups `filled_summary_pairs()` (which owns ALL the filtering) under
    scannable headed sections — Product Name, Service Plan, Quantity &
    Duration, plus either Mandatory User Input (narrowed scope,
    rule_governed_ids supplied) or Associated Options (full-detail-dump
    scope, rule_governed_ids=None) — instead of one flat bullet list,
    classified purely by variable_name fragment (`_summary_category`,
    generic across any ingested catalog, never a per-catalog literal).
    Used directly as the fallback whenever the LLM-narrated paragraph
    (ask_api `_cpq_summary_text`) is unavailable or fails.

    Live-confirmed gap (2026-08-19): in the narrowed scope, every item
    `categorized_summary_groups` buckets outside the first 3 categories
    is now, by construction, part of `_is_mandatory_input_attr`'s Tier
    A/B/C set (PR #222) — the OLD catch-all's "one vague, intention-
    ally-partial line" treatment (still used for the full-detail-dump
    scope's genuine, potentially 20-50+ item Associated Options
    catch-all) is wrong for that guaranteed-mandatory, always-small
    set, so Mandatory User Input is rendered as full bullets instead,
    just like every other real category.

    product_quantity — forwarded to `categorized_summary_groups` so
    this deterministic fallback shows the same Product Quantity fact,
    in the same position, as the LLM-narrated path.

    required_vns — optional (default `None`); forwarded to
    `categorized_summary_groups`/`_filled_summary_triples` for Tier C
    (see `mandatory_tier_c_vns`).
    """
    groups = engine.categorized_summary_groups(
        display_filled, attrs, rule_governed_ids, sources,
        product_quantity=product_quantity, required_vns=required_vns)
    if not groups:
        return ""
    heading = "**Configured so far:**" if rule_governed_ids is None else "**Key decisions:**"
    lines = [heading]
    for category, group in groups:
        lines.append(f"\n**{category}:**")
        if category == _engine_module._SUMMARY_FALLBACK_CATEGORY:
            # Only the full-detail-dump scope (rule_governed_ids=None)
            # can still reach this — the narrowed scope renames this
            # bucket to Mandatory User Input (see
            # `categorized_summary_groups`) before it ever gets here.
            # This category is a catch-all for everything not
            # classified into the other 3 (confirmed live: 20-50+
            # items on a real quote) — a bullet per item is no longer
            # scannable at that volume, unlike Product Name/Service
            # Plan/Quantity & Duration which stay small. Render as one
            # short, deterministic plain-text line instead — no LLM
            # call, so this path never depends on the narrator being
            # reachable (see this method's own docstring constraint).
            lines.append("; ".join(f"{label}: {value}" for label, value in group) + ".")
        else:
            # Mandatory User Input (like every other category) always
            # gets a full bullet per fact — live-confirmed gap,
            # 2026-08-19: the old catch-all's "one vague, intention-
            # ally-partial line" treatment silently narrated or
            # dropped genuinely mandatory fields (Software Release,
            # Ultimate Destination Country, ...) instead of listing
            # them.
            lines.extend(f"- **{label}** → {value}" for label, value in group)
    return "\n".join(lines)
