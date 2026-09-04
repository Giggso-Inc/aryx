"""Per-provider JSON completion paths — Anthropic / Ollama / OpenAI-compatible.

Split out of aryx.llm so each module stays under the 150-line budget.
_post_json includes 429 retry-with-backoff so callers transparently
recover from Gemini/OpenAI free-tier throttling.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), the
Anthropic and OCI GenAI providers moved to `llm_providers_anthropic.py`/
`llm_providers_oci.py` (zero patch risk, confirmed via grep). `post_json`
stays here with `ollama_json`/`openai_json` because it is directly
whitebox-patched (`aryx.llm_providers.post_json`) by
`tests/test_llm_json_parsing.py` and `tests/test_broker_gemini_embed.py`,
and both callers reach it by bare name within this module.
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
from aryx.llm_providers_anthropic import anthropic_json
from aryx.llm_providers_oci import _oci_chat_raw, oci_genai_json, oci_genai_text

__all__ = [
    "anthropic_json",
    "oci_genai_json",
    "oci_genai_text",
    "ollama_json",
    "openai_json",
    "post_json",
]

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
        except (urllib.error.URLError, OSError) as exc:
            # Transient network errors (DNS blip, connection reset, ECONNREFUSED).
            # Docker's embedded DNS occasionally fails under concurrent thread load.
            if attempt == 4:
                raise
            logger.warning("network error — sleep %.1fs then retry (%d/5): %s",
                           delay, attempt + 2, exc)
            time.sleep(delay)
            delay = min(delay * 2, 16.0)
    raise RuntimeError("unreachable")


def _parse_llm_json(content: str, log_prefix: str) -> dict[str, Any]:
    """Robustly extract a JSON object/array from a chat model's text content.

    Thinking-tier models (Ollama's qwen3.5, Gemini's *-pro-latest, etc.) do
    not reliably emit ONLY the JSON payload even when JSON mode is requested:
    they may wrap it in markdown fences, prepend/append a reasoning trace, or
    emit a JSON object followed by trailing commentary — the last of which
    fails plain json.loads() with "Extra data" (a real incident: gemini-pro-latest
    calls in _relate_isolated() failed this way on nearly every call, silently
    leaving hundreds of thousands of entities isolated in the graph).
    """
    if "<think>" in content:
        end = content.rfind("</think>")
        content = content[end + 8:].strip() if end != -1 else content
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        content = content.rsplit("```", 1)[0].strip()
    try:
        # strict=False allows literal control chars (e.g. unescaped \n) inside
        # string values — some models occasionally emit these in span fields.
        return json.loads(content, strict=False)
    except json.JSONDecodeError:
        pass
    # Fallback 1: parse only the leading JSON value, ignoring anything the
    # model appended after it (the "Extra data" case).
    try:
        return json.JSONDecoder(strict=False).raw_decode(content)[0]
    except json.JSONDecodeError:
        pass
    # Fallback 2: extract the first {...} or [...] block via regex. Handles
    # cases where the model prepends prose before the JSON payload too.
    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", content)
    if not m:
        logger.warning("%s: no JSON block found; content=%r", log_prefix, content[:200])
        raise json.JSONDecodeError("no JSON block found", content, 0)
    try:
        return json.loads(m.group(1), strict=False)
    except json.JSONDecodeError:
        logger.warning("%s: regex fallback also failed; content=%r", log_prefix, content[:200])
        raise


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
         "options": {"num_predict": get_settings().llm_num_predict},
         "messages": [{"role": "system", "content": system},
                      {"role": "user", "content": user}]},
        {},
    )
    content = out["message"]["content"]
    # Thinking models (e.g. qwen3.5) may emit <think>…</think> CoT blocks —
    # _parse_llm_json strips those before parsing.
    data = _parse_llm_json(content, "ollama_json")
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
    data = _parse_llm_json(out["choices"][0]["message"]["content"], "openai_json")
    usage = out.get("usage", {})
    return data, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
