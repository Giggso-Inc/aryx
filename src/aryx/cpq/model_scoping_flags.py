"""Switches and the anchor list of the model-scoped questions (PR #475 / #480), in one place.

The flags are read with a default so that a test double standing in for the settings object (several tests build one)
does not have to carry every new flag: this module is the only place that knows about that, instead of every call
site. Imports are late on purpose: this module is reached from the engine's own import chain.
"""
from __future__ import annotations

import functools


def scoped_questions_enabled() -> bool:
    """`cpq_model_scoped_questions_enabled` (default off)."""
    from aryx.config import get_settings  # noqa: PLC0415

    return bool(getattr(get_settings(), "cpq_model_scoped_questions_enabled", False))


def tree_fallback_enabled() -> bool:
    """`cpq_model_resolution_tree_fallback_enabled` (default off)."""
    from aryx.config import get_settings  # noqa: PLC0415

    return bool(getattr(get_settings(), "cpq_model_resolution_tree_fallback_enabled", False))


def base_model_defaults_enabled() -> bool:
    """`cpq_base_model_defaults_enabled` (default off)."""
    from aryx.config import get_settings  # noqa: PLC0415

    return bool(getattr(get_settings(), "cpq_base_model_defaults_enabled", False))


@functools.cache
def scoped_anchor_vns() -> frozenset[str]:
    """The exact variable names the engine resolves itself (country, hardware version, product, base model, region).
    They are kept by the scoping and are never cleared by the not-applicable guard. A fixed list, built once."""
    from aryx.cpq.catalog_profile import REGION_LITERAL  # noqa: PLC0415
    from aryx.cpq.fill_signature import _DECISION_ANCHOR_VNS  # noqa: PLC0415

    return frozenset((*_DECISION_ANCHOR_VNS, REGION_LITERAL))
