"""Base-model placeholder guard (port of aryxent PR 4).

A recommendation rule can write a PLACEHOLDER into the base-model attribute
instead of a real code -- e.g. "Set Base Model For DMSO" writes the literal
``*``. Accepting it blocks the real region-allow resolver for the rest of
the turn. Only the confirmed sentinel set is rejected, never a real code.
Gated by ``cpq_base_model_placeholder_guard_enabled`` (default off).
"""

from __future__ import annotations

from aryx.config import get_settings

_BASE_MODEL_PLACEHOLDER_VALUES: frozenset[str] = frozenset({"*"})


def is_base_model_placeholder(variable_name: str, value: str | None) -> bool:
    """True when `value` is a rule-written placeholder aimed at a
    base-model attribute and the guard flag is on."""
    if not get_settings().cpq_base_model_placeholder_guard_enabled:
        return False
    return (
        "basemodel" in (variable_name or "").lower().replace("_", "")
        and value in _BASE_MODEL_PLACEHOLDER_VALUES
    )
