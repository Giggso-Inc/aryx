"""Catalog/attribute-naming helpers, split out of `cpq/engine.py`'s
module-level scope (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.
md — module-level helper extraction beyond the 8 previously-deferred
methods, done purely to shrink engine.py further). Re-exported from
`aryx.cpq.engine` (see the import there) so every existing `from
aryx.cpq.engine import <name>` caller/test — and `_engine_module.
_strip_catalog_name_noise(...)`'s whole-module-reference call in
`nl_hint_extraction/entity_fetch.py` — keeps working unchanged. Logic
unchanged from the original inline definitions.
"""

from __future__ import annotations

import re

from aryx.cpq.bml import _operator_hit

# Ontology types ingested from an XML source are named '{SourceStem}Bm{Tag}'
# (e.g. 'ApxNextConfigBmConfigAttr', 'Sl3500EConfigBmConfigAttr') because every
# BigMachines/Oracle CPQ export element tag begins with 'bm_' — the PascalCase
# text before that marker is the ingested-source/catalog boundary.
_CATALOG_PREFIX_RE = re.compile(r"^(.*?)Bm[A-Z]")


def _catalog_prefix(type_name: str) -> str:
    """Source-derived catalog prefix of an ingested ontology type name.

    Used to keep two ingested product catalogs sharing one workspace (e.g.
    an APX Next export and an SL3500e export) from being treated as a
    single undifferentiated attribute/rule pool — see load_product_config's
    catalog scoping. Returns "" when no 'Bm<Upper>' marker is found (a
    workspace with no source-prefixed types, or a naming convention outside
    this pipeline's own PascalCase scheme) — callers must treat "" as
    "unknown catalog", never as a valid scope to filter on.
    """
    m = _CATALOG_PREFIX_RE.match(type_name or "")
    return m.group(1) if m else ""


def _strip_catalog_name_noise(norm: str) -> str:
    """Strip the internal-naming wrapper from a normalized BmPrdFamily/
    BmCatalog name so it can substring-match a natural-language sentence.

    Confirmed live: EVERY real family/catalog name across both ingested
    catalogs (77 total) ends in "bom" ("autoDGM8500E_BOM", "aPXNext_BOM",
    "mOTOTRBO_BOM", ...), and many also start with "auto" — neither
    fragment is something a customer ever says ("quote an auto DGM 8500 E
    bom radio"), so leaving them in place meant a full sentence like
    "quote DGM 8500e radios for a US customer" could never substring-match
    "autodgm8500ebom" even though the meaningful part ("dgm8500e") is right
    there in the sentence.
    """
    if norm.endswith("bom"):
        norm = norm[:-3]
    if norm.startswith("auto"):
        norm = norm[4:]
    return norm


# BigMachines variable_names are camelCase concatenations of the UI group an
# attribute lives under plus its own field name (e.g. "carrySolutionsType_apcr"
# groups under "Carry Solutions", field "Type") — the group name is what a
# customer actually says ("carry solutions"), so detect_attr_query needs the
# split words, not just the raw string, to resolve those questions.
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_GENERIC_ATTR_WORDS = frozenset({
    "type", "types", "selection", "option", "options", "all", "config",
    "attr", "value", "values",
})


def _variable_words(variable_name: str) -> list[str]:
    """CamelCase/underscore-split words from a variable_name, catalog-suffix
    and generic filler words (type/selection/option/...) dropped.

    Used only as a fallback signal in detect_attr_query — never for exact
    matching, since dropping generic words is intentionally lossy.
    """
    words: list[str] = []
    for part in variable_name.split("_"):
        if not part:
            continue
        spaced = _CAMEL_BOUNDARY_RE.sub(r"\1 \2", part)
        spaced = _ACRONYM_BOUNDARY_RE.sub(r"\1 \2", spaced)
        words.extend(w.lower() for w in spaced.split())
    return [w for w in words if len(w) > 1 and w not in _GENERIC_ATTR_WORDS]


def _condition_value_matches(
    current_val: str, condition_value: str, operator: str = "4",
) -> bool:
    """True when current_val satisfies a single condition_attr/condition_value
    pair, under the given BM-native operator (default "4" = "=" — the
    majority code, and the only one every existing caller assumed before
    docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md).

    condition_value is sometimes a "~"-delimited OR-list (same convention
    already handled for ConstraintRule.allowed_values, e.g. "PREMIER~ADVANCED
    SOFTWARE ONLY~ESSENTIAL SOFTWARE ONLY") rather than one literal value.
    A bare case-insensitive equality check against the whole string can
    never match any single real value in that case, so any hiding/
    constraint/recommendation rule using this encoding silently never
    fires (confirmed live: this is exactly why "Hide Include Accidental
    Damage for certain Service Type" never hid includeAccidentalDamageAddDMSCoverage_astro
    despite serviceTypeAdditionalDMSCoverage_astro="PREMIER" matching one of
    its 3 listed values — docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §3).
    Single-value condition_value strings behave identically to a plain
    equality check (a 1-element split set), so this is a strict superset
    fix, not a behavior change for the common case.

    A None result from the shared _operator_hit (a numeric operator that
    couldn't parse either side) is treated as "does not match" here rather
    than propagated as "unresolved" — every caller of this scalar path
    already treats a plain False the same as "condition not met, skip,"
    so collapsing None into False changes nothing observable for the
    handful of real rows that would hit this edge case, while keeping this
    function's simple bool return type callers already depend on.
    """
    return bool(_operator_hit(current_val, [condition_value], operator))
