"""Attr activation/multi-select-removal turn detectors (Phase 4 step 2
extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

``detect_attr_activation`` needs the live ``CpqEngine`` instance (``engine``
param) to re-check hiding rules against the current filled state via
``engine.apply_hiding_rules``; ``detect_multi_select_removal`` does not.
"""

from __future__ import annotations

from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.engine import _label_mentioned_strict
from aryx.cpq.state import ConfigAttr, HidingRule
from aryx.cpq.turn_intent.apply_multi import apply_multi_answer
from aryx.cpq.turn_intent.patterns import _REMOVE_VERB_RE
from aryx.cpq.turn_intent.patterns2 import _ADD_VERB_RE


def detect_multi_select_removal(
    question: str,
    attrs: list[ConfigAttr],
    filled_multi: dict[str, list[str]],
) -> "tuple[ConfigAttr, list[str]] | None":
    """Detect "remove X"/"deselect X" against an already-selected
    multi-select option (e.g. "remove Jacket Magnetic Mount" after
    selecting both Shirt and Jacket).

    Confirmed live this was a real gap: apply_multi_answer/
    _handle_cascade's multi-select branch only ever UNIONS mentioned
    options with the current selection (by design, for the "also
    include X" add case) — there was no removal path at all, so
    "remove Jacket Magnetic Mount" fell straight through to "I didn't
    quite catch that" with both mounts still selected.

    Returns (attr, item_values_to_remove) or None. Only fires when a
    removal verb is present AND at least one mentioned option is
    genuinely already in the current selection — naming an option
    that isn't currently selected is not a removal request (falls
    through to the normal change-request/collision paths instead, same
    "never guess" discipline as everywhere else in this file).
    """
    if not _REMOVE_VERB_RE.search(question):
        return None
    for attr in attrs:
        if attr.select_type != "multi":
            continue
        current = filled_multi.get(attr.variable_name)
        if not current:
            continue
        mentioned = apply_multi_answer(attr, question)
        to_remove = [iv for iv, _dn in mentioned if iv in current]
        if to_remove:
            return attr, to_remove
    return None

def detect_attr_activation(
    engine,
    question: str,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    filled_multi: dict[str, list[str]],
    hiding_rules: list[HidingRule],
    workspace_id: int,
    catalog_prefix: str,
    bml_eval: BmlEvaluator | None = None,
) -> ConfigAttr | None:
    """Detect "add X"/"activate X" re-activating a real, currently-
    excluded, optional attribute (D2). Never an invented field, never
    a required one, never a bypass of a currently-active hiding rule.

    A single unified eligibility check covers all 3 of D2's source
    pools at once: `required == False`, not `attr.hidden` (BM-native
    permanent hidden — a different concept from rule-conditional
    hiding, never surfaced regardless of rule state), not already
    filled/selected, and NOT currently hidden by an active hiding
    rule (re-checked live against the CURRENT filled state via
    `apply_hiding_rules`, never a cached/stale exclusion set — an
    attr whose hiding condition is still true is never a candidate,
    full stop). This naturally covers a declined multi-select (empty
    `filled_multi`), a flow-exclusion-dropped attr
    (`payload_flow_exclusions`), and a hiding-rule-excluded attr
    whose condition lapsed — all three reduce to the same "real,
    optional, currently invisible, not rule-blocked" predicate.
    """
    if not _ADD_VERB_RE.search(question):
        return None
    _visible_now, _msgs, hidden_now = engine.apply_hiding_rules(
        attrs, filled, hiding_rules, bml_eval=bml_eval, filled_multi=filled_multi,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix)
    q_lower = question.lower()
    for attr in attrs:
        vn = attr.variable_name
        if attr.required or attr.hidden:
            continue
        if vn in filled or filled_multi.get(vn):
            continue
        if vn in hidden_now:
            continue  # still genuinely hidden by an active rule
        if _label_mentioned_strict(attr.display_label.lower(), q_lower):
            return attr
    return None
