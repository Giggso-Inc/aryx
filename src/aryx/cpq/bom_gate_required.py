"""Required-field completeness check for the BOM gate.

Split out of `cpq/bom_gate.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Directly imported (bare name, not patched) by
`src/aryx/api/ask_api.py` and `tests/test_cpq_post_failure_guards.py` —
confirmed via grep.
"""
from __future__ import annotations

from aryx.cpq.bom_gate_noise import _is_noise_var
from aryx.cpq.state import ConfigAttr, CpqSession


def find_missing_required_fields(
    attrs: list[ConfigAttr], session: CpqSession,
) -> list[ConfigAttr]:
    """Every currently-visible attribute the catalog itself marks
    `required=True` that has no value at all -- in `session.filled` for a
    single-select/free-text attr, or a non-empty list in
    `session.filled_multi` for a multi-select.

    Confirmed live (2026-08-08): docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.
    md §2c's "only ask decision-attr anchors, skip everything else that
    nothing upstream resolved" behavior is deliberate (its own comment:
    "per your explicit call") -- but nothing anywhere ever checked whether
    one of those silently-skipped attrs was actually `required` before
    declaring the configuration "complete". This is a pure completeness
    check, independent of WHY an attr wasn't filled (§2c's skip, a rule
    that never fired, anything else) -- it never touches or second-guesses
    what §2c itself decides to ask or skip.

    `attrs` is the caller's currently-visible attribute list (post hiding-
    rule filtering) -- a required attr an active hiding rule has removed
    from view is never flagged; the catalog's own rules already say it
    doesn't apply here.

    Noise-shaped integration/system attrs (`_is_noise_var`, e.g. Price
    Book/User Currency/User Groups/User Language/User Number Format/Config
    Operation Context) are excluded even when `required=True` -- these are
    populated by the calling CRM/account layer, never by product
    configuration or by this engine, matching the same exclusion every
    other real-BOM-facing path (auto_fill, build_payload) already applies.
    """
    missing: list[ConfigAttr] = []
    for attr in attrs:
        if not attr.required:
            continue
        vn = attr.variable_name
        if _is_noise_var(vn):
            continue
        if attr.select_type == "multi":
            if session.filled_multi.get(vn):
                continue
        elif session.filled.get(vn):
            continue
        missing.append(attr)
    return missing
