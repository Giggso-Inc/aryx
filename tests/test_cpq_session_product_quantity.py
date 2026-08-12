"""docs/CPQ_QUANTITY_SLOTFILLING_AND_UI_ISSUES_PLAN_2026_08_11.md

Session-level product quantity: a dedicated, session-tracked "how many of
this product" concept, decoupled from any catalog attribute's own
options/constraints. Default 1, never leaks into the JSON payload (kept
outside filled/filled_multi entirely), and resolved directly for any
quantity-related question unless a real, competing catalog quantity
attribute also exists for the current configuration.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import aryx.api.ask_api as api
from aryx.api.ask_api import _cpq_summary_text, _llm_resolve_quantity_target, _run_cpq_turn
from aryx.api.ask_api import AskRequest
from aryx.cpq.engine import (
    MAX_PRODUCT_QUANTITY,
    MIN_PRODUCT_QUANTITY,
    extract_quantity_decimal_hint,
    extract_quantity_hint,
    find_catalog_quantity_attrs,
    is_valid_product_quantity,
    question_mentions_quantity,
    quantity_turn_precheck,
)
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import CpqSession, ConfigAttr, MenuOption


@pytest.fixture(autouse=True)
def _no_real_history_persistence(monkeypatch):
    """Every _run_cpq_turn call below must never touch a real Postgres
    pool -- same convention every other ask_api test file already uses
    (e.g. _llm_first_gate_setup). Without this, _persist_cpq_history tries
    to acquire a real connection to an unreachable 'postgres' host and
    blocks for a very long time rather than failing fast (confirmed via
    faulthandler stack dump during this test file's own development)."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)


def _vx650_qty_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="quantityVX650ItemType_astro",
        display_label="Quantity (VX650 Item Type)", required=False,
        default_value="", select_type="integer", options=[],
    )


# ── extract_quantity_hint ────────────────────────────────────────────────────

def test_extract_quantity_hint_covers_real_phrasings():
    assert extract_quantity_hint(
        "I want to order APX Next radios 50 in qty for customer",
    ) == 50
    assert extract_quantity_hint("i want 10 APX NEXT") == 10
    assert extract_quantity_hint("qty of 25") == 25
    assert extract_quantity_hint("quantity is 7") == 7
    assert extract_quantity_hint("30 units please") == 30


def test_extract_quantity_hint_ignores_unrelated_numbers():
    """A model code, a year, or an address digit must never be mistaken
    for quantity -- only numbers adjacent to a quantity-indicating word
    count."""
    assert extract_quantity_hint("model H55TGT9PW8AN for 2026 delivery") is None
    assert extract_quantity_hint("no number-adjacent quantity word here") is None


def test_extract_quantity_hint_never_lifts_digits_out_of_a_model_code():
    """PR #186 review, critical #1: a model code glued directly onto a
    quantity-trigger word ("APX8000 radios") must never be read as the
    stated quantity, even when the real quantity earlier in the message
    isn't itself adjacent to a trigger word. Without a left boundary on
    the digit group, "8000" (from "APX8000") matches "(-?\\d+)...radios"
    since \\d+ can start matching mid-identifier -- silently replacing the
    customer's real "5" with "8000"."""
    assert extract_quantity_hint("quote me 5 APX8000 radios") is None
    assert extract_quantity_hint("check pricing for XPR7000e units") is None


def test_extract_quantity_hint_captures_negative_numbers_rather_than_dropping_the_sign():
    """A negative number must be captured AS negative (then rejected by
    is_valid_product_quantity), never silently parsed as if the minus
    sign wasn't there -- "-5" must never come back as 5."""
    assert extract_quantity_hint("change quantity to -5") == -5
    assert extract_quantity_hint("quantity is -10") == -10


def test_extract_quantity_hint_never_truncates_a_decimal():
    """"1.5" must never come back as 1 -- silently dropping the fractional
    part is worse than not matching at all (a truncated integer looks like
    a confidently-parsed whole number when it isn't one)."""
    assert extract_quantity_hint("change quantity to 1.5") is None


def test_extract_quantity_hint_never_matches_the_fractional_remainder_of_a_decimal():
    """PR #186 review, medium: "10.0" must never come back as 0 -- the
    (?!\\.\\d) guard correctly blocks the direct "10" match, but without a
    left-boundary guard on the digit group, the regex engine backtracks
    and matches the trailing "0" after the decimal point instead of
    failing outright. Covers both prefix-style ("quantity is X") and
    suffix-style ("X units"/"X qty") trigger phrasing, since the two
    pattern shapes hit the bug differently."""
    assert extract_quantity_hint("change quantity to 10.0") is None
    assert extract_quantity_hint("quantity is 10.0") is None
    assert extract_quantity_hint("10.0 units please") is None
    assert extract_quantity_hint("10.0 qty") is None
    assert extract_quantity_hint("qty of 10.0") is None
    assert extract_quantity_hint("i want 10.0 radios") is None


def test_extract_quantity_decimal_hint_exposes_the_real_decimal_text():
    """The companion function must return the exact decimal substring the
    customer typed, so a rejection message can quote it correctly instead
    of the wrong digit the old regex-backtracking bug used to produce."""
    assert extract_quantity_decimal_hint("change quantity to 10.0") == "10.0"
    assert extract_quantity_decimal_hint("quantity is -3.5") == "-3.5"
    assert extract_quantity_decimal_hint("10.0 units please") == "10.0"
    assert extract_quantity_decimal_hint("I want 50 radios") is None
    assert extract_quantity_decimal_hint("no quantity mentioned here at all") is None


def test_extract_quantity_hint_strips_thousands_separator_commas():
    """PR #186 review, critical #2: "1,000" sits at a real word boundary
    right at the comma, so an unguarded integer pattern happily matches
    just the "1" before it and silently truncates the stated quantity --
    no rejection, no indication anything was mangled. Must resolve to the
    full intended value instead."""
    assert extract_quantity_hint("change quantity to 1,000") == 1000
    assert extract_quantity_hint("quantity is 100,000") == 100_000
    assert extract_quantity_hint("i want 12,345 units") == 12_345


def test_extract_quantity_hint_thousands_separator_requires_exactly_three_digits():
    """Only a comma glued directly onto exactly 3 trailing digits counts
    as thousands-grouping -- a comma followed by a space (an ordinary
    list separator, "5, 1000") or by a non-3-digit run is left untouched
    rather than being misread as a group separator."""
    # Comma + space is never grouping syntax -- untouched, so "i want"
    # still resolves to the adjacent "5", not the unrelated "1000".
    assert extract_quantity_hint("i want 5, 1000 items ordered separately") == 5
    # Only 2 digits after the comma -- not a real thousands group.
    assert extract_quantity_hint("quantity is 1,00") == 1


# ── is_valid_product_quantity ────────────────────────────────────────────────

def test_is_valid_product_quantity_rejects_zero_and_negative():
    assert is_valid_product_quantity(0) is False
    assert is_valid_product_quantity(-5) is False
    assert is_valid_product_quantity(-1) is False


def test_is_valid_product_quantity_rejects_absurd_overflow():
    assert is_valid_product_quantity(MAX_PRODUCT_QUANTITY + 1) is False
    assert is_valid_product_quantity(999_999_999_999) is False


def test_is_valid_product_quantity_accepts_the_real_range():
    assert is_valid_product_quantity(MIN_PRODUCT_QUANTITY) is True
    assert is_valid_product_quantity(1) is True
    assert is_valid_product_quantity(50) is True
    assert is_valid_product_quantity(MAX_PRODUCT_QUANTITY) is True


# ── Spelled-out ("word") quantities ───────────────────────────────────────────

def test_extract_quantity_hint_accepts_word_form_same_as_digit_form():
    """"I want ten APX Next" must work exactly as well as "I want 10 APX
    Next" -- a customer typing the number as a word is not asking for
    anything different."""
    assert extract_quantity_hint("I want ten APX Next") == 10
    assert extract_quantity_hint("I want 10 APX Next") == 10


def test_extract_quantity_hint_handles_a_quoted_number_word_or_digit():
    """The client's own example: quoting the number for emphasis must not
    break extraction, whether it's quoted as a word or a digit."""
    assert extract_quantity_hint('I want "ten" APX Next') == 10
    assert extract_quantity_hint('I want "10" APX Next') == 10


def test_extract_quantity_hint_handles_compound_and_scaled_number_words():
    assert extract_quantity_hint("change quantity to twenty-five") == 25
    assert extract_quantity_hint("qty of thirty") == 30
    assert extract_quantity_hint("quantity is one hundred and fifty") == 150
    assert extract_quantity_hint("set quantity to two thousand") == 2000


def test_extract_quantity_hint_handles_spelled_out_negative_numbers():
    """"negative five" must produce a real -5 (then rejected by
    is_valid_product_quantity, same as the digit form) -- silently
    dropping "negative" and returning 5 as if it were positive would be
    exactly the same class of bug already fixed for "-5"."""
    assert extract_quantity_hint("i want negative five radios") == -5
    assert extract_quantity_hint("change quantity to minus ten") == -10


def test_extract_quantity_hint_never_guesses_an_unrecognized_word():
    """A word that isn't a recognized number word at all must never
    produce a guess."""
    assert extract_quantity_hint("i want purple radios") is None


def test_extract_quantity_hint_never_misreads_a_bare_and_as_a_number():
    """"and" is only ever valid as glue INSIDE an already-started number
    run ("one hundred and fifty") -- it must never be treated as a
    standalone match on its own in ordinary text."""
    assert extract_quantity_hint("this and that, quantity of nothing") is None


# ── question_mentions_quantity / quantity_turn_precheck ──────────────────────

def test_question_mentions_quantity_cheap_trigger():
    assert question_mentions_quantity("what's my quantity") is True
    assert question_mentions_quantity("how many VX650 mics do I have") is True
    assert question_mentions_quantity("change hardware version") is False


def test_quantity_turn_precheck_none_when_not_quantity_related():
    assert quantity_turn_precheck("change hardware version", [_vx650_qty_attr()]) is None


def test_quantity_turn_precheck_finds_real_catalog_candidates():
    result = quantity_turn_precheck("what is my quantity", [_vx650_qty_attr()])
    assert result is not None
    assert result["candidates"] == [_vx650_qty_attr()]
    assert result["is_change"] is False
    assert result["value"] is None


def test_quantity_turn_precheck_detects_change_with_value():
    result = quantity_turn_precheck("change quantity to 20", [_vx650_qty_attr()])
    assert result["is_change"] is True
    assert result["value"] == 20


def test_find_catalog_quantity_attrs_excludes_menu_backed_and_unrelated():
    menu_attr = ConfigAttr(
        entity_id=2, variable_name="batteryType_astro", display_label="Battery Type",
        required=False, default_value="", select_type="single",
        options=[MenuOption(item_value="STANDARD", display_name="Standard")],
    )
    unrelated_numeric = ConfigAttr(
        entity_id=3, variable_name="serviceActivationDelay_astro",
        display_label="Service Activation Delay", required=False,
        default_value="", select_type="integer", options=[],
    )
    qty = _vx650_qty_attr()
    found = find_catalog_quantity_attrs([menu_attr, unrelated_numeric, qty])
    assert found == [qty]


# ── Session field defaults ────────────────────────────────────────────────────

def test_product_quantity_defaults_to_one():
    session = CpqSession()
    assert session.product_quantity == 1


def test_product_quantity_round_trips_through_to_dict_from_dict():
    session = CpqSession()
    session.product_quantity = 7
    restored = CpqSession.from_dict(session.to_dict())
    assert restored.product_quantity == 7


# ── End-to-end turn behavior ──────────────────────────────────────────────────

def _base_session(**overrides) -> CpqSession:
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States")
    for k, v in overrides.items():
        setattr(session, k, v)
    return session


class _EmptyReader:
    """Minimal fake graph reader: no product families found, but a real
    `distinct_types()` method so product-detection's own try/except takes
    its normal path instead of the AttributeError fallback a bare
    `object()` triggers -- irrelevant to what this test actually checks
    (quantity extraction, which runs before product detection either way)."""

    def distinct_types(self):
        return []

    def find_entities(self, **kwargs):
        return []


def test_opening_message_captures_quantity_without_being_asked(monkeypatch):
    """The real reproduction: "...radios 50 in qty..." must set
    product_quantity from turn 1, before product detection even runs --
    the extraction is unconditional, not gated on a product existing yet."""
    session = CpqSession()
    req = AskRequest(
        question="I want to order APX Next radios 50 in qty for customer "
                  "who is Houston City of with destination country as United States",
        workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn(req, _EmptyReader())
    assert resp["session_data"]["product_quantity"] == 50


def test_quantity_question_answers_from_session_with_no_competing_attribute(monkeypatch):
    """No catalog quantity attribute in play at all -- unambiguous, no LLM
    call, resolves straight from the session value."""
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: ([], "aSTRO25_bom"),
    )
    session = _base_session(product_quantity=5)
    req = AskRequest(question="what's my quantity", workspace_id=1,
                      session_data=session.to_dict())
    with patch("aryx.cpq.intent_gateway.complete_text") as mock_llm:
        resp = _run_cpq_turn(req, object())
    mock_llm.assert_not_called()
    assert "5" in resp["answer"]
    assert resp["session_data"]["product_quantity"] == 5


def test_quantity_change_with_no_competing_attribute_updates_session(monkeypatch):
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: ([], "aSTRO25_bom"),
    )
    session = _base_session(product_quantity=1)
    req = AskRequest(question="change quantity to 20", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp["session_data"]["product_quantity"] == 20


def test_explicit_zero_quantity_is_rejected_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: ([], "aSTRO25_bom"),
    )
    session = _base_session(product_quantity=50)
    req = AskRequest(question="change quantity to 0", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp["tools_called"] == ["cpq_product_quantity_rejected()"]
    assert "isn't a valid quantity" in resp["answer"]
    # The stale, still-valid value must survive untouched.
    assert resp["session_data"]["product_quantity"] == 50


def test_explicit_negative_quantity_is_rejected_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: ([], "aSTRO25_bom"),
    )
    session = _base_session(product_quantity=50)
    req = AskRequest(question="change quantity to -5", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp["tools_called"] == ["cpq_product_quantity_rejected()"]
    assert "-5" in resp["answer"]
    assert resp["session_data"]["product_quantity"] == 50


def test_explicit_absurd_quantity_is_rejected_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: ([], "aSTRO25_bom"),
    )
    session = _base_session(product_quantity=50)
    req = AskRequest(question="change quantity to 999999999", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp["tools_called"] == ["cpq_product_quantity_rejected()"]
    assert resp["session_data"]["product_quantity"] == 50


def test_explicit_decimal_quantity_is_rejected_quoting_the_real_input(monkeypatch):
    """PR #186 review, medium: the rejection message must quote the exact
    decimal the customer typed ("10.0"), never the wrong digit the old
    regex-backtracking bug used to surface ("0")."""
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: ([], "aSTRO25_bom"),
    )
    session = _base_session(product_quantity=50)
    req = AskRequest(question="change quantity to 10.0", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp["tools_called"] == ["cpq_product_quantity_rejected()"]
    assert "10.0" in resp["answer"]
    assert "isn't a valid quantity" in resp["answer"]
    # The stale, still-valid value must survive untouched.
    assert resp["session_data"]["product_quantity"] == 50


def test_implausible_number_in_opening_message_is_silently_ignored_not_accepted():
    """Turn 1's unconditional background capture never surfaces a
    rejection message (there was no explicit "set my quantity" request to
    reject) -- an implausible inferred number is just never adopted,
    leaving the default (1) in place rather than an invalid value."""
    session = CpqSession()
    req = AskRequest(
        question="I want to order APX Next radios 0 in qty for the customer",
        workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn(req, _EmptyReader())
    assert resp["session_data"]["product_quantity"] == 1


def test_quantity_question_before_any_quote_prompts_for_a_product_first():
    """Live-confirmed gap: "what is my quantity?" as the very first
    message (no product selected yet) fell into the product-family
    anchor gate and came back as "I didn't get ... for product family,
    please pick one" -- confusing, and doesn't answer what was actually
    asked. Must instead say quantity isn't configured yet and prompt for
    a product, never silently guess or crash into the anchor gate."""
    session = CpqSession()
    req = AskRequest(question="what is my quantity?", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn(req, _EmptyReader())
    assert resp["tools_called"] == ["cpq_product_quantity_no_quote()"]
    assert "not configured yet" in resp["answer"]
    assert "order" in resp["answer"].lower()
    assert resp["session_data"]["product_quantity"] == 1


def test_quantity_mention_alongside_a_real_order_start_is_not_short_circuited():
    """"I want to order 50 radios, what's my quantity" is establishing a
    quote RIGHT NOW, not asking about one that doesn't exist -- must fall
    through to the normal anchor flow (which also captures the 50), never
    hit the "no quote started" short-circuit."""
    session = CpqSession()
    req = AskRequest(
        question="I want to order APX Next radios, 50 in qty, what's my quantity",
        workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn(req, _EmptyReader())
    assert resp["tools_called"] != ["cpq_product_quantity_no_quote()"]
    assert resp["session_data"]["product_quantity"] == 50


def test_named_catalog_attribute_falls_through_to_normal_pipeline(monkeypatch):
    """"how many VX650 mics" clearly names the specific catalog attribute
    -- the gate must resolve to it via the LLM helper and then get out of
    the way (fall through), never answering from the session value.

    Falling through means the rest of the (large, real) turn pipeline
    runs for real, so this needs the same broad mocking every other
    fall-through-exercising test in this codebase uses (mirrors
    test_cpq_2026_07_28_fixes.py's _llm_first_gate_setup) -- otherwise it
    tries to reach a real Postgres-backed rules/BML load and hangs."""
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules", lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    # extract_flag_hints hits a real DB-backed function-script index
    # (_build_flag_keyword_index) several steps into the fallen-through
    # pipeline -- irrelevant to what this test checks (that the gate
    # falls through at all, not that the rest of a real turn succeeds
    # against a real catalog) and unreachable in this sandbox (no local
    # Postgres), so it's neutralized the same way every other DB-backed
    # rule/script loader above already is.
    monkeypatch.setattr(api._cpq_engine, "extract_flag_hints", lambda *a, **k: {})
    qty_attr = _vx650_qty_attr()
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: ([qty_attr], "aSTRO25_bom"),
    )
    # The VX650 mic must already be a real, selected part of this
    # configuration for asking "how many VX650 mics do I have" to make
    # sense as a real scenario at all -- see the relevance-filter comment
    # above this gate in ask_api.py.
    session = _base_session(product_quantity=1)
    session.filled[qty_attr.variable_name] = "1"
    req = AskRequest(question="how many VX650 mics do I have", workspace_id=1,
                      session_data=session.to_dict())
    fake_reply = '{"target": "quantityVX650ItemType_astro"}'
    with patch(
        "aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 5, 3),
    ):
        resp = _run_cpq_turn(req, object())
    # Fell through -- did NOT short-circuit with a session-quantity answer.
    assert "cpq_product_quantity()" not in resp["tools_called"]
    assert "cpq_quantity_disambiguation()" not in resp["tools_called"]


def test_ambiguous_bare_quantity_with_competing_attribute_asks_disambiguation(monkeypatch):
    qty_attr = _vx650_qty_attr()
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: ([qty_attr], "aSTRO25_bom"),
    )
    # This accessory must already be a REAL part of the current
    # configuration (a real value in session.filled) for it to count as a
    # genuine competing candidate -- load_product_config returns every
    # "Quantity of X" attribute the whole catalog could ever have, most of
    # which are irrelevant unless the customer actually selected that
    # accessory (live bug: a disambiguation question named several
    # accessories the customer never chose at all).
    session = _base_session(product_quantity=3)
    session.filled[qty_attr.variable_name] = "2"
    req = AskRequest(question="what's the quantity", workspace_id=1,
                      session_data=session.to_dict())
    fake_reply = '{"target": "ambiguous"}'
    with patch(
        "aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 5, 3),
    ):
        resp = _run_cpq_turn(req, object())
    assert resp["tools_called"] == ["cpq_quantity_disambiguation()"]
    assert "product quantity" in resp["answer"]
    assert "Quantity (VX650 Item Type)" in resp["answer"]


def test_disambiguation_resolving_to_product_answers_from_session(monkeypatch):
    qty_attr = _vx650_qty_attr()
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: ([qty_attr], "aSTRO25_bom"),
    )
    session = _base_session(product_quantity=12)
    req = AskRequest(question="what's the quantity", workspace_id=1,
                      session_data=session.to_dict())
    fake_reply = '{"target": "product"}'
    with patch(
        "aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 5, 3),
    ):
        resp = _run_cpq_turn(req, object())
    assert resp["tools_called"] == ["cpq_product_quantity()"]
    assert "12" in resp["answer"]


def test_unselected_catalog_quantity_attrs_are_never_offered_as_candidates(monkeypatch):
    """Live bug: "where is the quantity?" listed FOUR real catalog
    "Quantity of X" attributes (spares, RSM mics, an adaptor) the customer
    never selected at all -- load_product_config returns the whole
    catalog's attribute list, most of it irrelevant to this specific
    configuration. None of them being in session.filled means there is
    NO real competing candidate -- must resolve straight to the overall
    product quantity, no disambiguation question, no LLM call."""
    unrelated_attrs = [
        ConfigAttr(
            entity_id=i, variable_name=vn, display_label=label,
            required=False, default_value="", select_type="integer", options=[],
        )
        for i, (vn, label) in enumerate([
            ("quantityForSpares_astro", "Quantity for Spares"),
            ("qtyOfXVN500RemoteSpeakerMic_astro", "Qty of XVN500 Remote Speaker Mic"),
            ("qtyOf12PinAdaptor_astro", "Qty of 12-pin Interface-to-10-Pin RFDC Adaptor"),
            ("qtyOfSVXRemoteSpeakerMic_astro", "Qty of SVX Remote Speaker Mic"),
        ], start=1)
    ]
    monkeypatch.setattr(
        "aryx.api.ask_api._cpq_engine.load_product_config",
        lambda *a, **k: (unrelated_attrs, "aSTRO25_bom"),
    )
    session = _base_session(product_quantity=50)
    # None of the unrelated_attrs are in session.filled -- the customer
    # never selected any of these accessories.
    req = AskRequest(question="where is the quantity?", workspace_id=1,
                      session_data=session.to_dict())
    with patch("aryx.cpq.intent_gateway.complete_text") as mock_llm, \
         patch("aryx.api.ask_api.llm_runtime.chat") as mock_chat:
        resp = _run_cpq_turn(req, object())
    mock_llm.assert_not_called()
    mock_chat.assert_not_called()
    assert resp["tools_called"] == ["cpq_product_quantity()"]
    assert "50" in resp["answer"]
    for attr in unrelated_attrs:
        assert attr.display_label not in resp["answer"]


def test_summary_text_includes_quantity_line_when_provided(monkeypatch):
    """Live bug: "Configuration complete" never mentioned quantity at
    all, even though the customer had already stated one -- the summary
    line was planned but never actually wired into _cpq_summary_text.
    Forces the LLM-narration path to fail so the deterministic
    render_filled_summary fallback runs -- the quantity line must still
    be appended regardless of which internal path produced the base text."""
    monkeypatch.setattr(
        "aryx.api.ask_api.llm_runtime.chat",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("forced failure")),
    )
    hw_attr = ConfigAttr(
        entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", select_type="single",
        options=[MenuOption(item_value="H1", display_name="APX NEXT (4G LTE Only)")],
    )
    text = _cpq_summary_text(
        {"hWVersion_astro": "APX NEXT (4G LTE Only)"}, [hw_attr], {1},
        "aSTRO25_bom", 1, sources={"hWVersion_astro": "user"},
        product_quantity=50,
    )
    assert "50" in text
    assert "Quantity" in text


def test_summary_text_omits_quantity_line_when_not_provided(monkeypatch):
    """product_quantity=None (the default) must be a complete no-op --
    every existing caller that hasn't been updated to pass it keeps
    today's exact output, no accidental "Quantity: None" line."""
    monkeypatch.setattr(
        "aryx.api.ask_api.llm_runtime.chat",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("forced failure")),
    )
    hw_attr = ConfigAttr(
        entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", select_type="single",
        options=[MenuOption(item_value="H1", display_name="APX NEXT (4G LTE Only)")],
    )
    text = _cpq_summary_text(
        {"hWVersion_astro": "APX NEXT (4G LTE Only)"}, [hw_attr], {1},
        "aSTRO25_bom", 1, sources={"hWVersion_astro": "user"},
    )
    assert "Quantity" not in text
    assert "None" not in text


def test_product_quantity_never_leaks_into_build_payload():
    """Structural guarantee, not convention: product_quantity lives
    outside filled/filled_multi entirely, so build_payload -- which only
    ever iterates those two dicts -- can never emit it, regardless of
    value."""
    from aryx.cpq.engine import CpqEngine
    eng = CpqEngine()
    attr = ConfigAttr(
        entity_id=1, variable_name="hWVersion_astro", display_label="HW",
        required=False, default_value="", select_type="single",
        options=[MenuOption(item_value="H1", display_name="H1")],
    )
    session = CpqSession(product_quantity=99)
    session.filled = {"hWVersion_astro": "H1"}
    session.filled_source = {"hWVersion_astro": "user"}
    payload = eng.build_payload(
        session.filled, session.filled_source, session.filled_multi, [attr],
    )
    assert "product_quantity" not in payload["configData"]
    assert "99" not in str(payload)


def test_llm_resolve_quantity_target_rejects_invented_variable_name():
    """Never-guess discipline: a model reply naming something outside the
    real candidate list must be discarded, not trusted."""
    qty_attr = _vx650_qty_attr()
    session = _base_session(product_quantity=1)
    fake_reply = '{"target": "totallyMadeUpAttr_astro"}'
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 5, 3)):
        result = _llm_resolve_quantity_target(
            "what's the quantity", [qty_attr], session, workspace_id=1,
        )
    assert result is None
