"""``_match_change_request_candidate`` -- the per-attribute matching step
factored out of ``matches._change_request_matches`` purely to keep both
files under the file-size cap (Phase 4 step 2 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Behavior-identical to the original single ~220-line
``_change_request_matches`` method's per-``_try_order``-iteration loop
body: every ``continue`` (skip this attr, no match) became ``return
None``, and every ``yield attr, value`` became ``return attr, value`` --
no other logic changed. Needs the live ``CpqEngine`` instance (``engine``
param) for the hint-path fallback's ``engine.extract_hints`` call.
"""

from __future__ import annotations

import re

from aryx.cpq.engine import _valid
from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.apply import apply_answer
from aryx.cpq.turn_intent.apply_multi import apply_multi_answer
from aryx.cpq.turn_intent.match_candidate_gates import (
    attr_is_mentioned, untouched_multi_needs_explicit_mention,
)


def _match_change_request_candidate(
    engine,
    attr: ConfigAttr,
    question: str,
    q_lower: str,
    filled: dict[str, str],
    multi: dict[str, list[str]],
    has_change_verb: bool,
    label_spans: dict[str, tuple[int, int]],
) -> "tuple[ConfigAttr, str] | None":
    """Try to match a single candidate attr against the message -- see
    ``_change_request_matches``'s docstring for the overall matching
    contract this implements one iteration of.
    """
    if attr.variable_name not in filled and attr.variable_name not in multi:
        return None
    vn_flat = attr.variable_name.lower().replace("_", "")
    label_lower = attr.display_label.lower()

    # See match_candidate_gates.py for the two gate checks below --
    # split out purely to keep this file under the file-size cap.
    if not attr_is_mentioned(attr, vn_flat, label_lower, q_lower):
        return None
    if untouched_multi_needs_explicit_mention(attr, vn_flat, label_lower, q_lower, multi):
        return None

    # Direct apply_answer match — checked FIRST so the full NL question
    # (with verbatim display-name substring matching) wins over the coarse
    # hint token. Without this ordering, "4G LTE Only" collapsed to "LTE"
    # by _HINT_PATTERNS can't be distinguished from "4G LTE+5G".
    # Guard: skip option-less (free-text) attrs — apply_answer's free-text
    # fallback would accept ANY string as a spurious "value".
    if attr.options and attr.variable_name in multi:
        mentioned = apply_multi_answer(attr, question)
        current_rows = set(multi.get(attr.variable_name, []))
        if any(iv not in current_rows for iv, _dn in mentioned):
            return attr, question
        return None
    if attr.options:
        result = apply_answer(attr, question)
        if result and _valid(result[0]) and result[0] != filled.get(attr.variable_name):
            return attr, question
    elif has_change_verb:
        # Free-text attr (e.g. a per-mount quantity field) with an
        # explicit change verb — the label-mention gate above has
        # already confirmed THIS attr is the one being talked about,
        # but unlike options-backed attrs there's no menu list to
        # fuzzy-match a value against, and extract_hints() only knows
        # fixed concepts (country/region/hwversion) — never numbers
        # (confirmed live: "change the jacket magnetic mount quantity
        # to 15" fell through to "I didn't quite catch that" even
        # after the label-mention fix above, because nothing ever
        # extracted "15" out of the sentence). Anchor to the "to/from
        # N" phrasing FIRST — this catalog's own product names embed
        # digits (V200 Body Worn Camera, APX6500, both confirmed live
        # elsewhere in this file), so "change the V200 Body Worn
        # Camera quantity to 2" would otherwise match "200" before
        # the intended "2". Only fall back to the first standalone
        # number in the sentence when no directional verb is present.
        # Scoped to the text after THIS attr's own label mention (see
        # label_spans above) and before the next sibling attr's own
        # mention, if any — never the whole message, or a second
        # quantity attr named later in the same sentence would steal
        # this one's number (or vice versa).
        own_span = label_spans.get(attr.variable_name)
        if own_span:
            window_start = own_span[1]
            later_starts = [
                s for vn2, (s, _e) in label_spans.items()
                if vn2 != attr.variable_name and s >= window_start
            ]
            window_end = min(later_starts) if later_starts else len(question)
            search_text = question[window_start:window_end]
        else:
            # This attr matched only via vn_flat (the raw variable
            # name literally in the message), not its display label
            # — no span to scope by, so fall back to the whole
            # message like before (rare: natural phrasing almost
            # never types the internal snake_case variable name).
            search_text = question
        m = (re.search(r"\bto\s+(-?\d+(?:\.\d+)?)", search_text, re.IGNORECASE)
             or re.search(r"(?:->|→)\s*(-?\d+(?:\.\d+)?)", search_text)
             or re.search(r"\bfrom\s+(-?\d+(?:\.\d+)?)", search_text, re.IGNORECASE))
        value = m.group(1) if m else None
        if value is None:
            m2 = re.search(r"-?\d+(?:\.\d+)?", search_text)
            value = m2.group(0) if m2 else None
        if value is not None and value != filled.get(attr.variable_name, ""):
            return attr, value

    # Hint-path fallback — coarse extracted token (e.g. "LTE", "4G") confirms
    # the attr is mentioned but may not identify the exact option. Only reached
    # when apply_answer found no specific match (e.g. "make it LTE" with no
    # full option name in the message). Returns full question so _handle_cascade
    # can try apply_answer again with more context.
    hints_dcr = engine.extract_hints(question)
    for hk, hv in hints_dcr.items():
        hk_flat = hk.lower().replace("_", "")
        if hk_flat in vn_flat or vn_flat in hk_flat:
            if hv.lower() != filled.get(attr.variable_name, "").lower():
                return attr, question
    return None
