"""Contextvar/lock state and per-turn context binding for the rule trace.

Split out of `cpq/rule_trace.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import contextlib
import contextvars
import threading
from dataclasses import dataclass, field
from pathlib import Path

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
    # Fired-rule rows not yet flushed to the durable store (see
    # rule_trace.py's record_fire/_flush_trace) -- each is the exact
    # positional-argument tuple RuleTraceStore.append_entries_batch()
    # executemany()s in one round trip, instead of one connection
    # acquire + INSERT per rule fire (confirmed live, 2026-10-07: each
    # acquire pings the pool's connection -- oracle_connection_pool.py's
    # ping_interval=0 -- costing ~0.44s on top of the ~0.22s round trip
    # itself, and a single ws 1267/Astro25Configdata turn fires 1000+
    # rules, so this was ~650s of a ~2000s turn spent entirely on
    # per-fire connection pings and round trips).
    pending: list[tuple] = field(default_factory=list)
    # Set when a flush fails and the batch is re-queued (see rule_trace.
    # py's _flush_trace). Suppresses record_fire's size-triggered
    # auto-flush while True -- PR #458 review (new Medium finding): without
    # this, a failed flush left `pending` at/above the batch-size
    # threshold, so EVERY later record_fire re-triggered another flush of
    # the whole (growing) buffer -- 300 fires against an always-failing
    # store produced 201 flush attempts, each one a real connection
    # acquire + timeout wait, worse than the original one-INSERT-per-fire
    # behaviour during an outage. Explicit flush points (evaluate_rules_
    # loop's end, ask_api._run_cpq_turn's finally, seal()) still attempt a
    # flush regardless of this flag -- it only gates the automatic,
    # size-triggered one inside record_fire -- and a successful flush
    # clears it again, so recovery after the DB comes back needs no
    # separate signal.
    flush_suspended: bool = False


def bind_context(workspace_id: int, catalog_prefix: str) -> None:
    """Bind (workspace_id, catalog_prefix) for the current ask-turn.

    Call once per incoming ask request, alongside set_run_id() -- e.g. in
    ask_api.py right after the CpqSession is loaded/created.
    """
    _ctx_var.set((int(workspace_id), catalog_prefix or ""))


@contextlib.contextmanager
def untraced():
    """Rule evaluations inside the block record no fired-rule rows (a 'what would be hidden' query is not a decision)."""
    token = _ctx_var.set(None)
    try:
        yield
    finally:
        _ctx_var.reset(token)


def bind_pass(pass_num: int) -> None:
    """Bind the current fixed-point pass number. Call at the top of each
    evaluate_rules_loop() iteration, before apply_hiding_rules() etc."""
    _pass_var.set(pass_num)
