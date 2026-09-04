"""Live runtime config state + turn-usage tracking for llm_runtime.

Split out of `llm_runtime.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero patch risk — confirmed via grep (none of these call
`complete_text`/`get_settings`/`get_pool`/`load`, the names
`tests/test_llm_runtime_turn_usage.py`/`test_llm_runtime_log_call_dsn.py`
patch).
"""
from __future__ import annotations

import contextvars

from aryx.broker import Broker, ModelSpec, Registry, TokenGovernor
from aryx.config import get_settings

# docs/CPQ_Usage_Reporting_Gap — every CPQ turn response that took a
# deterministic path hardcoded {"menial_model": "cpq-engine", ...,
# "prompt_tokens": 0, ...} regardless of whether a real LLM call happened
# during the turn (BML Tier-2 script evaluation, or any of the many
# `_llm_*` Tier-2 fallback classifiers in ask_api.py) — the partial fix
# that existed (_with_classify_usage) only covered ONE classifier at ~10
# call sites, and BmlEvaluator's own Tier-2 calls discarded their token
# counts at the source entirely.
#
# `chat()` (llm_runtime.py) is the single choke point every LLM call in
# this codebase already goes through (BML Tier-2, every ask_api.py
# classifier, the general Ask synthesis path — everything), so recording
# usage there captures real cost from any current or future caller
# automatically, with no per-call-site plumbing needed. A ContextVar (not
# a plain module dict) so concurrent requests never see each other's
# totals — FastAPI/Starlette correctly copies the context into the
# threadpool worker that runs a sync endpoint, the same guarantee asyncio
# tasks get.
_turn_usage: "contextvars.ContextVar[dict | None]" = contextvars.ContextVar(
    "_turn_usage", default=None)


def reset_turn_usage() -> None:
    """Start tracking real LLM usage for a new turn.

    Call once at the top of a request/turn handler (e.g. _run_cpq_turn).
    Every chat() call made anywhere during this turn accumulates into it
    until the next reset_turn_usage() call in this same context.
    """
    _turn_usage.set({
        "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
        "calls": 0, "models": set(),
    })


def get_turn_usage() -> dict | None:
    """Real accumulated usage for the current turn.

    None if reset_turn_usage() was never called in this context (e.g. a
    code path that doesn't opt into turn-level usage tracking) — callers
    must treat that the same as "no real usage to report", not zero.
    """
    u = _turn_usage.get()
    if u is None:
        return None
    return {**u, "models": sorted(u["models"])}

_KEY_REF = "ARYX_RUNTIME_KEY"

_cfg = get_settings()
_state: dict[str, str] = {
    "provider": _cfg.llm_provider,
    "menial_model": _cfg.llm_menial_model,
    "answer_model": _cfg.llm_reason_model,
    "endpoint": _cfg.llm_base_url,
    "api_key": _cfg.llm_api_key,
}


class _RuntimeSecrets:
    """SecretProvider returning the key entered via the Settings panel."""

    def get(self, ref: str) -> str:
        return _state["api_key"]


def _broker_for(model: str) -> Broker:
    is_ollama = _state["provider"] == "ollama"
    registry = Registry()
    registry.add(ModelSpec(
        name=model, provider=_state["provider"], tier="cheap",
        local=is_ollama, endpoint=_state["endpoint"] or None,
        api_key_ref=None if is_ollama else _KEY_REF,
    ))
    return Broker(registry, TokenGovernor({}), secrets=_RuntimeSecrets())


def set_config(**fields: str) -> None:
    """Merge non-empty Settings fields into the live config."""
    for key in ("provider", "menial_model", "answer_model", "endpoint", "api_key"):
        if fields.get(key):
            _state[key] = fields[key]


def status() -> dict[str, object]:
    """Non-secret view of the current config (key presence only)."""
    return {
        "provider": _state["provider"],
        "menial_model": _state["menial_model"],
        "answer_model": _state["answer_model"],
        "endpoint": _state["endpoint"],
        "api_key_set": bool(_state["api_key"]),
    }
