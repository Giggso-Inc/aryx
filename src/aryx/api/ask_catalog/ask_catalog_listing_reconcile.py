"""Reconciling the LLM's proposed heading groups against the real,
de-duplicated label set for a "list the attributes" answer, split out of
`_build_catalog_attribute_listing_text` (Phase 3/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to
keep the sibling `ask_catalog_listing_text.py` under the line cap. Logic
unchanged from the original inline definitions.
"""

from __future__ import annotations

from typing import Any


def _normalize(s: str) -> str:
    return " ".join(s.split()).casefold()


def _reconcile_catalog_listing_groups(
    groups: Any, labels: list[str],
) -> list[tuple[str, list[str]]]:
    """Matches each LLM-proposed group's items against the real label set
    on a normalized key (collapsed whitespace, casefolded) -- Raven Review
    finding (2026-08-31): an exact byte-for-byte match fails on trivial
    LLM formatting drift (extra whitespace, different casing) even when
    the item is genuinely the real label, degrading grouping quality
    (dropped into "Other") without any actual data loss. The CANONICAL
    real label text is always what gets displayed -- the LLM's own
    casing/spacing is never trusted for output, only for lookup.

    Any real label the LLM's grouping never placed anywhere (dropped,
    over-written, or a parse/call failure upstream leaving `groups`
    empty) is appended under a final "Other" heading -- merged into an
    LLM-produced "Other" section if one already exists, rather than
    rendering two separate "Other" headings (also a 2026-08-31 Raven
    Review finding) -- so no real attribute is ever silently lost.
    """
    label_by_norm = {_normalize(label): label for label in labels}

    used: set[str] = set()
    rendered: list[tuple[str, list[str]]] = []
    for g in groups if isinstance(groups, list) else []:
        if not isinstance(g, dict):
            continue
        heading = str(g.get("heading") or "Other").strip() or "Other"
        items: list[str] = []
        for item in (g.get("items") or []):
            if not isinstance(item, str):
                continue
            canonical = label_by_norm.get(_normalize(item))
            if canonical is None or canonical in used:
                continue
            items.append(canonical)
        if not items:
            continue
        used.update(items)
        rendered.append((heading, items))

    leftover = [label for label in labels if label not in used]
    if leftover:
        for i, (heading, items) in enumerate(rendered):
            if heading.casefold() == "other":
                rendered[i] = (heading, items + leftover)
                break
        else:
            rendered.append(("Other", leftover))
    return rendered
