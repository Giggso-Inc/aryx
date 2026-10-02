"""Adapter from the pipeline's ``Completer`` to the project's LLM entry point.

Uses ``aryx.llm.llm_runtime.chat`` — the codebase's single choke point for LLM
calls, which already routes to OCI GenAI / Anthropic / Ollama by existing
settings and records usage — so this module adds no provider, key or client of
its own. Imported lazily so the package works without LLM configuration when
authoring is not needed.
"""
from __future__ import annotations

from aryx.csv_bml_ingestion.sql_author import Completer


def project_llm_completer(role: str = "answer") -> Completer:
    """Return a completer backed by the project's configured LLM."""
    def complete(system: str, user: str) -> str:
        from aryx.llm.llm_runtime import chat  # noqa: PLC0415

        text, _in_tok, _out_tok = chat(role, system, user)
        return text

    return complete
