"""Free-text-to-catalog resolution (Phase 4 step 11 extraction from
``cpq/engine.py`` -- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_normalize_for_hint`, `_catalog_prefix`, and `_HINT_MIN_PHRASE_LEN` are
read off the engine MODULE object (never patched by any test, but kept
consistent with this package's own convention). `_match_family_name`
and `_fetch_product_option_list` go back through the passed-in
`engine` instance.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq import engine as _engine_module


def resolve_product_hint(
    engine: Any, reader: Any, workspace_id: int, hint_text: str,
) -> tuple[str, str] | None:
    """Resolve free-text to (catalog_prefix, canonical_display_name)
    using only real ingested data — no hardcoded product-name list.

    Replaces reliance on _PRODUCT_PATTERNS' fixed regex list, which
    confirmed-live never recognizes products outside its hardcoded set
    (e.g. "DGM 8500e" — a real, ingested product this method resolves
    correctly with zero code changes, since DGM/MOTOTRBO models are
    genuinely present as BmCatalog entities and productSelectionProduct_all
    options inside the Sl3500EConfig ingestion).

    Two passes, in priority order — NOT merged into one combined check:
      1. BmPrdFamily/BmCatalog entity names (_match_family_name), across
         ALL catalogs. This is genuinely catalog-specific data (an
         internal BOM export code), so a unique match here is trusted
         immediately without even looking at pass 2.
      2. Only if pass 1 matched nothing anywhere: each catalog's
         productSelectionProduct_all option list. Confirmed live this
         field is a SHARED master list duplicated near-identically
         across every ingested catalog (not real per-catalog data), so
         it is deliberately the lower-priority, fallback signal — if
         pass 1 had been checked per-catalog and merged with pass 2
         additively instead, a real match in pass 1 (e.g. "DGM 8500e"
         uniquely matching Sl3500EConfig's BmCatalog entity) would get
         incorrectly reported as ambiguous the moment pass 2 also
         matched the same shared list entry in a second, unrelated
         catalog — confirmed live this exact false ambiguity happened
         before this two-pass ordering was added.

    Returns None if neither pass uniquely resolves to exactly one
    catalog — callers must ask rather than guess (D2), same principle
    as _scope_to_catalog's own "ambiguous → don't pick" behavior.
    """
    hint_norm = _engine_module._normalize_for_hint(hint_text)
    if not hint_norm:
        return None

    try:
        all_type_names = reader.distinct_types()
    except AttributeError:
        all_type_names = sorted({
            e.get("type") or "" for e in reader.find_entities(limit=1000)
        })
    prefixes = sorted({
        _engine_module._catalog_prefix(t) for t in all_type_names
        if _engine_module._catalog_prefix(t)
    })
    if not prefixes:
        return None

    family_matches: dict[str, str] = {}
    for prefix in prefixes:
        fname = engine._match_family_name(reader, workspace_id, prefix, hint_norm)
        if fname:
            family_matches[prefix] = fname
    if len(family_matches) == 1:
        prefix, name = next(iter(family_matches.items()))
        return prefix, name
    if family_matches:
        return None  # ambiguous at the trustworthy signal — never fall through

    option_matches: dict[str, str] = {}
    for prefix in prefixes:
        for item_value, display_name in engine._fetch_product_option_list(
            reader, workspace_id, prefix,
        ):
            for text in (item_value, display_name):
                stripped = text.strip()
                is_code = any(c.isdigit() for c in stripped) or "/" in stripped
                if len(stripped.split()) < 2 and not is_code:
                    continue  # same single-word guard as extract_catalog_hints
                norm = _engine_module._normalize_for_hint(text)
                if (
                    min(len(norm), len(hint_norm)) >= _engine_module._HINT_MIN_PHRASE_LEN
                    and (norm in hint_norm or hint_norm in norm)
                ):
                    option_matches[prefix] = display_name or item_value
                    break
            if prefix in option_matches:
                break

    if len(option_matches) == 1:
        prefix, name = next(iter(option_matches.items()))
        return prefix, name
    return None
