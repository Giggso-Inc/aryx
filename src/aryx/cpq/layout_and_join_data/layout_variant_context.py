"""Which model node a turn is on, for choosing a layout variant.

The ask flow binds the node once per turn (contextvar, same pattern as
``aryx.cpq.model_resolution.bind_turn``) so the ~20 callers of
``load_layout_display_order`` need no change. Sources, in order:
(1) the bound ``_bm_model_variable_name`` (session.filled / hints),
(2) the bound model-resolution turn's chosen node name (when resolution is on).
Neither depends on ``cpq_model_resolution_enabled``.
"""

from __future__ import annotations

import contextvars

from aryx.config import get_settings

# Platform constant: the model-context attribute BM injects at runtime.
MODEL_NODE_VAR = "_bm_model_variable_name"

_node_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cpq_layout_model_node", default=None,
)


def layout_variants_enabled() -> bool:
    """True when the ``cpq_layout_variants_enabled`` setting is on."""
    return bool(getattr(get_settings(), "cpq_layout_variants_enabled", False))


def bind_layout_model_node(node_var: str | None) -> None:
    """Bind (or clear, with None) this turn's model node name."""
    _node_var.set(node_var.strip() or None if isinstance(node_var, str) else None)


def current_model_node() -> str | None:
    """Model node for this turn: the bound variable name, else the bound
    model-resolution turn's chosen node name, else None."""
    bound = _node_var.get()
    if bound:
        return bound
    from aryx.cpq import model_resolution  # noqa: PLC0415 -- lazy, heavy chain
    turn = model_resolution.get_turn()
    chosen = turn.resolution.chosen if turn is not None else None
    return (getattr(chosen, "node_name", None) or None) if chosen is not None else None


def current_governed_names(workspace_id: int, catalog_prefix: str) -> set[str]:
    """Attribute names the bound model's data tables govern (coverage
    fallback input); empty when no resolved turn is bound."""
    from aryx.cpq import model_resolution  # noqa: PLC0415
    from aryx.cpq.data_table.data_table_governance import (  # noqa: PLC0415
        governed_attr_names_for_base_model,
    )
    turn = model_resolution.get_turn()
    chosen = turn.resolution.chosen if turn is not None else None
    if chosen is None:
        return set()
    names: set[str] = set()
    for base_model in sorted(chosen.base_models):
        got = governed_attr_names_for_base_model(
            chosen.cpq_model, base_model, workspace_id, catalog_prefix)
        names.update(got or ())
    return names
