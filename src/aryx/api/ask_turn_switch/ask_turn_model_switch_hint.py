"""Offering a model switch in the review stage from this turn's Product hint.

After "Configuration complete" the turn is routed through the LLM-first intent
gateway before any deterministic change check. A message such as "I want to
quote for APX N30 for United States" names a Product option that the catalog
hints (step 2) already resolved exactly, yet the gateway can still call it
ambiguous (the same text is an option of several attributes) and answer with a
"which attribute did you mean?" list, so the model switch never runs.

`_offer_model_switch_from_hint` runs in the review stage just before the
gateway. When `cpq_model_switch_snapshot_enabled` is on and this turn's hints
hold a Product item value that differs from the filled Product, it asks the
same yes/no question as a normal model switch. The value comes from the
catalog's own options (the hint), never from a literal.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.api.ask_turn_switch.ask_turn_model_switch import _BATCH_NOTE, _ask_to_switch, _norm
from aryx.config import get_settings
from aryx.cpq.catalog_profile import PRODUCT_LITERAL
from aryx.raven_log import raven_log

_HINT_OPTIONS = ["offer_model_switch", "skip"]
# Words that negate a model named right after them ("not APX N30", "without
# the APX N30", "don't want APX N30").
_NEGATORS = frozenset({"not", "no", "never", "without", "don", "dont", "except",
                       "instead", "than"})  # "instead of X", "rather than X"
# Wording that asks for a model switch outright; it overrides an earlier "no"
# ("ok, switch to X after all", "I want to quote for X").
_SWITCH_INTENT_RE = re.compile(
    r"\b(switch|quote|go\s+with|move\s+to|change\s+(?:the\s+)?(?:model|product|radio))\b", re.IGNORECASE)
_NEGATION_WINDOW = 4  # "don't" splits into two words: "I don't really want X"


def _log_hint_check(session: Any, selected: str, reason: str, target: str = "") -> None:
    """Record the review-stage hint decision."""
    raven_log("DEBUG", "P4", "ask.model_switch.hint_check review-stage product hint checked", context={
        "selected_option": selected, "available_options": _HINT_OPTIONS,
        "reason_code": reason, "turn": getattr(session, "turn", None),
        "current_model": session.filled.get(PRODUCT_LITERAL, ""), "target_model": target})


def _name_start(question: str, names: tuple[str, ...]) -> int | None:
    """Return the word index where one of the names starts, as whole words."""
    words = re.findall(r"[a-z0-9]+", (question or "").lower())
    targets = {_norm(n) for n in names if _norm(n)}
    if not targets:
        return None
    longest = max(len(t) for t in targets)
    for i in range(len(words)):
        joined = ""
        for word in words[i:]:
            # Stop once the run is longer than any name: linear in the message.
            joined += word
            if len(joined) > longest:
                break
            if joined in targets:
                return i
    return None


def _negated_before(question: str, start: int) -> bool:
    """Return True when a negating word sits just before the named model.

    The look-back stops at punctuation, so "not SRX 2200, APX 900" (the
    negation is about the OLD model) is not treated as negating APX 900.
    """
    low = (question or "").lower()  # positions and the cut use the same text
    matches = list(re.finditer(r"[a-z0-9]+", low))
    if start >= len(matches):
        return False
    name_pos = matches[start].start()
    clause_start = max((m.end() for m in re.finditer(r"[,;.!?—]", low[:name_pos])), default=0)
    before = [m.group() for m in matches[:start] if m.start() >= clause_start]
    return any(w in _NEGATORS for w in before[-_NEGATION_WINDOW:])


def _other_changes(question: str, session: Any, attrs: list, hints: dict) -> bool:
    """Return True when THIS message also changes answers besides Product.

    A hint counts only when its option is named in the message itself, so a
    hint merged from older text never triggers the "send again" note.
    """
    by_vn = {a.variable_name: a for a in attrs}
    for vn, iv in (hints or {}).items():
        attr = by_vn.get(vn)
        if vn == PRODUCT_LITERAL or attr is None or session.filled.get(vn) == iv:
            continue
        option = next((o for o in getattr(attr, "options", None) or () if o.item_value == iv), None)
        names = (option.display_name or iv, iv) if option is not None else (iv,)
        if _name_start(question, names) is not None:
            return True
    return False


def _offer_model_switch_from_hint(
    req: Any, session: Any, attrs: list, hints: dict,
) -> dict[str, Any] | None:
    """Ask to switch when this turn's hints name a different Product option.

    Args:
        req: The ask request (question, workspace_id).
        session: The live CpqSession in a review status.
        attrs: The catalog's config attributes (for the option display name).
        hints: This turn's extracted hints (variable_name -> item_value).

    Returns:
        The confirmation response, or None to let the review stage continue.
    """
    if not get_settings().cpq_model_switch_snapshot_enabled:
        _log_hint_check(session, "skip", "FLAG_OFF")
        return None
    hinted = (hints or {}).get(PRODUCT_LITERAL) or ""
    current = session.filled.get(PRODUCT_LITERAL, "")
    if not hinted or not current:
        _log_hint_check(session, "skip", "NO_PRODUCT_HINT_OR_NO_PRODUCT")
        return None
    if hinted == current:
        _log_hint_check(session, "skip", "HINT_IS_CURRENT_MODEL", hinted)
        return None
    if (list(getattr(session, "declined_model_switch", None) or []) == [current, hinted]
            and not _SWITCH_INTENT_RE.search(req.question or "")):
        # The user already said no to this exact switch and this message does
        # not ask for one outright; let the gateway handle it (its model text
        # may be another attribute's value). Explicit switch wording offers again.
        _log_hint_check(session, "skip", "SWITCH_DECLINED_EARLIER", hinted)
        return None
    product_attr = next((a for a in attrs if a.variable_name == PRODUCT_LITERAL), None)
    if getattr(product_attr, "select_type", "") == "multi":
        # Same rule as _offer_model_switch: a multi-select Product is not a model switch.
        _log_hint_check(session, "skip", "PRODUCT_IS_MULTI_SELECT", hinted)
        return None
    option = next((o for o in getattr(product_attr, "options", None) or () if o.item_value == hinted), None)
    if option is None:
        # The hint must be a real option of this catalog's Product attribute.
        _log_hint_check(session, "skip", "HINT_NOT_A_PRODUCT_OPTION", hinted)
        return None
    display = option.display_name or option.item_value
    # The model must be named in THIS message (not only in a merged older
    # text), and not negated ("not APX N30").
    start = _name_start(req.question, (display, option.item_value))
    if start is None:
        _log_hint_check(session, "skip", "MODEL_NOT_NAMED_IN_MESSAGE", hinted)
        return None
    if _negated_before(req.question, start):
        _log_hint_check(session, "skip", "MODEL_NAMED_WITH_NEGATION", hinted)
        return None
    note = _BATCH_NOTE if _other_changes(req.question, session, attrs, hints) else ""
    return _ask_to_switch(req, session, option.item_value, display, "PRODUCT_HINT_DIFFERS", note)
