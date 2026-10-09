"""Diagnostic for a recommendation rule that writes the base-model attribute.

ws 1267, APX N50: `TT2592A` and `T8343A` were written into the base model by a rule (`ask.base_model.write`, source `rule`, site
`resync_stale_recommendations`) over a derived `H25UCF9PW6AN`; the log never said which rule. This records the rule, its inputs
and whether the value has the SHAPE of the value it replaces (letters and digits in the same places), with no model or value
names involved."""
from __future__ import annotations

from typing import Any

from aryx.raven_log import raven_log


def value_shape(value: str) -> str:
    """'H25UCF9PW6AN' -> 'A99AAA9AA9AA': letters and digits by class, anything else as is."""
    return "".join("A" if ch.isalpha() else "9" if ch.isdigit() else ch for ch in str(value))


def log_base_model_rule_value(rule: Any, vn: str, recommended: str, current: str | None, site: str) -> None:
    """One record per base-model value a rule recommends: WARN when its shape differs from the current value's."""
    try:
        from aryx.cpq.auto_fill_stages.fill_log import is_base_model_vn  # noqa: PLC0415 -- diagnostic only

        if not is_base_model_vn(vn):
            return
        shape_new, shape_old = value_shape(recommended), value_shape(current or "")
        conditions = getattr(rule, "conditions", None) or []
        ctx = {
            "object_id": vn, "selected_option": "recommended", "available_options": ["recommended"],
            "reason_code": "BASE_MODEL_SHAPE_DIFFERS" if current and shape_new != shape_old else "BASE_MODEL_RULE_VALUE",
            "rule_name": getattr(rule, "rule_name", ""), "rule_ref_id": getattr(rule, "ref_id", "") or "",
            "recommended_state": recommended, "current_state": current, "shape_recommended": shape_new,
            "shape_current": shape_old, "write_site": site, "condition_count": len(conditions),
            "condition_attr_ids": [c[0] for c in conditions][:8] if conditions else [getattr(rule, "condition_attr_id", None)],
            "condition_values": [str(c[1])[:30] for c in conditions][:8] if conditions else [str(getattr(rule, "condition_value", ""))[:30]],
            "has_condition_script": bool(getattr(rule, "condition_script", None)), "has_script": bool(getattr(rule, "script", None))}
        if ctx["reason_code"] == "BASE_MODEL_SHAPE_DIFFERS":
            raven_log("WARN", "P3", "ask.base_model.rule_value a rule recommends a base-model value of a different shape",
                      error_code="ARYX_ASK_BASE_MODEL_RULE_SHAPE", context=ctx)
        else:
            raven_log("DEBUG", "P4", "ask.base_model.rule_value a rule recommends a base-model value", context=ctx)
    except Exception:  # noqa: BLE001 -- a diagnostic must never change the correction
        return
