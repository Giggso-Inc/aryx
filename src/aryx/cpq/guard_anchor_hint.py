"""The customer's own wording, for the not-applicable guard, as keyword arguments for the rules loop / auto_fill.

The guard (``tier0_not_applicable_guard``) resolves the device from that wording, so a call that omits it leaves
the guard a silent no-op. Every call that runs the loop for a session whose product is already chosen takes the
wording from here, so the condition lives in one place: the guard's flag is on AND the session has wording. Flag off
or no wording: no kwargs, and the call is byte-identical to before.
"""
from __future__ import annotations

from typing import Any

from aryx.config import get_settings


def guard_anchor_hint_kwargs(session: Any) -> dict[str, str]:
    """``{"product_anchor_hint": wording}`` when the guard is on and `session` has wording, else ``{}``."""
    wording = getattr(session, "product_anchor_question", "") or ""
    if wording and get_settings().cpq_not_applicable_guard_enabled:
        return {"product_anchor_hint": wording}
    return {}
