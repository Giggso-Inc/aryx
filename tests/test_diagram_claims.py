"""Contract tests for security and grounding claims in client diagrams."""
from __future__ import annotations

from pathlib import Path


_ASK_OVERVIEW = Path("docs/diagrams/ask-overview.html")
_MIGRATION_PLAN = Path("docs/LLM_GEMINI_MIGRATION_PLAN.md")


def test_ask_overview_does_not_claim_workspace_key_ownership() -> None:
    """The diagram must not promise tenant authorization absent from the API."""
    html = _ASK_OVERVIEW.read_text(encoding="utf-8")

    assert "confirmed to belong to the caller's API key" not in html


def test_ask_overview_does_not_claim_unsupported_claim_filtering() -> None:
    """Grounding coverage must not be described as claim verification."""
    html = _ASK_OVERVIEW.read_text(encoding="utf-8")

    assert "Anything the answer claims that isn't backed up" not in html
    assert "unconfirmed claims flagged" not in html


def test_migration_plan_does_not_recommend_retired_embedding_model() -> None:
    """Migration guidance must reference only supported Gemini models."""
    plan = _MIGRATION_PLAN.read_text(encoding="utf-8")

    assert "text-embedding-004" not in plan
