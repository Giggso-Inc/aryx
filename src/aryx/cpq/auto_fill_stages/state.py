"""``AttrResolution`` -- the mutable per-attribute state the `resolve_one_attr`
stage pipeline threads through every stage (docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md, the `auto_fill_resolve` stage split).

Every field here was a plain local in the original single 1,500-line
`resolve_one_attr` function body. The function was one continuous decision
tree -- several sequential/nested if/elif chains reading and writing those
same locals from top to bottom -- so the only behavior-preserving way to
split it across modules is to promote the shared locals to one mutable
object and gate the stages on `done`.

`done` replaces the original's bare `return` statements: a stage that would
have returned out of the whole function sets `done = True` and returns, and
every later stage (and the coordinator) skips itself while `done` is set.

One deliberate, documented difference from the original locals: in the
original body `allowed_for_attr` was only BOUND inside the
`if not value and attr.options:` branch, yet is read again much later by the
optional-empty multi-select fallback -- for an attr that never entered that
branch (no options at all) the original would have raised
`UnboundLocalError` there. `None` (the default here) is what that read
already expected in every reachable real case ("no active constraint
narrowed this attr"), and is the value that branch's own guard is written
against; the unbound-name crash is not preserved.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AttrResolution:
    """Mutable resolution state for one attribute in one `auto_fill` pass."""

    vn: str = ""
    vn_flat: str = ""
    value: str | None = None
    display: str | None = None
    source: str = "auto"
    fired_rule_name: str | None = None
    filled_multi_now: bool = False
    is_decision_attr: bool = False
    is_governed: bool = False
    governed_source: str = ""
    allowed_for_attr: set[str] | None = None
    valid_opts: list = field(default_factory=list)
    done: bool = False
