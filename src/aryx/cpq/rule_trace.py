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
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aryx.cpq.logging_context import get_run_id, install_run_id_logging
from aryx.store.rule_trace_store import RuleTraceStore

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)

# (workspace_id, catalog_prefix) for the current ask-turn -- bind once per
# turn via bind_context(), same lifecycle as run_id itself.
_ctx_var: contextvars.ContextVar[tuple[int, str] | None] = contextvars.ContextVar(
    "cpq_rule_trace_ctx", default=None,
)
# Current fixed-point pass number within evaluate_rules_loop -- bind once
# per loop iteration via bind_pass().
_pass_var: contextvars.ContextVar[int] = contextvars.ContextVar(
    "cpq_rule_trace_pass", default=0,
)

_open_sessions: dict[str, "_OpenTrace"] = {}
# run_ids sealed at least once, kept forever (unlike _open_sessions, which
# sheds the full _OpenTrace -- file_path, seq_no -- once sealed). Without
# this, seal() popping the entry from _open_sessions let a later record_fire()
# for the same run_id find no existing entry and treat it as brand new,
# silently reopening a fresh session/file instead of staying a no-op (Raven
# review: test_record_fire_after_seal_is_noop flaked on glob() file-ordering
# once 2+ trace files existed in the same directory). A bare set of run_id
# strings is far lighter than the _OpenTrace objects it replaces; unbounded
# growth over a long-lived process's full session history is the same class
# of growth this system already accepts for the durable session log itself.
_sealed_run_ids: set[str] = set()
_lock = threading.Lock()


@dataclass
class _OpenTrace:
    run_id: str
    file_path: Path | None
    seq_no: int = 0
    sealed: bool = False


def bind_context(workspace_id: int, catalog_prefix: str) -> None:
    """Bind (workspace_id, catalog_prefix) for the current ask-turn.

    Call once per incoming ask request, alongside set_run_id() -- e.g. in
    ask_api.py right after the CpqSession is loaded/created.
    """
    _ctx_var.set((int(workspace_id), catalog_prefix or ""))


def bind_pass(pass_num: int) -> None:
    """Bind the current fixed-point pass number. Call at the top of each
    evaluate_rules_loop() iteration, before apply_hiding_rules() etc."""
    _pass_var.set(pass_num)


def _trace_dir() -> Path | None:
    """Return the configured trace directory, or None if the current
    get_settings() doesn't look like a real Settings instance (e.g. a test
    broadly mocking get_settings() for something unrelated) -- never
    silently write a garbage path built from a mock's repr."""
    from aryx.config import get_settings
    raw = get_settings().cpq_rule_trace_dir
    if not isinstance(raw, str) or not raw:
        logger.warning("rule_trace: cpq_rule_trace_dir is not a real path (%r) -- skipping local file write", raw)
        return None
    d = Path(raw)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _store() -> RuleTraceStore:
    from aryx.config import get_settings
    return RuleTraceStore(get_settings().rdb_dsn)


def _get_or_open(run_id: str, workspace_id: int, catalog_prefix: str) -> _OpenTrace | None:
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
