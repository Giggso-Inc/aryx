"""``resync_stale_recommendations`` -- re-run recommendation rules over
engine-filled attrs whose driving values have since changed (Phase 4 step 6
extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Stateless and purely functional -- no ``CpqEngine`` instance needed; same
``attr_index`` helpers as ``apply_recommendation_rules``.
"""

from __future__ import annotations

from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.engine import _valid, logger
from aryx.cpq.hiding_rules.attr_index import _attr_index, _filled_by_rule_id
from aryx.cpq.recommendation_and_constraint_rules.rule_condition import (
    resolve_recommended_value,
)
from aryx.cpq.state import ConfigAttr, RecommendationRule


def resync_stale_recommendations(
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    filled_source: dict[str, str] | None,
    rules: list[RecommendationRule],
    bml_eval: BmlEvaluator | None = None,
    filled_multi: dict[str, list[str]] | None = None,
    constrained_opts: dict[int, list[str]] | None = None,
) -> dict[str, tuple[str, str]]:
    """Re-apply recommendation rules to attrs the ENGINE already filled
    (never a customer's own choice), correcting them when a driving
    attribute's later value now changes what they should be.

    docs/config_consistency_issues_2026-07-30.md issue 6 (FedRAMP) /
    docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1: this codebase
    previously only DETECTED this class of drift
    (`find_rule_inconsistencies` — logged, never corrected), deliberately,
    since "the engine can't be certain what the correct value should
    have been" for a value the CUSTOMER chose. That reasoning does not
    apply to a value the engine itself auto-filled before its own
    driving attribute had a value yet (the documented "first-by-order
    claimed it first" race in `auto_fill`'s own docstring) — re-running
    the SAME deterministic rule with fresher inputs isn't guessing, it's
    finishing a computation that fired too early. Scoped by
    `filled_source`, the exact boundary `find_rule_inconsistencies`
    already uses: "user" is never touched. Also excludes "hint" and
    "cascade" — both still trace back to something the customer said or
    confirmed, not a value this method has any business overwriting.

    Only ever revisits attrs already in `filled` (single-select) — a
    multi-select TARGET's value lives in `filled_multi`, out of scope
    for this pass; `apply_recommendation_rules` (unfilled attrs) is
    unaffected, this only ever touches already-filled ones. filled_multi
    is still accepted here for the separate purpose of reading a rule's
    CONDITION attribute when that attribute (not the target) is
    select_type=="multi" (operators "7"/"8" — see apply_hiding_rules).

    Returns {variable_name: (item_value, display)} for every attr whose
    value actually changed. The caller is expected to apply these
    exactly like any other rule-sourced fill and treat them as a real
    change for cascade-dependent invalidation, same as an explicit
    customer edit would.

    constrained_opts — see apply_recommendation_rules' identical
    parameter; a "correction" back to a value a different, currently-
    active constraint has already excluded is not a correction.
    """
    if not rules:
        return {}
    _NEVER_OVERRIDE = {"user", "hint", "cascade"}
    by_rule_id = _attr_index(attrs)
    filled_by_rule_id = _filled_by_rule_id(attrs, filled, filled_multi)
    corrections: dict[str, tuple[str, str]] = {}
    for rule in rules:
        target = by_rule_id.get(rule.target_attr_id)
        if not target:
            continue
        vn = target.variable_name
        current = filled.get(vn)
        if not current:
            continue  # unfilled — apply_recommendation_rules' job, not this one
        if filled_source and filled_source.get(vn) in _NEVER_OVERRIDE:
            continue
        recommended_value = resolve_recommended_value(
            rule, filled, filled_by_rule_id, bml_eval)
        if recommended_value is None:
            continue
        if not _valid(recommended_value) or current.lower() == recommended_value.lower():
            continue
        # Same guard as apply_recommendation_rules: a "correction" back
        # to a value a DIFFERENT, currently-active constraint has
        # already excluded is not a correction — it's silently undoing
        # auto_fill's own correct fallback. Live regression: auto_fill
        # correctly fell back to "ESSENTIAL" once Hardware Version
        # activated a constraint excluding "ADVANCED", but this method
        # ran right after (same pass) and — seeing its own unrelated
        # condition (Solution Type) still held, with no constraint
        # awareness at all — "resynced" it straight back to the
        # excluded value, every single pass.
        allowed_for_target = (
            constrained_opts.get(target.entity_id) if constrained_opts else None
        )
        if allowed_for_target is not None and not any(
            recommended_value.lower() == v.lower() for v in allowed_for_target
        ):
            continue
        matched_display = next(
            (o.display_name for o in target.options
             if o.item_value.lower() == recommended_value.lower()),
            recommended_value,
        )
        corrections[vn] = (recommended_value, matched_display)
    if corrections:
        logger.info(
            "cpq: resynced stale recommendation-governed attrs %s",
            list(corrections.keys()),
        )
    return corrections
