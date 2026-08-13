"""Quarantine + parse coverage for cpq/intent_gateway.py.

No live LLM calls — validation, candidate selection, agreement, and cache
are pure deterministic unit tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.intent_gateway import (
    MUTATING_CATEGORIES,
    AttrCandidateBundle,
    ValueCandidate,
    build_candidate_bundles,
    classify_intent,
    clear_gateway_cache,
    resolve_value_from_ref,
    session_state_hash,
)
from aryx.cpq.intent_schema import (
    GATEWAY_INTENT_JSON_SCHEMA,
    Confidence,
    GatewayIntentResult,
    IntentCategory,
    parse_gateway_intent,
    validate_gateway_quarantine,
)
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _attr(vn: str, label: str, options: list[tuple[str, str]] | None = None) -> ConfigAttr:
    opts = [
        MenuOption(item_value=iv, display_name=dn, order=i)
        for i, (iv, dn) in enumerate(options or [])
    ]
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=label,
        required=False, default_value="", options=opts,
    )


def test_gateway_schema_enum_matches_intent_category():
    schema_vals = GATEWAY_INTENT_JSON_SCHEMA["properties"]["intent_category"]["enum"]
    assert schema_vals == [c.value for c in IntentCategory]


def test_parse_gateway_intent_happy_path():
    raw = {
        "intent_category": "change_request",
        "confidence": "high",
        "variable_name": "hWVersion_astro",
        "value_ref": 1,
        "evidence_span": "change hardware to H45",
        "rationale": "clear change",
    }
    result = parse_gateway_intent(raw)
    assert result is not None
    assert result.intent_category == IntentCategory.CHANGE_REQUEST
    assert result.variable_name == "hWVersion_astro"
    assert result.value_ref == 1


def test_parse_rejects_non_int_value_ref():
    raw = {
        "intent_category": "change_request",
        "confidence": "high",
        "variable_name": "hWVersion_astro",
        "value_ref": "1",  # must be int index, not string
        "evidence_span": "change hardware",
    }
    assert parse_gateway_intent(raw) is None


def test_parse_rejects_bool_value_ref():
    # bool is a subclass of int in Python — must be rejected explicitly
    raw = {
        "intent_category": "change_request",
        "confidence": "high",
        "variable_name": "hWVersion_astro",
        "value_ref": True,
        "evidence_span": "change hardware",
    }
    assert parse_gateway_intent(raw) is None


def test_quarantine_rejects_unknown_variable_name():
    result = GatewayIntentResult(
        intent_category=IntentCategory.CHANGE_REQUEST,
        confidence=Confidence.HIGH,
        variable_name="invented_field_xyz",
        value_ref=0,
        evidence_span="change hardware",
    )
    out = validate_gateway_quarantine(
        result,
        question="please change hardware",
        candidate_vns={"hWVersion_astro"},
        value_counts={"hWVersion_astro": 3},
    )
    assert out.intent_category == IntentCategory.AMBIGUOUS
    assert "variable_name_not_in_candidates" in out.rationale


def test_quarantine_rejects_value_ref_out_of_range():
    result = GatewayIntentResult(
        intent_category=IntentCategory.CHANGE_REQUEST,
        confidence=Confidence.HIGH,
        variable_name="hWVersion_astro",
        value_ref=99,
        evidence_span="change hardware",
    )
    out = validate_gateway_quarantine(
        result,
        question="please change hardware",
        candidate_vns={"hWVersion_astro"},
        value_counts={"hWVersion_astro": 2},
    )
    assert out.intent_category == IntentCategory.AMBIGUOUS
    assert "value_ref_out_of_range" in out.rationale


def test_quarantine_rejects_missing_evidence_span():
    result = GatewayIntentResult(
        intent_category=IntentCategory.CHANGE_REQUEST,
        confidence=Confidence.HIGH,
        variable_name="hWVersion_astro",
        value_ref=0,
        evidence_span="not in the message at all",
    )
    out = validate_gateway_quarantine(
        result,
        question="please change hardware version",
        candidate_vns={"hWVersion_astro"},
        value_counts={"hWVersion_astro": 2},
    )
    assert out.intent_category == IntentCategory.AMBIGUOUS
    assert "evidence_span_missing" in out.rationale


def test_quarantine_accepts_valid_selection():
    result = GatewayIntentResult(
        intent_category=IntentCategory.CHANGE_REQUEST,
        confidence=Confidence.HIGH,
        variable_name="hWVersion_astro",
        value_ref=1,
        evidence_span="change hardware",
    )
    out = validate_gateway_quarantine(
        result,
        question="please change hardware to H45",
        candidate_vns={"hWVersion_astro"},
        value_counts={"hWVersion_astro": 3},
    )
    assert out.intent_category == IntentCategory.CHANGE_REQUEST
    assert out.variable_name == "hWVersion_astro"


def test_resolve_value_from_ref_uses_candidate_index_not_llm_text():
    attr = _attr("hWVersion_astro", "Hardware Version", [
        ("H1", "Hardware 1"), ("H45", "Hardware 45"),
    ])
    bundles = [AttrCandidateBundle(
        attr=attr,
        values=[
            ValueCandidate(0, "H1", "Hardware 1"),
            ValueCandidate(1, "H45", "Hardware 45"),
        ],
    )]
    result = GatewayIntentResult(
        intent_category=IntentCategory.CHANGE_REQUEST,
        confidence=Confidence.HIGH,
        variable_name="hWVersion_astro",
        value_ref=1,
        evidence_span="H45",
    )
    display, item = resolve_value_from_ref(result, bundles)
    assert display == "Hardware 45"
    assert item == "H45"


def test_build_candidates_prefers_filled_and_pending():
    session = CpqSession()
    session.filled = {"country_attr": "US"}
    session.pending_variables = ["hWVersion_astro"]
    attrs = [
        _attr("noise_a", "Noise A"),
        _attr("country_attr", "Country", [("US", "United States")]),
        _attr("hWVersion_astro", "Hardware Version", [("H1", "H1")]),
    ]
    bundles = build_candidate_bundles(attrs, session, "change hardware")
    vns = {b.attr.variable_name for b in bundles}
    assert "hWVersion_astro" in vns
    assert "country_attr" in vns


def test_session_state_hash_changes_with_filled():
    s1 = CpqSession()
    s1.filled = {"a": "1"}
    s2 = CpqSession()
    s2.filled = {"a": "2"}
    assert session_state_hash(s1) != session_state_hash(s2)


def test_classify_fallback_when_llm_returns_garbage():
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    session.filled = {"hWVersion_astro": "H1"}
    attrs = [_attr("hWVersion_astro", "Hardware Version", [("H1", "H1"), ("H45", "H45")])]
    engine = MagicMock()
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None

    with patch("aryx.cpq.intent_gateway._pinned_chat", return_value=("not json", 1, 1)):
        decision = classify_intent(
            "change hardware to H45", attrs, session, engine, workspace_id=1,
        )
    assert decision.action == "fallback"
    assert decision.reason == "schema_fail"


def test_classify_clarify_on_mutating_disagreement():
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    session.filled = {"hWVersion_astro": "H1"}
    attrs = [_attr("hWVersion_astro", "Hardware Version", [("H1", "H1"), ("H45", "H45")])]
    engine = MagicMock()
    # Deterministic path finds nothing → disagreement for mutating intent
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None

    good_json = (
        '{"intent_category":"change_request","confidence":"high",'
        '"variable_name":"hWVersion_astro","value_ref":1,'
        '"evidence_span":"change hardware","rationale":"llm only"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(good_json, 10, 5),
    ):
        decision = classify_intent(
            "please change hardware", attrs, session, engine, workspace_id=1,
        )
    assert decision.action == "clarify"
    assert decision.reason == "mutating_disagreement"
    assert decision.result is not None
    assert decision.result.intent_category == IntentCategory.AMBIGUOUS


def test_classify_dispatch_when_mutating_agrees():
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    session.filled = {"hWVersion_astro": "H1"}
    hw = _attr("hWVersion_astro", "Hardware Version", [("H1", "H1"), ("H45", "H45")])
    attrs = [hw]
    engine = MagicMock()
    engine.detect_change_request.return_value = (hw, "H45")
    engine.detect_change_requests_multi.return_value = [(hw, "H45")]
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None

    good_json = (
        '{"intent_category":"change_request","confidence":"high",'
        '"variable_name":"hWVersion_astro","value_ref":1,'
        '"evidence_span":"change hardware","rationale":"agreed"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(good_json, 10, 5),
    ):
        decision = classify_intent(
            "please change hardware", attrs, session, engine, workspace_id=1,
        )
    assert decision.action == "dispatch"
    assert decision.result is not None
    assert decision.result.variable_name == "hWVersion_astro"
    assert decision.value_item == "H45"
    assert decision.value_display == "H45"


def test_activation_clear_stay_unprobed_without_rule_context():
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 2b
    follow-up: any EXISTING caller of classify_intent that doesn't pass
    hiding_rules/rec_rules/con_rules/bml_eval must keep working exactly
    as before -- ATTR_ACTIVATION/ATTR_CLEAR simply stay unprobed (never
    called at all), never crashing on missing rule context."""
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    battery = _attr("extendedBattery_astro", "Extended Battery")
    attrs = [battery]
    engine = MagicMock()
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None

    good_json = (
        '{"intent_category":"attr_activation","confidence":"high",'
        '"variable_name":"extendedBattery_astro","value_ref":null,'
        '"evidence_span":"add extended battery","rationale":"llm only"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(good_json, 10, 5),
    ):
        decision = classify_intent(
            "add extended battery", attrs, session, engine, workspace_id=1,
        )
    engine.detect_attr_activation.assert_not_called()
    assert decision.action == "clarify"
    assert decision.reason == "mutating_disagreement"


def test_activation_dispatches_when_real_probing_agrees():
    """With hiding_rules/rec_rules/con_rules/bml_eval supplied, the real
    detect_attr_activation probe runs and a genuine agreement now
    reaches "dispatch" -- the fix this session's cost/impact analysis
    led to."""
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    battery = _attr("extendedBattery_astro", "Extended Battery")
    attrs = [battery]
    engine = MagicMock()
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None
    engine.detect_attr_activation.return_value = battery

    good_json = (
        '{"intent_category":"attr_activation","confidence":"high",'
        '"variable_name":"extendedBattery_astro","value_ref":null,'
        '"evidence_span":"add extended battery","rationale":"agreed"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(good_json, 10, 5),
    ):
        decision = classify_intent(
            "add extended battery", attrs, session, engine, workspace_id=1,
            hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
        )
    engine.detect_attr_activation.assert_called_once()
    assert decision.action == "dispatch"
    assert decision.result is not None
    assert decision.result.variable_name == "extendedBattery_astro"


def test_clear_dispatches_when_real_probing_agrees():
    """Same fix, ATTR_CLEAR side."""
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    session.filled = {"deviceColor_astro": "Black"}
    color = _attr("deviceColor_astro", "Device Color", [("Black", "Black"), ("Silver", "Silver")])
    attrs = [color]
    engine = MagicMock()
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None
    engine.detect_attr_clear.return_value = color

    good_json = (
        '{"intent_category":"attr_clear","confidence":"high",'
        '"variable_name":"deviceColor_astro","value_ref":null,'
        '"evidence_span":"clear device color","rationale":"agreed"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(good_json, 10, 5),
    ):
        decision = classify_intent(
            "clear device color", attrs, session, engine, workspace_id=1,
            hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
        )
    engine.detect_attr_clear.assert_called_once()
    assert decision.action == "dispatch"
    assert decision.result is not None
    assert decision.result.variable_name == "deviceColor_astro"


def test_activation_never_dispatches_via_last_qa_variables_shortcut_alone():
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md review
    finding (HIGH): last_qa_variables is a value-corroboration shortcut for
    the CHANGE_REQUEST family -- it must never substitute for a real
    detect_attr_activation hit, since activation carries no value to
    corroborate against. The variable being recently discussed is not
    evidence the customer asked to activate it."""
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    session.last_qa_variables = ["extendedBatteryColor_astro"]
    color = _attr("extendedBatteryColor_astro", "Extended Battery Color")
    attrs = [color]
    engine = MagicMock()
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None
    engine.detect_attr_activation.return_value = None  # real detector disagrees

    ambiguous_json = (
        '{"intent_category":"attr_activation","confidence":"high",'
        '"variable_name":"extendedBatteryColor_astro","value_ref":null,'
        '"evidence_span":"what does that even mean","rationale":"guess"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(ambiguous_json, 10, 5),
    ):
        decision = classify_intent(
            "actually hold on, what does that even mean?", attrs, session, engine,
            workspace_id=1, hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
        )
    assert decision.action != "dispatch"


def test_clear_never_dispatches_via_last_qa_variables_shortcut_alone():
    """Same fix, ATTR_CLEAR side -- a recently-discussed color attribute
    must not get silently cleared just because it's in last_qa_variables;
    the real detect_attr_clear must actually agree."""
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    session.filled = {"deviceColor_astro": "Black"}
    session.last_qa_variables = ["deviceColor_astro"]
    color = _attr("deviceColor_astro", "Device Color", [("Black", "Black"), ("Silver", "Silver")])
    attrs = [color]
    engine = MagicMock()
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None
    engine.detect_attr_clear.return_value = None  # real detector disagrees

    ambiguous_json = (
        '{"intent_category":"attr_clear","confidence":"high",'
        '"variable_name":"deviceColor_astro","value_ref":null,'
        '"evidence_span":"what does that even mean","rationale":"guess"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(ambiguous_json, 10, 5),
    ):
        decision = classify_intent(
            "actually hold on, what does that even mean?", attrs, session, engine,
            workspace_id=1, hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None,
        )
    assert decision.action != "dispatch"


def test_mutating_categories_cover_change_family():
    assert IntentCategory.CHANGE_REQUEST in MUTATING_CATEGORIES
    assert IntentCategory.ATTR_CLEAR in MUTATING_CATEGORIES
    assert IntentCategory.QA_QUESTION not in MUTATING_CATEGORIES


# ── docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §8 ────────────────
# Live bug: "make it ATT/FirstNet" right after asking "what are the other
# options for Wireless Carrier" kept re-triggering the disambiguation
# clarify, even though the customer had just named the attribute by asking
# about it. Root cause: two sibling attrs (Wireless Carrier, Carrier
# Selection) both genuinely accept "ATT/FirstNet" as a valid option, so
# deterministic detectors can never disambiguate a bare-value reply — the
# only usable signal is conversational recency (session.last_qa_variable).

def test_classify_dispatch_when_last_qa_variable_corroborates():
    """Deterministic side finds nothing at all (bare-value reply names no
    attribute) but the LLM confidently names the attribute the customer
    was JUST asking about — last_qa_variable must corroborate and dispatch,
    not force a clarify."""
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    session.filled = {
        "wirelessCarrier_astro": "LTE_NO_SVC",
        "carrierSelectionMultiSelect_astro": "LTE_NO_SVC",
    }
    session.last_qa_variables = ["wirelessCarrier_astro"]
    wireless = _attr(
        "wirelessCarrier_astro", "Wireless Carrier",
        [("LTE_NO_SVC", "LTE CAPABILITY NO SERVICE"), ("ATT_FN", "ATT/FirstNet")],
    )
    carrier_sel = _attr(
        "carrierSelectionMultiSelect_astro", "Carrier Selection",
        [("LTE_NO_SVC", "LTE CAPABILITY NO SERVICE"), ("ATT_FN", "ATT/FirstNet")],
    )
    attrs = [wireless, carrier_sel]
    engine = MagicMock()
    # Bare-value reply — deterministic detectors find NOTHING (no attribute
    # name/label mentioned in "make it ATT/FirstNet").
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None

    good_json = (
        '{"intent_category":"change_request","confidence":"high",'
        '"variable_name":"wirelessCarrier_astro","value_ref":1,'
        '"evidence_span":"make it ATT/FirstNet",'
        '"rationale":"customer just asked about this attribute"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(good_json, 10, 5),
    ):
        decision = classify_intent(
            "make it ATT/FirstNet", attrs, session, engine, workspace_id=1,
        )
    assert decision.action == "dispatch"
    assert decision.result is not None
    assert decision.result.variable_name == "wirelessCarrier_astro"


def test_classify_still_clarifies_when_last_qa_variable_points_elsewhere():
    """last_qa_variable must only corroborate ITS OWN attribute — if the LLM
    names a DIFFERENT attribute than the one last discussed, and the
    deterministic side still finds nothing, the disagreement guard must
    still fire (no blanket bypass of the agreement check)."""
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    session.filled = {
        "wirelessCarrier_astro": "LTE_NO_SVC",
        "carrierSelectionMultiSelect_astro": "LTE_NO_SVC",
    }
    session.last_qa_variables = ["wirelessCarrier_astro"]
    wireless = _attr(
        "wirelessCarrier_astro", "Wireless Carrier",
        [("LTE_NO_SVC", "LTE CAPABILITY NO SERVICE"), ("ATT_FN", "ATT/FirstNet")],
    )
    carrier_sel = _attr(
        "carrierSelectionMultiSelect_astro", "Carrier Selection",
        [("LTE_NO_SVC", "LTE CAPABILITY NO SERVICE"), ("ATT_FN", "ATT/FirstNet")],
    )
    attrs = [wireless, carrier_sel]
    engine = MagicMock()
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None

    good_json = (
        '{"intent_category":"change_request","confidence":"high",'
        '"variable_name":"carrierSelectionMultiSelect_astro","value_ref":1,'
        '"evidence_span":"make it ATT/FirstNet","rationale":"llm only"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(good_json, 10, 5),
    ):
        decision = classify_intent(
            "make it ATT/FirstNet", attrs, session, engine, workspace_id=1,
        )
    assert decision.action == "clarify"
    assert decision.reason == "mutating_disagreement"


def test_build_candidates_boosts_last_qa_variable():
    session = CpqSession()
    session.last_qa_variables = ["wirelessCarrier_astro"]
    attrs = [
        _attr("noise_a", "Noise A"),
        _attr("wirelessCarrier_astro", "Wireless Carrier", [("ATT_FN", "ATT/FirstNet")]),
    ]
    bundles = build_candidate_bundles(attrs, session, "make it ATT/FirstNet")
    assert bundles[0].attr.variable_name == "wirelessCarrier_astro"


def test_classify_intent_still_calls_the_llm_with_empty_attrs():
    """Regression for a real production bug found while scoping Phase 4
    (docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md §8): classify_intent used
    to bail to action="fallback" whenever `attrs` was empty, WITHOUT ever
    calling the LLM. PRODUCT_QUANTITY_CHANGE/COUNTRY_CHANGE confirmations
    call this with attrs=[] (the catalog isn't loaded yet at that point in
    the turn) -- the old bail-out silently made both checkpoints always
    reject, a no-op in production that every existing test missed because
    they mock classify_intent/gateway_classify_intent directly instead of
    exercising this function for real."""
    clear_gateway_cache()
    session = CpqSession()
    session.product_name = "astro"
    engine = MagicMock()
    engine.detect_change_request.return_value = None
    engine.detect_change_requests_multi.return_value = []
    engine.detect_change_target_without_value.return_value = None
    engine.detect_multi_select_removal.return_value = None
    engine.detect_bulk_quantity_change.return_value = None

    good_json = (
        '{"intent_category":"country_change","confidence":"high",'
        '"variable_name":null,"value_ref":null,"quantity_text":null,'
        '"evidence_span":"change country to Canada","rationale":"llm only"}'
    )
    with patch(
        "aryx.cpq.intent_gateway._pinned_chat",
        return_value=(good_json, 10, 5),
    ) as mock_chat:
        decision = classify_intent(
            "change country to Canada", [], session, engine, workspace_id=1,
        )
    mock_chat.assert_called_once()
    assert decision.action == "dispatch"
    assert decision.result is not None
    assert decision.result.intent_category == IntentCategory.COUNTRY_CHANGE


def test_classify_intent_empty_question_still_bails_without_calling_the_llm():
    clear_gateway_cache()
    session = CpqSession()
    engine = MagicMock()
    with patch("aryx.cpq.intent_gateway._pinned_chat") as mock_chat:
        decision = classify_intent("   ", [], session, engine, workspace_id=1)
    mock_chat.assert_not_called()
    assert decision.action == "fallback"
    assert decision.reason == "empty_question"
