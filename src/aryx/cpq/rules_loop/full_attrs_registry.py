"""What the current request's rules loop learned per catalog: the full attribute list and the rule-hidden attributes.

Full list (flag ``cpq_required_set_rules_read_all_attrs_enabled``): rule inputs are read from the full attribute list,
which ``evaluate_rules_loop`` puts in its turn cache. The post-loop ``auto_fill`` of /ask step 10 shares that cache only
with ``cpq_post_loop_timeout_enabled`` on, and the recompute paths never do, so they read the ~30 visible attributes
instead: the Encryption Type rule fired in the loop and was dropped again by the post-loop call (ws 1267, APX 3000 and
APX 900, ``rule_inputs_from_all_attrs: false``).

Rule-hidden (flag ``cpq_beautify_hide_rule_hidden_enabled``): the attributes a hiding rule removed from the loop's visible
list. Beautify is built from the session's filled values over the whole catalog without re-running the hiding rules, so
a value on an attribute the real screen hides was still shown (ws 1267, APX N70 Operation Type and Provisioning
Assistance).

Both live in a context variable holding a dict keyed by (workspace, catalog prefix). A context variable is per request
(each request runs in its own copied context), so a concurrent request on another product, catalog or workspace never
sees it, and the next turn's loop replaces it. A loop run for another catalog in the same request (the country-switch
check) gets its own entry instead of replacing this one. The dict is copied on every write so a copied context never
changes its parent's, and the list is stored as a tuple so no reader can change the loop's own list.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_Key = tuple[int | None, str]
_LOOP_FACTS: ContextVar[dict[_Key, dict[str, Any]] | None] = ContextVar("aryx_cpq_loop_facts", default=None)


def _record(workspace_id: int | None, catalog_prefix: str, name: str, value: Any) -> None:
    facts = dict(_LOOP_FACTS.get() or {})
    key = (workspace_id, catalog_prefix)
    facts[key] = {**facts.get(key, {}), name: value}
    _LOOP_FACTS.set(facts)


def _read(workspace_id: int | None, catalog_prefix: str, name: str) -> Any:
    return ((_LOOP_FACTS.get() or {}).get((workspace_id, catalog_prefix)) or {}).get(name)


def remember_full_attrs(workspace_id: int | None, catalog_prefix: str, attrs: list[Any]) -> None:
    """Record the loop's full list for this request and catalog (replaces any earlier one)."""
    if attrs:
        _record(workspace_id, catalog_prefix, "full_attrs", tuple(attrs))


def full_attrs(workspace_id: int | None, catalog_prefix: str) -> list[Any] | None:
    """This request's full list for the catalog, or None when no loop ran for it."""
    stored = _read(workspace_id, catalog_prefix, "full_attrs")
    return None if stored is None else list(stored)


def remember_rule_hidden(workspace_id: int | None, catalog_prefix: str, vns: set[str]) -> None:
    """Record the attributes the loop's hiding rules removed (replaces any earlier set)."""
    _record(workspace_id, catalog_prefix, "rule_hidden", frozenset(vns))


def rule_hidden(workspace_id: int | None, catalog_prefix: str) -> frozenset[str] | None:
    """The attributes this request's loop hid by rule for the catalog, or None when no loop ran for it."""
    return _read(workspace_id, catalog_prefix, "rule_hidden")


def _clear() -> None:
    """Tests only."""
    _LOOP_FACTS.set(None)
