"""The full attribute list of the current request's rules loop, for the required set's rule inputs.

Flag ``cpq_required_set_rules_read_all_attrs_enabled`` reads rule inputs from the full attribute list, which
``evaluate_rules_loop`` puts in its turn cache. The post-loop ``auto_fill`` of /ask step 10 shares that cache only with
``cpq_post_loop_timeout_enabled`` on, and the recompute paths never do, so they read the ~30 visible attributes
instead: the Encryption Type rule fired in the loop and was dropped again by the post-loop call (ws 1267, APX 3000 and
APX 900, ``rule_inputs_from_all_attrs: false``).

The loop now also records its list in a context variable. A context variable is per request (each request runs in
its own copied context), so a concurrent request on another product, catalog or workspace never sees it, and the next
turn's loop replaces it. The list is stored as a tuple so no reader can change the loop's own list.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_FULL_ATTRS: ContextVar[tuple[tuple[int | None, str], tuple[Any, ...]] | None] = ContextVar(
    "aryx_cpq_full_attrs", default=None)


def remember_full_attrs(workspace_id: int | None, catalog_prefix: str, attrs: list[Any]) -> None:
    """Record the loop's full list for this request (replaces any earlier one)."""
    if attrs:
        _FULL_ATTRS.set(((workspace_id, catalog_prefix), tuple(attrs)))


def full_attrs(workspace_id: int | None, catalog_prefix: str) -> list[Any] | None:
    """This request's full list when its loop ran for the same catalog, else None."""
    entry = _FULL_ATTRS.get()
    if entry is None or entry[0] != (workspace_id, catalog_prefix):
        return None
    return list(entry[1])


def _clear() -> None:
    """Tests only."""
    _FULL_ATTRS.set(None)
