"""The tail of `resolve_one_attr`: commit a resolved value, or run the
not-yet-resolved fallback chain (multi-select fallbacks -> noise-var default
-> the final ask/blind-pick/skip decision).

This is the original body's LAST if/elif chain (`if value: ... elif ... elif
... elif ... elif ... elif ...:`), which ran all the way to the end of the
function -- nothing followed it. Because it is the function's tail, each
branch can be a sequential call that reports whether it fired, with the first
one that fires ending the pipeline (`state.done = True`): identical
first-match-wins semantics to the original `elif` chain, and identical
"nothing after this" behavior.

The mutual exclusion matters here and is NOT implicit: the multi-select
opt-out, optional-empty and final-fallback branches share the same leading
`select_type == "multi" and not required and not a grid selector` test and
their remaining clauses do not all negate one another (optional-empty in
particular does not exclude the final fallback), so more than one condition
can be true for a single attr and only the first may run.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import (
    ask_or_pending,
    commit_value as commit_value_mod,
    multi_fallback,
    multi_optout_and_empty,
    noise_var_default,
)
from aryx.cpq.auto_fill_stages.state import AttrResolution

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_commit_and_tail(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Commit a resolved value, or run the unresolved-attr fallback chain."""
    if state.done:
        return
    # Original: `if filled_multi_now: return` -- a multi-select already
    # written into ctx.filled_multi upstream needs none of what follows.
    if state.filled_multi_now:
        state.done = True
        return
    if state.value:
        commit_value_mod.commit_value(engine, attr, ctx, scope, state)
        state.done = True
        return
    if multi_optout_and_empty.try_multi_opt_out(engine, attr, ctx, scope, state):
        state.done = True
        return
    if multi_optout_and_empty.try_multi_optional_empty(
            engine, attr, ctx, scope, state):
        state.done = True
        return
    if multi_fallback.try_multi_fallback(engine, attr, ctx, scope, state):
        state.done = True
        return
    if noise_var_default.try_noise_default(engine, attr, ctx, scope, state):
        state.done = True
        return
    ask_or_pending.resolve_ask_or_pending(engine, attr, ctx, scope, state)
    state.done = True
