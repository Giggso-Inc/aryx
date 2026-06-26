"""Per-provider JSON completion paths — Anthropic / Ollama / OpenAI-compatible.

Split out of aryx.llm so each module stays under the 150-line budget.
_post_json includes 429 retry-with-backoff so callers transparently
recover from Gemini/OpenAI free-tier throttling.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any

from aryx.broker.specs import ModelSpec
from aryx.config import get_settings

logger = logging.getLogger(__name__)

# Per-call LLM timeout sourced from Settings (ARYX_LLM_TIMEOUT, default 120 s).
_DEFAULT_TIMEOUT = get_settings().llm_timeout


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
                user: str,
                schema: dict[str, Any] | None = None) -> tuple[dict[str, Any], int, int]:
    """Call an Ollama model in JSON mode via /api/chat.

    Pass `schema` to use Ollama's grammar-based structured output (format=<schema>)
    which enforces the exact JSON shape. Falls back to format="json" if omitted.
    """
    fmt: Any = schema if schema else "json"
    out = post_json(
        (spec.endpoint or "").rstrip("/") + "/api/chat",
        {"model": spec.name, "format": fmt, "stream": False,
         "think": False,
         "options": {"num_predict": 2048},
         "messages": [{"role": "system", "content": system},
                      {"role": "user", "content": user}]},
        {},
    )
    content = out["message"]["content"]
    # Thinking models (e.g. qwen3.5) may emit <think>…</think> CoT blocks —
    # strip so json.loads only sees the JSON payload.
    if "<think>" in content:
        end = content.rfind("</think>")
        content = content[end + 8:].strip() if end != -1 else content
    # qwen3.5 wraps JSON in markdown fences (```json…```) even in json mode —
    # strip them before parsing.
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        content = content.rsplit("```", 1)[0].strip()
    try:
        # strict=False allows literal control chars (e.g. unescaped \n) inside
        # string values — qwen3.5 occasionally emits these in span fields.
        data = json.loads(content, strict=False)
    except json.JSONDecodeError:
        # Fallback: extract the first {...} or [...] block via regex.
        # Handles cases where the model prepends/appends prose or has
        # structural issues the fence-strip didn't fully resolve.
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", content)
        if not m:
            logger.warning("ollama_json: no JSON block found; content=%r", content[:200])
            raise
        try:
            data = json.loads(m.group(1), strict=False)
        except json.JSONDecodeError:
            logger.warning("ollama_json: regex fallback also failed; content=%r", content[:200])
            raise
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
    logger.info("oci_chat model=%s prompt_chars=%d", spec.name, len(system) + len(user))
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
    response = client.chat(chat_details=request)
    text = response.data.chat_response.text.strip()
    in_tok = (len(system) + len(user)) // 4
    out_tok = len(text) // 4
    logger.info("oci_chat ok model=%s response_chars=%d in_tok=%d out_tok=%d", spec.name, len(text), in_tok, out_tok)
    return text, in_tok, out_tok


def oci_genai_text(
    spec: ModelSpec, system: str, user: str,
) -> tuple[str, int, int]:
    """Call OCI GenAI Chat API for plain-text output (used by complete_text)."""
    return _oci_chat_raw(spec, system, user, max_tokens=1024)


def oci_genai_json(
    spec: ModelSpec, system: str, user: str,
) -> tuple[dict[str, Any], int, int]:
    """Call OCI GenAI Chat API (Cohere Command R / R+) for structured JSON output.

    Command R 08-2024 and later require the Chat API, not the older
    GenerateText endpoint. JSON mode is enforced via the user prompt instruction.
    """
    json_instruction = "\n\nRespond with valid JSON only. Do not wrap in markdown code fences."
    generated, in_tok, out_tok = _oci_chat_raw(
        spec, system, user + json_instruction, max_tokens=2048
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
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"OCI GenAI returned non-JSON output (model={spec.name!r}): "
            f"{generated[:200]!r}"
        ) from exc
    return data, in_tok, out_tok
