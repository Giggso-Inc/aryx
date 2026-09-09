"""Durable option / product candidate scope for CPQ reply matching.

PROMPT 7 — when the engine shows a candidate list (family disambiguation,
constrained product options, attr options, "did you mean" suggestions),
the next reply must be resolved against THAT list first. Losing scope is
the same family of bug as gateway clarify-amnesia.

Scope is stored flat on CpqSession (pending_scope_*) for session_data echo.
This module stays free of FastAPI / graph imports so offline regression
can load it.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split
across `pending_scope_state.py` (set/clear + candidate building),
`pending_scope_resolve.py` (the exact/partial/fuzzy matching ladder, kept
whole for cohesion), and `pending_scope_messages.py` (re-ask phrasing +
logging), all re-imported here. Zero whitebox test patches exist anywhere
against `aryx.cpq.pending_scope.pending_scope.*` (confirmed via grep).
"""
from __future__ import annotations

from aryx.cpq.pending_scope.pending_scope_messages import (
    format_did_you_mean,
    log_scope_lost,
    log_scope_retained,
)
from aryx.cpq.pending_scope.pending_scope_resolve import (
    ScopeResolve,
    is_confident_scope_suggestion,
    resolve_against_scope,
    scope_loop_exit_threshold,
)
from aryx.cpq.pending_scope.pending_scope_state import (
    ScopeKind,
    candidates_from_attr_options,
    clear_pending_scope,
    set_pending_scope,
)

__all__ = [
    "ScopeKind",
    "ScopeResolve",
    "candidates_from_attr_options",
    "clear_pending_scope",
    "format_did_you_mean",
    "is_confident_scope_suggestion",
    "log_scope_lost",
    "log_scope_retained",
    "resolve_against_scope",
    "scope_loop_exit_threshold",
    "set_pending_scope",
]
