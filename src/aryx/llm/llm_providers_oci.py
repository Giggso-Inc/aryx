"""OCI GenAI (Cohere Command R / R+) completion paths — plain text and JSON.

Split out of `aryx.llm.llm_providers` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against these functions — confirmed via grep.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import time

from aryx.broker.specs import ModelSpec
from aryx.raven_log import raven_log, would_log

logger = logging.getLogger(__name__)


def _oci_chat_raw(
    spec: ModelSpec, system: str, user: str, max_tokens: int = 2048,
) -> tuple[str, int, int]:
    """Call OCI GenAI Chat API (Cohere Command R / R+) and return raw text.

    Uses the Chat API endpoint which is the correct path for Command R 08-2024
    and Command R+ 08-2024 models. The older GenerateText endpoint is NOT used
    as it is not supported by these model versions.
    """
    import oci  # noqa: PLC0415
    from aryx.config import get_settings
    from aryx.oci_client import get_genai_client

    settings = get_settings()
    compartment_id = settings.oci_compartment_id
    if not compartment_id:
        raise RuntimeError(
            "ARYX_OCI_COMPARTMENT_ID must be set when using OCI GenAI LLM backend"
        )

    client = get_genai_client()
    logger.debug("oci_chat model=%s prompt_chars=%d", spec.name, len(system) + len(user))
    request = oci.generative_ai_inference.models.ChatDetails(
        compartment_id=compartment_id,
        serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
            model_id=spec.name,
        ),
        chat_request=oci.generative_ai_inference.models.CohereChatRequest(
            message=user,
            preamble_override=system,
            max_tokens=max_tokens,
            temperature=0.2,
        ),
    )
    _t0 = time.monotonic()
    try:
        response = client.chat(chat_details=request)
    except Exception as exc:
        raven_log("ERROR", "P2", "llm.call.failed oci genai chat call failed",
                  error_code="ARYX_LLM_FAILED",
                  context={"dependency_name": "oci_genai", "operation": "chat", "model": spec.name,
                           "provider": "oci_genai", "role": "pipeline", "result": "error",
                           "error_class": type(exc).__name__, "attempt": 1,
                           "duration_ms": int((time.monotonic() - _t0) * 1000),
                           "input_ref": None, "output_ref": None})
        raise
    chat_response = response.data.chat_response
    text = chat_response.text.strip()
    token_count = getattr(chat_response, "token_count", None)
    if token_count is not None:
        in_tok = int(getattr(token_count, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(token_count, "completion_tokens", 0) or 0)
    else:
        in_tok = (len(system) + len(user)) // 4
        out_tok = len(text) // 4
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "llm.call.oci llm call done",
                  context={"model": spec.name, "provider": "oci_genai", "role": "pipeline",
                           "tokens_in": in_tok, "tokens_out": out_tok, "max_tokens": max_tokens,
                           "tokens_reported_by_api": token_count is not None,
                           "latency_ms": int((time.monotonic() - _t0) * 1000), "retry_count": 0})
    logger.debug("oci_chat ok model=%s response_chars=%d in_tok=%d out_tok=%d", spec.name, len(text), in_tok, out_tok)
    return text, in_tok, out_tok


def oci_genai_text(
    spec: ModelSpec, system: str, user: str,
) -> tuple[str, int, int]:
    """Call OCI GenAI Chat API for plain-text output (used by complete_text)."""
    return _oci_chat_raw(spec, system, user, max_tokens=1024)


def oci_genai_json(
    spec: ModelSpec, system: str, user: str,
    schema: "dict[str, Any] | None" = None,
) -> tuple[dict[str, Any], int, int]:
    """Call OCI GenAI Chat API (Cohere Command R / R+) for structured JSON output.

    Command R 08-2024 and later require the Chat API, not the older
    GenerateText endpoint. JSON mode is enforced via the user prompt
    instruction, including an upfront brevity cap on string fields to avoid
    verbose reasoning text overflowing `max_tokens` before the retry below
    even runs.

    Args:
        spec: Model spec identifying which OCI GenAI model to call.
        system: System prompt.
        user: User prompt; the JSON-mode and brevity instructions are
            appended to this before sending.
        schema: Optional JSON schema whose `properties`/`required` fields
            are used to name the exact fields the model must return.

    Returns:
        A 3-tuple of (parsed JSON dict, prompt tokens used, completion
        tokens used) — the latter two summed across the retry if one ran.

    Raises:
        RuntimeError: If the model's output still isn't valid JSON after
            the brevity-constrained retry.
    """
    # Cap string-field verbosity on the FIRST attempt, not just the retry
    # below -- verbose reasoning text (e.g. FK-judging "reason" fields
    # describing why two columns don't align) routinely overflowed
    # max_tokens=4096 even before the retry got a chance to run, wasting a
    # full round-trip on a failure that a brevity instruction up front avoids
    # for most cases.
    brevity_hint = " Keep every string value under 60 words."
    if schema and schema.get("properties"):
        required = schema.get("required", list(schema["properties"].keys()))
        fields_str = ", ".join(f'"{f}"' for f in required)
        json_instruction = (
            f"\n\nRespond with valid JSON only using exactly these fields: {fields_str}."
            f"{brevity_hint} Do not wrap in markdown code fences."
        )
    else:
        json_instruction = (
            f"\n\nRespond with valid JSON only.{brevity_hint} Do not wrap in markdown code fences."
        )
    generated, in_tok, out_tok = _oci_chat_raw(
        spec, system, user + json_instruction, max_tokens=4096
    )

    # Strip markdown code fences if the model ignores the instruction
    if generated.startswith("```"):
        lines = generated.splitlines()
        generated = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(generated)
    except json.JSONDecodeError:
        # If the response looks like truncated JSON (starts with '{' but doesn't
        # close), retry once with an explicit brevity constraint.  Truncation
        # happens when the model produces verbose output that exceeds max_tokens.
        logger.debug("oci_genai_json parse failed model=%s raw=%r", spec.name, generated)
        if generated.lstrip().startswith("{") and not generated.rstrip().endswith("}"):
            raven_log("WARN", "P3", "llm.retry.scheduled oci genai truncated json, retry with brevity",
                      error_code="ARYX_LLM_RETRY",
                      context={"triggering_error": "TRUNCATED_JSON", "attempt": 2, "max_attempts": 2,
                               "backoff_ms": 0, "recovery_selected": "retry_with_brevity_constraint",
                               "fallback_target": "", "exit_condition": "parse_ok_or_second_failure",
                               "result": "retry_scheduled", "model": spec.name, "provider": "oci_genai",
                               "role": "pipeline", "tokens_in": in_tok, "tokens_out": out_tok,
                               "response_len": len(generated)})
            logger.warning(
                "oci_genai_json truncated JSON detected model=%s len=%d — retrying with brevity constraint",
                spec.name, len(generated),
            )
            brevity = (
                "\n\nIMPORTANT: Be extremely concise. Each string value must be under 60 words."
                " Respond with valid JSON only. Do not wrap in markdown code fences."
            )
            retry_generated, retry_in, retry_out = _oci_chat_raw(
                spec, system, user + brevity, max_tokens=4096
            )
            if retry_generated.startswith("```"):
                retry_generated = "\n".join(
                    line for line in retry_generated.splitlines()
                    if not line.startswith("```")
                ).strip()
            try:
                data = json.loads(retry_generated)
                logger.info("oci_genai_json retry succeeded model=%s", spec.name)
                raven_log("INFO", "P4", "llm.retry.succeeded oci genai brevity retry parsed",
                          context={"model": spec.name, "provider": "oci_genai", "attempt": 2,
                                   "result": "ok", "tokens_in": in_tok + retry_in,
                                   "tokens_out": out_tok + retry_out})
                return data, in_tok + retry_in, out_tok + retry_out
            except json.JSONDecodeError:
                logger.debug("oci_genai_json retry also failed model=%s raw=%r", spec.name, retry_generated)
        raven_log("ERROR", "P2", "llm.retry.exhausted oci genai returned non-json",
                  error_code="ARYX_LLM_FAILED",
                  context={"dependency_name": "oci_genai", "operation": "oci_genai_json", "model": spec.name,
                           "provider": "oci_genai", "role": "pipeline", "result": "error",
                           "error_class": "NonJsonOutput", "tokens_in": in_tok, "tokens_out": out_tok,
                           "exit_condition": "not_truncated_or_retry_failed", "response_len": len(generated)})
        raise RuntimeError(
            f"OCI GenAI returned non-JSON output (model={spec.name!r}): "
            f"{generated[:200]!r}"
        )
    return data, in_tok, out_tok
