"""Script-derived "flag" hints for option-less attrs (Phase 4 step 11
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_build_flag_keyword_index` scans every BML script for literal
comparisons against option-less fields (the customerType class) and
`extract_flag_hints` matches that index against the question. Kept in
one module because the index's safety guards are the whole contract of
the hint lookup on top of it.

`get_cpq_rdb`, `extract_literal_comparisons`, the normalizers and
`_FLAG_KEYWORD_INDEX_CACHE` are reached off the engine MODULE object --
`get_cpq_rdb` in particular is patched as
``aryx.cpq.engine.get_cpq_rdb`` by many tests, so importing it by value
here would silently break those patches.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aryx.cpq import engine as _engine_module

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def _build_flag_keyword_index(
    engine: Any, attrs: list["ConfigAttr"], workspace_id: int, catalog_prefix: str,
) -> dict[str, tuple[str, str]]:
    """{normalized_keyword: (variable_name, literal_value)} for
    option-less attrs whose value a real BML script actually checks.

    Confirmed live this closes a real gap extract_catalog_hints cannot:
    attrs like customerType have no menu options at all, so there is no
    curated option text to match a phrase like "federal customer"
    against — yet a real hiding rule's script literally checks
    customerType=="FEDERAL". The keyword itself is read directly off
    the script's own comparison (via extract_literal_comparisons), not
    derived from the attribute's name — customerType's own name
    ("customer", "type") contains nothing resembling "federal", so
    camelCase-splitting the attribute name would find nothing useful
    here; the useful signal only exists in the script body.

    Never guesses (D2), two ways:
      - A candidate value is dropped if 2+ different option-less
        fields' scripts compare against the same normalized text —
        same "ambiguous → don't guess" principle as extract_catalog_hints.
      - A candidate value is ALSO dropped if it collides with any real,
        curated menu option's text anywhere in the catalog (confirmed
        live: "FEDERAL" is itself a real option on
        systemEnhancementFeatureType_astro, plus a substring of several
        others) — this fuzzy, script-derived mechanism must never
        disagree with extract_catalog_hints about which attribute a
        word belongs to.

    Cached per (workspace_id, catalog_prefix) — this depends only on
    the catalog's own static rules/attrs, not on conversation state, so
    it is built once per catalog per process lifetime rather than
    re-scanning every script on every turn.
    """
    cache_key = (workspace_id, catalog_prefix)
    cached = _engine_module._FLAG_KEYWORD_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    by_vn = {a.variable_name: a for a in attrs}
    option_less = {
        vn for vn, a in by_vn.items() if not a.options and not a.hidden
    }

    scripts = _engine_module.get_cpq_rdb().fetch_function_scripts(
        workspace_id, catalog_prefix)
    candidates: dict[str, set[str]] = {}
    literal_by_norm_and_var: dict[tuple[str, str], str] = {}
    for script in scripts.values():
        if not script:
            continue
        for var, value in _engine_module.extract_literal_comparisons(script):
            if var not in option_less:
                continue
            norm = _engine_module._normalize_for_hint(value)
            if len(norm) < _engine_module._HINT_MIN_PHRASE_LEN:
                continue
            candidates.setdefault(norm, set()).add(var)
            literal_by_norm_and_var[(norm, var)] = value

    index: dict[str, tuple[str, str]] = {
        norm: (next(iter(vns)), literal_by_norm_and_var[(norm, next(iter(vns)))])
        for norm, vns in candidates.items() if len(vns) == 1
    }

    for a in attrs:
        if a.hidden or a.select_type == "multi":
            continue
        for opt in a.options:
            for text in (opt.item_value, opt.display_name):
                index.pop(_engine_module._normalize_for_hint(text), None)

    _engine_module._FLAG_KEYWORD_INDEX_CACHE[cache_key] = index
    return index


def extract_flag_hints(
    engine: Any, question: str, attrs: list["ConfigAttr"],
    workspace_id: int, catalog_prefix: str,
) -> dict[str, str]:
    """{variable_name: literal_value} for option-less, BML-referenced
    fields whose expected literal value appears (un-negated) in the
    question. See _build_flag_keyword_index for the safety guards.

    Negation drops the match entirely rather than inventing an
    "opposite" literal — unlike a real YES/NO option pair, there is no
    second value the script defines for "not federal", so the safe
    behavior is to leave the field unfilled (same as any other
    genuinely unresolvable case), not guess one.
    """
    index = engine._build_flag_keyword_index(attrs, workspace_id, catalog_prefix)
    if not index:
        return {}
    q_norm, q_index_map = _engine_module._normalize_for_hint_with_map(question)
    q_lower = question.lower()
    hints: dict[str, str] = {}
    for norm_value, (vn, literal_value) in index.items():
        idx = _engine_module._find_plural_tolerant(q_norm, norm_value)
        if idx == -1:
            continue
        if _engine_module._is_negated_before(q_lower, q_index_map[idx]):
            continue
        hints[vn] = literal_value
    return hints
