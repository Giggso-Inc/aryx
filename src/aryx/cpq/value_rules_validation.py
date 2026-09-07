"""Message-only (validation) value-rule actions, split out of
`_load_value_rules`'s per-row loop body (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import ValidationRule
from aryx.cpq.value_rules_state import RuleLoadState


def append_validation_rules(
    state: RuleLoadState, eid: int, rule_name: str, acts: list[tuple],
    condition_script: str | None, cond_attr_id: int, cond_value: str,
    cond_operator: str, inp_list: list[tuple] | None,
    declarative_condition_collision: bool,
) -> None:
    for aid, _at, val, act_fn, _set_type, comments in acts:
        # "System recommendation" is BigMachines' own generic
        # boilerplate default comment (confirmed: 365
        # occurrences across this one catalog alone) — not a
        # real, customer-facing message a rule author actually
        # wrote. Excluded so a meaningless "⚠️ System
        # recommendation" is never shown. Re-confirmed as the
        # only such placeholder across all 138 declarative
        # candidates too (see the plan doc's boilerplate scan).
        if (act_fn == -1 and not val and comments
                and comments.strip().lower() != "system recommendation"):
            if declarative_condition_collision:
                state.validation_collisions_skipped += 1
                continue
            state.validation_rules.append(ValidationRule(
                rule_name=rule_name or str(eid),
                target_attr_id=aid,
                message=comments,
                condition_script=condition_script,
                condition_attr_id=cond_attr_id,
                condition_value=cond_value,
                condition_operator=cond_operator,
                conditions=list(inp_list) if condition_script is None else None,
            ))
