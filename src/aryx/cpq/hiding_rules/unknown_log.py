"""One debug line when a script hide rule gives no answer (diagnostic only; behaviour is unchanged).

An undecided script hide rule leaves its target visible and, until now, said nothing, so "why is this attribute still
asked although the real screen hides it" could not be answered from the logs (ws 1267, 2026-10-07: the two
"Hide Professional Services if No Values Available" rules never fired). The line names the rule, the target and WHY
it was undecided. Once per (run, rule, target, reason), so the many passes of a turn do not repeat it.
"""
from __future__ import annotations

from aryx.cpq.logging_context import get_run_id
from aryx.raven_log import raven_log, would_log

_SEEN: dict[str, set[tuple[str, str, str]]] = {}
_MAX_RUNS = 20


def unknown_reason(rule, has_evaluator: bool, master_hide_on: bool, master_tried: bool) -> str:
    """Why a script hide rule produced no hide/show answer."""
    if not has_evaluator:
        return "NO_EVALUATOR"
    writers = getattr(rule, "master_writers", None)
    if writers and not master_hide_on:
        return "MASTER_STRING_FLAG_OFF"
    if writers and master_tried:
        return "MASTER_STRING_UNRESOLVED"
    if "findinarray" in str(getattr(rule, "script", "") or "").lower() and not writers:
        return "MASTER_SEARCH_WITHOUT_WRITER_RULE"
    return "EVALUATOR_UNKNOWN"


def log_unknown_script_hide(rule, target_variable: str, has_evaluator: bool, master_tried: bool = False) -> None:
    """Debug record that `rule` left `target_variable` visible because it could not be decided.

    Cheap when DEBUG is off (one level check, nothing else is evaluated) and can never affect hiding: any failure in
    building or writing the line is swallowed.
    """
    try:
        if not would_log("DEBUG"):
            return
        from aryx.cpq.hiding_rules.master_writers import master_hide_enabled  # noqa: PLC0415 -- only when logging

        reason = unknown_reason(rule, has_evaluator, master_hide_enabled(), master_tried)
        run_id = get_run_id() or ""
        seen = _SEEN.setdefault(run_id, set())
        if len(_SEEN) > _MAX_RUNS:
            for stale in list(_SEEN)[:-_MAX_RUNS]:
                _SEEN.pop(stale, None)
        key = (str(rule.rule_name), str(target_variable), reason)
        if key in seen:
            return
        seen.add(key)
        raven_log("DEBUG", "P4", "ask.rules_loop.hide_unknown script hide rule gave no answer", context={
            "selected_option": "left_visible", "available_options": ["hide", "show", "left_visible"],
            "reason_code": reason, "rule_name": rule.rule_name, "attr": target_variable,
            "master_writer_count": len(getattr(rule, "master_writers", None) or [])})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change rule evaluation
        return
