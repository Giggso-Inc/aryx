"""Model discovery/registration + per-backend embedding implementations.

Split out of `broker/__init__.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03) as a mixin so `Broker` keeps these methods on `self` while the
backend-specific wire-protocol details live in their own file. Zero test
patches against this module — confirmed via grep.
"""
from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

_OCI_EMBED_MODEL = "cohere.embed-multilingual-v3.0"
_GEMINI_EMBED_MODEL = "gemini-embedding-2"
_GEMINI_EMBED_DIM = 768


class _BrokerMixin:
    """Backend-specific embed() implementations, mixed into Broker."""

    def add_ollama(self, host: str) -> int:
        """Discover and register an Ollama instance's models; return the count."""
        from aryx.broker.discovery import discover_ollama

        specs = discover_ollama(host)
        for spec in specs:
            self._registry.add(spec)
        return len(specs)

    def add_openai_endpoint(
        self, base_url: str, provider: str, tier: str = "mid",
        api_key_ref: str | None = None,
    ) -> int:
        """Discover + register models from an OpenAI-compatible endpoint.

        Covers Grok (xAI), Gemini, OpenRouter, vLLM, LM Studio, etc.
        """
        from aryx.broker.discovery import discover_openai_compatible

        key = self.secrets.get(api_key_ref) if api_key_ref else None
        specs = discover_openai_compatible(
            base_url, provider, tier=tier, api_key=key, api_key_ref=api_key_ref
        )
        for spec in specs:
            self._registry.add(spec)
        return len(specs)

    def _ollama_embed(self, texts: list[str]) -> list[list[float]]:
        """Embed via local Ollama /api/embed endpoint."""
        endpoint = self._embed.get("endpoint", "")
        if not self._embed.get("model") or not endpoint:
            return []
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError(f"broker: Ollama endpoint must be http(s)://: {endpoint!r}")
        logger.debug("ollama_embed model=%s texts=%d endpoint=%s", self._embed["model"], len(texts), endpoint)
        body = json.dumps({"model": self._embed["model"], "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/api/embed",
            data=body, headers={"Content-Type": "application/json"},
        )
        from aryx.config import get_settings
        embed_timeout = get_settings().embed_http_timeout
        with urllib.request.urlopen(req, timeout=embed_timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        embeddings = payload.get("embeddings", [])
        logger.debug("ollama_embed ok vectors=%d dim=%d", len(embeddings), len(embeddings[0]) if embeddings else 0)
        return embeddings

    def _oci_embed(self, texts: list[str], settings: object,
                  input_type: str = "SEARCH_DOCUMENT") -> list[list[float]]:
        """Embed via OCI Generative AI (Cohere Embed v3)."""
        import oci  # noqa: PLC0415
        from aryx.oci_client import get_genai_client

        model_id = (
            getattr(settings, "embed_model_override", "") or
            _OCI_EMBED_MODEL
        )
        compartment_id = getattr(settings, "oci_compartment_id", "")
        if not compartment_id:
            raise RuntimeError(
                "ARYX_OCI_COMPARTMENT_ID must be set when ARYX_EMBED_BACKEND=oci"
            )
        client = get_genai_client()
        logger.debug("oci_embed model=%s texts=%d", model_id, len(texts))
        request = oci.generative_ai_inference.models.EmbedTextDetails(
            inputs=texts,
            serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
                model_id=model_id
            ),
            compartment_id=compartment_id,
            input_type=input_type,
        )
        response = client.embed_text(embed_text_details=request)
        embeddings = response.data.embeddings
        dim = len(embeddings[0]) if embeddings else 0
        logger.debug("oci_embed ok vectors=%d dim=%d", len(embeddings), dim)
        return embeddings

    def _gemini_embed(self, texts: list[str], settings: object) -> list[list[float]]:
        """Embed via Gemini's native batchEmbedContents API.

        NOT the OpenAI-compatible surface chat uses (aryx/llm.py) — Gemini's
        embedding API is its own protocol: API key in the `x-goog-api-key`
        header, and a request/response shape with an extra "values" nesting
        level vs. Ollama's flat vector lists. `output_dimensionality` is always
        sent explicitly (768, matching the existing
        `aryx_chunk_embedding.embedding vector(768)` column) — required for
        gemini-embedding-2 (3072-dim by default; Google's own docs recommend
        truncating to 768 for production, with auto-normalization) — see
        docs/LLM_GEMINI_MIGRATION_PLAN.md §4.3 for why this is pinned rather
        than widening the column.
        """
        from aryx.llm.llm_providers import post_json  # noqa: PLC0415

        key = getattr(settings, "llm_api_key", "") or ""
        if not key:
            raise RuntimeError(
                "ARYX_LLM_API_KEY must be set when ARYX_EMBED_BACKEND=gemini "
                "(the same key already used for Gemini chat covers embeddings)"
            )
        model_id = getattr(settings, "embed_model_override", "") or _GEMINI_EMBED_MODEL
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_id}:batchEmbedContents"
        )
        body = {
            "requests": [
                {
                    "model": f"models/{model_id}",
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": _GEMINI_EMBED_DIM,
                }
                for t in texts
            ],
        }
        logger.debug("gemini_embed model=%s texts=%d", model_id, len(texts))
        payload = post_json(url, body, {"x-goog-api-key": key})
        embeddings = [e.get("values", []) for e in payload.get("embeddings", [])]
        dim = len(embeddings[0]) if embeddings else 0
        logger.debug("gemini_embed ok vectors=%d dim=%d", len(embeddings), dim)
        return embeddings
