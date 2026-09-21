"""run_ask() routing to the feature/region search path (2026-09-16) --
detect_feature_region_search fires before any CPQ/gateway work, short-
circuiting to _route_feature_region_search -> search_products_combined().
Same mocking style as tests/test_cpq_negative_harden.py's run_ask tests.

Patch targets are the module each name is ACTUALLY bound in, per this
branch's Phase 9/11-phase ask_api decomposition -- not all read through
ask_api itself. `_reader` is called via ask_core_helpers's module object;
`_deterministic_cpq_gate` via ask_finish_cpq_result's; `_route_quote` and
`search_products_combined` are bound by direct `from...import` inside
ask_run_ask.py/ask_feature_region_search.py respectively, so those two
must be patched where the name actually lives, not on ask_api.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import AskRequest, run_ask


def _base_req(question: str) -> AskRequest:
    return AskRequest(question=question, workspace_id=1, history=[], session_data={})


class TestRunAskRoutesToFeatureRegionSearch:
    def test_region_question_routes_before_any_cpq_work(self):
        """A real region-search question must short-circuit run_ask before
        _deterministic_cpq_gate/classify_ask_route ever run -- proven by
        NOT mocking them and asserting they're never called."""
        req = _base_req("Which products are available in region NA?")

        with patch("aryx.api.ask_core_helpers._reader", return_value=object()), \
             patch("aryx.api.ask_feature_region_search.search_products_combined") as mock_combined, \
             patch("aryx.api.ask_response_building.ask_finish_cpq_result._deterministic_cpq_gate") as mock_gate, \
             patch("aryx.api.ask_api.classify_ask_route") as mock_classify:
            mock_combined.return_value = [
                {"model": "APXNEXTSINGLE", "source": ["data_table"],
                 "data_table_matches": [{"region": "NA"}], "graph_entity": None},
            ]
            result = run_ask(req)

        mock_gate.assert_not_called()
        mock_classify.assert_not_called()
        assert "APXNEXTSINGLE" in result["answer"]
        assert result["tools_called"] == ["search_products_combined()"]
        assert result["cpq_payload"]["feature_region_search_results"] == mock_combined.return_value
        _, kwargs = mock_combined.call_args
        assert kwargs["region"] == "NA"
        assert kwargs["feature_label"] is None

    def test_feature_question_routes_correctly(self):
        req = _base_req("Which products support Encryption feature?")

        with patch("aryx.api.ask_core_helpers._reader", return_value=object()), \
             patch("aryx.api.ask_feature_region_search.search_products_combined") as mock_combined:
            mock_combined.return_value = []
            result = run_ask(req)

        _, kwargs = mock_combined.call_args
        assert kwargs["feature_label"] == "Feature Type"
        assert kwargs["feature_value"] == "Encryption"
        assert "couldn't find" in result["answer"]

    def test_multiple_matches_lists_all_model_names(self):
        req = _base_req("Which models are available in region NA?")

        with patch("aryx.api.ask_core_helpers._reader", return_value=object()), \
             patch("aryx.api.ask_feature_region_search.search_products_combined") as mock_combined:
            mock_combined.return_value = [
                {"model": "APXNEXTSINGLE", "source": ["data_table"], "data_table_matches": [], "graph_entity": None},
                {"model": "APXNEXTDUAL", "source": ["data_table"], "data_table_matches": [], "graph_entity": None},
            ]
            result = run_ask(req)

        assert "APXNEXTSINGLE" in result["answer"]
        assert "APXNEXTDUAL" in result["answer"]
        assert "2 products" in result["answer"]

    def test_search_error_falls_back_to_a_clean_no_results_answer(self):
        """A search_products_combined failure (e.g. a real Postgres/graph
        outage) must never surface a raw exception to the user -- degrade
        to the same "nothing found" answer as a genuine zero-match query."""
        req = _base_req("Which products are available in region NA?")

        with patch("aryx.api.ask_core_helpers._reader", return_value=object()), \
             patch("aryx.api.ask_feature_region_search.search_products_combined", side_effect=RuntimeError("db down")):
            result = run_ask(req)

        assert "couldn't find" in result["answer"]
        assert result["cpq_payload"]["feature_region_search_results"] == []

    def test_a_live_cpq_session_is_never_hijacked(self):
        """A live session (product_name already set) must always go
        through _route_quote, even if the current turn's text happens to
        contain 'region' -- feature/region search only ever applies to a
        cold-start turn."""
        req = AskRequest(
            question="which region do you want for APX NEXT?",
            workspace_id=1, history=[],
            session_data={"mode": "cpq", "product_name": "APX NEXT"},
        )

        with patch("aryx.api.ask_core_helpers._reader", return_value=object()), \
             patch("aryx.api.ask_run_ask._route_quote") as mock_quote, \
             patch("aryx.api.ask_feature_region_search.search_products_combined") as mock_combined:
            mock_quote.return_value = {"answer": "quote", "tools_called": [], "usage": {}}
            run_ask(req)

        mock_quote.assert_called_once()
        mock_combined.assert_not_called()

    def test_a_plain_cpq_order_question_is_not_hijacked(self):
        """A cold-start CPQ order question must still reach the normal
        CPQ/gateway router -- detect_feature_region_search's own negative
        test coverage already proves this at the regex level; this proves
        it end-to-end through run_ask."""
        from aryx.cpq.intent_gateway import AskRouteDecision

        req = _base_req("I want to order APX Next radios, 50 qty, region NA")
        meta = AskRouteDecision(
            route="quote", confidence="high", clarifying_question=None,
            rationale="order", model_id="m", det_is_cpq=True, agreement=True,
        )

        with patch("aryx.api.ask_core_helpers._reader", return_value=object()), \
             patch("aryx.api.ask_api.get_settings") as gs, \
             patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
             patch("aryx.api.ask_response_building.ask_finish_cpq_result._deterministic_cpq_gate", return_value=True), \
             patch("aryx.api.ask_run_ask._route_quote") as mock_quote, \
             patch("aryx.api.ask_feature_region_search.search_products_combined") as mock_combined, \
             patch("aryx.api.ask_api.mark_top_level_route_used"):
            gs.return_value.cpq_intent_mode = "shadow"
            gs.return_value.cpq_intent_timeout_s = 10.0
            mock_quote.return_value = {"answer": "quote", "tools_called": [], "usage": {}}
            run_ask(req)

        mock_combined.assert_not_called()
        mock_quote.assert_called_once()
