"""Identical-display-label ambiguity detection for options-queries and
change requests (Phase 4 step 2 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Neither needs
engine-instance callback.
"""

from __future__ import annotations

from aryx.cpq.engine import _label_mentioned_strict
from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.patterns import _ARROW_RE, _CHANGE_VERB_RE
from aryx.cpq.turn_intent.patterns2 import _OPTIONS_KEYWORDS


def detect_label_collision(question: str, attrs: list[ConfigAttr],
) -> list[ConfigAttr] | None:
    """Detect an options-query naming a display_label 2+ distinct attrs
    share (BigMachines source-data reuse — confirmed real, not an
    ingestion artifact; see docs/CPQ_SESSION_2_OPEN_ISSUES.md item 2).

    Only fires for the label-matching tier — a variable_name match is
    already unambiguous by construction (variable_name is unique), so
    this must run BEFORE detect_attr_query's own label fallback tier
    silently resolves the tie via `max(..., key=len)`. Returns the tied
    candidates so the caller can ask the user to disambiguate instead of
    guessing, or None when there's no collision to report.

    docs/config_consistency_issues_2026-07-30.md — live-confirmed bug: a
    genuine COLLISION (one shared label, 2+ attrs) was being conflated
    with a compound question naming several DIFFERENT, unambiguous
    attrs by their own distinct labels in one sentence ("what are the
    Frequency Bands and Wireless Carrier available?" wrongly pulled
    wirelessCarrier_astro — label "Wireless Carrier", zero shared
    tokens with "Frequency Bands" — into the SAME disambiguation
    prompt, because the old check only counted `len(distinct_vns) >= 2`
    across ALL label matches combined, never checking whether they
    actually shared ONE label. Now groups matches by their OWN exact
    label text first — only a group where 2+ DISTINCT variable_names
    share the SAME label text is a real collision. Every `_narrow_label_
    collision` caller already assumes this invariant (its own docstring:
    "every candidate here has the IDENTICAL label by construction") —
    this fix makes that actually true instead of assumed.
    """
    q_lower = question.lower()
    if not any(kw in q_lower for kw in _OPTIONS_KEYWORDS):
        return None
    q_flat = q_lower.replace("_", "")
    vn_matches = [
        attr for attr in attrs
        if attr.variable_name.lower().replace("_", "") in q_flat
        or attr.variable_name.lower() in q_lower
    ]
    if vn_matches:
        return None
    label_matches = [attr for attr in attrs if attr.display_label.lower() in q_lower]
    by_label: dict[str, list[ConfigAttr]] = {}
    for a in label_matches:
        by_label.setdefault(a.display_label.lower(), []).append(a)
    for group in by_label.values():
        if len({a.variable_name for a in group}) >= 2:
            return group
    return None

def detect_change_request_collision(
    question: str,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    filled_multi: dict[str, list[str]] | None = None,
) -> list[ConfigAttr] | None:
    """Same identical-label ambiguity as detect_label_collision, but for
    change requests rather than options-queries (docs/CPQ_SESSION_2_
    OPEN_ISSUES.md item 2 — that doc claimed this closed the gap for
    "the whole conversational flow", but detect_change_request only
    ever had the separate, narrower substring-subsumption fix, which
    does nothing when two candidates' labels are IDENTICAL rather than
    one subsuming the other — confirmed: "change service type to
    Premier" against 3 identically-labeled "Service Type" attrs
    resolved silently to whichever was first in catalog order).

    detect_label_collision itself isn't reused directly — it gates on
    _OPTIONS_KEYWORDS ("what options...", never present in a change
    request) and considers every attr, not just already-filled ones.
    Here the gate is a change-verb/arrow (mirrors detect_change_
    request's own has_change_verb check) and candidates are restricted
    to attrs actually in `filled`/`filled_multi` — an unfilled attr
    can't be the target of a "change X" request in the first place.

    Returns the tied candidates (so the caller can ask which one was
    meant), or None when there's no collision to report.
    """
    if not (_CHANGE_VERB_RE.search(question) or _ARROW_RE.search(question)):
        return None
    q_lower = question.lower()
    multi = filled_multi or {}
    # _label_mentioned_strict (2026-07-28 fix), NOT the loose
    # _label_mentioned — live-confirmed bug: "change solution type and
    # hardware type" (neither phrase contains "service type" anywhere)
    # still reported a "Service Type" collision, because the loose
    # matcher's leading-word-drop tier let "Service Type" degrade to
    # the single generic shared word "Type", which then substring-
    # matched "type" inside BOTH "solution type" and "hardware type".
    # _label_mentioned's own docstring says this loose tier is "safe
    # only as a coarse pre-filter" specifically because its OTHER
    # caller (detect_change_request) always requires a separate real
    # value-match before resolving anything — this function has no
    # such second check; it hands loose matches straight to the user
    # as a real collision, so it needs the strict variant instead,
    # which explicitly never degrades to a single generic shared word
    # (see _label_mentioned_strict's own docstring). Multi-word
    # dropped-prefix matches (e.g. "mounting type Shirt Magnetic Mount
    # Quantity" naming just "Shirt Magnetic Mount Quantity") still work
    # under the strict variant — only the single-generic-word
    # degradation is excluded.
    candidates = [
        a for a in attrs
        if (a.variable_name in filled or a.variable_name in multi)
        and _label_mentioned_strict(a.display_label.lower(), q_lower)
    ]
    # Group by the EXACT label text, not just "2+ candidates matched at
    # all" — a substring containment match (e.g. "Quantity" inside
    # "...Locking Molle Mount Quantity to 10") can pull in candidates
    # with genuinely DIFFERENT labels, which is detect_change_request's
    # own _superseded subsumption case, not an identical-label collision.
    by_label: dict[str, list[ConfigAttr]] = {}
    for a in candidates:
        by_label.setdefault(a.display_label.lower(), []).append(a)
    all_labels = set(by_label.keys())
    for label, group in by_label.items():
        if len({a.variable_name for a in group}) < 2:
            continue
        # A more specific match already present (e.g. "mounting type
        # Shirt Magnetic Mount Quantity" contains this group's generic
        # "mounting type" as its own prefix) resolves the request on its
        # own — the generic label's collision is superseded, not real
        # (confirmed live: "change mounting type Shirt Magnetic Mount
        # Quantity to 88" false-positived a "Mounting Type" collision
        # between mountType_viSoln/mountingTypeArray_viSoln even though
        # neither was meant — same principle as detect_change_request's
        # own _superseded mechanism, just not yet applied here).
        if any(other != label and label in other for other in all_labels):
            continue
        return group
    return None
