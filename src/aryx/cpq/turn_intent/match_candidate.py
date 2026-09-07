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

from aryx.cpq.engine import _label_mentioned, _valid
from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.apply import apply_answer
from aryx.cpq.turn_intent.apply_multi import apply_multi_answer


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

    # Require the attr to be mentioned by name/label REGARDLESS of
    # change-verb presence (2026-07-28 fix) — the original gate
    # only skipped an unmentioned attr when has_change_verb was
    # True, which backwards-guarded exactly the wrong case: a bare
    # reply with NO change verb (e.g. a plain "77" meant to answer
    # a totally different pending free-text quantity attr) let
    # EVERY filled attr through unfiltered, since the whole
    # condition short-circuits False when has_change_verb is
    # False. Live-verified: with no verb and no mention, "77" got
    # tried against ultimateDestinationCountry's own apply_answer,
    # which treats a bare number as a 1-based option INDEX — and
    # position 77 in that catalog's 251-country list happens to be
    # United Kingdom — silently overwriting the country and
    # cascading a dozen dependent attrs, while the customer's
    # actual answer (a quantity) was never even attempted here.
    # Naming still isn't required through the SEPARATE hint-path
    # fallback further below (extract_hints's own token-to-vn
    # match is its own, narrower signal) — this only closes the
    # "nothing at all ties this attr to the message" hole.
    #
    # A multi-select attr's own OPTION VALUE mentioned in the text
    # counts too, not just its label/variable_name — "add the
    # Jacket Clip Mount too" legitimately names the value being
    # added, never the generic "Mounting Type" label itself
    # (pre-existing, tested behavior — test_cpq_grid_decline.py).
    _multi_option_mentioned = attr.select_type == "multi" and any(
        o.display_name.lower() in q_lower for o in attr.options
    )
    if (
        vn_flat not in q_lower.replace("_", "")
        and not _label_mentioned(label_lower, q_lower)
        and not _multi_option_mentioned
    ):
        return None

    # docs/config_consistency_issues_2026-07-30.md issue 4 follow-up
    # — a multi-select the customer never touched still gets a `[]`
    # entry in filled_multi from auto_fill/hiding-rule evaluation
    # (confirmed live: nearly every multi-select in a real catalog
    # carries this, touched or not), so the gate above alone lets a
    # BARE VALUE mention — with no explicit label/variable_name
    # naming at all — match an untouched, empty multi-select purely
    # because that value happens to also be one of ITS real
    # options. Live-confirmed: with Frequency Bands (single-select)
    # correctly the sole pending attribute, a bare "VHF" reply
    # still matched an unrelated, never-touched
    # modelSelectionFrequencyBandMsl_astro this way, writing the
    # reply into the wrong attribute and leaving the real pending
    # one stale (bom_gate re-detects it as invalid every confirm,
    # looping forever). An EMPTY multi-select stays eligible when
    # explicitly named by label/variable_name (test_cpq_grid_
    # decline.py's declined-grid-reconsidered case: "I wanted to
    # include the mounting type: X" must still work) — only a
    # bare, unnamed value-only mention requires the multi-select to
    # already hold a real selection.
    if (
        attr.select_type == "multi"
        and not multi.get(attr.variable_name)
        and vn_flat not in q_lower.replace("_", "")
        and not _label_mentioned(label_lower, q_lower)
    ):
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
