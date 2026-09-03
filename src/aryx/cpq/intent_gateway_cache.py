"""Process-local classification cache for the CPQ intent gateway.

Split out of `cpq/intent_gateway.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). `_cache_key`'s fallback `get_settings()` call only fires when
`model_id` isn't supplied — every test call site passes it explicitly
(confirmed via grep), so this carries no patch-retargeting risk in
practice; the fallback still works correctly (against the real settings)
if ever exercised unpatched.
"""
from __future__ import annotations

import hashlib
import json
import os

from aryx.config import get_settings
from aryx.cpq.intent_schema import GatewayIntentResult
from aryx.cpq.state import CpqSession

# Module-level cache: key → (GatewayIntentResult, pt, ct, model_id)
_CACHE: dict[str, tuple[GatewayIntentResult, int, int, str]] = {}
_CACHE_MAX = 256


def _normalize_question(question: str) -> str:
    return " ".join(question.lower().split())


def session_state_hash(session: CpqSession) -> str:
    """Stable fingerprint of the config state the candidates depend on."""
    payload = {
        "product": session.product_name,
        "filled": sorted(session.filled.items()),
        "filled_multi": sorted(
            (k, tuple(v)) for k, v in session.filled_multi.items()
        ),
        "pending": list(session.pending_variables[:20]),
        "pending_change_no_value": session.pending_change_no_value_vn,
        "pending_change_collision": list(session.pending_change_collision_vns),
        "pending_clarify": list(session.pending_clarify_vns),
        "status": session.status,
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cache_key(question: str, session: CpqSession, model_id: str = "") -> str:
    # N9: isolate cache by model + worker pid so multi-worker / model
    # flips never reuse a stale classification from another process identity.
    mid = model_id or get_settings().cpq_intent_gemini_model
    return (
        f"{mid}|pid={os.getpid()}|"
        f"{_normalize_question(question)}|{session_state_hash(session)}"
    )


def _store_cache(
    key: str, result: GatewayIntentResult, pt: int, ct: int, model_id: str,
) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # Drop an arbitrary oldest-ish entry (insertion order on 3.7+)
        _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE[key] = (result, pt, ct, model_id)


def clear_gateway_cache() -> None:
    """Test helper — wipe the process-local intent cache."""
    _CACHE.clear()
