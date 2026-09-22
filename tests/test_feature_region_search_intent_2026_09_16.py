"""Tests for detect_feature_region_search() (aryx.cpq.intent_gateway) --
the deterministic trigger that routes a feature/region product-search
question into search_products_combined() from the Ask conversational
flow. Same style as the existing hard_off_topic/soft_quote_heuristic
tests in tests/test_cpq_negative_harden.py.
"""
from __future__ import annotations

from aryx.cpq.intent_gateway import detect_feature_region_search


class TestRegionSearch:
    def test_region_after_keyword(self):
        region, label, value = detect_feature_region_search(
            "Which models are available in region NA?",
        )
        assert region == "NA"
        assert label is None
        assert value is None

    def test_region_before_keyword(self):
        region, _, _ = detect_feature_region_search(
            "What products can I sell in EMEA region?",
        )
        assert region == "EMEA"

    def test_case_insensitive(self):
        region, _, _ = detect_feature_region_search(
            "which PRODUCTS work in region apac",
        )
        assert region == "apac"


class TestFeatureSearch:
    def test_feature_colon_form(self):
        region, label, value = detect_feature_region_search(
            "Which products have feature: Encryption?",
        )
        assert region is None
        assert label == "Feature Type"
        assert value == "Encryption"

    def test_feature_type_phrase(self):
        _, label, value = detect_feature_region_search(
            "What models support feature type GPS Tracking?",
        )
        assert label == "Feature Type"
        assert value == "GPS Tracking"

    def test_support_x_feature_phrasing(self):
        _, label, value = detect_feature_region_search(
            "Which products support Encryption feature?",
        )
        assert label == "Feature Type"
        assert value == "Encryption"

    def test_has_x_feature_phrasing(self):
        _, label, value = detect_feature_region_search(
            "What models have GPS Tracking feature?",
        )
        assert value == "GPS Tracking"


class TestBothRegionAndFeature:
    def test_both_extracted_together(self):
        region, label, value = detect_feature_region_search(
            "Which products support Encryption feature in region NA?",
        )
        assert region == "NA"
        assert label == "Feature Type"
        assert value == "Encryption"


class TestNegativeCases:
    def test_cpq_configuration_command_not_triggered(self):
        """'Set region to NA' is a live CPQ configuration action, not a
        search question -- must never be hijacked into this route (no
        search verb + product/model noun present)."""
        assert detect_feature_region_search("set region to NA") == (None, None, None)

    def test_order_command_not_triggered(self):
        assert detect_feature_region_search(
            "I want to order APX Next radios for region NA",
        ) == (None, None, None)

    def test_generic_question_without_region_or_feature_not_triggered(self):
        assert detect_feature_region_search(
            "Which products do you sell?",
        ) == (None, None, None)

    def test_unrelated_question_not_triggered(self):
        assert detect_feature_region_search(
            "What's the weather like today?",
        ) == (None, None, None)

    def test_empty_and_none_question(self):
        assert detect_feature_region_search("") == (None, None, None)
        assert detect_feature_region_search(None) == (None, None, None)

    def test_region_keyword_without_search_verb_not_triggered(self):
        """'region NA' alone, with no which/what/list/show/find + product/
        model/catalog noun, must not trigger -- avoids over-triggering on
        every mention of the word 'region' during a live CPQ turn."""
        assert detect_feature_region_search(
            "I need this configured for region NA",
        ) == (None, None, None)
