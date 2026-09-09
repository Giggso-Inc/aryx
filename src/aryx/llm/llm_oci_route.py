"""OCI GenAI routing decisions: which model/tier short-circuits to OCI.

Split out of `llm.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

from aryx.broker.specs import Tier


def _oci_model_for(tier: Tier) -> str:
    """Return the OCI GenAI model ID for the given tier, respecting overrides."""
    from aryx.config import get_settings
    settings = get_settings()
    if tier == "cheap":
        return settings.llm_cheap_model_override or "cohere.command-r-08-2024"
    return settings.llm_frontier_model_override or "cohere.command-r-plus-08-2024"


def _use_oci_for(tier: Tier) -> bool:
    """Return True if the given tier is configured to use OCI GenAI."""
    from aryx.config import get_settings
    settings = get_settings()
    if tier == "cheap":
        return settings.effective_llm_cheap_backend() == "oci"
    if tier == "frontier":
        return settings.effective_llm_frontier_backend() == "oci"
    return False
