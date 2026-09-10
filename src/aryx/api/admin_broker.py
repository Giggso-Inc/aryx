"""Pipeline broker construction for the admin/ingest APIs.

Split out of `api/admin_api.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
Re-exported from `admin_api.py` since several other modules import
`_local_broker` from there directly.
"""
from __future__ import annotations

import os

from aryx.llm import llm_runtime
from aryx.broker import Broker, ModelSpec, Registry, TokenGovernor


def _local_broker() -> Broker:
    """Pipeline broker — honours Settings → LLM Provider (live, no restart).

    Reads aryx.llm.llm_runtime.status() so the doc ingest pipeline + the Ask API
    share ONE config. Switching provider/model in the Settings panel now
    drives both. `embed_config` below is always Ollama-shaped (model +
    endpoint) — harmless when ARYX_EMBED_BACKEND is "oci" or "gemini",
    since Broker.embed() checks that global setting BEFORE ever touching
    this dict, routing to _oci_embed/_gemini_embed instead (see
    docs/LLM_GEMINI_MIGRATION_PLAN.md). Only actually used on the default
    "local" (Ollama) backend.
    """
    cfg = llm_runtime.status()
    provider = str(cfg.get("provider") or "ollama")
    endpoint = str(cfg.get("endpoint") or "http://ollama:11434")
    menial = str(cfg.get("menial_model") or "qwen3.5:0.8b")
    answer = str(cfg.get("answer_model") or "lfm2.5-thinking:latest")
    is_ollama = provider == "ollama"
    api_key_ref = None if is_ollama else llm_runtime._KEY_REF
    embed_model = os.environ.get("ARYX_EMBED_MODEL", "nomic-embed-text")
    embed_endpoint = os.environ.get(
        "ARYX_EMBED_ENDPOINT",
        endpoint if is_ollama else "http://ollama:11434",
    )
    registry = Registry()
    for name, tier in ((menial, "cheap"), (answer, "frontier")):
        registry.add(ModelSpec(name=name, provider=provider, tier=tier,
                               local=is_ollama, endpoint=endpoint,
                               api_key_ref=api_key_ref))
    return Broker(
        registry, TokenGovernor({}),
        secrets=llm_runtime._RuntimeSecrets(),
        embed_config={"model": embed_model, "endpoint": embed_endpoint},
    )
