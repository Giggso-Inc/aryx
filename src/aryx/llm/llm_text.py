"""Plain-text completion at a tier, routed to the chosen provider.

Split out of `llm.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging
import time as _time
from typing import Any

import aryx.llm.llm_providers as oci_providers
from aryx.broker import Broker
from aryx.broker.specs import ModelSpec, Tier
from aryx.config import get_settings
from aryx.llm.llm_call_log import _log_llm_call
from aryx.llm.llm_oci_route import _oci_model_for, _use_oci_for
from aryx.llm.llm_providers import post_json

logger = logging.getLogger(__name__)


def complete_text(
    broker: Broker, tier: Tier, system: str, user: str,
    think: bool | None = None,
) -> tuple[str, int, int]:
    """Plain-text completion at the given tier; returns (text, in_tok, out_tok).

    `think` toggles hybrid-model reasoning on the Ollama path (False keeps fast
    models off thinking for menial work). Token counts let callers meter usage.

    When ARYX_LLM_*_BACKEND=oci the OCI path short-circuits before the broker
    registry is consulted — no local models need to be registered.
    """
    if _use_oci_for(tier):
        model_name = _oci_model_for(tier)
        spec = ModelSpec(name=model_name, provider="oci", tier=tier, endpoint="")
        _t0 = _time.monotonic()
        text, in_tok, out_tok = oci_providers.oci_genai_text(spec, system, user)
        _ms = int((_time.monotonic() - _t0) * 1000)
        broker.charge(tier, in_tok + out_tok)
        logger.debug("complete_text tier=%s provider=oci model=%s tokens=%d",
                    tier, model_name, in_tok + out_tok)
        _log_llm_call(tier, model_name, "oci", in_tok, out_tok, _ms)
        return text.strip(), in_tok, out_tok

    spec = broker.choose(tier)
    key = broker.secrets.get(spec.api_key_ref) if spec.api_key_ref else None
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": user}]
    if spec.provider == "anthropic":
        import anthropic  # lazy: only on the Anthropic path
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        resp = client.messages.create(model=spec.name, max_tokens=1024,
                                       system=system,
                                       messages=[{"role": "user", "content": user}])
        text = next(b.text for b in resp.content if b.type == "text")
        in_tok, out_tok = resp.usage.input_tokens, resp.usage.output_tokens
    elif spec.provider == "ollama":
        body: dict[str, Any] = {"model": spec.name, "stream": False,
                                "messages": msgs,
                                "options": {"temperature": 0.2,
                                            "num_predict": get_settings().llm_num_predict}}
        if think is not None:
            body["think"] = think
        out = post_json((spec.endpoint or "").rstrip("/") + "/api/chat",
                        body, {})
        text = out["message"]["content"]
        in_tok = int(out.get("prompt_eval_count", 0))
        out_tok = int(out.get("eval_count", 0))
    else:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        out = post_json((spec.endpoint or "").rstrip("/") + "/chat/completions",
                        {"model": spec.name, "messages": msgs}, headers)
        text = out["choices"][0]["message"]["content"]
        u = out.get("usage", {})
        in_tok = int(u.get("prompt_tokens", 0))
        out_tok = int(u.get("completion_tokens", 0))
    broker.charge(tier, in_tok + out_tok)
    return text.strip(), in_tok, out_tok
