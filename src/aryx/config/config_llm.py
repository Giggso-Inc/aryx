"""LLM provider settings — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class LlmSettingsMixin(BaseSettings):
    llm_provider: str = Field(
        default="ollama",
        description="LLM provider: ollama, openai, anthropic, or gemini.",
    )
    llm_base_url: str = Field(
        default="http://ollama:11434",
        description="Base URL for the configured LLM provider.",
    )
    llm_menial_model: str = Field(
        default="llama3.2:3b",
        description="Model name for routine/menial LLM calls.",
    )
    llm_reason_model: str = Field(
        default="llama3.2:3b",
        description="Model name for reasoning and adjudication calls.",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for cloud LLM providers (OpenAI, Anthropic, Gemini).",
    )
    llm_timeout: float = Field(
        default=900.0,
        description="Per-call HTTP timeout in seconds for LLM requests.",
    )
    llm_num_predict: int = Field(
        default=768,
        description=(
            "Max tokens Ollama generates per JSON completion call. "
            "768 fits schema-FK responses for up to ~25 entity types. "
            "Raise to 1024+ only if schema_fk returns truncated JSON. "
            "Override with ARYX_LLM_NUM_PREDICT."
        ),
    )
    bml_use_llm: bool = Field(
        default=False,
        description=(
            "Enable Tier-2 LLM fallback for BML constraint-script evaluation "
            "(aryx.cpq.bml.BmlEvaluator). Off by default: a single slow/"
            "rate-limited call can cost up to 5 retries x llm_timeout plus "
            "backoff sleeps (tens of minutes in the worst case) INSIDE one "
            "CPQ turn, since constraint evaluation runs synchronously in the "
            "request path. Disabling Tier-2 only drops evaluation for "
            "script-backed constraints Tier-1's deterministic parser can't "
            "handle — those already fell back to 'no constraint enforced' "
            "before Tier-2 existed, so this is not a new correctness gap, "
            "just reverting to that same safe fallback. Override with "
            "ARYX_BML_USE_LLM=true once the LLM provider path is fast/"
            "reliable enough not to risk stalling a live request."
        ),
    )
    bml_tier2_max_per_turn: int = Field(
        default=50,
        description=(
            "Amendment 18 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): hard "
            "ceiling on how many distinct scripts one CPQ turn's BmlEvaluator "
            "will attempt via Tier-2 LLM, across every pass of that turn's "
            "evaluate_rules_loop combined. Live-measured need: a single large "
            "catalog (900+ attrs) surfaced 823 distinct scripts needing "
            "Tier-2 in one turn before parallelization/Tier-1 idiom work — "
            "concurrency (BmlEvaluator.prefetch_tier2) and a smarter Tier-1 "
            "(evaluate_hide_master_list) both cut that dramatically, but "
            "this cap is the backstop for whatever's still left, or a "
            "different large catalog this session hasn't seen. Once "
            "reached, every FURTHER script this turn treats Tier-2 as "
            "unavailable and falls back to today's existing safe default "
            "(no constraint/hide decision derived — never a guess), exactly "
            "as if ARYX_BML_USE_LLM were off for just those extra scripts. "
            "Override with ARYX_BML_TIER2_MAX_PER_TURN."
        ),
    )
