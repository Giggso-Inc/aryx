"""Unified model completion: route a tiered request to the chosen provider.

The Broker decides which model serves a tier; this calls it. Four wire paths:
- 'anthropic'  -> Claude SDK (structured outputs)
- 'ollama'     -> native Ollama JSON mode
- 'oci'        -> OCI Generative AI (Cohere Command R / R+) — active when
                  ARYX_LLM_CHEAP_BACKEND=oci or ARYX_LLM_FRONTIER_BACKEND=oci
- anything else-> OpenAI-compatible /chat/completions (Grok, Gemini, vLLM, ...)

OCI path short-circuits before broker.choose() so it does not require local
models to be registered in the broker catalog.

Token usage is charged back to the governor so budgets actually bite.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`llm_call_log.py` (`_log_llm_call`), `llm_oci_route.py`
(`_oci_model_for`/`_use_oci_for`), `llm_text.py` (`complete_text`), and
`llm_json.py` (`complete_json`), all re-imported here. Zero whitebox test
patches exist anywhere against `aryx.llm.*` (confirmed via grep), so the
split was purely mechanical.
"""
from __future__ import annotations

from aryx.llm.llm_call_log import _log_llm_call
from aryx.llm.llm_json import complete_json
from aryx.llm.llm_oci_route import _oci_model_for, _use_oci_for
from aryx.llm.llm_providers import anthropic_json, ollama_json, openai_json, post_json
from aryx.llm.llm_text import complete_text

__all__ = [
    "_anthropic_json",
    "_log_llm_call",
    "_oci_model_for",
    "_ollama_json",
    "_openai_json",
    "_post_json",
    "_use_oci_for",
    "complete_json",
    "complete_text",
]

# Re-export so legacy callers keep working.
_post_json = post_json
_anthropic_json = anthropic_json
_ollama_json = ollama_json
_openai_json = openai_json
