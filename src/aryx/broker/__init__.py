"""Model Broker: roll-call, tier association, token rationing, and embeddings.

Provider-agnostic selection layer (Anthropic + Ollama + OCI GenAI + any
OpenAI-compatible endpoint). It decides which model serves a tier and enforces
budgets; actual chat invocation lives in aryx/llm.py. Embeddings run via Ollama
(local dev), OCI GenAI Cohere Embed v3 (OCI deployment), or Gemini's native
embedContent API (ARYX_EMBED_BACKEND=gemini) — the latter is NOT the same
wire protocol as chat's OpenAI-compatible path, so it gets its own method.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), model
discovery/registration (`add_ollama`/`add_openai_endpoint`) and the
per-backend embed implementations moved to `broker/embed_backends.py`
(mixed into `Broker` as `_BrokerMixin`), and the two factory functions
moved to `broker/factories.py`, both re-imported here. Zero whitebox test
patches exist anywhere against `aryx.broker.*` (confirmed via grep), so
the split was purely mechanical.
"""
from __future__ import annotations

import logging

from aryx.broker.embed_backends import _BrokerMixin
from aryx.broker.factories import default_broker, oci_broker
from aryx.broker.governor import TokenGovernor
from aryx.broker.registry import Registry
from aryx.broker.secrets import EnvSecretProvider, SecretProvider
from aryx.broker.specs import TIER_LADDER, ModelSpec, Tier

logger = logging.getLogger(__name__)

__all__ = ["Broker", "default_broker", "ModelSpec", "oci_broker", "Registry", "TokenGovernor"]


class Broker(_BrokerMixin):
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
        from aryx.broker.embed_backends import _GEMINI_EMBED_MODEL, _OCI_EMBED_MODEL
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
