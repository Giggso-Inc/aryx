"""Applying a ConstraintRule's ALLOW/DISALLOW mode (plan F2).

``ConstraintRule.allowed_values`` is an allow-list by default. A rule built from
a ``setConstraintValuesInSession`` action carries ``mode`` ("ALLOW" or
"DISALLOW") and, optionally, a ``guard_attr``: a variable that must hold a
value for the call to run at all.
"""
from __future__ import annotations

from typing import Any


def guard_open(rule: Any, filled: dict[str, str]) -> bool:
    """False when the rule's guard variable is empty (the call would not run)."""
    guard = getattr(rule, "guard_attr", "")
    return not guard or bool((filled.get(guard) or "").strip())


def effective_allowed(rule: Any, target: Any) -> list[str]:
    """The values that remain legal on `target`: the rule's own list, or, for
    a DISALLOW rule, every option of the target except the listed values."""
    if str(getattr(rule, "mode", "") or "").upper() != "DISALLOW":
        return rule.allowed_values
    blocked = {v.strip().upper() for v in rule.allowed_values}
    return [o.item_value for o in target.options if o.item_value.strip().upper() not in blocked]
