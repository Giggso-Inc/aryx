"""Structured-JSON completion at a tier, routed to the chosen provider.

Split out of `llm.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging
import time as _time
from typing import Any

from aryx.broker import Broker
from aryx.broker.specs import ModelSpec, Tier
from aryx.llm.llm_call_log import _log_llm_call
from aryx.llm.llm_normalize import normalize as _normalize_json
from aryx.llm.llm_oci_route import _oci_model_for, _use_oci_for
from aryx.llm.llm_providers import anthropic_json, oci_genai_json, ollama_json, openai_json

logger = logging.getLogger(__name__)


def complete_json(
    broker: Broker, tier: Tier, system: str, user: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Run a structured-JSON completion at the given tier via the Broker.

    Returns the parsed JSON object the model produced, normalized to the
    schema shape (envelope coercion + synonym renaming via llm_normalize).

    When ARYX_LLM_*_BACKEND=oci the OCI path short-circuits before the broker
    registry is consulted — no local models need to be registered.
    """
    if _use_oci_for(tier):
        model_name = _oci_model_for(tier)
        spec = ModelSpec(name=model_name, provider="oci", tier=tier, endpoint="")
        _t0 = _time.monotonic()
        data, in_tok, out_tok = oci_genai_json(spec, system, user, schema)
        _ms = int((_time.monotonic() - _t0) * 1000)
        broker.charge(tier, in_tok + out_tok)
        logger.debug("complete tier=%s provider=oci model=%s tokens=%d",
                    tier, model_name, in_tok + out_tok)
        _log_llm_call(tier, model_name, "oci", in_tok, out_tok, _ms)
        return _normalize_json(data, schema)

    spec = broker.choose(tier)
    key = broker.secrets.get(spec.api_key_ref) if spec.api_key_ref else None
    if spec.provider == "anthropic":
        data, in_tok, out_tok = anthropic_json(spec, system, user, schema, key)
    elif spec.provider == "ollama":
        data, in_tok, out_tok = ollama_json(spec, system, user, schema)
    else:
        data, in_tok, out_tok = openai_json(spec, system, user, key)
    broker.charge(tier, in_tok + out_tok)
    logger.debug("complete tier=%s provider=%s model=%s tokens=%d", tier,
                spec.provider, spec.name, in_tok + out_tok)
    # Provider-quirk normalization: list-vs-dict envelope + synonym rename.
    return _normalize_json(data, schema)
