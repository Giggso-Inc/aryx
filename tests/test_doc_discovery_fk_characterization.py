"""Characterization tests for _detect_fk_links (doc_discovery_fk.py), written
2026-09-23 BEFORE an O(N^2) -> O(N) rewrite of its Pass 1/Pass 2 plan-pair
loops (see docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md,
Phase 1, step 1).

No test coverage of this function's actual matching logic existed before
this file — every other test file only whitebox-patches the whole function
as a mock for its callers. These tests lock in current behavior against
real plan/CSV fixtures so the rewrite can be verified behavior-preserving,
not just "doesn't crash."

Covers: Pass 1 (_id suffix, multi-word stem, exact type-name match), Pass 2
(rule A shared match key), Pass 3 (XML element-type FK), and the O(N)
scaling case (many plans, must still find the expected links and run fast).
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.pipeline.doc_discovery.doc_discovery_fk import _detect_fk_links


def _csv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    lines = [",".join(header)] + [",".join(r) for r in rows]
    return ("\n".join(lines)).encode("utf-8")


def _plan(otype: str, header: list[str], rows: list[list[str]],
          match_keys: list[str] | None = None) -> dict:
    return {
        "ontology_type": otype,
        "data": _csv_bytes(header, rows),
        "match_keys": match_keys or [],
    }


def _default_settings():
    """Real default values (config_fk_detection.py), used so these tests
    don't depend on env vars or a real Settings() build."""
    s = type("S", (), {})()
    s.fk_key_suffixes = "_code,_id,_key,_num,_ref,_no,_cage"
    s.id_like_column_names = "id,uuid,guid,key"
    s.name_like_column_names = "name,full_name,title"
    return s


class TestPass1IdSuffixMatch:
    def test_simple_id_suffix_matches_target_id_column(self):
        plan_a = _plan("Order", ["customer_id", "total"],
                        [["1", "100"], ["2", "200"]])
        plan_b = _plan("Customer", ["id", "name"],
                        [["1", "Alice"], ["2", "Bob"]])
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        assert links == [{
            "source_type": "Order", "source_attr": "customer_id",
            "target_type": "Customer", "target_attr": "id",
            "name": "CUSTOMER_HAS_ORDER",
        }]

    def test_multiword_camelcase_stem_suffix_matches(self):
        # "BmConfigAttrSet" -> de-camelCased suffix-word-run "attr_set" ->
        # a column ending "attr_set_id" should match, per the docstring's
        # own example (attr_set_id -> BmConfigAttrSet).
        plan_a = _plan("X", ["attr_set_id", "other"], [["1", "a"], ["2", "b"]])
        plan_b = _plan("BmConfigAttrSet", ["id", "name"], [["1", "A"], ["2", "B"]])
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        assert links == [{
            "source_type": "X", "source_attr": "attr_set_id",
            "target_type": "BmConfigAttrSet", "target_attr": "id",
            "name": "BMCONFIGATTRSET_HAS_X",
        }]

    def test_exact_type_name_column_matches_without_suffix(self):
        plan_a = _plan("Y", ["customer", "other"], [["1", "a"], ["2", "b"]])
        plan_b = _plan("Customer", ["id", "name"], [["1", "A"], ["2", "B"]])
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        assert links == [{
            "source_type": "Y", "source_attr": "customer",
            "target_type": "Customer", "target_attr": "id",
            "name": "CUSTOMER_HAS_Y",
        }]

    def test_no_match_when_no_suffix_or_type_column(self):
        plan_a = _plan("Y", ["unrelated_col"], [["1"], ["2"]])
        plan_b = _plan("Customer", ["id", "name"], [["1", "A"], ["2", "B"]])
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        assert links == []

    def test_fewer_than_two_plans_returns_empty(self):
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            assert _detect_fk_links([_plan("A", ["x"], [["1"]])]) == []
            assert _detect_fk_links([]) == []


class TestPass2RuleASharedMatchKey:
    def test_shared_code_match_key_produces_rule_a_link(self):
        # own_mk="a_key" (not "shared_code"), mk_b="shared_code" (>=3-char
        # stem after stripping "_code"), column "shared_code" in plan_a must
        # vary (>=2 distinct values in first 20 rows) to pass the guard.
        plan_a = _plan(
            "A", ["a_key", "shared_code"],
            [["1", "X1"], ["2", "X2"], ["3", "X3"]],
            match_keys=["a_key"],
        )
        plan_b = _plan(
            "B", ["shared_code", "val"],
            [["X1", "v1"], ["X2", "v2"]],
            match_keys=["shared_code"],
        )
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        assert {
            "source_type": "A", "source_attr": "shared_code",
            "target_type": "B", "target_attr": "shared_code",
            "name": "B_HAS_A",
        } in links

    def test_constant_column_does_not_produce_rule_a_link(self):
        # Same shape, but shared_code is constant in plan_a (1 distinct
        # value) -> _col_is_varying guard must suppress the link.
        plan_a = _plan(
            "A", ["a_key", "shared_code"],
            [["1", "SAME"], ["2", "SAME"], ["3", "SAME"]],
            match_keys=["a_key"],
        )
        plan_b = _plan(
            "B", ["shared_code", "val"],
            [["SAME", "v1"]],
            match_keys=["shared_code"],
        )
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        assert links == []


class TestPass2RuleBSubstringStem:
    def test_stem_fragment_inside_column_produces_rule_b_link(self):
        # mk_b="widget_code" -> mk_stem="widget" (>=3 chars). Column
        # "big_widget_ref" contains "widget" as a fragment, is != mk_b_l,
        # ends with a key suffix ("_ref"), and both sides vary.
        plan_a = _plan(
            "A", ["big_widget_ref"],
            [["1"], ["2"], ["3"]],
            match_keys=["a_key"],
        )
        plan_a["data"] = _csv_bytes(
            ["big_widget_ref"], [["W1"], ["W2"], ["W3"]],
        )
        plan_b = _plan(
            "B", ["widget_code", "val"],
            [["W1", "v1"], ["W2", "v2"]],
            match_keys=["widget_code"],
        )
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        assert {
            "source_type": "A", "source_attr": "big_widget_ref",
            "target_type": "B", "target_attr": "widget_code",
            "name": "B_HAS_A",
        } in links

    def test_short_stem_below_three_chars_is_skipped(self):
        # mk_b="ab_id" -> after stripping "_id", stem="ab" (2 chars, < 3)
        # -> Rule B must not fire. Column deliberately uses a DIFFERENT
        # suffix ("_code" vs mk_b's "_id") so Rule C's shared-suffix check
        # can't independently produce a link and mask what's being tested.
        plan_a = _plan(
            "A", ["grab_code"],
            [["1"], ["2"], ["3"]],
            match_keys=["a_key"],
        )
        plan_a["data"] = _csv_bytes(["grab_code"], [["X1"], ["X2"], ["X3"]])
        plan_b = _plan(
            "B", ["ab_id", "val"],
            [["X1", "v1"], ["X2", "v2"]],
            match_keys=["ab_id"],
        )
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        assert links == []


class TestPass2RuleCSharedSuffix:
    def test_shared_suffix_different_stems_produces_rule_c_link(self):
        # col="alt_ref" and mk_b="other_ref" share suffix "_ref" but have
        # DIFFERENT stems (not a Rule B substring match: "other" not in
        # "alt_ref") -> only Rule C's shared-suffix condition can fire.
        plan_a = _plan(
            "A", ["alt_ref"],
            [["1"], ["2"], ["3"]],
            match_keys=["a_key"],
        )
        plan_a["data"] = _csv_bytes(["alt_ref"], [["R1"], ["R2"], ["R3"]])
        plan_b = _plan(
            "B", ["other_ref", "val"],
            [["R1", "v1"], ["R2", "v2"]],
            match_keys=["other_ref"],
        )
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        assert {
            "source_type": "A", "source_attr": "alt_ref",
            "target_type": "B", "target_attr": "other_ref",
            "name": "B_HAS_A",
        } in links


class TestPass3XmlElementType:
    def test_element_type_id_column_matches_parent(self):
        plan_a = _plan("Child", ["parenttype_id", "name"],
                        [["1", "a"], ["2", "b"]])
        plan_a["data"] = _csv_bytes(
            ["parenttype_id", "name", "_element_type"],
            [["1", "a", "child"], ["2", "b", "child"]],
        )
        plan_b = _plan("Parent", ["id"], [["1"], ["2"]])
        plan_b["data"] = _csv_bytes(
            ["id", "_element_type"], [["1", "parenttype"], ["2", "parenttype"]],
        )
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b])
        # Pass 1 might also independently find a link here depending on type
        # names chosen deliberately distinct (Child/Parent) from
        # "parenttype" so only Pass 3's _element_type mechanism can match.
        assert any(
            lnk["source_attr"] == "parenttype_id" and lnk["target_type"] == "Parent"
            for lnk in links
        )


class TestDuplicateOntologyTypeAcrossPlans:
    def test_second_occurrence_of_same_type_pair_is_not_double_linked(self):
        """Edge case: two different plans share the same ontology_type
        (unusual but not impossible — e.g. a split export). `seen` in the
        original is keyed by TYPE STRING, not plan index, so once (A, B) is
        resolved via one B-plan, a second plan with the same type "B" must
        NOT also produce a link for the same (A, B) pair_key. This locks in
        that cross-index dedup behavior before the O(N) rewrite."""
        plan_a = _plan("A", ["b_id"], [["1"], ["2"]])
        plan_b1 = _plan("B", ["id", "name"], [["1", "x"], ["2", "y"]])
        plan_b2 = _plan("B", ["id", "name"], [["3", "z"], ["4", "w"]])
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links([plan_a, plan_b1, plan_b2])
        b_links = [lnk for lnk in links if lnk["target_type"] == "B"]
        assert len(b_links) == 1, (
            "duplicate-type plans must not produce duplicate (A,B) links"
        )


class TestManyPlansStillFindsExpectedLinks:
    def test_needle_link_found_among_many_unrelated_plans(self):
        """The scaling-relevant case: the expected match must still be found
        correctly when there are many other plans present — this is what an
        O(N) rewrite must preserve exactly, not just 'runs faster'."""
        plans = [
            _plan(f"Noise{i}", [f"col_{i}"], [["1"], ["2"]])
            for i in range(50)
        ]
        plan_a = _plan("Order", ["customer_id", "total"],
                        [["1", "100"], ["2", "200"]])
        plan_b = _plan("Customer", ["id", "name"],
                        [["1", "Alice"], ["2", "Bob"]])
        plans = plans[:25] + [plan_a, plan_b] + plans[25:]
        with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
                    return_value=_default_settings()):
            links = _detect_fk_links(plans)
        assert {
            "source_type": "Order", "source_attr": "customer_id",
            "target_type": "Customer", "target_attr": "id",
            "name": "CUSTOMER_HAS_ORDER",
        } in links
