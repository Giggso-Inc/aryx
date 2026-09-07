"""Plain-language rewrite/enforcement for the standard (non-CPQ) Ask pipeline.

Split out of `ask_api.py` per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md Phase 4 step 1.

`_SENTENCE_SPLIT` is intentionally a separate compiled regex from
`ask_api.py`'s own copy (used by `_cpq_summary_text`, which stays there) —
identical pattern, not a shared import, to avoid a module-level circular
import between the two modules for a plain, never-patched constant.
"""
from __future__ import annotations

import logging
import re
import time

from aryx import llm_runtime
from aryx.api.ask_standard_pipeline._text_utils import _strip_think

logger = logging.getLogger(__name__)

_MAX_ANSWER_LINES = 5
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')


def _line_count(text: str) -> int:
    """Logical line count — the greater of physical newlines and sentence count.

    A model asked for "N lines" can still return one dense multi-sentence
    paragraph with no line breaks at all; counting sentences too catches that.
    """
    physical = len([ln for ln in text.splitlines() if ln.strip()])
    sentences = len([s for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()])
    return max(physical, sentences)


def _rewrite_plain(text: str, context_hint: str, workspace_id: int) -> tuple[str, int, int]:
    """Force a short, plain-English rewrite. Returns the original untouched on any failure.

    Shared by `_enforce_plain_answer` (Q&A) and `_cpq_summary_text` (config
    summaries) — the flow must never block on the rewrite.
    """
    sys = "You rewrite text in plain, everyday English for a non-technical reader."
    user = (
        f"Rewrite the TEXT below to at most {_MAX_ANSWER_LINES} short lines, one "
        "idea per line, in plain jargon-free English — direct point first. Keep "
        "every fact and proper noun (product names, codes) exactly as given; "
        "don't invent or drop any.\n\n"
        f"{context_hint}\n\nTEXT:\n{text}"
    )
    try:
        rewritten, it, ot = llm_runtime.chat("menial", sys, user, workspace_id=workspace_id)
        rewritten = _strip_think(rewritten).strip()
        if rewritten:
            return rewritten, it, ot
    except Exception:  # noqa: BLE001
        logger.debug("plain-language rewrite failed — using original", exc_info=True)
    return text, 0, 0


def _enforce_plain_answer(
    text: str, question: str, workspace_id: int,
) -> tuple[str, int, int, int]:
    """Second pass: force a short, plain-English rewrite if the model overran."""
    if _line_count(text) <= _MAX_ANSWER_LINES:
        return text, 0, 0, 0
    start = time.monotonic()
    rewritten, it, ot = _rewrite_plain(text, f"QUESTION: {question}", workspace_id)
    ms = int((time.monotonic() - start) * 1000) if (it or ot) else 0
    return rewritten, it, ot, ms
