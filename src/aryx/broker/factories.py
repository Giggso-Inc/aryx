"""Broker factory functions: catalog-seeded default, and OCI-Functions-only.

Split out of `broker/__init__.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aryx.broker import Broker

from aryx.broker.discovery import anthropic_catalog
from aryx.broker.governor import TokenGovernor
from aryx.broker.registry import Registry
from aryx.broker.specs import ModelSpec

_CATALOG = Path(__file__).parent / "catalog.json"


def default_broker() -> "Broker":
    """Build a Broker seeded from catalog.json plus the Claude catalog."""
    from aryx.broker import Broker  # noqa: PLC0415 — avoid a circular import at module load

    data = json.loads(_CATALOG.read_text(encoding="utf-8"))
    registry = Registry()
    for entry in data.get("models", []):
        registry.add(ModelSpec(**entry))
    for spec in anthropic_catalog():
        registry.add(spec)
    return Broker(registry, TokenGovernor(data.get("budgets", {})),
                  embed_config=data.get("embed", {}))


def oci_broker() -> "Broker":
    """Build a Broker with OCI GenAI models for use inside OCI Functions."""
    from aryx.broker import Broker  # noqa: PLC0415 — avoid a circular import at module load
    from aryx.config import get_settings

    settings = get_settings()
    registry = Registry()
    registry.add(ModelSpec(
        name=settings.llm_cheap_model_override or "cohere.command-r-08-2024",
        provider="oci", tier="cheap", local=False, endpoint="",
    ))
    registry.add(ModelSpec(
        name=settings.llm_frontier_model_override or "cohere.command-r-plus-08-2024",
        provider="oci", tier="frontier", local=False, endpoint="",
    ))
    return Broker(
        registry,
        TokenGovernor({}),
        embed_config={
            "provider": "oci",
            "model": settings.embed_model_override or "cohere.embed-multilingual-v3.0",
        },
    )
