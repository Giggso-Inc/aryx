"""Per-attribute resolution helper for `ask_pending_exclusion.py`'s
`_hard_exclude_from_pending` (split out purely to keep that file under
the line cap). Logic unchanged from the original inline per-attr loop
body. `_cpq_engine` is read through the ask_api MODULE object (not
imported by name) since at least one test replaces the whole singleton
via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.cpq.engine import _valid

logger = logging.getLogger(__name__)


def resolve_hard_excluded_attr(
    attr: Any, filled: dict, con_rules: list, rec_rules: list | None,
    bml_eval: Any, workspace_id: int | None, catalog_prefix: str,
    all_attrs: list | None,
) -> Any | None:
    """Returns the single MenuOption a real rule/default justifies for
    this hard-excluded `attr`, or None when nothing does (caller must
    leave it in `pending` rather than guess)."""
    from aryx.api import ask_api as _ask_api_module
    from aryx.cpq.bml.bml import referenced_variables

    valid_opts = [o for o in attr.options if _valid(o.item_value)]
    governing_scripts = [
        r.script for r in list(con_rules or []) + list(rec_rules or [])
        if getattr(r, "target_attr_id", None) == attr.entity_id and r.script
    ]
    governing_vars: set[str] = set()
    for script in governing_scripts:
        governing_vars |= referenced_variables(script)
    attrs_by_vn = {a.variable_name: a for a in (all_attrs or [])}
    filled_for_check = dict(filled)
    for vn in governing_vars:
        governing_attr = attrs_by_vn.get(vn)
        if governing_attr is not None and governing_attr.select_type != "multi":
            continue
        filled_for_check.setdefault(vn, "")
    if con_rules and bml_eval is not None:
        try:
            allowed = _ask_api_module._cpq_engine.apply_constraint_rules(
                [attr], con_rules, filled_for_check, bml_eval,
                workspace_id=workspace_id, catalog_prefix=catalog_prefix,
            ).get(attr.entity_id)
        except Exception:  # noqa: BLE001 — best-effort, never blocks the turn
            logger.debug(
                "cpq: hard-exclude constraint check failed for %r",
                attr.variable_name, exc_info=True,
            )
            allowed = None
        if allowed:
            # Only a genuine single-value resolution counts as real
            # justification -- 2+ remaining legal values is still an
            # unresolved choice among real options, not a computed
            # answer, so it must NOT be blind-picked here either.
            narrowed = [o for o in valid_opts if o.item_value in allowed]
            if len(narrowed) == 1:
                return narrowed[0]
    if rec_rules and bml_eval is not None:
        for rule in rec_rules:
            if rule.target_attr_id != attr.entity_id or not rule.script:
                continue
            try:
                rec_allowed = bml_eval.allowed_values_for_script(
                    rule.script, filled_for_check,
                )
            except Exception:  # noqa: BLE001 — best-effort, never blocks the turn
                logger.debug(
                    "cpq: hard-exclude recommendation check failed for %r "
                    "(rule=%r)", attr.variable_name, rule.rule_name, exc_info=True,
                )
                rec_allowed = None
            if rec_allowed and len(rec_allowed) == 1:
                match = next(
                    (o for o in valid_opts if o.item_value == rec_allowed[0]), None,
                )
                if match is not None:
                    return match
    if attr.default_value:
        return next(
            (o for o in valid_opts if o.item_value == attr.default_value), None,
        )
    return None
