"""Anthropic (Claude) structured-JSON completion path.

Split out of `aryx.llm.llm_providers` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this function — confirmed via grep.
"""
from __future__ import annotations

import json
from typing import Any

from aryx.broker.specs import ModelSpec


def anthropic_json(
    spec: ModelSpec, system: str, user: str, schema: dict[str, Any],
    key: str | None,
) -> tuple[dict[str, Any], int, int]:
    """Call a Claude model with structured JSON output."""
    import anthropic  # lazy: only on the Anthropic path

    client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    resp = client.messages.create(
        model=spec.name, max_tokens=4096, system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), resp.usage.input_tokens, resp.usage.output_tokens
