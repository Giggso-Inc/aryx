"""Stale-constraint recheck for the BOM gate.

Split out of `cpq/bom_gate.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). `recheck_constraints` is directly imported (bare name, not
patched) by `ask_api.py` and test files — confirmed via grep.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.bom_gate_types import StaleConstraintViolation
from aryx.cpq.state import ConfigAttr, CpqSession


def recheck_constraints(
    engine: Any,
    attrs: list[ConfigAttr],
    session: CpqSession,
    con_rules: list,
    bml_eval: Any,
) -> list[StaleConstraintViolation]:
    """Re-run constraint rules; return attrs whose filled value no longer
    satisfies the freshly recomputed allowed set. Raises on an unexpected
    engine error — the caller (`validate_before_payload`) decides how to
    handle that, this function never silently swallows one.

    docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §9 — this
    previously called `engine.apply_constraint_rules(attrs, session.filled,
    con_rules, ...)`, i.e. (attrs, filled, rules), then unpacked the result
    as a 2-tuple. The real signature is `(attrs, rules, filled, bml_eval=None)
    -> dict[int, list[str]]` — a SINGLE dict of {entity_id: [allowed
    item_values]}, no messages of its own. `session.filled` (a dict) landed
    in the `rules` parameter, `for rule in rules:` iterated its keys (plain
    strings), and `rule.target_attr_id` crashed every confirm with an active
    constraint rule. Every other call site in the codebase (ask_api.py,
    engine.py) already uses the correct order and treats the return as a
    plain dict — this was the only outlier.

    docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §11 — once this
    was actually reachable (rather than crash-and-swallowed), live traffic
    showed real, legitimate hits: an independent mechanism
    (`find_rule_inconsistencies`, ask_api.py) already logs this exact same
    class of issue and — per docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md
    §4.1 — deliberately does NOT hard-fail on it, since the engine can't be
    sure what the correct replacement value is. Returns structured
    violations (not messages) so the caller can auto-clear + re-ask rather
    than hard-block confirm.

    docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §12 — two review
    findings fixed: (1) this used to swallow ANY exception and return `[]`
    ("no violations"), which would fail OPEN — a genuine, unexpected engine
    error looked identical to "config is fine." Now propagates; the caller
    treats an exception as a hard-fail, same fail-closed discipline as
    `check_provenance`. (2) multi-select attrs (`select_type == "multi"`)
    were invisible to this check entirely — it only ever read
    `session.filled`, never `session.filled_multi`. Now checks both.
    """
    if not con_rules:
        return []
    constrained = engine.apply_constraint_rules(
        attrs, con_rules, session.filled, bml_eval=bml_eval, filled_multi=session.filled_multi,
    )
    if not constrained:
        return []
    by_eid = {a.entity_id: a for a in attrs}
    violations: list[StaleConstraintViolation] = []
    for entity_id, allowed in constrained.items():
        attr = by_eid.get(entity_id)
        if attr is None:
            continue
        if attr.select_type == "multi":
            current_multi = session.filled_multi.get(attr.variable_name)
            if not current_multi:
                continue
            invalid = [v for v in current_multi if v not in allowed]
            if invalid:
                violations.append(
                    StaleConstraintViolation(attr, ", ".join(invalid), allowed),
                )
            continue
        current = session.filled.get(attr.variable_name)
        if current is not None and current not in allowed:
            violations.append(StaleConstraintViolation(attr, current, allowed))
    return violations
