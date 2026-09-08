"""Per-attribute word-overlap/verbatim-grounding scoring for pending-
clarify candidates, split out of `_ground_clarify_candidates` (Phase 2/
11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md) purely to keep `ask_pending_clarify_grounding.py` under the line
cap. Logic unchanged from the original inline loop. `_cpq_engine` is read
through the ask_api MODULE object (not imported by name) since at least
one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_pending_clarify_constants import _WORD_TOKEN_RE


def _score_clarify_candidates(
    attrs: list,
    session: Any,
    q_words: set,
    q_lower: str,
    cq_lower: str,
    hidden_vns: set,
) -> "tuple[dict[str, Any], dict[str, float], set[str]]":
    """Attrs whose full display label or variable_name appears verbatim in
    the customer's own message — a categorically stronger signal than
    incidental word-overlap with some OTHER attribute's label. Live bug:
    "Set SmartProgramming to 2 Years" named anywhereProgramming_astro
    ("SmartProgramming") outright, yet still got paired in a
    disambiguation prompt with applicationServicesDurationYears_astro,
    which only shared the single generic word "years". Rather than
    hardcoding "years"/"duration" onto the stopword list (the same
    whack-a-mole pattern already used for "all"/"is" — brittle, and only
    ever closes the exact collision already hit live), this tracks every
    candidate with SOME strong, explicit grounding — its own label/
    variable_name verbatim in either the customer's message or the LLM's
    clarifying question — so that when exactly ONE candidate overall is
    grounded this way, it resolves directly; a genuine multi-attribute
    disambiguation (the clarifying question itself naming two real
    candidates, e.g. "Frequency Bands or Additional Frequency Bands?")
    still leaves 2+ strongly-grounded candidates and is left untouched.

    Returns (by_vn, scores, strong_vns).
    """
    from aryx.api import ask_api as _ask_api_module
    by_vn: dict[str, Any] = {}
    scores: dict[str, float] = {}
    strong_vns: set[str] = set()
    for a in attrs:
        if a.variable_name in hidden_vns:
            continue
        # Same noise/HTML/hide_in_trans/set_type checks build_payload() and
        # _is_summary_excluded() already apply (docs/config_consistency_
        # issues_2026-07-30.md items 1/2) — an internal help-text/HTML/
        # transaction-excluded field must never be OFFERED as something a
        # customer could mean to change, regardless of how well its
        # variable_name happens to word-overlap the utterance (confirmed
        # live: accessoriesHelpText_all, configProcessStepHTML_all, and a
        # hidden internal rule attr all surfaced in a real disambiguation
        # prompt this way).
        if _ask_api_module._cpq_engine._is_noise_var(a.variable_name):
            continue
        if a.hide_in_trans:
            continue
        if a.set_type == "2" and not a.auto_lock:
            continue
        is_filled = (
            a.variable_name in session.filled
            or a.variable_name in session.filled_multi
        )
        if a.hidden and not is_filled:
            continue
        label_l = (a.display_label or "").lower()
        vn_words = set(_WORD_TOKEN_RE.findall(
            a.variable_name.lower().replace("_", " "),
        ))
        label_words = set(_WORD_TOKEN_RE.findall(label_l))
        vocab = label_words | vn_words
        overlap = len(q_words & vocab) if q_words else 0
        label_in_cq = bool(label_l) and label_l in cq_lower
        vn_in_cq = a.variable_name.lower() in cq_lower
        # Same verbatim-containment check as label_in_cq/vn_in_cq above,
        # against the customer's own message instead of the LLM's
        # clarifying text — an attribute the customer named outright.
        label_in_q = bool(label_l) and label_l in q_lower
        vn_in_q = bool(a.variable_name) and a.variable_name.lower() in q_lower
        if label_in_cq or vn_in_cq or label_in_q or vn_in_q:
            strong_vns.add(a.variable_name)
        if overlap > 0 or label_in_cq or vn_in_cq or label_in_q or vn_in_q:
            # Prefer filled for change-like clarifies; still allow unfilled
            # when the catalog label is explicitly grounded in the CQ text.
            if is_filled or label_in_cq or vn_in_cq or label_in_q or vn_in_q or overlap >= 2:
                by_vn[a.variable_name] = a
                # docs/config_consistency_issues_2026-07-30.md Issue 11:
                # a label grounded in the LLM's own clarifying text is the
                # strongest possible signal — rank it above any word-count
                # match. Otherwise rank by overlap (relevance), NOT label
                # length — the old `-len(display_label)` sort let long,
                # only-incidentally-matching already-filled labels ("Is
                # provisioning required in the Motorola Solutions
                # Authorized Cloud environment?") bump genuinely relevant,
                # short-labeled attrs ("Frequency Bands", "Wireless
                # Carrier") out of the top-8 cutoff entirely.
                strong = label_in_cq or vn_in_cq or label_in_q or vn_in_q
                scores[a.variable_name] = overlap + (100 if strong else 0)
    return by_vn, scores, strong_vns
