"""Regression coverage for docs/CPQ_QUANTITY_EXTRACTION_DEFECTS_PLAN_2026_08_13.md
-- the 10-row QA transcript sheet of quantity-extraction defects, plus the
new `_llm_confirm_and_extract_quantity` checkpoint and the related
negative-quantity quarantine bug found during implementation.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _llm_confirm_and_extract_quantity, _run_cpq_turn
from aryx.cpq.engine import extract_quantity_hint
from aryx.cpq.intent_gateway import GatewayDecision
from aryx.cpq.intent_schema import (
    Confidence,
    GatewayIntentResult,
    IntentCategory,
    _is_signed_digit_quantity_text,
    validate_gateway_quarantine,
)
from aryx.cpq.state import CpqSession


# ═══════════════════════════════════════════════════════════════════════
# Cluster 1 — "twelve" misclassified as a dozen-style multiplier
# ═══════════════════════════════════════════════════════════════════════

def test_spelled_out_compound_number_resolves_correctly():
    assert extract_quantity_hint("one hundred and twelve units") == 112


def test_number_word_run_with_no_scale_word_is_plain_addition():
    assert extract_quantity_hint("twenty twelve units") == 32


# ═══════════════════════════════════════════════════════════════════════
# Cluster 2 — fraction/count modifiers before "dozen" dropped
# ═══════════════════════════════════════════════════════════════════════

def test_half_a_dozen_resolves_to_six():
    assert extract_quantity_hint("half a dozen units") == 6


def test_a_couple_dozen_resolves_to_twenty_four():
    assert extract_quantity_hint("a couple dozen units") == 24


def test_plain_dozen_still_resolves_to_twelve():
    """Regression guard: the new modifier handling must not break the
    plain, unmodified "a dozen" case that already worked."""
    assert extract_quantity_hint("a dozen APX NEXT radios") == 12


# ═══════════════════════════════════════════════════════════════════════
# Cluster 3 — sign word ignored for the digit form
# ═══════════════════════════════════════════════════════════════════════

def test_sign_word_before_a_digit_produces_a_real_negative():
    assert extract_quantity_hint("minus 5 units") == -5


def test_sign_word_before_a_number_word_still_works():
    """Regression guard: the pre-existing word-form sign path must be
    unaffected by the new digit-form sign substitution."""
    assert extract_quantity_hint("negative five radios") == -5
    assert extract_quantity_hint("change quantity to minus ten") == -10


# ═══════════════════════════════════════════════════════════════════════
# Cluster 4 — "N model(s)" matching a year
# ═══════════════════════════════════════════════════════════════════════

def test_year_before_model_is_never_read_as_a_quantity():
    assert extract_quantity_hint("the 2026 model") is None


def test_real_5_digit_quantity_ending_in_a_year_shape_still_extracts():
    """PR review finding, 2026-08-13: a fixed-width lookbehind guard can
    only ever see the trailing 4 characters before the match, so it
    can't distinguish a real year ("2026") from a longer, real quantity
    whose LAST 4 digits merely happen to look like one ("12026",
    "32026") -- both were wrongly rejected entirely. The exclusion must
    be checked against the full captured digit string's length, not
    just its tail."""
    assert extract_quantity_hint("order 12026 models") == 12026
    assert extract_quantity_hint("order 32026 models") == 32026
    assert extract_quantity_hint("order 55026 models") == 55026


def test_plain_digit_before_model_still_works():
    assert extract_quantity_hint("order 12 models") == 12


# ═══════════════════════════════════════════════════════════════════════
# Cluster 5 — adjacency defeated by an intervening product name
# ═══════════════════════════════════════════════════════════════════════

def test_intervening_product_name_does_not_block_extraction():
    assert extract_quantity_hint(
        "Can you price 15 APX NEXT radios for a customer in Canada?"
    ) == 15
    assert extract_quantity_hint("order 15 APX NEXT radios") == 15


def test_model_code_glued_to_digits_still_never_matches():
    """Regression guard (PR #186 review, critical #1): a model code must
    still block the match entirely, even though intervening words are
    now tolerated -- an intervening "word" containing digits must never
    be treated as an acceptable product-name word."""
    assert extract_quantity_hint("quote me 5 APX8000 radios") is None


# ═══════════════════════════════════════════════════════════════════════
# Cluster 6 — "qty to N" unsupported
# ═══════════════════════════════════════════════════════════════════════

def test_qty_to_n_now_matches_same_as_quantity_to_n():
    assert extract_quantity_hint("update qty to 30") == 30
    assert extract_quantity_hint("change qty to 30") == 30


# ═══════════════════════════════════════════════════════════════════════
# _is_signed_digit_quantity_text / quarantine — negative quantity bug
# ═══════════════════════════════════════════════════════════════════════

def test_signed_digit_helper_accepts_negative():
    assert _is_signed_digit_quantity_text("-5") is True
    assert _is_signed_digit_quantity_text("67") is True


def test_signed_digit_helper_rejects_non_digits():
    assert _is_signed_digit_quantity_text(None) is False
    assert _is_signed_digit_quantity_text("") is False
    assert _is_signed_digit_quantity_text("abc") is False
    assert _is_signed_digit_quantity_text("5.0") is False


def _qty_gateway_result(quantity_text) -> GatewayIntentResult:
    return GatewayIntentResult(
        intent_category=IntentCategory.PRODUCT_QUANTITY_CHANGE,
        confidence=Confidence.HIGH,
        quantity_text=quantity_text,
        evidence_span="minus 5 units",
        rationale="test",
    )


def test_quarantine_accepts_a_genuine_negative_quantity_text():
    """Before the fix, `.isdigit()` rejected the leading "-" and this
    always downgraded to AMBIGUOUS, even when the LLM correctly reported
    a real negative quantity."""
    result = validate_gateway_quarantine(
        _qty_gateway_result("-5"), "minus 5 units", set(), {},
    )
    assert result.intent_category == IntentCategory.PRODUCT_QUANTITY_CHANGE
    assert result.quantity_text == "-5"


def test_quarantine_still_rejects_a_non_digit_quantity_text():
    result = validate_gateway_quarantine(
        _qty_gateway_result("a dozen"), "minus 5 units", set(), {},
    )
    assert result.intent_category == IntentCategory.AMBIGUOUS


# ═══════════════════════════════════════════════════════════════════════
# _llm_confirm_and_extract_quantity — the new checkpoint, in isolation
# ═══════════════════════════════════════════════════════════════════════

def _base_req_session():
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(question="anything", workspace_id=1, session_data=session.to_dict())
    return req, session


def _decision(category, quantity_text=None):
    return GatewayDecision(
        action="dispatch",
        result=GatewayIntentResult(
            intent_category=category, confidence=Confidence.HIGH,
            quantity_text=quantity_text, evidence_span="", rationale="test",
        ),
    )


def test_extract_uses_the_llms_own_value_over_the_deterministic_one():
    """The exact mechanism this checkpoint exists to fix: the LLM's own
    quantity_text corrects a wrong deterministic value from the SAME
    call, instead of the deterministic mis-parse winning unconditionally
    once the category is merely confirmed."""
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_decision(IntentCategory.PRODUCT_QUANTITY_CHANGE, "112"),
    ):
        confirmed, value, decimal = _llm_confirm_and_extract_quantity(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="", fallback_value=1200, fallback_decimal=None,
        )
    assert (confirmed, value, decimal) == (True, 112, None)


def test_extract_falls_back_to_deterministic_value_when_llm_text_unusable():
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_decision(IntentCategory.PRODUCT_QUANTITY_CHANGE, None),
    ):
        confirmed, value, decimal = _llm_confirm_and_extract_quantity(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="", fallback_value=24, fallback_decimal=None,
        )
    assert (confirmed, value, decimal) == (True, 24, None)


def test_extract_rejects_on_category_disagreement():
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_decision(IntentCategory.AMBIGUOUS),
    ):
        confirmed, value, decimal = _llm_confirm_and_extract_quantity(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="", fallback_value=6, fallback_decimal=None,
        )
    assert (confirmed, value, decimal) == (False, None, None)


def test_extract_rejects_on_gateway_exception():
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent", side_effect=TimeoutError("llm unreachable"),
    ):
        confirmed, value, decimal = _llm_confirm_and_extract_quantity(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="", fallback_value=6, fallback_decimal=None,
        )
    assert (confirmed, value, decimal) == (False, None, None)


def test_extract_accepts_a_negative_value_from_the_llm():
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_decision(IntentCategory.PRODUCT_QUANTITY_CHANGE, "-5"),
    ):
        confirmed, value, decimal = _llm_confirm_and_extract_quantity(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="", fallback_value=5, fallback_decimal=None,
        )
    assert (confirmed, value, decimal) == (True, -5, None)


# ═══════════════════════════════════════════════════════════════════════
# Full turn — the STEP-6 gate corrects a wrong deterministic value
# ═══════════════════════════════════════════════════════════════════════

@patch.object(api, "_persist_cpq_history", lambda *a, **k: None)
def test_full_turn_change_command_uses_llm_corrected_value(monkeypatch):
    """"change the quantity to one hundred and twelve" with the pre-fix
    dozen/twelve collision would deterministically resolve to 1200 --
    the STEP-6 gate must prefer the LLM's own correctly-extracted 112."""
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: _decision(IntentCategory.PRODUCT_QUANTITY_CHANGE, "112"),
    )
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", product_quantity=1)
    req = AskRequest(
        question="change the quantity to one hundred and twelve",
        workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn(req, object())
    assert resp["session_data"]["product_quantity"] == 112
