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
from typing import Any

from aryx.cpq.logging_context import get_run_id, install_run_id_logging
from aryx.cpq.rule_trace.rule_trace_io import _trace_dir
from aryx.cpq.rule_trace.rule_trace_state import (
    _ctx_var,
    _lock,
    _open_sessions,
    _pass_var,
    _sealed_run_ids,
    _OpenTrace,
    bind_context,
    bind_pass,
)
from aryx.cpq.auto_fill_stages import fill_log
from aryx.raven_log import raven_log, would_log
from aryx.store.rule_trace_store import RuleTraceStore

__all__ = [
    "bind_context",
    "bind_pass",
    "flush_pending",
    "record_fire",
    "seal",
    "sweep_orphans",
]

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)

# Buffered durable writes (2026-10-07 perf fix): a fresh pool.connection()
# acquire pings the connection before returning it (oracle_connection_
# pool.py's ping_interval=0), costing ~0.44s on top of the insert's own
# ~0.22s round trip -- confirmed live, ws 1267/Astro25Configdata fires
# 1000+ rules in one turn, so writing one row per fire cost ~650s of a
# ~2000s turn on nothing but connection pings and round trips. Flushing
# every _flush_batch_size() fires (plus always at evaluate_rules_loop's
# end, ask_api._run_cpq_turn's finally, and at seal(), see flush_pending()
# /seal() below) keeps the same "durable before the turn's response
# returns" guarantee while turning ~1000 round trips into a handful.


def _flush_batch_size() -> int:
    """PR #458 review (Low finding 4): settings-backed, not a hardcoded
    constant, so a deployment can tune the durability/round-trip-count
    trade-off without a code change."""
    from aryx.config import get_settings
    return get_settings().cpq_rule_trace_flush_batch_size


def _durable_failed(operation: str, exc: BaseException, run_id: str = "") -> None:
    """R11 -- a durable rule-trace write failed and was swallowed (WARN P3)."""
    raven_log("WARN", "P3", "ask.rule_trace.durable_failed durable rule trace write failed",
              error_code="ARYX_ASK_RULE_TRACE_FAILED", context={
                  "dependency_name": "rule_trace_store", "operation": operation, "result": "failed",
                  "error_class": type(exc).__name__, "run_id": run_id, "attempt": 1})


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
    except Exception as exc:
        logger.exception("rule_trace: durable open_session failed run_id=%s", run_id)
        _durable_failed("open_session", exc)
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
    except Exception as exc:
        logger.exception("rule_trace: durable sweep_orphans failed")
        _durable_failed("sweep_orphans", exc)
        return []


def _log_fired(rule_type: str, rule_id: str, attr: str | None, ref_id: Any, bml_tier: str | None,
               pass_num: int | None, seq_no: int) -> None:
    """G6 -- ask.rule.fired: rule name, ref_id (None when the rule carries only a name), target
    attribute and the attribute's source tag now. Rules carry only ``rule_name``; the new source
    is inferred from the rule type (recommendation -> rule, auto_fill:<tag> -> <tag>)."""
    fired = fill_log.count_rule_fire()
    if not would_log("DEBUG"):
        return
    old = fill_log.current_source(attr)
    new = "rule" if rule_type == "recommendation" else (
        str(rule_id).split(":", 1)[1] if str(rule_id).startswith("auto_fill:") else None)
    raven_log("DEBUG", "P4", "ask.rule.fired attributed to a target attribute", context={
        "actor": "rule_engine", "requested_action": "set_attribute" if rule_type != "hiding" else "hide_attribute",
        "resource": attr, "required_permission": "rule_in_model_scope", "decision": "applied",
        "reason_code": "RULE_FIRED", "policy_version": "rule_scope_unscoped_v0",
        "rule_id": rule_id, "rule_name": rule_id, "ref_id": ref_id, "rule_type": rule_type,
        "bml_tier": bml_tier, "target_attribute": attr, "pass": pass_num, "seq_no": seq_no,
        "old_source": old, "new_source": new, "rules_fired_this_turn": fired,
        "rules_in_scope_for_model": None})


def record_fire(
    *,
    rule_type: str,
    rule_id: str,
    attr: str | None,
    outcome: str,
    bml_tier: str | None = None,
    ref_id: int | str | None = None,
) -> None:
    """Append one fired-rule entry to the current session's trace.

    A no-op when no run_id/context is bound (get_run_id() == "", or
    bind_context() was never called), or the session's trace is already
    sealed -- callers at the fire points in apply_hiding_rules /
    apply_recommendation_rules / apply_constraint_rules never need to
    check either condition themselves.

    The durable (DB) write is buffered, not immediate -- see
    _flush_batch_size()'s docstring -- and flushed in one round trip once
    that many fires accumulate, or at flush_pending()/seal()'s call
    sites. The local .jsonl write stays immediate (cheap, local disk, no
    round trip to batch).
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
    with _lock:
        trace.pending.append(
            (run_id, seq_no, pass_num, rule_type, rule_id, attr, outcome, bml_tier),
        )
        # flush_suspended (set by a prior failed flush) blocks this
        # size-triggered auto-flush only -- see _OpenTrace.flush_suspended's
        # docstring for why (PR #458 review, new Medium finding). Explicit
        # flush points (flush_pending/seal) are unaffected.
        should_flush = (
            not trace.flush_suspended and len(trace.pending) >= _flush_batch_size()
        )
    if should_flush:
        _flush_trace(trace)
    logger.info("cpq: rule trace fired seq=%d rule_id=%s type=%s", seq_no, rule_id, rule_type)
    _log_fired(rule_type, rule_id, attr, ref_id, bml_tier, pass_num, seq_no)


def _flush_trace(trace: "_OpenTrace") -> None:
    """Durably write `trace`'s buffered fires in one batched round trip.

    A failed batch is put back at the front of `trace.pending` (PR #458
    review, Medium finding) rather than dropped -- one failure previously
    cost one row (the old per-fire append_entry had no retry either); a
    batch failure must not cost up to _flush_batch_size() rows instead. The
    local .jsonl copy already has these rows regardless (written in
    record_fire, independent of this), so no data is lost either way --
    this only affects whether the DURABLE (DB) copy eventually gets them
    too. Still bounded: a run_id whose breaker is open (see
    RuleTraceStore.append_entries_batch) is silently skipped, not
    retried forever -- same accepted trade-off as before this PR.

    A failure also sets trace.flush_suspended, which stops record_fire's
    own size-triggered auto-flush from immediately retrying the re-queued
    (now even larger) batch on every subsequent fire -- PR #458 review
    (new Medium finding): without this, a sustained outage turned every
    later fire into another full connection-acquire-and-timeout attempt,
    worse than the original one-INSERT-per-fire behaviour. Retries instead
    happen only at the next explicit flush point (flush_pending()'s
    callers: evaluate_rules_loop's end, ask_api._run_cpq_turn's finally,
    seal()) -- which still runs unconditionally, ignoring this flag, since
    those are exactly the points this guarantee already relies on. A
    successful flush clears the flag, so recovery once the DB comes back
    needs no separate signal.
    """
    with _lock:
        batch, trace.pending = trace.pending, []
    if not batch:
        return
    try:
        _store().append_entries_batch(batch)
    except Exception as exc:
        logger.exception("rule_trace: durable append_entries_batch failed run_id=%s", trace.run_id)
        _durable_failed("append_entries_batch", exc, trace.run_id)
        with _lock:
            trace.pending = batch + trace.pending
            trace.flush_suspended = True
    else:
        with _lock:
            trace.flush_suspended = False


def flush_pending(run_id: str | None = None) -> None:
    """Durably flush run_id's (or the current context's) buffered fires now.

    Call at the end of a turn's rule evaluation (evaluate_rules_loop) so
    the turn's trace is durable by the time its HTTP response returns,
    even though individual fires are no longer written one at a time.
    A no-op when no trace is open for run_id, or nothing is pending.
    """
    run_id = run_id or get_run_id()
    if not run_id:
        return
    trace = _open_sessions.get(run_id)
    if trace is None:
        return
    _flush_trace(trace)


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
    _flush_trace(trace)
    try:
        _store().seal_session(run_id, status=status)
    except Exception as exc:
        logger.exception("rule_trace: durable seal_session failed run_id=%s", run_id)
        _durable_failed("seal_session", exc, run_id)
    logger.info("cpq: rule trace sealed run_id=%s status=%s", run_id, status)
    with _lock:
        _sealed_run_ids.add(run_id)
        _open_sessions.pop(run_id, None)
