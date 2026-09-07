"""Per-attribute resolution for `CpqEngine.auto_fill` (Phase 4, the
`FillContext`/`FillScope` decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md). `resolve_one_attr` is `auto_fill`'s P1 tier -- the 6-tier
priority cascade its own docstring documents (already filled -> NL hint
-> satisfied recommendation -> XML default_value -> rule-governed
default-or-first -> first-eligible-option-by-order), plus hidden-attr
and multi-select handling woven through.

Public entry point only. The implementation was one continuous 1,500-line
decision tree in this file; it now lives in `aryx.cpq.auto_fill_stages` as
an ordered pipeline of stage modules, each holding exactly the branches it
held before (see `auto_fill_stages/coordinator.py` for the stage order and
`auto_fill_stages/state.py` for the shared state the stages thread through).
The split is mechanical and behavior-preserving; this module keeps the same
name and the same `resolve_one_attr(engine, attr, ctx, scope)` signature, so
`engine.py`'s `from aryx.cpq import auto_fill_resolve` call site is
unchanged.

`engine` is the live `CpqEngine` instance (for its own method calls,
`self.` in the original); `ctx` is a `FillContext` (mutable, shared
across every attr in one `auto_fill` call); `scope` is a `FillScope`
(read-only, includes already-bound closures for `is_pointer_default`/
`satisfied_recommendation`/`dt_never_governed_anywhere`, built once by
`auto_fill`'s own P0 setup before this loop starts).
"""
from __future__ import annotations

from aryx.cpq.auto_fill_stages.coordinator import resolve_one_attr

__all__ = ["resolve_one_attr"]
