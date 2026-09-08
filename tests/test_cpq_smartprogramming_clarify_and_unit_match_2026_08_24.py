"""Root-cause regression coverage for the live SmartProgramming bugs
(docs handoff 2026-08-24, MSI_cpq workspace / aSTRO25_bom):

Bug 1 — "Set SmartProgramming to 2 Years" named anywhereProgramming_astro
("SmartProgramming") outright, yet the disambiguation prompt still paired
it with applicationServicesDurationYears_astro, which only shared the
single generic word "years". Fixed generically in
_ground_clarify_candidates (src/aryx/api/ask_api.py) by tracking every
candidate with an explicit, verbatim label/variable_name match against
either the customer's message or the LLM's clarifying question — when
exactly one candidate has this strong grounding, the ambiguity resolves
outright instead of asking the customer to pick between an explicit
match and an incidental one. No new stopwords were added.

Bug 2 — two independent, stacked defects that discarded the value a
customer had already supplied:
  (a) _apply_pending_clarify_resolution replayed the STALE first-turn
      utterance instead of trying the customer's CURRENT reply first.
  (b) CpqEngine.apply_answer had no unit/pluralization tolerance, so
      "2 Yrs"/"2 Years" never matched a catalog option displayed as
      "2 Year".
Fixed generically: (a) tries req.question before falling back to the
original vague utterance; (b) adds a token-normalized matching tier
(plural stripping + ordered-subsequence abbreviation check) with no
per-unit synonym table.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import (
    AskRequest,
    _apply_pending_clarify_resolution,
    _ground_clarify_candidates,
)
from aryx.cpq.engine import (
    CpqEngine,
    _is_ordered_abbreviation,
    _option_matches_with_unit_normalization,
    _singularize_token,
    _tokens_match_loosely,
)
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [
        MenuOption(item_value=v, display_name=v, order=i)
        for i, v in enumerate(values, start=1)
    ]


def _smart_programming() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="anywhereProgramming_astro",
        display_label="SmartProgramming", required=False, default_value="",
        select_type="single", options=_menu("1 Year", "2 Year"),
        catalog_prefix="aSTRO25",
    )


def _app_services_duration() -> ConfigAttr:
    return ConfigAttr(
        entity_id=2, variable_name="applicationServicesDurationYears_astro",
        display_label="Application Services Duration Years", required=False,
        default_value="", select_type="single", options=_menu("1 Year", "2 Year"),
        catalog_prefix="aSTRO25",
    )


def _session_with_both_filled() -> CpqSession:
    s = CpqSession(product_name="aSTRO25_bom", status="configuring")
    s.filled = {
        "anywhereProgramming_astro": "1 Year",
        "applicationServicesDurationYears_astro": "1 Year",
    }
    s.display_filled = dict(s.filled)
    s.filled_source = {k: "auto" for k in s.filled}
    s.filled_multi = {}
    return s


# ── Bug 1 ────────────────────────────────────────────────────────────────

def test_explicitly_named_attribute_is_not_paired_with_a_generic_word_overlap():
    attrs = [_smart_programming(), _app_services_duration()]
    session = _session_with_both_filled()

    cands = _ground_clarify_candidates(
        "Set SmartProgramming to 2 Years", attrs, session,
    )
    vns = [a.variable_name for a in cands]

    assert vns == ["anywhereProgramming_astro"], (
        "an attribute named outright must resolve directly, not be offered "
        "alongside an unrelated attribute that only shares a generic word"
    )


def test_two_explicitly_named_attributes_still_disambiguate():
    """Guardrail against over-correction: when the clarifying question
    itself names two real candidates, both must remain — this is the
    scenario test_llm_first_ambiguous_excludes_hidden_attr_from_clarify_
    candidates (tests/test_cpq_2026_07_28_fixes.py) exercises live; this
    is the minimal, isolated version of the same invariant."""
    attrs = [_smart_programming(), _app_services_duration()]
    session = _session_with_both_filled()
    cq = "Did you mean SmartProgramming or Application Services Duration Years?"

    cands = _ground_clarify_candidates(
        "change the duration to 2 years", attrs, session, cq,
    )
    vns = {a.variable_name for a in cands}

    assert vns == {
        "anywhereProgramming_astro", "applicationServicesDurationYears_astro",
    }


# ── Bug 2a ───────────────────────────────────────────────────────────────

def test_pending_clarify_resolution_prefers_the_current_reply_value():
    """_handle_cascade (real rule/graph loading) is mocked out here — this
    test targets _apply_pending_clarify_resolution's own precedence logic,
    not the cascade machinery downstream of it."""
    attrs = [_smart_programming()]
    session = _session_with_both_filled()
    session.pending_clarify_question = "Set SmartProgramming to 2 Years"
    req = AskRequest(
        question="SmartProgramming 2 Year",
        workspace_id=1, history=[], session_data=session.to_dict(),
    )

    with patch("aryx.api.ask_core_helpers._persist_cpq_history"), patch(
        "aryx.api.ask_handle_cascade._handle_cascade",
    ) as mock_cascade:
        mock_cascade.return_value = {"tools_called": ["stubbed"]}
        _apply_pending_clarify_resolution(
            req, session, attrs,
            resolved_vn="anywhereProgramming_astro",
            orig_question=session.pending_clarify_question,
            hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
        )

    mock_cascade.assert_called_once()
    _attr, value_hint = mock_cascade.call_args.args[3], mock_cascade.call_args.args[4]
    assert _attr.variable_name == "anywhereProgramming_astro"
    assert value_hint == "SmartProgramming 2 Year"


def test_pending_clarify_resolution_falls_back_to_original_utterance_value():
    """Pre-existing intended behavior must survive: a bare label reply
    ("SmartProgramming") with no value of its own still picks up the
    value from the earlier vague utterance that triggered the clarify."""
    attrs = [_smart_programming()]
    session = _session_with_both_filled()
    session.pending_clarify_question = "Set SmartProgramming to 2 Year"
    req = AskRequest(
        question="SmartProgramming",
        workspace_id=1, history=[], session_data=session.to_dict(),
    )

    with patch("aryx.api.ask_core_helpers._persist_cpq_history"), patch(
        "aryx.api.ask_handle_cascade._handle_cascade",
    ) as mock_cascade:
        mock_cascade.return_value = {"tools_called": ["stubbed"]}
        _apply_pending_clarify_resolution(
            req, session, attrs,
            resolved_vn="anywhereProgramming_astro",
            orig_question=session.pending_clarify_question,
            hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
        )

    mock_cascade.assert_called_once()
    _attr, value_hint = mock_cascade.call_args.args[3], mock_cascade.call_args.args[4]
    assert _attr.variable_name == "anywhereProgramming_astro"
    assert value_hint == "Set SmartProgramming to 2 Year"


# ── Bug 2b ───────────────────────────────────────────────────────────────

def test_apply_answer_accepts_plural_and_abbreviated_unit_forms():
    engine = CpqEngine()
    attr = _smart_programming()

    assert engine.apply_answer(attr, "2 Years") == ("2 Year", "2 Year")
    assert engine.apply_answer(attr, "2 Yrs") == ("2 Year", "2 Year")
    assert engine.apply_answer(attr, "2 yr") == ("2 Year", "2 Year")


def test_apply_answer_unit_normalization_finds_value_inside_a_full_sentence():
    engine = CpqEngine()
    attr = _smart_programming()

    assert engine.apply_answer(
        attr, "Set SmartProgramming to 2 Years",
    ) == ("2 Year", "2 Year")


def test_apply_answer_unit_normalization_does_not_cross_match_wrong_quantity():
    engine = CpqEngine()
    attr = _smart_programming()

    assert engine.apply_answer(attr, "3 Years") is None


# ── Adversarial: the unit tier must never fire on non-quantity options ────
# (Raven review on this PR, finding C1 — confirmed live against the
# original implementation: _is_ordered_abbreviation("and", "android") was
# True, and _option_matches_with_unit_normalization("Android", "please
# select and go") matched a single-word, non-numeric catalog option
# against an ordinary English word with no relation to it at all. Fixed
# by requiring the option to carry a genuine quantity token — see
# _option_matches_with_unit_normalization's digit gate and
# _tokens_match_loosely's digit-exactness rule.)

def _android_option() -> ConfigAttr:
    return ConfigAttr(
        entity_id=3, variable_name="osChoice_astro", display_label="OS Choice",
        required=False, default_value="", select_type="single",
        options=_menu("Android", "iOS"), catalog_prefix="aSTRO25",
    )


def test_unit_tier_never_fires_on_a_non_numeric_option():
    engine = CpqEngine()
    attr = _android_option()

    assert engine.apply_answer(attr, "please select and go") is None
    assert _option_matches_with_unit_normalization("Android", "please select and go") is False


def test_ordered_abbreviation_alone_is_too_permissive_without_the_digit_gate():
    """Documents exactly what Raven flagged: the letter-subsequence check
    by itself has no concept of "unit word" — it's the digit-token gate
    in _option_matches_with_unit_normalization that scopes it correctly.
    "and"/"android", "sam"/"samsung", and "apx"/"apex" (this catalog's own
    short product-line prefix shape) all still pass this raw building
    block; that's expected and fine, since the caller-level gate is what
    prevents them from ever reaching a real catalog option."""
    assert _is_ordered_abbreviation("and", "android") is True
    assert _is_ordered_abbreviation("sam", "samsung") is True
    assert _is_ordered_abbreviation("apx", "apex") is True


def test_short_product_prefix_option_is_not_matched_via_unit_normalization():
    engine = CpqEngine()
    attr = ConfigAttr(
        entity_id=4, variable_name="modelFamily_astro", display_label="Model Family",
        required=False, default_value="", select_type="single",
        options=_menu("Apex", "Samsung"), catalog_prefix="aSTRO25",
    )

    assert engine.apply_answer(attr, "the apx radio please") is None
    assert engine.apply_answer(attr, "I have a sam device") is None


def test_tokens_match_loosely_requires_exact_equality_for_any_digit_token():
    """A quantity must never be treated as an "abbreviation" of a
    different quantity — "1" is a letter-subsequence of "12" by the same
    mechanism that let "and" abbreviate "android"."""
    assert _tokens_match_loosely("1", "12") is False
    assert _tokens_match_loosely("2", "20") is False
    assert _tokens_match_loosely("2", "2") is True


# ── Direct coverage of the new helpers (Raven review N1) ──────────────────

def test_singularize_token_strips_short_plural_forms_only():
    assert _singularize_token("years") == "year"
    assert _singularize_token("yrs") == "yr"
    assert _singularize_token("is") == "is"
    assert _singularize_token("as") == "as"
    assert _singularize_token("glass") == "glass"


def test_is_ordered_abbreviation_requires_order_and_half_coverage():
    assert _is_ordered_abbreviation("yr", "year") is True
    assert _is_ordered_abbreviation("ry", "year") is False
    assert _is_ordered_abbreviation("y", "year") is False
    assert _is_ordered_abbreviation("year", "year") is False


def test_tokens_match_loosely_handles_plural_and_abbreviation():
    assert _tokens_match_loosely("years", "year") is True
    assert _tokens_match_loosely("yrs", "year") is True
    assert _tokens_match_loosely("month", "year") is False
