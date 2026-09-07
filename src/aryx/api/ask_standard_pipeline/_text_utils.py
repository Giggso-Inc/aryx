"""Small text/history helpers shared by the standard (non-CPQ) Ask pipeline.

Split out of `ask_api.py` per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md Phase 4 step 1.
"""
from __future__ import annotations

from aryx.api.ask_request_models import Turn

_HISTORY_MINE_LIMIT = 8


def _strip_think(text: str) -> str:
    """Drop any <think> chain-of-thought a model inlines into its answer."""
    text = text.rsplit("</think>", 1)[-1] if "</think>" in text else text
    return text.replace("<think>", "").strip()


def _recent(history: list[Turn], limit: int = 4) -> str:
    if not history:
        return ""
    turns = history[-limit:]
    return "\n".join(f"{t.role}: {t.text}" for t in turns)


def _user_texts_from_history(
    history: list[Turn], limit: int = _HISTORY_MINE_LIMIT,
) -> list[str]:
    """User-role utterances from Ask history (oldest → newest within window)."""
    if not history:
        return []
    out: list[str] = []
    for t in history[-limit:]:
        role = (getattr(t, "role", None) or "").lower()
        text = (getattr(t, "text", None) or "").strip()
        if not text:
            continue
        # Treat empty role as user; clients sometimes omit role on user turns.
        if role in ("", "user", "human", "h", "customer"):
            out.append(text)
    return out
