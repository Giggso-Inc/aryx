"""One debug line when a script hide rule gives no answer (diagnostic only; behaviour is unchanged).

An undecided script hide rule leaves its target visible and, until now, said nothing, so "why is this attribute still
asked although the real screen hides it" could not be answered from the logs (ws 1267, 2026-10-07: the two
"Hide Professional Services if No Values Available" rules never fired). The line names the rule, the target and WHY
it was undecided. Once per (run, rule, target, reason), so the many passes of a turn do not repeat it.
"""
from __future__ import annotations

import threading

from aryx.cpq.logging_context import get_run_id
from aryx.raven_log import raven_log, would_log

_SEEN: dict[str, set[tuple[str, str, str]]] = {}
_SEEN_LOCK = threading.Lock()
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
        key = (str(rule.rule_name), str(target_variable), reason)
        with _SEEN_LOCK:
            seen = _SEEN.setdefault(run_id, set())
            if len(_SEEN) > _MAX_RUNS:
                for stale in list(_SEEN)[:-_MAX_RUNS]:
                    _SEEN.pop(stale, None)
            if key in seen:
                return
            seen.add(key)
        raven_log("DEBUG", "P4", "ask.rules_loop.hide_unknown script hide rule gave no answer", context={
            "selected_option": "left_visible", "available_options": ["hide", "show", "left_visible"],
            "reason_code": reason, "rule_name": rule.rule_name, "attr": target_variable,
            "master_writer_count": len(getattr(rule, "master_writers", None) or [])})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change rule evaluation
        return


def log_master_unresolved(rule, reason: str, detail: dict | None = None) -> None:
    """Debug record of the exact step at which a master-string hide rule could not be computed."""
    try:
        if not would_log("DEBUG"):
            return
        run_id = get_run_id() or ""
        key = (str(rule.rule_name), "master", reason)
        with _SEEN_LOCK:
            seen = _SEEN.setdefault(run_id, set())
            if key in seen:
                return
            seen.add(key)
        raven_log("DEBUG", "P4", "ask.rules_loop.master_unresolved master string could not be computed", context={
            "selected_option": "left_visible", "available_options": ["hide", "show", "left_visible"],
            "reason_code": reason, "rule_name": rule.rule_name,
            "master_writer_count": len(getattr(rule, "master_writers", None) or []), **((detail or {}).get("build", dict)())})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change rule evaluation
        return


def log_master_context(rule, target_variable: str, decided: dict | None, result: bool | None) -> None:
    """Debug record of WHAT a master-string hide rule decided on: the model and base-model scope of the writer query, how many
    attribute names the computed master string holds, whether the rule's target is one of them. Once per (run, rule, target,
    outcome). Answers "is this hide right": a master built for the wrong model, or without the target, hides it."""
    try:
        if not would_log("DEBUG") or not decided:
            return
        names = decided.get("_names") or set()
        outcome = "hide" if result else "show"
        run_id = get_run_id() or ""
        key = (str(rule.rule_name), str(target_variable), f"context:{outcome}")
        with _SEEN_LOCK:
            seen = _SEEN.setdefault(run_id, set())
            if key in seen:
                return
            seen.add(key)
        raven_log("DEBUG", "P4", "ask.rules_loop.master_context what the computed master string held", context={
            "selected_option": outcome, "available_options": ["hide", "show"], "reason_code": "DECIDED_MASTER_STRING_CONTEXT",
            "rule_name": rule.rule_name, "attr": target_variable, "master_var": decided.get("master_var"),
            "cpq_model": decided.get("cpq_model"), "base_models": decided.get("base_models"),
            "master_names": decided.get("master_names"), "master_len": decided.get("master_len"),
            "live_writers": decided.get("live_writers"), "target_in_master": target_variable in names,
            "names_sample": sorted(names)[:15], "rule_ref_id": getattr(rule, "ref_id", "") or ""})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change rule evaluation
        return


def log_decided_master_hide(rule, target_variable: str, hide: bool, via_master: bool) -> None:
    """Debug record of a master-string hide rule that DID decide (hide or show), once per (run, rule, target, outcome).

    A "show" from one rule re-adds an attribute another rule hid (the last rule wins), and a rule that decides is
    otherwise silent, so "why is this attribute still asked" could not be answered from the logs when no rule was
    undecided. `via_master` says whether the computed master string decided it or the ordinary evaluator did.
    """
    try:
        if not would_log("DEBUG"):
            return
        outcome = "hide" if hide else "show"
        run_id = get_run_id() or ""
        key = (str(rule.rule_name), str(target_variable), f"decided:{outcome}")
        with _SEEN_LOCK:
            seen = _SEEN.setdefault(run_id, set())
            if key in seen:
                return
            seen.add(key)
        raven_log("DEBUG", "P4", "ask.rules_loop.hide_decided master-string hide rule decided", context={
            "selected_option": outcome, "available_options": ["hide", "show"],
            "reason_code": "DECIDED_BY_MASTER_STRING" if via_master else "DECIDED_BY_SCRIPT_EVALUATOR",
            "rule_name": rule.rule_name, "attr": target_variable,
            "master_writer_count": len(getattr(rule, "master_writers", None) or [])})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change rule evaluation
        return

