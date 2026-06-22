"""Per-provider JSON completion paths — Anthropic / Ollama / OpenAI-compatible.

Split out of aryx.llm so each module stays under the 150-line budget.
_post_json includes 429 retry-with-backoff so callers transparently
recover from Gemini/OpenAI free-tier throttling.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from aryx.broker.specs import ModelSpec

logger = logging.getLogger(__name__)

# Per-call LLM timeout. Default 120s — long enough for a slow local model,
# short enough that one frozen call recovers instead of wedging the job for
# 10 minutes. Override with ARYX_LLM_TIMEOUT.
_DEFAULT_TIMEOUT = float(os.environ.get("ARYX_LLM_TIMEOUT", "120"))


def post_json(url: str, body: dict[str, Any], headers: dict[str, str],
              timeout: float | None = None) -> dict[str, Any]:
    """POST a JSON body and return the parsed JSON response.

    Retries on HTTP 429 (rate-limit) with exponential backoff capped at
    ~60s total wait so a single chunk doesn't stall the whole pipeline.
    """
    if timeout is None:
        timeout = _DEFAULT_TIMEOUT
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={**headers,
                                 "Content-Type": "application/json"})
    delay = 2.0
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            logger.warning("429 throttled — sleep %.1fs then retry (%d/5)",
                           delay, attempt + 2)
            time.sleep(delay)
            delay = min(delay * 2, 16.0)
    raise RuntimeError("unreachable")


def anthropic_json(
    spec: ModelSpec, system: str, user: str, schema: dict[str, Any],
    key: str | None,
) -> tuple[dict[str, Any], int, int]:
    """Call a Claude model with structured JSON output."""
    import anthropic  # lazy: only on the Anthropic path

    client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    resp = client.messages.create(
        model=spec.name, max_tokens=4096, system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), resp.usage.input_tokens, resp.usage.output_tokens


def ollama_json(spec: ModelSpec, system: str,
                user: str) -> tuple[dict[str, Any], int, int]:
    """Call an Ollama model in JSON mode via /api/chat."""
    out = post_json(
        (spec.endpoint or "").rstrip("/") + "/api/chat",
        {"model": spec.name, "format": "json", "stream": False,
         "messages": [{"role": "system", "content": system},
                      {"role": "user", "content": user}]},
        {},
    )
    data = json.loads(out["message"]["content"])
    return data, int(out.get("prompt_eval_count", 0)), int(out.get("eval_count", 0))


def openai_json(
    spec: ModelSpec, system: str, user: str, key: str | None,
) -> tuple[dict[str, Any], int, int]:
    """Call any OpenAI-compatible endpoint via /chat/completions (JSON mode)."""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    out = post_json(
        (spec.endpoint or "").rstrip("/") + "/chat/completions",
        {"model": spec.name, "response_format": {"type": "json_object"},
         "messages": [{"role": "system", "content": system},
                      {"role": "user", "content": user}]},
        headers,
    )
    data = json.loads(out["choices"][0]["message"]["content"])
    usage = out.get("usage", {})
    return data, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def oci_genai_json(
    spec: ModelSpec, system: str, user: str,
) -> tuple[dict[str, Any], int, int]:
    """Call an OCI Generative AI model (Cohere Command R / R+) for JSON output.

    OCI GenAI does not have a native JSON-mode flag for Cohere models; we
    instruct the model via the system prompt and parse the response manually.
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
    full_prompt = f"{system}\n\n{user}\n\nRespond with valid JSON only."

    request = oci.generative_ai_inference.models.GenerateTextDetails(
        prompts=[full_prompt],
        serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(
            model_id=spec.name
        ),
        compartment_id=compartment_id,
        inference_request=oci.generative_ai_inference.models.CohereLlmInferenceRequest(
            prompt=full_prompt,
            max_tokens=2048,
            temperature=0.2,
            return_likelihoods="NONE",
        ),
    )

    response = client.generate_text(generate_text_details=request)
    generated = response.data.inference_response.generated_texts[0].text.strip()

    # Strip markdown code fences if the model wraps the JSON
    if generated.startswith("```"):
        lines = generated.splitlines()
        generated = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()

    data = json.loads(generated)
    # OCI GenAI does not expose per-call token counts in the current SDK;
    # estimate from prompt length to keep the governor roughly accurate.
    in_tok = len(full_prompt) // 4
    out_tok = len(generated) // 4
    return data, in_tok, out_tok
