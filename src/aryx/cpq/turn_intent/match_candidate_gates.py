"""Gate checks for ``match_candidate._match_change_request_candidate``,
split off purely to keep both files under the file-size cap (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). No logic changed --
each function is the exact original inline block, just given a name.
"""

from __future__ import annotations

from aryx.cpq.engine import _label_mentioned
from aryx.cpq.state import ConfigAttr


def attr_is_mentioned(attr: ConfigAttr, vn_flat: str, label_lower: str, q_lower: str) -> bool:
    """Require the attr to be mentioned by name/label REGARDLESS of
    change-verb presence (2026-07-28 fix) -- the original gate
    only skipped an unmentioned attr when has_change_verb was
    True, which backwards-guarded exactly the wrong case: a bare
    reply with NO change verb (e.g. a plain "77" meant to answer
    a totally different pending free-text quantity attr) let
    EVERY filled attr through unfiltered, since the whole
    condition short-circuits False when has_change_verb is
    False. Live-verified: with no verb and no mention, "77" got
    tried against ultimateDestinationCountry's own apply_answer,
    which treats a bare number as a 1-based option INDEX -- and
    position 77 in that catalog's 251-country list happens to be
    United Kingdom -- silently overwriting the country and
    cascading a dozen dependent attrs, while the customer's
    actual answer (a quantity) was never even attempted here.
    Naming still isn't required through the SEPARATE hint-path
    fallback further below (extract_hints's own token-to-vn
    match is its own, narrower signal) -- this only closes the
    "nothing at all ties this attr to the message" hole.

    A multi-select attr's own OPTION VALUE mentioned in the text
    counts too, not just its label/variable_name -- "add the
    Jacket Clip Mount too" legitimately names the value being
    added, never the generic "Mounting Type" label itself
    (pre-existing, tested behavior -- test_cpq_grid_decline.py).
    """
    multi_option_mentioned = attr.select_type == "multi" and any(
        o.display_name.lower() in q_lower for o in attr.options
    )
    return (
        vn_flat in q_lower.replace("_", "")
        or _label_mentioned(label_lower, q_lower)
        or multi_option_mentioned
    )


def untouched_multi_needs_explicit_mention(
    attr: ConfigAttr, vn_flat: str, label_lower: str, q_lower: str,
    multi: dict[str, list[str]],
) -> bool:
    """docs/config_consistency_issues_2026-07-30.md issue 4 follow-up
    -- a multi-select the customer never touched still gets a `[]`
    entry in filled_multi from auto_fill/hiding-rule evaluation
    (confirmed live: nearly every multi-select in a real catalog
    carries this, touched or not), so the mention gate alone lets a
    BARE VALUE mention -- with no explicit label/variable_name
    naming at all -- match an untouched, empty multi-select purely
    because that value happens to also be one of ITS real
    options. Live-confirmed: with Frequency Bands (single-select)
    correctly the sole pending attribute, a bare "VHF" reply
    still matched an unrelated, never-touched
    modelSelectionFrequencyBandMsl_astro this way, writing the
    reply into the wrong attribute and leaving the real pending
    one stale (bom_gate re-detects it as invalid every confirm,
    looping forever). An EMPTY multi-select stays eligible when
    explicitly named by label/variable_name (test_cpq_grid_
    decline.py's declined-grid-reconsidered case: "I wanted to
    include the mounting type: X" must still work) -- only a
    bare, unnamed value-only mention requires the multi-select to
    already hold a real selection.

    Returns True when this attr must be REJECTED (untouched multi,
    named only by a bare value mention).
    """
    return (
        attr.select_type == "multi"
        and not multi.get(attr.variable_name)
        and vn_flat not in q_lower.replace("_", "")
        and not _label_mentioned(label_lower, q_lower)
    )
