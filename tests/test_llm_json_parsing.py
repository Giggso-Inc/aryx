"""_parse_llm_json / openai_json / ollama_json robustness against non-strict
JSON output from "thinking" models.

Real incident: gemini-pro-latest calls in _relate_isolated() failed with
"Extra data: line N column M" on nearly every call — the model's response
content was valid JSON followed by trailing text, and openai_json() used a
plain json.loads() that requires the ENTIRE string to be valid JSON with
nothing extra. Every isolated-entity-linking call silently failed as a
result, leaving hundreds of thousands of entities isolated in the graph.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from aryx.llm_providers import _parse_llm_json, ollama_json, openai_json
from aryx.broker.specs import ModelSpec


def test_parse_plain_json() -> None:
    assert _parse_llm_json('{"related": true}', "t") == {"related": True}


def test_parse_trailing_extra_data() -> None:
    """The exact failure mode: valid JSON followed by trailing text."""
    content = '{"related": true, "name": "is_material_of", "confidence": 0.8}\nNote: inferred from shared FSC group.'
    assert _parse_llm_json(content, "t") == {
        "related": True, "name": "is_material_of", "confidence": 0.8,
    }


def test_parse_markdown_fenced_json() -> None:
    content = '```json\n{"related": false}\n```'
    assert _parse_llm_json(content, "t") == {"related": False}


def test_parse_think_block_prefix() -> None:
    content = '<think>reasoning about the entities</think>\n{"related": false}'
    assert _parse_llm_json(content, "t") == {"related": False}


def test_parse_prose_prefixed_json() -> None:
    content = 'Here is my answer:\n{"related": true, "name": "x", "confidence": 0.5}'
    assert _parse_llm_json(content, "t") == {
        "related": True, "name": "x", "confidence": 0.5,
    }


def test_parse_unparseable_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        _parse_llm_json("not json at all, no braces", "t")


def test_openai_json_survives_trailing_extra_data() -> None:
    spec = ModelSpec(name="gemini-pro-latest", provider="gemini", tier="frontier",
                      local=False, endpoint="https://example.test")
    fake_response = {
        "choices": [{"message": {
            "content": '{"related": true, "name": "rel", "confidence": 0.9}\nextra trailing text',
        }}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    with patch("aryx.llm_providers.post_json", return_value=fake_response):
        data, pt, ct = openai_json(spec, "system", "user", "key")
    assert data == {"related": True, "name": "rel", "confidence": 0.9}
    assert (pt, ct) == (10, 5)


def test_ollama_json_survives_trailing_extra_data() -> None:
    spec = ModelSpec(name="qwen3.5", provider="ollama", tier="cheap",
                      local=True, endpoint="http://ollama:11434")
    fake_response = {
        "message": {"content": '{"related": false}\ntrailing commentary'},
        "prompt_eval_count": 8, "eval_count": 3,
    }
    with patch("aryx.llm_providers.post_json", return_value=fake_response):
        data, pt, ct = ollama_json(spec, "system", "user")
    assert data == {"related": False}
    assert (pt, ct) == (8, 3)
