"""Raven structured-log helpers for the CPQ ask engine (area ``ask_engine``).

One place for the G1-G8 records so the stage modules only need a one-line
call at each write site (no new branches in the stages themselves):

- ``log_write``      -- ask.fill.set / ask.fill.overwritten / ask.base_model.write
- ``log_pruned``     -- ask.attr.pruned (INFO for ``_bm_model*`` attributes, else DEBUG)
- ``log_stage_trail`` -- ask.fill.attribute (one per attribute per pass)
- ``set_pass`` / ``current_pass`` -- the rules-loop pass number, held in a contextvar
- ``fallback_static_first_in_turn`` -- per-turn dedupe for the static model fallback WARN
- ``build_turn_state_record`` -- ask.turn.state (end of quote turn)

Everything here is best-effort: it never raises into the engine and never
changes a value. Values follow D6: enumerated/numeric values are logged,
free-text attribute values only as length + hash (``value_fields``).
"""
from __future__ import annotations

import contextvars
import threading
from types import SimpleNamespace
from typing import Any

from aryx.raven_log import current_run_id, raven_log, value_fields, would_log

_PASS: contextvars.ContextVar[int | None] = contextvars.ContextVar("ask_fill_pass", default=None)
_PLACEHOLDERS = frozenset({"*", "", "tbd", "any", "all", "n/a", "na", "none", "null", "unknown"})
_SOURCES: contextvars.ContextVar[Any] = contextvars.ContextVar("ask_fill_sources", default=None)
_FIRES = {"run": None, "n": 0}
_SEEN_LOCK = threading.Lock()
_SEEN: dict[str, Any] = {"run": None, "keys": set()}


def set_pass(n: int | None) -> None:
    """Record the rules-loop pass number for the records emitted in this context."""
    _PASS.set(n)


def current_pass() -> int | None:
    return _PASS.get()


def bind_sources(sources: Any) -> None:
    """Remember the live ``filled_source`` dict so rule-fire records can show old/new source."""
    _SOURCES.set(sources)


def current_source(vn: Any) -> str | None:
    src = _SOURCES.get()
    return src.get(vn) if isinstance(src, dict) else None


def count_rule_fire() -> int:
    """Rules fired so far in the current turn (run id)."""
    run = current_run_id()
    with _SEEN_LOCK:
        if _FIRES["run"] != run:
            _FIRES["run"], _FIRES["n"] = run, 0
        _FIRES["n"] += 1
        return _FIRES["n"]


def is_free_text(attr: Any) -> bool:
    """True when the attribute is not an enumerated/boolean choice (unsure -> free text)."""
    if attr is None:
        return True
    if getattr(attr, "select_type", "") == "boolean":
        return False
    return not getattr(attr, "options", None)


def is_model_context(vn: str) -> bool:
    return str(vn).lower().startswith("_bm_model")


def is_base_model_vn(vn: str) -> bool:
    return "basemodel" in str(vn).lower().replace("_", "")


def _state(v: Any, free: bool) -> Any:
    """previous/requested/final state: the value itself only for non-free-text."""
    if v is None:
        return "unset"
    return "set" if free else v


def log_write_dicts(filled: dict, filled_multi: dict, sources: dict, attr: Any, vn: str, value: Any,
                    display: Any, source: str, site: str, *, multi: bool = False,
                    force: bool = False) -> None:
    """``log_write`` for callers that hold the three dicts instead of a FillContext."""
    ns = SimpleNamespace(filled=filled, filled_multi=filled_multi, sources=sources)
    log_write(ns, attr, vn, value, display, source, site, multi=multi, force=force)


def log_write(ctx: Any, attr: Any, vn: str, value: Any, display: Any, source: str,
              site: str, *, multi: bool = False, force: bool = False) -> None:
    """Log one write to ``ctx.filled`` / ``ctx.filled_multi`` BEFORE it happens.

    Emits ask.fill.set (DEBUG), ask.fill.overwritten (WARN P3) when a different
    value already sits there, and ask.base_model.write for the base-model attr.
    """
    try:
        store = ctx.filled_multi if multi else ctx.filled
        old = store.get(vn)
        old_src = ctx.sources.get(vn)
        new = list(value) if multi and value is not None else value
        free = is_free_text(attr)
        differs = old is not None and old != new
        pass_no = current_pass()
        if differs:
            raven_log("WARN", "P3", "ask.fill.overwritten a different value replaced an earlier one",
                      error_code="ARYX_ASK_FILL_OVERWRITTEN", context={
                          "object_id": vn, "previous_state": _state(old, free),
                          "requested_state": _state(new, free), "final_state": _state(new, free),
                          "trigger": site, "result": "overwritten", "reason_code": "DIFFERENT_VALUE_REPLACED",
                          "pass": pass_no, "old_source": old_src, "new_source": source,
                          "source_kept": source if force else (old_src or source), **value_fields(new, free_text=free)})
        elif would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ask.fill.set write site", context={
                "object_id": vn, "previous_state": _state(old, free), "requested_state": _state(new, free),
                "final_state": _state(new, free), "trigger": site,
                "result": "rewritten_same" if old is not None else "written",
                "reason_code": "SAME_VALUE" if old is not None else "FIRST_WRITE",
                "pass": pass_no, "source": source, "previous_source": old_src,
                "display_len": len(str(display)) if display is not None else 0,
                **value_fields(new, free_text=free)})
        if is_base_model_vn(vn):
            log_base_model(vn, new, source, site, old)
    except Exception:  # logging must never affect the fill
        return


def log_base_model(vn: str, value: Any, source: str, site: str, old: Any = None) -> None:
    """ask.base_model.write; WARN P3 when the value is a wildcard/placeholder."""
    items = value if isinstance(value, (list, tuple)) else [value]
    texts = [str(i).strip() for i in items]
    wildcard = any("*" in t for t in texts)
    placeholder = wildcard or any(t.lower() in _PLACEHOLDERS for t in texts)
    ctxd = {"object_id": vn, "previous_state": "unset" if old is None else old, "requested_state": value,
            "final_state": value, "trigger": source, "result": "written_placeholder" if placeholder else "written",
            "reason_code": "WILDCARD_VALUE" if wildcard else ("PLACEHOLDER_VALUE" if placeholder else "REAL_VALUE"),
            "pass": current_pass(), "source": source, "write_site": site, "is_wildcard": wildcard}
    if placeholder:
        raven_log("WARN", "P3", "ask.base_model.write a placeholder value was written",
                  error_code="ARYX_ASK_BASE_MODEL_PLACEHOLDER", context=ctxd)
    elif would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.base_model.write", context=ctxd)


def log_pruned(vn: str, reason: str, trigger: str, *, state: str = "skipped") -> None:
    """ask.attr.pruned -- INFO for platform/model-context attrs, DEBUG otherwise."""
    model_ctx = is_model_context(vn)
    lv = "INFO" if model_ctx else "DEBUG"
    if not would_log(lv):
        return
    raven_log(lv, "P4", f"ask.attr.pruned attribute {state}", context={
        "object_id": vn, "previous_state": "present", "requested_state": state, "final_state": state,
        "trigger": trigger, "result": state, "reason_code": reason, "pass": current_pass(),
        "is_model_context": model_ctx})


def log_load(name: str, **fields: Any) -> None:
    """DEBUG ask.load.<name> -- one loader/cache step (counts, cache hit/miss, catalog prefix)."""
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", f"ask.load.{name} loader step", context=fields)


def log_load_failed(name: str, exc: BaseException, reason: str, **fields: Any) -> None:
    """WARN P3 ARYX_ASK_LOAD_DEGRADED -- a loader swallowed an error and continued with empty data."""
    raven_log("WARN", "P3", f"ask.load.{name} loader failed, continuing with empty data",
              error_code="ARYX_ASK_LOAD_DEGRADED", context={
                  "dependency_name": name, "operation": name, "result": "degraded_empty",
                  "error_class": type(exc).__name__, "reason_code": reason, "attempt": 1, **fields})


def log_decision(vn: str, trigger: str, result: str, reason: str, **extra: Any) -> None:
    """DEBUG ask.fill.decision -- one deciding condition's outcome for an attribute."""
    if not would_log("DEBUG"):
        return
    raven_log("DEBUG", "P4", "ask.fill.decision stage branch", context={
        "object_id": vn, "trigger": trigger, "result": result, "reason_code": reason,
        "pass": current_pass(), **extra})


def stage_snapshot(ctx: Any, state: Any) -> tuple:
    vn = state.vn
    return (state.value, state.done, vn in ctx.filled, vn in ctx.filled_multi, len(ctx.pending),
            ctx.filled.get(vn), tuple(ctx.filled_multi.get(vn) or ()))


def stage_outcome(before: tuple, after: tuple) -> str:
    """Outcome code for one stage from two ``stage_snapshot`` values."""
    if after[2:4] != before[2:4] or after[5:] != before[5:]:
        return "wrote"
    if after[4] > before[4]:
        return "deferred_pending"
    if after[1] and not before[1]:
        return "finished"
    if after[0] != before[0]:
        return "value_chosen"
    return "no_op"


def log_stage_trail(ctx: Any, state: Any, trail: list, previous_source: str | None,
                    had_value: bool, before_value: Any, attr: Any = None) -> None:
    """ask.fill.attribute -- one DEBUG record per attribute per pass."""
    try:
        vn = state.vn
        src = ctx.sources.get(vn)
        decided = next((n for n, o in reversed(trail) if o in ("wrote",)), None) \
            or next((n for n, o in reversed(trail) if o not in ("no_op",)), None)
        free = is_free_text(attr)
        now = ctx.filled_multi.get(vn) if vn in ctx.filled_multi else ctx.filled.get(vn)
        pending = any(getattr(a, "variable_name", None) == vn for a in ctx.pending)
        result = "pending" if pending else ("filled" if now is not None else "left_open")
        raven_log("DEBUG", "P4", "ask.fill.attribute decided", context={
            "object_id": vn, "previous_state": _state(before_value, free), "requested_state": _state(now, free),
            "final_state": _state(now, free), "trigger": "auto_fill", "result": result,
            "reason_code": (decided or "NO_STAGE").upper(), "pass": current_pass(), "decided_by": decided,
            "source": src, "previous_source": previous_source, "previous_value_set": had_value,
            "changed": now != before_value, "stage_trail": trail})
    except Exception:
        return


def fallback_static_first_in_turn(result: tuple) -> bool:
    """True the first time this exact result is seen in the current turn (run id)."""
    run = current_run_id()
    key = tuple(result)
    with _SEEN_LOCK:
        if _SEEN["run"] != run:
            _SEEN["run"], _SEEN["keys"] = run, set()
        if key in _SEEN["keys"]:
            return False
        _SEEN["keys"].add(key)
        return True


def build_turn_state_record(session: Any, attrs: Any = None, *, emit: bool = True) -> dict:
    """ask.turn.state -- end-of-turn filled_source map, counts and values (D6).

    Call once at the end of each quote turn. Reads ``filled``, ``filled_multi``,
    ``filled_source`` and ``pending_variables`` off ``session`` by name; missing
    -> empty. ``attrs`` (the turn's ConfigAttr list, optional) tells enumerated from
    free-text attributes; an attribute not found there is treated as free text.
    Returns the context dict (also emitted at DEBUG when ``emit``).
    """
    try:
        by_vn = {getattr(a, "variable_name", None): a for a in (attrs or [])}
        filled = dict(getattr(session, "filled", None) or {})
        multi = dict(getattr(session, "filled_multi", None) or {})
        src = dict(getattr(session, "filled_source", None) or {})
        ctxd: dict[str, Any] = {
            "object_id": getattr(session, "run_id", "") or current_run_id(),
            "filled_source": src, "filled_count": len(filled), "filled_multi_count": len(multi),
            "source_counts": _count(src.values()),
            "pending_count": len(getattr(session, "pending_variables", None) or []),
            "values": {k: (value_fields(v, free_text=True) if is_free_text(by_vn.get(k)) else v)
                       for k, v in {**filled, **multi}.items()},
        }
        if emit and would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ask.turn.state final filled state of the turn", context=ctxd)
            _mark_turn_state(ctxd["object_id"], getattr(session, "turn", None))
        return ctxd
    except Exception:
        return {}


_TURN_STATE_DONE: dict[tuple, None] = {}  # insertion-ordered set of (run_id, turn) already logged
_TURN_STATE_MAX = 2000


def _mark_turn_state(run_id: Any, turn: Any) -> None:
    with _SEEN_LOCK:
        _TURN_STATE_DONE[(run_id, turn)] = None
        while len(_TURN_STATE_DONE) > _TURN_STATE_MAX:
            _TURN_STATE_DONE.pop(next(iter(_TURN_STATE_DONE)))


def turn_state_from_session_data(session_data: Any) -> None:
    """ask.turn.state for turns that ended before step 11 (gates, product or model questions).

    Reads the serialized session (``result["session_data"]``); a turn whose step 11 already
    wrote the record is skipped. No attribute definitions here, so every value is logged as
    length + hash (D6 free-text form).
    """
    try:
        if not would_log("DEBUG") or not isinstance(session_data, dict):
            return
        key = (session_data.get("run_id") or current_run_id(), session_data.get("turn"))
        with _SEEN_LOCK:
            if key in _TURN_STATE_DONE:
                return
        build_turn_state_record(SimpleNamespace(**{k: session_data.get(k) for k in (
            "run_id", "turn", "filled", "filled_multi", "filled_source", "pending_variables")}))
    except Exception:
        return


def _count(items: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[str(i)] = out.get(str(i), 0) + 1
    return out
