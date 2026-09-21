"""search_by_feature() composes find_entities(attrs=...) with CpqEngine's
hiding-rule evaluation, verified session-free 2026-09-15 (see
Feature_Region_Search_Spec.docx Section 5). A candidate matching on static
attribute value alone can still be one a hiding rule would suppress for
its product -- this closes that gap by annotating each result.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aryx.graph.feature_search import search_by_feature


def _config_attr(variable_name: str, catalog_prefix: str = "astro25"):
    attr = MagicMock()
    attr.variable_name = variable_name
    attr.display_label = variable_name
    attr.catalog_prefix = catalog_prefix
    return attr


def test_candidate_not_part_of_any_product_gets_none_not_false() -> None:
    """A bare graph entity (not a CPQ-configurable product) can't be
    checked against product-level rules at all -- must be distinguishable
    from a real, checked 'not hidden' result."""
    reader = MagicMock()
    reader.find_entities.return_value = [{"id": 1, "type": "Thing", "name": "Widget"}]
    engine = MagicMock()
    engine.load_product_config.side_effect = Exception("not a configurable product")

    results = search_by_feature(reader, engine, workspace_id=1, name="Widget")

    assert results[0]["hidden_by_rule"] is None
    assert results[0]["hiding_rule_names"] == []


def test_candidate_with_no_hiding_rules_marked_visible() -> None:
    reader = MagicMock()
    reader.find_entities.return_value = [{"id": 1, "type": "Product", "name": "SL3500e"}]
    engine = MagicMock()
    engine.load_product_config.return_value = ([_config_attr("hWVersion_astro")], "SL3500e")
    engine.load_hiding_rules.return_value = []

    results = search_by_feature(reader, engine, workspace_id=1, name="SL3500e")

    assert results[0]["hidden_by_rule"] is False
    engine.build_bml_evaluator.assert_not_called()


def test_candidate_hidden_by_a_fired_rule() -> None:
    reader = MagicMock()
    reader.find_entities.return_value = [{"id": 1, "type": "Product", "name": "hWVersion_astro"}]
    engine = MagicMock()
    engine.load_product_config.return_value = ([_config_attr("hWVersion_astro")], "hWVersion_astro")
    engine.load_hiding_rules.return_value = [MagicMock()]
    engine.apply_hiding_rules.return_value = (
        [], ["Rule 'Hide HW Version unless region=NA' hid **hWVersion_astro**"], {"hWVersion_astro"},
    )

    results = search_by_feature(
        reader, engine, workspace_id=1, name="hWVersion_astro",
        filled={"region": "EMEA"},
    )

    assert results[0]["hidden_by_rule"] is True
    assert "hWVersion_astro" in results[0]["hiding_rule_names"][0]
    # bml_eval must be built and threaded through -- most real hiding rules
    # are script-backed (62% in a real catalog), so skipping this would
    # silently under-report hidden results.
    engine.build_bml_evaluator.assert_called_once_with(1, "astro25")
    engine.apply_hiding_rules.assert_called_once()
    _, kwargs = engine.apply_hiding_rules.call_args
    assert kwargs["bml_eval"] is engine.build_bml_evaluator.return_value


def test_empty_filled_defaults_to_not_hidden_not_an_error() -> None:
    reader = MagicMock()
    reader.find_entities.return_value = [{"id": 1, "type": "Product", "name": "SL3500e"}]
    engine = MagicMock()
    engine.load_product_config.return_value = ([_config_attr("hWVersion_astro")], "SL3500e")
    engine.load_hiding_rules.return_value = [MagicMock()]
    engine.apply_hiding_rules.return_value = ([_config_attr("hWVersion_astro")], [], set())

    results = search_by_feature(reader, engine, workspace_id=1, name="SL3500e")

    assert results[0]["hidden_by_rule"] is False
    called_filled = engine.apply_hiding_rules.call_args[0][1]
    assert called_filled == {}
