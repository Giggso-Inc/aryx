"""Per-configuration-session, execution-ordered rule-fire trace.

docs/CPQ_RULE_EXPORT_AND_TRACE_TDD_PLAN.md's feature 2. One trace spans an
entire CpqSession (see state.py's CpqSession.run_id -- minted once per
session, not per ask-turn), from the first rule that fires until the
session is confirmed, sealed into one file + one durable session row.

Confirm signal correction (found while implementing, not during planning):
CpqSession.status is never actually set to "approved" anywhere in the
codebase (confirmed via a full grep of src/aryx) -- it is dead legacy code,
normalized away by ask_api.py's own comment ("approved is a legacy
dead-end value... used to be set once at STEP 8 and never checked again").
The real confirm event is ask_api.py's cpq_payload_approved() branch, which
sets session.complete = True and session.status = "post_approval" together
at the exact point build_payload() generates the final BOM JSON. This
module therefore seals on session.complete becoming True, not on any
particular status string.

Every fired rule is written as its own row to the durable store in real
time (RuleTraceStore.append_entry) AND appended to a local .jsonl file at
the same time -- neither write depends on the other completing. This is
the deliberate opposite of the aryx_discovery incident (migration 0036):
that crash came from one oversized blob written once; many small writes
here never approach any single-write size ceiling, and a mid-session crash
still leaves the partial trace durably saved in Postgres even if the local
file is lost.

Deliberately contextvar-based, not threaded as required parameters through
apply_hiding_rules/apply_recommendation_rules/apply_constraint_rules --
same reasoning as aryx.cpq.logging_context's run_id: those methods are
called directly (with no context bound) from 30+ existing unit tests that
construct rule/attr objects in isolation. Absent context, record_fire()
silently does nothing.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`rule_trace_state.py` (contextvars/lock state + `bind_context`/
`bind_pass`) and `rule_trace_io.py` (`_trace_dir`, the one piece with no
patch coupling), both re-imported here. `_store`/`_get_or_open`/
`record_fire`/`seal`/`sweep_orphans` stay together in the hub: an earlier
pass moved `_store`/`sweep_orphans` out and broke
`test_cpq_rule_trace.py`'s `monkeypatch.setattr(rule_trace, "_store", ...)`
— that only rebinds the hub module's own attribute, so any function
resolving `_store()` via a different module's namespace misses the
patch. Caught by a test failure, not by grep (there's no `patch()` string
literal to search for a plain `monkeypatch.setattr` on a function
object).
"""
from __future__ import annotations

import json
import logging

from aryx.cpq.logging_context import get_run_id, install_run_id_logging
from aryx.cpq.rule_trace_io import _trace_dir
from aryx.cpq.rule_trace_state import (
    _ctx_var,
    _lock,
    _open_sessions,
    _pass_var,
    _sealed_run_ids,
    _OpenTrace,
    bind_context,
    bind_pass,
)
from aryx.store.rule_trace_store import RuleTraceStore

__all__ = [
    "bind_context",
    "bind_pass",
    "record_fire",
    "seal",
    "sweep_orphans",
]

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


def _store() -> RuleTraceStore:
    from aryx.config import get_settings
    return RuleTraceStore(get_settings().effective_dsn())


def _get_or_open(run_id: str, workspace_id: int, catalog_prefix: str) -> "_OpenTrace | None":
    from datetime import datetime, timezone
    with _lock:
        if run_id in _sealed_run_ids:
            return None
        existing = _open_sessions.get(run_id)
        if existing is not None:
            return None if existing.sealed else existing
        safe_prefix = catalog_prefix or "unscoped"
        start_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        file_key = f"{safe_prefix}_{start_ts}"
        try:
            trace_dir = _trace_dir()
        except Exception:
            logger.exception("rule_trace: local trace dir unavailable, durable-only")
            trace_dir = None
        file_path = (trace_dir / f"{file_key}.jsonl") if trace_dir is not None else None
        trace = _OpenTrace(run_id=run_id, file_path=file_path)
        _open_sessions[run_id] = trace
    try:
        _store().open_session(run_id, workspace_id, catalog_prefix, file_key)
    except Exception:
        logger.exception("rule_trace: durable open_session failed run_id=%s", run_id)
    logger.info("cpq: rule trace opened file=%s", file_path.name if file_path else "<local write disabled>")
    return trace


def sweep_orphans(timeout_hours: int | None = None) -> list[str]:
    """Seal every durable session still 'open' past the orphan timeout.

    Intended to run on a schedule (cron/background task), not per-request.
    Returns the run_ids sealed as 'orphaned_timeout', or [] if the durable
    store is unreachable (e.g. no Oracle-variant migration exists yet for
    aryx_rule_trace_session/entry -- Raven review, PR #156: unlike
    open_session/append_entry/seal_session above, this had no try/except,
    so a scheduled sweep would raise instead of degrading gracefully like
    its siblings on an Oracle-backed deployment).
    """
    if timeout_hours is None:
        from aryx.config import get_settings
        timeout_hours = get_settings().cpq_rule_trace_orphan_timeout_hours
    try:
        return _store().sweep_orphans(timeout_hours=timeout_hours)
    except Exception:
        logger.exception("rule_trace: durable sweep_orphans failed")
        return []


def record_fire(
    *,
    rule_type: str,
    rule_id: str,
    attr: str | None,
    outcome: str,
    bml_tier: str | None = None,
) -> None:
    """Append one fired-rule entry to the current session's trace.

    A no-op when no run_id/context is bound (get_run_id() == "", or
    bind_context() was never called), or the session's trace is already
    sealed -- callers at the fire points in apply_hiding_rules /
    apply_recommendation_rules / apply_constraint_rules never need to
    check either condition themselves.
    """
    run_id = get_run_id()
    ctx = _ctx_var.get()
    if not run_id or ctx is None:
        return
    workspace_id, catalog_prefix = ctx
    trace = _get_or_open(run_id, workspace_id, catalog_prefix)
    if trace is None:
        return
    pass_num = _pass_var.get()
    with _lock:
        trace.seq_no += 1
        seq_no = trace.seq_no
    entry = {
        "seq_no": seq_no, "pass_num": pass_num, "rule_type": rule_type,
        "rule_id": rule_id, "attr": attr, "outcome": outcome, "bml_tier": bml_tier,
    }
    if trace.file_path is not None:
        try:
            with trace.file_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            logger.exception("rule_trace: local file write failed run_id=%s", run_id)
    try:
        _store().append_entry(
            run_id, seq_no, pass_num, rule_type, rule_id, attr, outcome, bml_tier,
        )
    except Exception:
        logger.exception("rule_trace: durable append_entry failed run_id=%s", run_id)
    logger.info("cpq: rule trace fired seq=%d rule_id=%s type=%s", seq_no, rule_id, rule_type)


def seal(run_id: str | None = None, status: str = "post_approval") -> None:
    """Seal the current (or given) session's trace -- call exactly once,
    at the confirm point (session.complete becoming True in ask_api.py).

    A no-op if no trace was ever opened for this run_id (a session that
    confirmed without any rule ever firing).
    """
    run_id = run_id or get_run_id()
    if not run_id:
        return
    with _lock:
        if run_id in _sealed_run_ids:
            return
        trace = _open_sessions.get(run_id)
        if trace is None:
            return
        trace.sealed = True
    try:
        _store().seal_session(run_id, status=status)
    except Exception:
        logger.exception("rule_trace: durable seal_session failed run_id=%s", run_id)
    logger.info("cpq: rule trace sealed run_id=%s status=%s", run_id, status)
    with _lock:
        _sealed_run_ids.add(run_id)
        _open_sessions.pop(run_id, None)
