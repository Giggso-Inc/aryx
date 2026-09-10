"""Narrowing a multi-catalog workspace to one catalog (Phase 4 step 11
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_scope_to_catalog` is the guard against hybrid, cross-catalog configs:
given every ingested attr type and a product hint, it returns only the
types belonging to the one catalog the hint resolves to -- falling back
to ALL types unscoped rather than ever returning zero attrs.

`_catalog_prefix`, `_HINT_MIN_PHRASE_LEN` and `logger` are read off the
engine MODULE object so the original bare-global references -- and any
patch of them -- resolve at call time; `_match_family_name`,
`_batch_fetch` and `ingested_product_alias_map` go back through the
passed-in `engine` instance.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.cpq import engine as _engine_module


def _scope_to_catalog(
    engine: Any, reader: Any, workspace_id: int,
    attr_types: list[str], product_hint: str,
) -> tuple[list[str], str]:
    """Restrict attr_types to the single catalog the requested product belongs to.

    A workspace can hold more than one ingested XML source at once (e.g. an
    APX Next export and an SL3500e export side by side) — without this,
    every product request pulls attributes/rules from ALL of them, producing
    a hybrid config that mixes incompatible product lines (confirmed live:
    asking for "APX Next" returned attrs from both '_astro' and '_apcr'
    catalogs simultaneously).

    Resolution: group attr_types by their source-derived _catalog_prefix,
    look up each prefix's BmPrdFamily/BmCatalog entity name (via
    _match_family_name), and match product_hint against those names.
    Falls back to returning ALL types unscoped (the pre-fix behavior)
    whenever there's only one catalog to begin with, or the hint can't
    be uniquely matched to one — this must never silently return zero
    attrs for an unresolved hint.

    Returns (scoped_attr_types, resolved_catalog_prefix) — the prefix is
    "" when scoping did not narrow to exactly one catalog, and callers
    (rule loaders) must treat that the same as "no catalog filter".
    """
    prefixes = {_engine_module._catalog_prefix(t) for t in attr_types}
    if "" in prefixes:
        # "" means _catalog_prefix found no PascalCase marker — either a
        # genuinely unprefixed catalog (confirmed live: CommandCentral
        # Aware, ingested via the generic doc_discovery pipeline, emits
        # bare 'BmConfigAttr'/'BmPrdFamily' with no distinguishing
        # prefix at all) or unrecognized noise. Keep "" as a real,
        # matchable catalog only when it resolves to an actual
        # BmPrdFamily/BmCatalog entity; otherwise it's noise and must
        # still be discarded, never treated as a valid scope.
        has_real_family = bool(
            reader.find_entities(ontology_type="BmPrdFamily", limit=1)
            or reader.find_entities(ontology_type="BmCatalog", limit=1)
        )
        if not has_real_family:
            prefixes.discard("")
    if len(prefixes) <= 1:
        return attr_types, (next(iter(prefixes)) if prefixes else "")

    hint_norm = re.sub(r"[^a-z0-9]", "", (product_hint or "").lower())
    if not hint_norm:
        return attr_types, ""

    matched_prefixes = {
        prefix for prefix in prefixes
        if engine._match_family_name(reader, workspace_id, prefix, hint_norm)
    }

    if len(matched_prefixes) == 1:
        chosen = next(iter(matched_prefixes))
        scoped = [
            t for t in attr_types if _engine_module._catalog_prefix(t) == chosen
        ]
        if scoped:
            return scoped, chosen

    # Family-name matching failed (or was ambiguous) — customers name the
    # real product/model ("SVX Video Remote Speaker Microphone"), not the
    # internal BOM export codename ("videoSolutions_BOM"), which never
    # substring-matches. productSelectionProduct_all's option list (the
    # OTHER fallback used elsewhere) doesn't help either — it's a flat,
    # identical-across-every-catalog portfolio list, not catalog-scoped
    # data. ingested_product_alias_map's bm_catalog TREE names ARE
    # catalog-scoped (confirmed live: "SVX Video Remote Speaker
    # Microphone"/"vX650_BOM" only exist in the SVX export) — reuse that
    # same signal detect_product_mention already relies on successfully,
    # instead of re-deriving a weaker one here (confirmed live this was
    # the actual reason catalog_prefix resolution — and everything
    # downstream that depends on it, e.g. resolve_always_ask_skips —
    # behaved inconsistently for SVX).
    if not matched_prefixes:
        alias_map = engine.ingested_product_alias_map(reader, workspace_id)
        ordered = sorted(
            ((name, re.sub(r"[^a-z0-9]", "", name.lower())) for name in alias_map),
            key=lambda t: len(t[1]), reverse=True,
        )
        matched_family: str | None = None
        for name, name_norm in ordered:
            if name_norm and min(len(name_norm), len(hint_norm)) \
                    >= _engine_module._HINT_MIN_PHRASE_LEN \
                    and name_norm in hint_norm:
                matched_family = alias_map[name]
                break
        if matched_family:
            # matched_family is the owning FAMILY name (e.g.
            # "videoSolutions_BOM") — resolve it back to a prefix by
            # exact equality against each candidate's own BmPrdFamily
            # entity name, not another substring search.
            for prefix in prefixes:
                fam_ents = reader.find_entities(
                    ontology_type=f"{prefix}BmPrdFamily", limit=5)
                fam_pg = engine._batch_fetch(
                    [e["id"] for e in fam_ents], workspace_id)
                fname = next(
                    (str(fam_pg.get(e["id"], {}).get("name") or e.get("name") or "").strip()
                     for e in fam_ents), "")
                if fname == matched_family:
                    scoped = [
                        t for t in attr_types
                        if _engine_module._catalog_prefix(t) == prefix
                    ]
                    if scoped:
                        return scoped, prefix

    _engine_module.logger.warning(
        "cpq: could not uniquely scope product_hint=%r to one catalog among "
        "prefixes=%s — loading ALL catalogs (cross-catalog mixing risk)",
        product_hint, sorted(prefixes),
    )
    return attr_types, ""
