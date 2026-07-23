"""Dynamic (value-overlap + LLM judge) FK detection — the general, no-hardcoding
replacement/supplement for doc_discovery._detect_fk_links' column-name-only
passes.

Covers:
  - value sampling: dedupes, respects the configured sample size, normalizes
  - overlap scoring: full/partial/zero/degenerate cases
  - candidate generation: config-driven thresholds, already-linked pairs
    skipped, self-pairs skipped, constant columns skipped
  - LLM judge stage: accepted/rejected verdicts, a failing call doesn't drop
    other candidates, and — the explicit no-hardcoding requirement — EVERY
    candidate that clears Stage 1 gets judged, none silently dropped by count
  - detect_dynamic_fk_links: disabled-by-config and too-few-plans short-circuits
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.pipeline.dynamic_fk import (
    detect_dynamic_fk_links,
    estimate_join_fanout,
    generate_candidate_pairs,
    judge_candidates_with_llm,
    sample_distinct_values,
    sample_value_counts,
    value_overlap_ratio,
)


def _csv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    lines = [",".join(header)] + [",".join(r) for r in rows]
    return ("\n".join(lines)).encode("utf-8")


def _settings(**overrides):
    base = dict(
        fk_dynamic_detection_enabled=True,
        fk_value_sample_size=200,
        fk_value_overlap_threshold=0.05,
        fk_dynamic_judge_workers=4,
        fk_fanout_scan_rows=20000,
        fk_max_estimated_fanout=5000,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── sample_distinct_values ───────────────────────────────────────────────────

def test_sample_distinct_values_dedupes_and_normalizes():
    data = _csv_bytes(["code"], [["M1"], ["m1"], [" M1 "], ["M2"]])
    values = sample_distinct_values(data, ["code"], "code", sample_size=200)
    assert values == {"m1", "m2"}


def test_sample_distinct_values_respects_sample_size_even_with_more_rows():
    rows = [[f"V{i}"] for i in range(500)]
    data = _csv_bytes(["code"], rows)
    values = sample_distinct_values(data, ["code"], "code", sample_size=10)
    assert len(values) == 10


def test_sample_distinct_values_missing_column_returns_empty():
    data = _csv_bytes(["code"], [["M1"]])
    assert sample_distinct_values(data, ["code"], "nope", sample_size=200) == set()


# ── value_overlap_ratio ──────────────────────────────────────────────────────

def test_overlap_full_containment_scores_high():
    lookup = {"m1", "m2"}
    fact = {"m1", "m2", "m3", "m4", "m5"}
    assert value_overlap_ratio(lookup, fact) == 1.0


def test_overlap_zero_when_disjoint():
    assert value_overlap_ratio({"a", "b"}, {"c", "d"}) == 0.0


def test_overlap_zero_when_either_side_empty():
    assert value_overlap_ratio(set(), {"a"}) == 0.0
    assert value_overlap_ratio({"a"}, set()) == 0.0


def test_overlap_partial():
    a = {"m1", "m2", "m3", "m4"}
    b = {"m1", "m2"}
    # smaller side is b (2 values), both present in a -> 2/2 = 1.0
    assert value_overlap_ratio(a, b) == 1.0
    c = {"m1", "x", "y", "z"}
    # smaller side is a (4 values in first test) — use asymmetric sizes properly
    assert value_overlap_ratio({"m1", "m2", "m3"}, {"m1", "q", "r"}) == 1 / 3


# ── sample_value_counts / estimate_join_fanout (selectivity guard) ─────────
# Regression coverage for a real incident: a shared low-cardinality category
# column ("Matl Group") had a perfectly reasonable distinct-value overlap
# ratio but produced 1,529,548 relationship rows from one FK spec, because
# nothing checked how many ROWS shared each value before accepting the join.

def test_sample_value_counts_counts_occurrences_not_just_distinctness():
    data = _csv_bytes(["code"], [["A"], ["A"], ["A"], ["B"]])
    counts = sample_value_counts(data, ["code"], "code", max_rows=20000)
    assert counts == {"a": 3, "b": 1}


def test_sample_value_counts_respects_row_scan_cap():
    rows = [["A"]] * 100
    data = _csv_bytes(["code"], rows)
    counts = sample_value_counts(data, ["code"], "code", max_rows=10)
    assert counts["a"] == 10


def test_estimate_join_fanout_multiplies_matching_counts():
    # 3 rows of "X" on side A, 4 rows of "X" on side B -> 12 pairs from "X".
    # Plus "Y" appears twice on A but never on B -> contributes 0.
    data_a = _csv_bytes(["code"], [["X"], ["X"], ["X"], ["Y"], ["Y"]])
    data_b = _csv_bytes(["ref"], [["X"], ["X"], ["X"], ["X"]])
    fanout = estimate_join_fanout(data_a, ["code"], "code", data_b, ["ref"], "ref", max_rows=20000)
    assert fanout == 12


def test_estimate_join_fanout_zero_when_no_shared_values():
    data_a = _csv_bytes(["code"], [["X"], ["X"]])
    data_b = _csv_bytes(["ref"], [["Y"], ["Y"]])
    fanout = estimate_join_fanout(data_a, ["code"], "code", data_b, ["ref"], "ref", max_rows=20000)
    assert fanout == 0


def test_high_fanout_category_column_is_rejected_despite_good_overlap_ratio():
    """The exact real-world shape that caused the incident: a small set of
    category codes, each shared by MANY rows on both sides. Distinct-value
    overlap is 100% (looks like a great join key) but the actual row-level
    fan-out is enormous — the candidate must be rejected before Stage 2."""
    # 3 distinct category codes, each repeated 20x on each side -> perfect
    # distinct overlap, but 20*20*3 = 1200 relationship rows if joined.
    codes = ["G1", "G2", "G3"]
    rows_a = [[c] for c in codes for _ in range(20)]
    rows_b = [[c] for c in codes for _ in range(20)]
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["matl_group"], rows_a)},
        {"ontology_type": "B", "data": _csv_bytes(["matl_group"], rows_b)},
    ]
    with patch("aryx.pipeline.dynamic_fk.get_settings",
               return_value=_settings(fk_max_estimated_fanout=500)):
        candidates = generate_candidate_pairs(plans)
    assert candidates == [], "non-selective category column must be rejected, not passed to Stage 2"


def test_selective_join_key_survives_the_fanout_guard():
    """A real near-unique join key (each value appears once per side) must
    NOT be rejected by the fanout guard — only genuinely non-selective
    columns should be filtered."""
    rows_a = [[f"ID{i}"] for i in range(20)]
    rows_b = [[f"ID{i}"] for i in range(20)]
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["id"], rows_a)},
        {"ontology_type": "B", "data": _csv_bytes(["ref_id"], rows_b)},
    ]
    with patch("aryx.pipeline.dynamic_fk.get_settings",
               return_value=_settings(fk_max_estimated_fanout=500)):
        candidates = generate_candidate_pairs(plans)
    assert len(candidates) == 1


# ── generate_candidate_pairs ─────────────────────────────────────────────────

def test_finds_candidate_between_overlapping_columns_across_types():
    plans = [
        {
            "ontology_type": "Transaction",
            "data": _csv_bytes(["material_code"], [["M1"], ["M2"], ["M1"]]),
        },
        {
            "ontology_type": "Material",
            "data": _csv_bytes(["code"], [["M1"], ["M2"], ["M9"]]),
        },
    ]
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()):
        candidates = generate_candidate_pairs(plans)
    pairs = {(c["type_a"], c["col_a"], c["type_b"], c["col_b"]) for c in candidates}
    assert ("Transaction", "material_code", "Material", "code") in pairs


def test_self_type_pairs_are_never_candidates():
    plans = [
        {"ontology_type": "Same", "data": _csv_bytes(["c"], [["A"], ["B"]])},
        {"ontology_type": "Same", "data": _csv_bytes(["c"], [["A"], ["B"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()):
        candidates = generate_candidate_pairs(plans)
    assert candidates == []


def test_already_linked_pairs_are_skipped():
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["x"], [["1"], ["2"]])},
        {"ontology_type": "B", "data": _csv_bytes(["y"], [["1"], ["2"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()):
        candidates = generate_candidate_pairs(plans, already_linked={("A", "B")})
    assert candidates == []
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()):
        candidates_reverse_direction = generate_candidate_pairs(plans, already_linked={("B", "A")})
    assert candidates_reverse_direction == []


def test_constant_column_excluded_as_not_a_real_key():
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["const"], [["X"], ["X"], ["X"]])},
        {"ontology_type": "B", "data": _csv_bytes(["const"], [["X"], ["X"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()):
        candidates = generate_candidate_pairs(plans)
    assert candidates == []


def test_below_threshold_pairs_excluded():
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["x"], [["1"], ["2"], ["3"], ["4"], ["5"]])},
        {"ontology_type": "B", "data": _csv_bytes(["y"], [["1"], ["9"], ["10"], ["11"], ["12"]])},
    ]
    # overlap ratio = 1/5 = 0.2 for the smaller side; set threshold above that.
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings(fk_value_overlap_threshold=0.5)):
        candidates = generate_candidate_pairs(plans)
    assert candidates == []
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings(fk_value_overlap_threshold=0.1)):
        candidates = generate_candidate_pairs(plans)
    assert len(candidates) == 1


# ── judge_candidates_with_llm ────────────────────────────────────────────────

def _candidate(i: int) -> dict:
    return {
        "type_a": f"TypeA{i}", "col_a": "col_a",
        "type_b": f"TypeB{i}", "col_b": "col_b",
        "overlap": 0.5, "samples_a": ["x"], "samples_b": ["x"],
    }


def test_accepted_verdict_produces_a_link():
    candidates = [_candidate(0)]
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()), \
         patch("aryx.pipeline.dynamic_fk.complete_json",
               return_value={"linked": True, "reason": "same code space"}):
        links = judge_candidates_with_llm(candidates, broker=object())
    assert len(links) == 1
    assert links[0]["source_type"] == "TypeA0"
    assert links[0]["target_type"] == "TypeB0"
    assert links[0]["reason"] == "same code space"


def test_rejected_verdict_produces_no_link():
    candidates = [_candidate(0)]
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()), \
         patch("aryx.pipeline.dynamic_fk.complete_json",
               return_value={"linked": False, "reason": "coincidental overlap"}):
        links = judge_candidates_with_llm(candidates, broker=object())
    assert links == []


def test_llm_failure_on_one_candidate_does_not_drop_others():
    candidates = [_candidate(0), _candidate(1)]

    def side_effect(*args, **kwargs):
        # args[2] is `user` in complete_json(broker, tier, system, user, schema)
        if "TypeA0" in args[3]:
            raise RuntimeError("provider error")
        return {"linked": True, "reason": "ok"}

    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()), \
         patch("aryx.pipeline.dynamic_fk.complete_json", side_effect=side_effect):
        links = judge_candidates_with_llm(candidates, broker=object())
    assert len(links) == 1
    assert links[0]["source_type"] == "TypeA1"


def test_no_hardcoded_cap_every_candidate_is_judged():
    """The explicit requirement: no cap on candidate pairs, so no node is
    silently dropped. Generate many candidates and assert every single one
    receives an LLM verdict (call count == candidate count), regardless of
    worker concurrency."""
    candidates = [_candidate(i) for i in range(57)]
    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        call_count["n"] += 1
        return {"linked": False, "reason": "no"}

    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings(fk_dynamic_judge_workers=4)), \
         patch("aryx.pipeline.dynamic_fk.complete_json", side_effect=side_effect):
        judge_candidates_with_llm(candidates, broker=object())
    assert call_count["n"] == 57


def test_judge_workers_setting_bounds_concurrency_not_coverage():
    """Different worker counts must still judge every candidate — the setting
    only changes throughput, never how many get judged."""
    candidates = [_candidate(i) for i in range(10)]
    for workers in (1, 2, 8):
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            return {"linked": False, "reason": "no"}

        with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings(fk_dynamic_judge_workers=workers)), \
             patch("aryx.pipeline.dynamic_fk.complete_json", side_effect=side_effect):
            judge_candidates_with_llm(candidates, broker=object())
        assert call_count["n"] == 10


# ── detect_dynamic_fk_links ──────────────────────────────────────────────────

def test_disabled_via_config_returns_no_links():
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["x"], [["1"], ["2"]])},
        {"ontology_type": "B", "data": _csv_bytes(["y"], [["1"], ["2"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings(fk_dynamic_detection_enabled=False)):
        links = detect_dynamic_fk_links(plans, broker=object())
    assert links == []


def test_fewer_than_two_plans_returns_no_links():
    plans = [{"ontology_type": "A", "data": _csv_bytes(["x"], [["1"]])}]
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()):
        links = detect_dynamic_fk_links(plans, broker=object())
    assert links == []


def test_end_to_end_finds_and_judges_a_real_relationship():
    plans = [
        {"ontology_type": "Transaction", "data": _csv_bytes(["material_code"], [["M1"], ["M2"]])},
        {"ontology_type": "Material", "data": _csv_bytes(["code"], [["M1"], ["M2"], ["M9"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.get_settings", return_value=_settings()), \
         patch("aryx.pipeline.dynamic_fk.complete_json",
               return_value={"linked": True, "reason": "shared material code space"}):
        links = detect_dynamic_fk_links(plans, broker=object())
    assert len(links) == 1
    assert links[0]["source_type"] == "Transaction"
    assert links[0]["target_type"] == "Material"
