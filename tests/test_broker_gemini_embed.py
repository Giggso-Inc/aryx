"""Broker._gemini_embed — Phase 2 of the Grok-to-Gemini migration.

docs/LLM_GEMINI_MIGRATION_PLAN.md §4: Gemini's embedding API is NOT the
OpenAI-compatible surface chat uses — different wire protocol (API key in a
dedicated header, "values"-nested response), so it needs its own dispatch branch
and its own method rather than reusing openai_json/_ollama_embed.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.broker import Broker
from aryx.broker.governor import TokenGovernor
from aryx.broker.registry import Registry


def _settings(**overrides: object) -> SimpleNamespace:
    """Build the minimal settings object required by embedding tests."""
    base = {"llm_api_key": "test-gemini-key", "embed_model_override": ""}
    base.update(overrides)
    return SimpleNamespace(**base)


def _broker() -> Broker:
    """Build a broker without registered chat models."""
    return Broker(Registry(), TokenGovernor({}))


def test_embed_dispatches_to_gemini_when_backend_configured() -> None:
    """Gemini configuration routes embedding requests to its native API."""
    broker = _broker()
    settings = _settings()
    fake_response = {"embeddings": [{"values": [0.1] * 768}, {"values": [0.2] * 768}]}

    with patch("aryx.config.get_settings") as mock_get_settings, \
         patch("aryx.llm_providers.post_json", return_value=fake_response) as mock_post:
        mock_get_settings.return_value = SimpleNamespace(
            effective_embed_backend=lambda: "gemini", **vars(settings),
        )
        vectors = broker.embed(["hello", "world"])

    assert vectors == [[0.1] * 768, [0.2] * 768]
    assert mock_post.called
    url, body, headers = mock_post.call_args[0]
    assert "batchEmbedContents" in url
    assert "key=" not in url
    assert headers == {"x-goog-api-key": "test-gemini-key"}
    assert len(body["requests"]) == 2
    assert body["requests"][0]["outputDimensionality"] == 768
    assert body["requests"][0]["content"]["parts"][0]["text"] == "hello"


def test_gemini_embed_defaults_model_when_no_override() -> None:
    """Gemini embedding uses the supported stable model by default."""
    broker = _broker()
    settings = _settings(embed_model_override="")
    fake_response = {"embeddings": [{"values": [0.0] * 768}]}

    with patch("aryx.config.get_settings") as mock_get_settings, \
         patch("aryx.llm_providers.post_json", return_value=fake_response) as mock_post:
        mock_get_settings.return_value = SimpleNamespace(
            effective_embed_backend=lambda: "gemini", **vars(settings),
        )
        broker.embed(["x"])

    url = mock_post.call_args[0][0]
    assert "gemini-embedding-2" in url


def test_gemini_embed_respects_model_override() -> None:
    """An explicit Gemini embedding model overrides the default."""
    broker = _broker()
    settings = _settings(embed_model_override="custom-gemini-embed")
    fake_response = {"embeddings": [{"values": [0.0] * 768}]}

    with patch("aryx.config.get_settings") as mock_get_settings, \
         patch("aryx.llm_providers.post_json", return_value=fake_response) as mock_post:
        mock_get_settings.return_value = SimpleNamespace(
            effective_embed_backend=lambda: "gemini", **vars(settings),
        )
        broker.embed(["x"])

    url, body, _headers = mock_post.call_args[0]
    assert "custom-gemini-embed" in url
    assert body["requests"][0]["model"] == "models/custom-gemini-embed"


def test_gemini_embed_raises_without_api_key() -> None:
    """Gemini embedding fails closed when no API key is configured."""
    broker = _broker()
    settings = _settings(llm_api_key="")

    with patch("aryx.config.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(
            effective_embed_backend=lambda: "gemini", **vars(settings),
        )
        try:
            broker.embed(["x"])
        except RuntimeError as exc:
            assert "ARYX_LLM_API_KEY" in str(exc)
        else:
            raise AssertionError("expected RuntimeError for missing API key")


def test_embed_still_dispatches_to_ollama_by_default() -> None:
    """Backward compatibility: an unset/'local' backend must NOT be routed
    to Gemini or OCI — the existing Ollama path stays the default."""
    broker = Broker(Registry(), TokenGovernor({}), embed_config={})
    with patch("aryx.config.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(
            effective_embed_backend=lambda: "local",
        )
        vectors = broker.embed(["x"])

    assert vectors == [], "no endpoint/model configured -> empty list, not an exception"


def test_embed_model_id_uses_gemini_default() -> None:
    """Persisted vectors carry the default Gemini model identity."""
    broker = _broker()
    settings = _settings()

    with patch("aryx.config.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(
            effective_embed_backend=lambda: "gemini", **vars(settings),
        )
        model_id = broker.embed_model_id

    assert model_id == "gemini-embedding-2"


def test_embed_model_id_uses_gemini_override() -> None:
    """Persisted vectors carry an explicitly configured Gemini model identity."""
    broker = _broker()
    settings = _settings(embed_model_override="custom-gemini-embed")

    with patch("aryx.config.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(
            effective_embed_backend=lambda: "gemini", **vars(settings),
        )
        model_id = broker.embed_model_id

    assert model_id == "custom-gemini-embed"


def test_embed_model_id_preserves_local_catalog_model() -> None:
    """The backend-aware identity change preserves the local model label."""
    broker = Broker(
        Registry(),
        TokenGovernor({}),
        embed_config={"model": "nomic-embed-text", "endpoint": "http://ollama:11434"},
    )

    with patch("aryx.config.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(
            effective_embed_backend=lambda: "local",
        )
        model_id = broker.embed_model_id

    assert model_id == "nomic-embed-text"


def test_embed_model_id_uses_oci_default() -> None:
    """The backend-aware identity change preserves OCI's default model label."""
    broker = _broker()
    settings = _settings()

    with patch("aryx.config.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(
            effective_embed_backend=lambda: "oci", **vars(settings),
        )
        model_id = broker.embed_model_id

    assert model_id == "cohere.embed-multilingual-v3.0"
