"""`auto_fill`'s already-satisfied-recommendation check (Phase 4, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md), split out of the P0 setup
block. Logic unchanged from the original inline closure.
"""

from __future__ import annotations

from typing import Any, Callable

from aryx.cpq.engine import RecommendationRule, _condition_value_matches


def build_rec_by_target(
    rec_rules: list[RecommendationRule] | None,
) -> dict[int, list[RecommendationRule]]:
    # target attr id -> recommendation rules targeting it, so step 4 can
    # check for an already-satisfied recommendation before blindly
    # picking first-by-order (see auto_fill's docstring — the ordering
    # bug this closes).
    rec_by_target: dict[int, list[RecommendationRule]] = {}
    if rec_rules:
        for _r in rec_rules:
            rec_by_target.setdefault(_r.target_attr_id, []).append(_r)
    return rec_by_target


def make_satisfied_recommendation(
    engine: Any, filled: dict[str, str], rec_by_target: dict[int, list[RecommendationRule]],
    attr_by_rule_id: dict[int, Any], bml_eval: Any | None,
) -> Callable[[Any, list[Any]], tuple[str, str, str] | None]:
    def _satisfied_recommendation(
        attr: Any, candidate_opts: list[Any],
    ) -> tuple[str, str, str] | None:
        """A targeted recommendation whose condition is ALREADY true
        in the current `filled` state — more specific than a generic
        XML default_value and must win over it (confirmed live:
        solutionTypeDevices_astro's own default_value silently beat
        the "Set CLOUD RC as default value" rule because the old step
        3 ran unconditionally before any rule got a chance to apply,
        since apply_recommendation_rules() never revisits an attr
        already in `filled` — docs/CPQ_SESSION_2_OPEN_ISSUES.md).

        Also handles script/condition_script-backed rules (via
        bml_eval), not just the plain condition_attr_id/condition_value
        pair — same Tier-1/Tier-2 machinery apply_recommendation_rules
        uses. Purely additive: a script that resolves is always a
        correct answer, never a wrong guess, and never asks a
        question that wasn't already going to be asked (it can only
        resolve an attr that would otherwise stay unfilled/pending).
        bml_eval=None (caller opted out) falls back to skipping script
        rules entirely, same as apply_recommendation_rules.

        Returns (item_value, display_name, rule_name) — the rule_name
        (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2e) is the
        specific rule that fired, for the rule-trace attribution call
        sites use it for instead of the old generic "auto_fill:rule"
        tag. Every return path below already has `rrule` in scope, so
        this is free — no separate lookup.
        """
        for aid_key in (attr.entity_id, attr.source_id):
            if aid_key is None:
                continue
            for rrule in rec_by_target.get(aid_key, []):
                if rrule.script is not None:
                    if bml_eval is None:
                        continue
                    allowed = bml_eval.allowed_values_for_script(rrule.script, filled)
                    if not allowed or len(allowed) != 1:
                        continue  # unknown, or ambiguous — never guess
                    recommended_value = allowed[0]
                elif rrule.condition_script is not None:
                    if bml_eval is None:
                        continue
                    fires = bml_eval.condition_holds(rrule.condition_script, filled)
                    if fires is not True:
                        continue  # False or unknown — never guess, doesn't fire
                    recommended_value = rrule.recommended_value
                else:
                    cond_attr = attr_by_rule_id.get(rrule.condition_attr_id)
                    if not cond_attr:
                        continue
                    cond_val = filled.get(cond_attr.variable_name)
                    if cond_val is None or not _condition_value_matches(
                        cond_val, rrule.condition_value, rrule.condition_operator
                    ):
                        continue
                    recommended_value = rrule.recommended_value
                match = next(
                    (o for o in candidate_opts
                     if o.item_value.lower() == recommended_value.lower()),
                    None,
                )
                if match:
                    return match.item_value, match.display_name, rrule.rule_name
        return None

    return _satisfied_recommendation
