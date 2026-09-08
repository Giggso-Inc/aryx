"""Hard exclusion of "native UI never asks this conversationally" attrs
from `pending`, split out of `api/ask_api.py` (Phase 4/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). The
per-attribute resolution logic lives in `ask_pending_exclusion_resolve.py`
(split out purely to keep this file under the line cap). Logic unchanged
from the original inline definitions.
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.api.ask_pending_exclusion_resolve import resolve_hard_excluded_attr

logger = logging.getLogger(__name__)

# Attributes the native Motorola UI genuinely never asks about as a
# conversational question at all -- confirmed live against the real
# APX NEXT product screenshots: these show up ONLY under the passive,
# system-computed "Recommended Configuration" section (with an "Edit"
# override affordance), never under "Mandatory User Input". No database
# flag distinguishes the two sections in this catalog (confirmed live:
# zero BmConfigLayoutAttrAssoc rows exist for ANY attribute here, so this
# isn't a layout-tier gap our loader could read if only it looked in the
# right place -- the signal genuinely isn't ingested data at all). The
# real, already-established proxy this session has used throughout is
# rule governance: every attribute in this set has enough real
# constraint/recommendation coverage to be system-computed, which is
# exactly what "Recommended Configuration" means natively.
#
# packingPackageType_astro ("Package Type"): 9 active constraint rules
# (engine.py's _BLIND_FILL_RISK_ACCEPTED_VNS / _auto_resolve_singleton_
# pending already lean on this same governance to auto-fill it in the
# common case) -- but its real script-backed rule (18131370895) depends
# on BmlEvaluator's Tier-2 (LLM) path (Tier 1 doesn't support its
# findinArray/split idiom), so on some turns it still reached `pending`
# and got asked, then a genuine catalog-duplicate-option matching bug
# (live-confirmed: "Bulk" rejected against a list that visibly contains
# "Bulk") made it unanswerable from chat at all. Hard exclusion here is
# the backstop: never let it reach `pending` regardless of whether the
# timing-dependent auto-fill happened to catch it, mirroring the native
# UI's own "this is never a chat question" contract exactly.
_NEVER_ASK_RECOMMENDED_ONLY_VNS: frozenset[str] = frozenset({
    "packingPackageType_astro",
})


def _hard_exclude_from_pending(
    pending: list, filled: dict, display_filled: dict, filled_source: dict,
    con_rules: list, bml_eval: Any, rec_rules: list | None = None,
    workspace_id: int | None = None, catalog_prefix: str = "",
    all_attrs: list | None = None,
) -> list:
    """Remove an attribute in `_NEVER_ASK_RECOMMENDED_ONLY_VNS` from
    `pending` ONLY when something real justifies a value -- the currently
    active constraint/recommendation narrowing to exactly one legal
    option, or the attribute's own catalog default_value. Deliberately
    does NOT fall back to blindly picking `valid_opts[0]` when neither
    resolves it (PR #215 review, C1): packingPackageType_astro has 8
    genuinely different real options (SINGLE/BULK/N/A/DEMO KIT CASE/...)
    -- an unconstrained blind pick here is exactly the "guess among real
    business choices with no justification" failure mode _no_real_fill_
    justification/_BLIND_FILL_RISK_ACCEPTED_VNS (engine.py) exist to
    prevent, and unlike the native UI's own "Recommended Configuration"
    section (which shows an "Edit" override affordance), a silent chat
    guess gives the customer no cue anything needs checking. When
    nothing justifies a value, the attribute stays in `pending` --
    same as `_auto_resolve_singleton_pending` already does for its own
    ambiguous case -- so it still gets asked rather than guessed.
    Only ever touches attrs individually named in the frozenset above --
    never a generic "skip anything hard to resolve" mechanism.

    Checks BOTH con_rules and rec_rules -- live-confirmed Package Type's
    real governing rule (18131370895, the ICE-KIT script) loads as a
    RecommendationRule, not a ConstraintRule (CpqEngine's set_type-based
    classification, same reclassification confirmed for Duration's
    equivalent rule this session), so a constraint-only check would
    never see it at all regardless of any variable-handling fix.

    "ICE Kit not yet asked" fix (generic, not hardcoded per attribute):
    the native UI's "Recommended Configuration" section is computed once
    the entire "Mandatory User Input" form is submitted -- by which
    point every governing input has a real, definitive state (even
    "never touched" is a resolved empty, not a live unknown). Our
    engine evaluates hard-excluded attrs mid-conversation, genuinely
    before some of their real governing inputs (e.g. the ICE Kit
    feature-type selection, order_number 120 vs Package Type's own 37 --
    Package Type is reached first in this catalog's own ordering) have
    ever come up. For THIS individually-vetted attribute set only,
    treat a governing variable that's entirely absent from `filled` the
    same as "explicitly answered empty" -- discovered dynamically via
    bml.referenced_variables() over each of the attr's own real
    governing scripts, never a hand-maintained per-attribute variable
    list. Only ever applied on a LOCAL COPY of `filled` used for this
    one check; the real session state is never mutated, so every other
    attribute's missing-vs-empty distinction is completely unaffected.

    PR #218 review (M1): "unasked -> empty" is only a safe default for a
    governing variable whose real-world meaning HAS a valid empty state
    -- true for additionalSystemEnhancementFeatureType_astro (a
    multi-select feature checklist, where "never touched" and
    "explicitly selected nothing" are the same real state), but NOT true
    for a decision-anchor single-select (Hardware Version, Country,
    Product) where every real option is mutually exclusive and blank
    means "not yet known", not "resolved empty". So this default is
    restricted to governing variables that are themselves multi-select
    (`select_type == "multi"`, looked up via `all_attrs`) -- a
    single-select governing variable that's entirely unasked is left
    genuinely missing, same as everywhere else in the engine.
    """
    if not pending:
        return pending
    survivors: list = []
    for attr in pending:
        if attr.variable_name not in _NEVER_ASK_RECOMMENDED_ONLY_VNS or not attr.options:
            survivors.append(attr)
            continue
        chosen = resolve_hard_excluded_attr(
            attr, filled, con_rules, rec_rules, bml_eval,
            workspace_id, catalog_prefix, all_attrs,
        )
        if chosen is None:
            # Nothing justifies a value -- leave it in pending so it
            # still gets asked, rather than guessing among real,
            # materially different business choices.
            survivors.append(attr)
            continue
        filled[attr.variable_name] = chosen.item_value
        display_filled[attr.variable_name] = chosen.display_name
        filled_source.setdefault(attr.variable_name, "rule")
        logger.info(
            "cpq: %r hard-excluded from pending (native UI never asks "
            "this conversationally) -- resolved to %r",
            attr.variable_name, chosen.item_value,
        )
    return survivors
