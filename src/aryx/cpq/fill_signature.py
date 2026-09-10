"""Decision-anchor constants and the auto-fill "state signature" used to
gate redundant blind re-derivation, split out of `cpq/engine.py`'s
module-level scope (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.
md -- module-level constant/helper extraction, done purely to shrink
engine.py further). Re-exported from `aryx.cpq.engine` (see the import
there) so every existing `from aryx.cpq.engine import <name>` caller/
test -- including `auto_fill_resolve`'s submodules' bare-name imports and
`monkeypatch.setattr(engine_module, "_fill_signature", ...)` -- keeps
working unchanged. Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import _valid

# Country/Region are the only two attrs whose absence blocks question
# routing entirely (D1, CPQ_CASCADE_CONVERSATION_PLAN.md §2) -- every
# other attr's readiness is decided by the normal rule cascade/attrSequence
# default_value. hwVersion was removed per D1
# (CPQ_CASCADE_CONVERSATION_PLAN.md §2) — it's no longer a special-cased
# anchor, it resolves through the normal rule cascade like any other
# dependent variable.
_DECISION_REQUIRED_KEYS: frozenset[str] = frozenset({
    "country", "region",
})

# Public alias so ask_api can access it without importing a private name.
DECISION_REQUIRED_KEYS = _DECISION_REQUIRED_KEYS

# The exact (not fragment-matched) variable names of this catalog's real
# decision anchors -- used by evaluate_rules_loop to tell "hidden because an
# anchor is still blank" (merely gating, values dormant/preserved) apart
# from "hidden with every anchor already answered" (a real, current-state
# conflict, values stripped exactly as before). See the strip-vs-preserve
# comment at its one call site for the live-confirmed regression this
# narrower, exact-name check exists to avoid repeating.
_DECISION_ANCHOR_VNS: tuple[str, ...] = (
    "ultimateDestinationCountry", "hWVersion_astro",
    "productSelectionProduct_all", "modelSelectionbaseModel_astro",
)

# Multi-select attrs confirmed live (2026-08-16) to default to EVERY
# Whitelist/Data-Table-confirmed-legal option checked, not just one --
# real-world meaning is "which of these apply" (coverage), not "pick one
# among many". See the one call site (auto_fill's narrowed-legal-values
# branch) for why this is a narrow, named allowlist rather than a change
# to that branch's default behavior for every multi-select.
_SELECT_ALL_NARROWED_LEGAL_MULTI_VNS: frozenset[str] = frozenset({
    "modelSelectionFrequencyBandMsl_astro",
})

# Live-confirmed (2026-08-16): additionalSystemEnhancementFeatureType_
# astro got blind-picked to its first menu option with NOTHING in the
# catalog behind it -- required=False, no real default_value, zero
# recommendation rules ever targeting it -- and that guess silently
# cascaded into narrowing an unrelated, real question (Application
# Services) down to the wrong 5-option set. `_no_real_fill_justification`
# is the dynamic, catalog-agnostic test for this exact shape, computed
# per-attribute at call time rather than a hardcoded attribute-name list
# -- any attribute anywhere in this (or another) catalog with the same
# profile gets the same protection automatically, with no code change
# needed to name it. Checked at the two specific auto_fill call sites
# that had no other real-data guard at all: the unconditional multi-
# select "nothing to justify a subset" fallback, and the two single-
# select first-by-order fallbacks (display-order-based and the final
# bare-menu-order one). Every earlier, more specific branch in the same
# method (satisfied recommendation, Data Table single-match, confirmed-
# valid default under an active constraint, exactly-one-remaining-
# option) is left completely untouched and still fires normally for any
# attr whenever real data actually supports it -- this only blocks the
# LAST-resort "guess from the whole unconstrained menu" step.
def _no_real_fill_justification(
    attr: "Any", rec_by_target: dict[int, list[Any]],
) -> bool:
    if attr.required:
        return False
    if _valid(attr.default_value):
        return False
    if rec_by_target.get(attr.entity_id) or rec_by_target.get(attr.source_id):
        return False
    return True


def _fill_signature(
    filled: dict[str, str],
    filled_multi: dict[str, list[str]],
    visible_ids: set[int],
) -> tuple:
    """docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md — a broad, unhashed
    snapshot of everything a "default_first_available" blind guess could
    plausibly depend on: every filled single/multi value plus the current
    visible-attribute-id set (a hiding-rule-driven visibility change can
    alter legal options too, not just a value change). Deliberately NOT
    scoped down to "only attrs this one plausibly depends on" -- no safe
    dependency graph exists yet for script-backed rules (docs/CPQ_TURN_
    LATENCY_FIX_CORRECTNESS_RISK_2026_08_19.md), so a narrower signature
    risks silently missing a real narrowing, the same failure class as the
    Package Type bug. Compared by direct tuple equality, never hashed --
    sidesteps Python's per-process-randomized hash() entirely.
    """
    return (
        tuple(sorted(filled.items())),
        tuple(sorted((k, tuple(sorted(v))) for k, v in filled_multi.items())),
        tuple(sorted(visible_ids)),
    )
