"""Document-processing settings — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class DocumentSettingsMixin(BaseSettings):
    per_doc_timeout: float = Field(
        default=7200.0,
        description="Wall-clock budget in seconds for a single document extraction.",
    )
    doc_workers: int = Field(
        default=1,
        description="Parallel document extraction workers (1 = sequential).",
    )
    extract_mention_workers: int = Field(
        default=4,
        description=(
            "Parallel LLM calls within extract_mentions() for a single "
            "document's chunks. Extraction used to be one chunk at a time: a "
            "50-page PDF (~330 chunks) measured at 36 minutes wall-clock; a "
            "1000+ page document scales roughly linearly to many hours at "
            "that rate, which per_doc_timeout would abandon partway through "
            "(and, before incremental persistence, lost every mention "
            "extracted so far when that happened). Raise for a cloud LLM "
            "provider (Gemini/OpenAI/Anthropic) that handles concurrent "
            "requests; keep at 1-2 for a single local Ollama instance, where "
            "parallel requests just queue with no real throughput gain. "
            "Override with ARYX_EXTRACT_MENTION_WORKERS."
        ),
    )
    extract_mention_progress_flush_chunks: int = Field(
        default=20,
        description=(
            "How often (in completed chunks) extract_mentions() invokes its "
            "progress callback, which persists the mentions extracted so far "
            "and updates the job's live stage/pct. Without this, a "
            "per_doc_timeout expiry or crash partway through a long document "
            "lost every mention extracted up to that point, since the full "
            "record list was previously only returned at the very end of "
            "extraction. Override with "
            "ARYX_EXTRACT_MENTION_PROGRESS_FLUSH_CHUNKS."
        ),
    )
