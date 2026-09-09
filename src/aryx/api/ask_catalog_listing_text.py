"""Answering a "list the attributes" style question straight from the
real, already-loaded catalog, split out of `api/ask_api.py` (Phase 3/11-
phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md). Logic unchanged from the original inline definition; the
in-scope-label computation and the LLM-groups reconciliation live in the
sibling `ask_catalog_listing_scope.py`/`ask_catalog_listing_reconcile.py`
purely to keep this file under the line cap. `_llm_classify_intent_core`
is read through the ask_api MODULE object (not imported by name) since
ask_api tests patch several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_llm.ask_llm_intent_core import _llm_classify_intent_core
from aryx.api.ask_catalog_listing_reconcile import _reconcile_catalog_listing_groups
from aryx.api.ask_catalog_listing_scope import _scope_catalog_listing_labels


def _build_catalog_attribute_listing_text(
    attrs: list, product_name: str, workspace_id: int, catalog_prefix: str = "",
) -> str:
    """Answer a "list the attributes" style question straight from the
    real, already-loaded `ConfigAttr` list -- never the graph. The LLM is
    used only to PHRASE the answer (choose groupings/headings); the final
    bullet text is rendered by THIS function from the real label strings,
    never from the LLM's own prose.

    Hallucination guard (2026-08-31, live-confirmed): the original
    implementation let the LLM free-write the entire answer as prose. At
    catalog scale (~400+ items) it invented plausible-sounding filler
    attributes -- "Boolean Continue 1", "Session Variable TER", "Package
    Invoked Flag" -- that do NOT exist anywhere in the real ingested
    catalog (confirmed directly against Postgres: no `bm_config_attr` row
    with any of those names in this workspace). The "never invent" prompt
    instruction alone did not prevent this. So the LLM is now asked for a
    structured JSON *grouping* (which real items go under which heading)
    instead of free prose, and every item it returns is checked for an
    EXACT match against the real label set before being shown -- anything
    that doesn't match (invented, paraphrased, merged, renamed) is
    silently dropped.

    "List the attributes" means "what will actually end up in the
    submitted JSON/BOM payload" -- live-confirmed 2026-08-31 (twice) this
    is a much narrower question than "every attribute this catalog's
    static field data doesn't structurally forbid": a real submitted
    payload for one actual quote had only 7 keys, while filtering the
    full ~430-attr catalog by `hide_in_trans`/`set_type`/noise-var alone
    still leaves ~200 -- because those static checks only decide what's
    excluded from an attr that's ALREADY been asked and filled; they say
    nothing about which attrs actually get asked at all. Which attrs get
    asked is path-dependent (it depends on choices not yet made) with
    ONE exception the scope helper (`ask_catalog_listing_scope.py`) leans
    on: the real native-UI layout export (`CpqEngine.
    load_layout_display_order`, config_layouts/*.txt) is BigMachines' own
    curated "what the real screen actually shows" set -- the same source
    `build_payload`'s own `display_order` param already uses for exactly
    this "real UI visible set" purpose.

    One more QA-listing-specific filter applies (not part of
    build_payload, which has no concept of a "display label" at all): a
    `display_label` that still LOOKS like a raw variable_name -- no
    spaces, starts lowercase, has an internal capital, i.e. camelCase's
    own shape -- is dropped. Live-confirmed several real attrs (e.g.
    `sessionVariable_TER`, `packageInvokedFlag`, and `commerceAttrsFlag`
    -- the last one's real variable_name is `commerceAttrsFlag_all`, so
    an exact label==variable_name check alone missed it) simply never
    got a human-readable label from the source XML. Showing that raw
    name to a customer is worse than omitting the item; the earlier fix
    tried having the LLM prettify it into readable English instead
    ("Session Variable TER"), but that's exactly the kind of invented
    wording the hallucination guard above now (correctly) blocks -- so
    these are left out entirely. A genuine short label/acronym
    (`CCAWARE`, `VX650`) starts uppercase and is kept.
    """
    labels = _scope_catalog_listing_labels(attrs, workspace_id, catalog_prefix)
    catalog_lines = "\n".join(f"- {label}" for label in labels)
    sys = (
        "You are Aryx, a product-configuration assistant. A customer asked "
        "you to list the attributes/options a CPQ catalog configures. You "
        "are given the REAL, COMPLETE list below. Organize it into groups "
        "under short, plain-language headings (e.g. by shared naming "
        "pattern) -- put anything that doesn't fit an obvious group under "
        "a generic 'Other' heading, do not force a bad grouping. "
        "CRITICAL: every item you place under a heading must be copied "
        "EXACTLY, character-for-character, from the given list -- never "
        "invent, paraphrase, abbreviate, merge, rename, or summarize an "
        "item; every item you return is checked against the real list and "
        "anything that doesn't match exactly is discarded."
    )
    user = (
        f"CATALOG: {product_name}\n\n"
        f"REAL, COMPLETE ATTRIBUTE LIST ({len(labels)} items):\n{catalog_lines}\n\n"
        'Reply ONLY as JSON: {"groups": [{"heading": "...", "items": ["...", ...]}, ...]}'
    )

    def _validate(parsed: dict) -> list[Any] | None:
        groups = parsed.get("groups")
        return groups if isinstance(groups, list) else None

    groups = _llm_classify_intent_core(
        sys, user, workspace_id, _validate,
    ) or []
    rendered = _reconcile_catalog_listing_groups(groups, labels)

    lines: list[str] = []
    for heading, items in rendered:
        lines.append(f"**{heading}**")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    return "\n".join(lines).strip()
