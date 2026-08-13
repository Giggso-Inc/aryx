"""Regression coverage for docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md
-- all 5 transcript-sourced bugs plus the turn-1 unified extraction plan
(quantity/country fused into classify_ask_route's single LLM call).
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import (
    AskRequest,
    _build_show_summary_response,
    _cpq_summary_text,
    _dispatch_intent_result,
    _run_cpq_turn_inner,
)
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.engine import CpqEngine, extract_quantity_hint
from aryx.cpq.intent_gateway import AskRouteDecision, _parse_route
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption

_engine = CpqEngine()


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None, required=False, select_type="single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=required,
        default_value="", options=options or [], select_type=select_type,
    )


# ═══════════════════════════════════════════════════════════════════════
# Issue 1 — "a dozen" quantity
# ═══════════════════════════════════════════════════════════════════════

def test_extract_quantity_hint_a_dozen():
    assert extract_quantity_hint("a dozen radios") == 12


def test_extract_quantity_hint_two_dozen():
    assert extract_quantity_hint("two dozen radios") == 24


def test_extract_quantity_hint_pricing_for_a_dozen_models():
    assert extract_quantity_hint(
        "I need pricing for a dozen APX NEXT standard models") == 12


def test_extract_quantity_hint_pricing_for_plain_digit_models():
    assert extract_quantity_hint(
        "I need pricing for 12 APX NEXT standard models") == 12


def test_extract_quantity_hint_dozens_plural_never_matches():
    assert extract_quantity_hint("dozens of options available") is None


def test_extract_quantity_hint_dozen_without_a_quantity_context_word_returns_none():
    # "minutes" isn't a quantity-context noun the patterns recognize, so
    # this never matches at all -- safer than a naive substitution would
    # suggest, not a false positive.
    assert extract_quantity_hint("call me back in a dozen minutes") is None


# ═══════════════════════════════════════════════════════════════════════
# Issue 2 — quantity change should show the full summary once complete
# ═══════════════════════════════════════════════════════════════════════

def test_quantity_change_shows_full_summary_when_config_already_complete(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    attrs = [battery]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_layout_display_order", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "rule_governed_ids", lambda *a, **k: {1, 2})
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"batteryType_astro": "STANDARD"},
        display_filled={"batteryType_astro": "Standard"},
        filled_source={"batteryType_astro": "user"},
        status="awaiting_approval", turn=4, pending_variables=[],
        product_quantity=1,
    )
    req = AskRequest(question="let's change the quantity to 15", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert "**Quantity** → 15" in resp["answer"]
    assert "Configuration complete" in resp["answer"]
    assert resp["tools_called"] == ["cpq_product_quantity()"]


def test_build_show_summary_response_derives_catalog_prefix_from_attrs_not_load_product_config(
    monkeypatch,
):
    """Live-verified bug, 2026-08-13: load_product_config's second return
    value is the RESOLVED PRODUCT NAME (its own docstring says so), never
    a catalog_prefix. Using it as catalog_prefix silently loaded the
    WRONG (or empty) hiding/recommendation/constraint rule set every
    time, zeroing out rule_governed_ids and emptying the summary --
    always falling back to the bare "Quantity → N" line even once the
    config was complete. This test fails if that mistake is reintroduced,
    unlike the other tests above whose mocks ignore the catalog_prefix
    argument entirely and so can't catch this."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    attrs = [battery]
    attrs[0].catalog_prefix = "real_catalog_prefix"
    # Second element is deliberately NOT a catalog_prefix -- exactly the
    # real shape (a human-facing resolved product name) that caused the
    # live bug.
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "APX NEXT Single Band"))
    seen_prefixes = []

    def _capture_hiding_rules(workspace_id, catalog_prefix):
        seen_prefixes.append(catalog_prefix)
        return []

    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", _capture_hiding_rules)
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    session = CpqSession(
        mode="cpq", product_name="APX NEXT Single Band",
        filled={"batteryType_astro": "STANDARD"},
        display_filled={"batteryType_astro": "Standard"},
        filled_source={"batteryType_astro": "user"},
    )
    req = AskRequest(question="recap", workspace_id=1, session_data=session.to_dict())
    _build_show_summary_response(req, session, object())
    assert seen_prefixes == ["real_catalog_prefix"]


def test_quantity_change_mid_configuration_still_shows_only_the_short_line(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([battery], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        pending_variables=["batteryType_astro"], status="configuring", turn=2,
        product_quantity=1,
    )
    req = AskRequest(question="change the quantity to 15", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["answer"] == "**Quantity** → 15"
    assert "Configuration complete" not in resp["answer"]


def test_quantity_change_invalid_value_still_rejects_without_a_summary(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([battery], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"batteryType_astro": "STANDARD"},
        display_filled={"batteryType_astro": "Standard"},
        status="awaiting_approval", turn=4, pending_variables=[], product_quantity=1,
    )
    req = AskRequest(question="change the quantity to -5", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_product_quantity_rejected()"]
    assert "isn't a valid quantity" in resp["answer"]


def test_quantity_change_summary_build_failure_falls_back_to_plain_line(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([battery], "aSTRO25_bom"))
    monkeypatch.setattr(api, "_build_show_summary_response", lambda *a, **k: None)
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"batteryType_astro": "STANDARD"},
        display_filled={"batteryType_astro": "Standard"},
        status="awaiting_approval", turn=4, pending_variables=[], product_quantity=1,
    )
    req = AskRequest(question="change the quantity to 15", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["answer"] == "**Quantity** → 15"


# ═══════════════════════════════════════════════════════════════════════
# Issue 6 (live feedback, 2026-08-13) — Product Quantity missing from the
# actual JSON payload, not just the text summary
# ═══════════════════════════════════════════════════════════════════════

def test_build_payload_omits_quantity_key_when_not_supplied():
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    payload = _engine.build_payload({"batteryType_astro": "STANDARD"}, attrs=[battery])
    assert "quantity" not in payload
    assert "configData" in payload


def test_build_payload_includes_quantity_as_a_sibling_of_configdata():
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    payload = _engine.build_payload(
        {"batteryType_astro": "STANDARD"}, attrs=[battery], product_quantity=15,
    )
    assert payload["quantity"] == 15
    assert "quantity" not in payload["configData"]


def test_final_approval_payload_includes_the_product_quantity(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([battery], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"batteryType_astro": "STANDARD"},
        display_filled={"batteryType_astro": "Standard"},
        status="awaiting_approval", turn=4, product_quantity=10,
    )
    req = AskRequest(question="confirm", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["cpq_payload"] is not None
    assert resp["cpq_payload"]["quantity"] == 10


# ═══════════════════════════════════════════════════════════════════════
# Issue 3 — quantity positioned under Product Name, not appended last
# ═══════════════════════════════════════════════════════════════════════

def test_categorized_summary_groups_injects_product_quantity_under_product_name():
    attrs = [_attr(1, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))]
    display_filled = {"productSelectionProduct_all": "APX NEXT"}
    groups = _engine.categorized_summary_groups(display_filled, attrs, product_quantity=15)
    assert groups[0][0] == "Product Name"
    assert groups[0][1][0] == ("Product Quantity", "15")


def test_categorized_summary_groups_no_product_selected_yet_shows_no_quantity():
    groups = _engine.categorized_summary_groups({}, [], product_quantity=1)
    assert groups == []


def test_render_filled_summary_shows_quantity_under_product_name():
    attrs = [_attr(1, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))]
    display_filled = {"productSelectionProduct_all": "APX NEXT"}
    text = _engine.render_filled_summary(display_filled, attrs, product_quantity=15)
    assert text.index("Product Quantity") < text.index("APX NEXT")


def test_product_quantity_none_omits_the_fact_entirely():
    attrs = [_attr(1, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))]
    display_filled = {"productSelectionProduct_all": "APX NEXT"}
    text = _engine.render_filled_summary(display_filled, attrs, product_quantity=None)
    assert "Product Quantity" not in text


def test_raw_state_table_fallback_still_shows_quantity_via_trailing_append(monkeypatch):
    # Force both the LLM narration and the deterministic bullet fallback
    # to miss a curated fact, so we reach the last-resort raw_state_table
    # tier -- the one path intentionally left on the old append mechanism.
    attrs = [_attr(1, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))]
    display_filled = {"productSelectionProduct_all": "APX NEXT"}

    def _valid_shape_chat(*a, **k):
        # Correctly segmented (1 lead-in + 1 category) so the narration
        # parses successfully and reaches the summary_guard check, rather
        # than falling through earlier on a segment-count mismatch.
        return "Your configuration is ready.@@@- **Product** → APX NEXT", 0, 0

    monkeypatch.setattr(api.llm_runtime, "chat", _valid_shape_chat)
    with patch(
        "aryx.cpq.summary_guard.fields_missing_from_summary",
        return_value=["Product Quantity"],
    ):
        text = _cpq_summary_text(
            display_filled, attrs, {1}, "APX NEXT", 1, product_quantity=15,
        )
    assert "**Quantity:** 15" in text


# ═══════════════════════════════════════════════════════════════════════
# Issue 4 — "give the final summary now" / "give the configuration"
# ═══════════════════════════════════════════════════════════════════════

def test_detect_show_summary_request_matches_common_phrasings():
    for q in (
        "give the final summary now", "give the configuration",
        "show me the configuration", "recap",
        "review my order", "what do I have so far",
        "what's my configuration",
    ):
        assert _engine.detect_show_summary_request(q) is True, q


def test_detect_show_summary_request_does_not_over_trigger_on_attr_query_phrasing():
    assert _engine.detect_show_summary_request(
        "what are the options for Configuration Type") is False


def test_show_summary_reshows_the_current_configuration_when_complete(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([battery], "aSTRO25_bom"))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_layout_display_order", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "rule_governed_ids", lambda *a, **k: {1, 2})
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"batteryType_astro": "STANDARD"},
        display_filled={"batteryType_astro": "Standard"},
        filled_source={"batteryType_astro": "user"},
        status="awaiting_approval", turn=5, pending_variables=[],
    )
    req = AskRequest(question="give the final summary now", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_show_summary()"]
    assert "Configuration complete" in resp["answer"]
    assert "outside what I track here" not in resp["answer"]


def test_show_summary_never_hijacked_into_an_unrelated_attr_prompt(monkeypatch):
    """Reproduces the suspected 'Configuration Type' collision directly."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    config_type = _attr(2, "configType_astro", "Configuration Type",
                         options=_opt("Software Bundles", "Custom Configuration"))
    attrs = [battery, config_type]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_layout_display_order", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "rule_governed_ids", lambda *a, **k: {1, 2})
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"batteryType_astro": "STANDARD", "configType_astro": "Software Bundles"},
        display_filled={"batteryType_astro": "Standard", "configType_astro": "Software Bundles"},
        filled_source={"batteryType_astro": "user", "configType_astro": "user"},
        status="awaiting_approval", turn=6, pending_variables=[],
    )
    req = AskRequest(question="give the configuration", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert "Configuration Type" not in resp["answer"] or resp["tools_called"] == ["cpq_show_summary()"]
    assert resp["tools_called"] == ["cpq_show_summary()"]


def test_show_summary_never_fires_with_no_product_selected():
    session = CpqSession(mode="cpq")
    req = AskRequest(question="give the final summary now", workspace_id=1,
                      session_data=session.to_dict())
    resp = _build_show_summary_response(req, session, object())
    assert resp is None


def test_show_summary_never_steals_a_pending_anchor_reply(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    built = {"called": False}

    def _fake_build(*a, **k):
        built["called"] = True
        return None

    monkeypatch.setattr(api, "_build_show_summary_response", _fake_build)
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", pending_anchor="country")
    req = AskRequest(question="give the configuration", workspace_id=1,
                      session_data=session.to_dict())
    try:
        _run_cpq_turn_inner(req, object())
    except Exception:
        # Only the show-summary guard is under test here -- the rest of
        # the turn may fail on an unmocked reader call downstream, which
        # is irrelevant to what this test asserts.
        pass
    assert built["called"] is False


def test_show_summary_never_intercepts_a_literal_matching_option_answer(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    config_type = _attr(2, "configType_astro", "Configuration Type",
                         options=_opt("Software Bundles", "Custom Configuration"))
    attrs = [config_type]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        display_filled={}, pending_variables=["configType_astro"],
    )
    req = AskRequest(question="Custom Configuration", workspace_id=1,
                      session_data=session.to_dict())
    resp = _build_show_summary_response(req, session, object())
    assert resp is None


def test_show_summary_catalog_load_failure_falls_through_safely(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("graph unavailable")

    monkeypatch.setattr(api._cpq_engine, "load_product_config", _boom)
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", display_filled={"x": "y"})
    req = AskRequest(question="recap", workspace_id=1, session_data=session.to_dict())
    resp = _build_show_summary_response(req, session, object())
    assert resp is None


# ═══════════════════════════════════════════════════════════════════════
# Issue 5 — country regex + Turn-1 unified extraction (classify_ask_route)
# ═══════════════════════════════════════════════════════════════════════

def test_extract_hints_country_still_fails_on_article_between_preposition_and_name():
    hints = api._cpq_engine.extract_hints(
        "I need pricing for a dozen APX NEXT standard models in the United States")
    assert "country" not in hints


def test_extract_hints_country_succeeds_without_the_article():
    hints = api._cpq_engine.extract_hints(
        "I need pricing for a dozen APX NEXT standard models in United States")
    assert hints.get("country") == "United States"


def test_route_schema_has_quantity_and_country_fields():
    from aryx.cpq.intent_gateway import GATEWAY_INTENT_JSON_SCHEMA  # noqa: F401 sanity import
    from aryx.cpq.intent_gateway import _ROUTE_SCHEMA
    assert "quantity" in _ROUTE_SCHEMA["properties"]
    assert "country" in _ROUTE_SCHEMA["properties"]


def test_parse_route_extracts_quantity_and_country():
    decision = _parse_route({
        "route": "quote", "confidence": "high", "clarifying_question": None,
        "rationale": "ok", "quantity": 12, "country": "United States",
    })
    assert decision.quantity == 12
    assert decision.country == "United States"


def test_parse_route_rejects_non_integer_quantity():
    decision = _parse_route({
        "route": "quote", "confidence": "high", "clarifying_question": None,
        "rationale": "ok", "quantity": "twelve", "country": None,
    })
    assert decision.quantity is None


def test_route_meta_quantity_and_country_seed_the_turn_before_step_1(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "list_ingested_families", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "resolve_product_hint", lambda *a, **k: None)
    session = CpqSession(mode="cpq")
    req = AskRequest(
        question="I need pricing for a dozen APX NEXT standard models in the United States",
        workspace_id=1, session_data=session.to_dict(),
    )
    route_meta = AskRouteDecision(
        route="quote", confidence="high", clarifying_question=None,
        rationale="ok", quantity=12, country="United States",
    )
    resp = _run_cpq_turn_inner(req, object(), route_meta)
    assert resp["session_data"]["country"] == "United States"
    assert resp["session_data"]["product_quantity"] == 12


def test_regex_extracted_values_are_not_overwritten_by_the_router(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "list_ingested_families", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "resolve_product_hint", lambda *a, **k: None)
    session = CpqSession(mode="cpq")
    req = AskRequest(
        question="I need 50 radios in Canada",
        workspace_id=1, session_data=session.to_dict(),
    )
    route_meta = AskRouteDecision(
        route="quote", confidence="high", clarifying_question=None,
        rationale="ok", quantity=999, country="Germany",
    )
    resp = _run_cpq_turn_inner(req, object(), route_meta)
    assert resp["session_data"]["country"] == "Canada"
    assert resp["session_data"]["product_quantity"] == 50


def test_route_meta_rejects_a_hallucinated_country(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "list_ingested_families", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "resolve_product_hint", lambda *a, **k: None)
    session = CpqSession(mode="cpq")
    req = AskRequest(
        question="I need pricing for a dozen APX NEXT standard models",
        workspace_id=1, session_data=session.to_dict(),
    )
    route_meta = AskRouteDecision(
        route="quote", confidence="high", clarifying_question=None,
        rationale="ok", quantity=12, country="Wakanda",
    )
    resp = _run_cpq_turn_inner(req, object(), route_meta)
    assert resp["session_data"]["country"] in (None, "")
    assert resp["session_data"]["product_quantity"] == 12


def test_route_meta_rejects_an_invalid_quantity(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "list_ingested_families", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "resolve_product_hint", lambda *a, **k: None)
    session = CpqSession(mode="cpq")
    req = AskRequest(
        question="I need pricing for something in the United States",
        workspace_id=1, session_data=session.to_dict(),
    )
    route_meta = AskRouteDecision(
        route="quote", confidence="high", clarifying_question=None,
        rationale="ok", quantity=-5, country="United States",
    )
    resp = _run_cpq_turn_inner(req, object(), route_meta)
    assert resp["session_data"]["product_quantity"] == 1  # default, untouched
    assert resp["session_data"]["country"] == "United States"


def test_turn_2_never_has_a_route_meta_and_still_works(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "list_ingested_families", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "resolve_product_hint", lambda *a, **k: None)
    session = CpqSession(mode="cpq", country="United States", turn=2)
    req = AskRequest(question="anything else", workspace_id=1,
                      session_data=session.to_dict())
    # route_meta defaults to None -- must not crash, must not require it.
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["country"] == "United States"


def test_llm_first_router_failure_surfaces_a_customer_facing_error():
    req = AskRequest(question="order APX Next", workspace_id=1, session_data={})
    meta = AskRouteDecision(
        route="quote", confidence="low", clarifying_question=None,
        rationale="timeout", timed_out=True, error="timeout", model_id="m",
        det_is_cpq=True,
    )
    with patch("aryx.api.ask_api._reader", return_value=object()), \
         patch("aryx.api.ask_api.get_settings") as gs, \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api._deterministic_cpq_gate", return_value=True), \
         patch("aryx.api.ask_api._run_cpq_turn") as mock_cpq:
        gs.return_value.cpq_intent_mode = "llm_first"
        gs.return_value.cpq_intent_timeout_s = 10.0
        out = api.run_ask(req)
    mock_cpq.assert_not_called()
    assert "went wrong" in out["answer"].lower()
    assert out["tools_called"] == ["cpq_router_error()"]


def test_shadow_mode_strips_quantity_and_country_before_the_turn(monkeypatch):
    """Shadow mode is observe-only -- quantity/country must never leak
    into actual turn behavior in this mode, only routing/logging."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "list_ingested_families", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "resolve_product_hint", lambda *a, **k: None)
    session = CpqSession(mode="cpq")
    req = AskRequest(
        question="I need pricing for a couple dozen APX NEXT standard models in the United States",
        workspace_id=1, session_data=session.to_dict(),
    )
    meta = AskRouteDecision(
        route="quote", confidence="high", clarifying_question=None,
        rationale="ok", det_is_cpq=True, quantity=24, country="United States",
    )
    with patch("aryx.api.ask_api._reader", return_value=object()), \
         patch("aryx.api.ask_api.get_settings") as gs, \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api._deterministic_cpq_gate", return_value=True), \
         patch("aryx.api.ask_api._attach_share_flags", side_effect=lambda r, *a, **k: r):
        gs.return_value.cpq_intent_mode = "shadow"
        gs.return_value.cpq_intent_timeout_s = 10.0
        out = api.run_ask(req)
    # Neither quantity nor country from the (observe-only) router made it
    # into the actual session -- regex alone decides in shadow mode, and
    # regex itself misses this exact phrasing (the reproduced bug).
    assert out["session_data"].get("country") in (None, "")
    assert out["session_data"].get("product_quantity", 1) == 1
