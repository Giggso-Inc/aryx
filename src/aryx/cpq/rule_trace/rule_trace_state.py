"""Contextvar/lock state and per-turn context binding for the rule trace.

Split out of `cpq/rule_trace.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass
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
