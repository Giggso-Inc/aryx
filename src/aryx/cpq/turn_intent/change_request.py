"""Single/multi change-request detection (Phase 4 step 2 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`detect_change_request`/`detect_change_requests_multi` take a leading
`engine` argument (unlike this module's other functions) purely to pass
through to `_change_request_matches` (matches.py), which needs it for
`engine._CHANGE_VERB_RE`/`engine._ARROW_RE`.
"""

from __future__ import annotations

from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.change_targets_all import detect_all_change_targets_without_value
from aryx.cpq.turn_intent.matches import _change_request_matches
from aryx.cpq.turn_intent.patterns2 import _MAX_MULTI_CHANGE_REQUESTS


def detect_change_request(
    engine,
    question: str,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    filled_multi: dict[str, list[str]] | None = None,
) -> "tuple[ConfigAttr, str] | None":
    """Detect if the user wants to change an already-filled attribute (Step 6).

    Returns (attr_to_change, new_value_hint) or None if no change detected.
    Strategy: look for change-verb vocabulary first; then fall back to
    checking if the raw message maps to a different value for any filled attr.

    filled_multi — multi-select selections (variable_name → item_values).
    Without it, multi-selects were INVISIBLE to change detection (the
    loop only consulted the scalar `filled` dict), so no multi-select
    could ever be changed after completion — confirmed live: "I wanted
    to include the mounting type: Locking Molle Mount" against a
    declined (empty, user-confirmed) mount grid fell through to the
    review nudge. A key present in filled_multi counts as filled —
    including the explicitly-declined empty selection; for multi attrs
    a "different value" means the mentioned option isn't already in
    the selected rows.

    Just the first match from `_change_request_matches` — see
    `detect_change_requests_multi` for a message naming several
    attrs at once.
    """
    return next(_change_request_matches(engine, question, attrs, filled, filled_multi), None)

def detect_change_target_without_value(question: str, attrs: list[ConfigAttr], filled: dict[str, str],
) -> ConfigAttr | None:
    """A change-verb naming an already-filled attr, but with no
    resolvable new value ("change hardware version", "change product")
    — distinct from detect_change_request, which requires BOTH a verb
    AND a value and returns None otherwise. Confirmed live
    (docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md Related finding 1): a
    valueless change message fell through every detector, regex and
    LLM, straight to the generic "I didn't quite catch that" nudge —
    this lets the caller instead ask which value, the same way
    detect_attr_query's "what values are available" answer already
    does. Only ever called AFTER detect_change_request/
    detect_change_requests_multi have already returned nothing, so a
    message with a resolvable value never reaches here.

    Returns the first of ``detect_all_change_targets_without_value``
    (appearance order) so multi-target callers can still use the
    singular form for "active" while enqueuing the rest.
    """
    all_targets = detect_all_change_targets_without_value(
        question, attrs, filled,
    )
    return all_targets[0] if all_targets else None

def detect_change_requests_multi(
    engine,
    question: str,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    filled_multi: dict[str, list[str]] | None = None,
) -> list[tuple[ConfigAttr, str]]:
    """Up to `_MAX_MULTI_CHANGE_REQUESTS` (attr, new_value_hint) matches
    from a SINGLE message naming several attrs at once — e.g. "change
    the Shirt Magnetic Mount Quantity to 25 and the Jacket Magnetic
    Mount Quantity to 25". `detect_change_request` only ever returns
    the first match (`_change_request_matches` is a generator; each
    `for attr in _try_order` iteration yields independently, so
    collecting more than one is exactly this: keep scanning instead of
    stopping at the first).

    Returns [] when no match is found, mirroring the "no change
    detected" contract callers already expect from the singular form.
    """
    out: list[tuple[ConfigAttr, str]] = []
    for match in _change_request_matches(engine, question, attrs, filled, filled_multi):
        out.append(match)
        if len(out) >= _MAX_MULTI_CHANGE_REQUESTS:
            break
    return out
