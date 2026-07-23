"""Model Broker: roll-call, tier association, token rationing, and embeddings.

Provider-agnostic selection layer (Anthropic + Ollama + OCI GenAI + any
OpenAI-compatible endpoint). It decides which model serves a tier and enforces
budgets; actual chat invocation lives in aryx/llm.py. Embeddings run via Ollama
(local dev), OCI GenAI Cohere Embed v3 (OCI deployment), or Gemini's native
embedContent API (ARYX_EMBED_BACKEND=gemini) — the latter is NOT the same
wire protocol as chat's OpenAI-compatible path, so it gets its own method.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

from aryx.broker.discovery import (
    anthropic_catalog,
    discover_ollama,
    discover_openai_compatible,
)
from aryx.broker.governor import TokenGovernor
from aryx.broker.registry import Registry
from aryx.broker.secrets import EnvSecretProvider, SecretProvider
from aryx.broker.specs import TIER_LADDER, ModelSpec, Tier

logger = logging.getLogger(__name__)

_CATALOG = Path(__file__).parent / "catalog.json"
_OCI_EMBED_MODEL = "cohere.embed-multilingual-v3.0"
_GEMINI_EMBED_MODEL = "gemini-embedding-2"
_GEMINI_EMBED_DIM = 768

__all__ = ["Broker", "default_broker", "ModelSpec", "oci_broker", "Registry", "TokenGovernor"]


class Broker:
    """Chooses a model for a requested tier, honoring token budgets."""

    def __init__(
        self,
        registry: Registry,
        governor: TokenGovernor,
        secrets: SecretProvider | None = None,
        embed_config: dict[str, str] | None = None,
    ) -> None:
        """Wire the broker to a registry, governor, secrets, and embed config."""
        self._registry = registry
        self._governor = governor
        self.secrets = secrets or EnvSecretProvider()
        self._embed = embed_config or {}

    def add_ollama(self, host: str) -> int:
        """Discover and register an Ollama instance's models; return the count."""
        specs = discover_ollama(host)
        for spec in specs:
            self._registry.add(spec)
        return len(specs)

    def add_openai_endpoint(
        self, base_url: str, provider: str, tier: Tier = "mid",
        api_key_ref: str | None = None,
    ) -> int:
        """Discover + register models from an OpenAI-compatible endpoint.

        Covers Grok (xAI), Gemini, OpenRouter, vLLM, LM Studio, etc.
        """
        key = self.secrets.get(api_key_ref) if api_key_ref else None
        specs = discover_openai_compatible(
            base_url, provider, tier=tier, api_key=key, api_key_ref=api_key_ref
        )
        for spec in specs:
            self._registry.add(spec)
        return len(specs)

    def register(self, spec: ModelSpec) -> None:
        """Hand-register a single model (manual config path)."""
        self._registry.add(spec)

    def choose(self, tier: Tier) -> ModelSpec:
        """Pick a model for the tier, downgrading if its budget is spent."""
        effective = self._governor.effective_tier(tier)
        for candidate in TIER_LADDER[TIER_LADDER.index(effective):]:
            options = self._registry.by_tier(candidate)
            if options:
                return options[0]
        raise LookupError(f"no model available for tier '{tier}'")

    def charge(self, tier: Tier, tokens: int) -> None:
        """Record spend so subsequent choices can downgrade."""
        self._governor.charge(tier, tokens)

    @property
    def embed_model_id(self) -> str | None:
        """Return the model identity for the effective embedding backend."""
        from aryx.config import get_settings

        settings = get_settings()
        backend = settings.effective_embed_backend()
        if backend == "gemini":
            return settings.embed_model_override or _GEMINI_EMBED_MODEL
        if backend == "oci":
            return settings.embed_model_override or _OCI_EMBED_MODEL
        return self._embed.get("model") or None

    def models(self) -> list[ModelSpec]:
        """Return every registered model (for the setup UI roll-call)."""
        return self._registry.all()

    def embed(self, texts: list[str],
              input_type: str = "SEARCH_DOCUMENT") -> list[list[float]]:
        """Embed texts via the configured backend (Ollama, OCI GenAI, or Gemini).

        Args:
            texts: Texts to embed.
            input_type: Cohere input type hint for the OCI path.
                Use "SEARCH_DOCUMENT" when indexing (default) and
                "SEARCH_QUERY" when embedding a search query at retrieval time.
                Ignored on the local Ollama and Gemini paths.

        Returns an empty list if no embed model is configured, so callers can
        gracefully fall back to string-only similarity. Also returns an empty
        list — never a short/misaligned one — if the backend's vector count
        doesn't match len(texts): every real caller (pipeline/embed.py's
        embed_chunks, resolution/run.py's _block_embeddings) zips the result
        positionally against its input with no independent count check of
        its own, so a partial-batch response (a plausible edge case on any
        of the 3 backends — a 200-OK reply that's structurally short) would
        otherwise silently attribute a vector to the wrong text/chunk rather
        than failing loudly. Checked ONCE here, at the shared chokepoint all
        3 backends and every caller go through, rather than duplicated per
        backend or per call site — this exact count check already existed,
        duplicated, only in scripts/reembed_gemini.py's own batch helper.
        """
        from aryx.config import get_settings
        settings = get_settings()
        backend = settings.effective_embed_backend()
        if backend == "oci":
            result = self._oci_embed(texts, settings, input_type=input_type)
        elif backend == "gemini":
            result = self._gemini_embed(texts, settings)
        else:
            result = self._ollama_embed(texts)
        if result and len(result) != len(texts):
            logger.error(
                "broker.embed() backend=%s returned %d vector(s) for %d text(s) "
                "— discarding to avoid a misaligned embedding-to-text mapping",
                backend, len(result), len(texts),
            )
            return []
        return result

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
        from aryx.llm_providers import post_json  # noqa: PLC0415

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


def default_broker() -> Broker:
    """Build a Broker seeded from catalog.json plus the Claude catalog."""
    data = json.loads(_CATALOG.read_text(encoding="utf-8"))
    registry = Registry()
    for entry in data.get("models", []):
        registry.add(ModelSpec(**entry))
    for spec in anthropic_catalog():
        registry.add(spec)
    return Broker(registry, TokenGovernor(data.get("budgets", {})),
                  embed_config=data.get("embed", {}))


def oci_broker() -> Broker:
    """Build a Broker with OCI GenAI models for use inside OCI Functions."""
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
