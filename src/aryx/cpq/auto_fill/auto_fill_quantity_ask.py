"""Quantity fields the catalog's own rules read as a number are asked, never left blank (flag
`cpq_rule_compared_quantity_ask_enabled`).

ws 1267, APX N70: choosing a Video RSM turns on "Add SVX Video Wireless Remote Speaker Mic", which shows
"Qty of SVX Remote Speaker Mic" -- a free-entry field with no options. The ask stage only asks a free-entry field a
validation rule targets, and none targets this one, so the field stayed blank, the session said "Configuration
complete", and MSI's Add Configuration To Transaction answered "Configuration is incomplete".

The signal is the catalog's data, not a name: a declarative recommendation rule whose condition compares the field to
a number with a numeric operator (`<`, `<=`, `>`, `>=`) -- here "Set TRUE if ... > 0". A field only reaches the fill
pass while it is visible (rule-hidden attributes are pruned before it), so an add-on that is not chosen keeps its
quantity hidden and unasked. No model, attribute or value is named here.
"""
from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.cpq.bml.bml_declarative import _NUMERIC_OPERATORS


def _is_number(value: Any) -> bool:
    try:
        float(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True


def _numeric_condition_attr_ids(rule: Any) -> set[int]:
    """Attribute ids a declarative rule compares to a number. Script rules are not read: their conditions live in
    BML text, and guessing the shape of a script is exactly what this module avoids."""
    if getattr(rule, "script", None) is not None or getattr(rule, "condition_script", None) is not None:
        return set()
    ids: set[int] = set()
    for attr_id, value, operator in getattr(rule, "conditions", None) or []:
        if str(operator) in _NUMERIC_OPERATORS and _is_number(value):
            ids.add(attr_id)
    if str(getattr(rule, "condition_operator", "")) in _NUMERIC_OPERATORS and _is_number(rule.condition_value):
        ids.add(rule.condition_attr_id)
    return ids


def rule_compared_quantity_vns(
    attrs: list[Any], rec_rules: list[Any] | None, display_order: dict[str, int] | None,
) -> frozenset[str]:
    """Variable names of the visible free-entry fields a declarative recommendation rule compares to a number.

    Empty with the flag off. A field with options, a multi-select, a boolean, a catalog-hidden field and a field the
    loaded layout does not show are never included."""
    if getattr(get_settings(), "cpq_rule_compared_quantity_ask_enabled", False) is not True or not rec_rules:
        return frozenset()
    compared: set[int] = set()
    for rule in rec_rules:
        compared |= _numeric_condition_attr_ids(rule)
    if not compared:
        return frozenset()
    return frozenset(
        a.variable_name for a in attrs
        if (a.entity_id in compared or (a.source_id is not None and a.source_id in compared))
        and not a.options and not a.hidden and a.select_type not in ("multi", "boolean")
        and (display_order is None or a.variable_name in display_order)
    )
