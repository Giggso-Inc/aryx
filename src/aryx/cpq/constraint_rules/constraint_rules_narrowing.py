"""``narrowing_rec_rules`` handling for ``apply_constraint_rules``
(Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline loop.

Live-confirmed gap (2026-08-25, SVX Mounting Type): a real catalog rule
can be authored with recommendation mechanics (set_type != -1, per
`_load_value_rules`'s own classification) while its script's actual job
is narrowing an attribute's legal VALUE SET, not picking one value
(confirmed via `allowed_values_for_script` returning 5-6 candidates for
SVX's Mounting Type (Array) rule, which `apply_recommendation_rules`
correctly refuses to guess from -- D2 "never guess" -- but then
discards entirely rather than surfacing as a narrowing signal). Each
script-backed `RecommendationRule` here whose script evaluates to 2+
values is intersected into the SAME `constrained` result as a genuine
constraint rule would be, without reclassifying the rule itself or
touching `_load_value_rules`. A script resolving to 0 or 1 value is
left alone here -- that's `apply_recommendation_rules`'s job.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.rule_trace import rule_trace
from aryx.cpq.constraint_rules.constraint_rules_intersect import intersect
from aryx.cpq.constraint_rules.constraint_rules_stats import ScriptEvalStats
from aryx.cpq.engine import _substitute_util_get_constraint_vals


def apply_narrowing_rec_rules(
    narrowing_rec_rules: list[Any],
    by_rule_id: dict[int, Any],
    filled: dict[str, str],
    bml_eval: Any | None,
    workspace_id: int | None,
    catalog_prefix: str,
    dt_cache: dict[tuple[int, str], tuple] | None,
    constrained: dict[int, list[str]],
    contributions: dict[int, list[tuple[frozenset, list[str], str]]],
    stats: ScriptEvalStats | None = None,
) -> None:
    """Mutates `constrained`/`contributions` in place for every
    script-backed narrowing RecommendationRule that resolves 2+ values.
    """
    for rule in narrowing_rec_rules:
        if rule.script is None or bml_eval is None:
            continue
        target = by_rule_id.get(rule.target_attr_id)
        if target is None:
            continue
        # Live-confirmed perf regression (2026-08-25, APX Next):
        # apply_recommendation_rules skips a rule immediately when
        # its target is already filled, so it only pays allowed_
        # values_for_script's real cost for the small set of
        # genuinely-unresolved targets (confirmed live it stays
        # ~10ms even with 1091 script-backed rec rules loaded). This
        # loop was missing that same guard, so it evaluated the
        # expensive script for ALL 1091 rules every pass regardless
        # of fill state -- confirmed live this alone cost 82s/59s/37s
        # on passes 0/1/2 for APX Next before the per-pass constraint
        # cache stabilized. Same "nothing left to narrow once it's
        # answered" logic applies here identically. NOT copied to
        # constraint_rules_apply.py's real-ConstraintRule loop --
        # find_rule_inconsistencies needs already-filled targets
        # evaluated there.
        if filled.get(target.variable_name):
            continue
        _script = _substitute_util_get_constraint_vals(
            rule.script, filled, workspace_id, catalog_prefix, dt_cache,
        )
        if stats is not None:
            allowed = stats.timed(bml_eval.allowed_values_for_script, _script, filled)
        else:
            allowed = bml_eval.allowed_values_for_script(_script, filled)
        if allowed and len(allowed) >= 2:
            intersect(
                constrained, contributions, target, allowed,
                frozenset({f"script_narrowing:{rule.rule_name}"}), rule.rule_name,
            )
            rule_trace.record_fire(
                rule_type="constraint", rule_id=rule.rule_name,
                attr=target.variable_name, outcome=f"allowed={allowed}",
                bml_tier="script_narrowing",
            )
