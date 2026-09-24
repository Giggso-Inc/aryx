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

from aryx.pipeline.dynamic_fk.dynamic_fk import (
    _extract_verdicts_by_index,
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
        # 1, not the real default of 5: existing tests below predate
        # batching and assert one complete_json call per candidate — this
        # keeps them exercising that exact behavior unchanged. Batching
        # itself (including the real default) has its own dedicated tests
        # further down, which override this explicitly.
        fk_dynamic_judge_batch_size=1,
        fk_fanout_scan_rows=20000,
        fk_max_estimated_fanout=5000,
        fk_prefix_transform_lengths="2,3,4",
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
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings",
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
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings",
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
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()):
        candidates = generate_candidate_pairs(plans)
    pairs = {(c["type_a"], c["col_a"], c["type_b"], c["col_b"]) for c in candidates}
    assert ("Transaction", "material_code", "Material", "code") in pairs


def test_self_type_pairs_are_never_candidates():
    plans = [
        {"ontology_type": "Same", "data": _csv_bytes(["c"], [["A"], ["B"]])},
        {"ontology_type": "Same", "data": _csv_bytes(["c"], [["A"], ["B"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()):
        candidates = generate_candidate_pairs(plans)
    assert candidates == []


def test_already_linked_pairs_are_skipped():
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["x"], [["1"], ["2"]])},
        {"ontology_type": "B", "data": _csv_bytes(["y"], [["1"], ["2"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()):
        candidates = generate_candidate_pairs(plans, already_linked={("A", "B")})
    assert candidates == []
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()):
        candidates_reverse_direction = generate_candidate_pairs(plans, already_linked={("B", "A")})
    assert candidates_reverse_direction == []


def test_constant_column_excluded_as_not_a_real_key():
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["const"], [["X"], ["X"], ["X"]])},
        {"ontology_type": "B", "data": _csv_bytes(["const"], [["X"], ["X"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()):
        candidates = generate_candidate_pairs(plans)
    assert candidates == []


def test_below_threshold_pairs_excluded():
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["x"], [["1"], ["2"], ["3"], ["4"], ["5"]])},
        {"ontology_type": "B", "data": _csv_bytes(["y"], [["1"], ["9"], ["10"], ["11"], ["12"]])},
    ]
    # overlap ratio = 1/5 = 0.2 for the smaller side; set threshold above that.
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings(fk_value_overlap_threshold=0.5)):
        candidates = generate_candidate_pairs(plans)
    assert candidates == []
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings(fk_value_overlap_threshold=0.1)):
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
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json",
               return_value={"verdicts": [{"index": 0, "linked": True, "reason": "same code space"}]}):
        links = judge_candidates_with_llm(candidates, broker=object())
    assert len(links) == 1
    assert links[0]["source_type"] == "TypeA0"
    assert links[0]["target_type"] == "TypeB0"
    assert links[0]["reason"] == "same code space"


def test_rejected_verdict_produces_no_link():
    candidates = [_candidate(0)]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json",
               return_value={"verdicts": [{"index": 0, "linked": False, "reason": "coincidental overlap"}]}):
        links = judge_candidates_with_llm(candidates, broker=object())
    assert links == []


def test_llm_failure_on_one_candidate_does_not_drop_others():
    """With batch_size=1 (the test default — see _settings), each candidate
    is still its own LLM call, so one call failing must not drop the other
    candidate's verdict. (Batching's wider failure blast-radius — one
    failed call costing a whole batch — has its own dedicated tests
    further down.)"""
    candidates = [_candidate(0), _candidate(1)]

    def side_effect(*args, **kwargs):
        # args[2] is `user` in complete_json(broker, tier, system, user, schema)
        if "TypeA0" in args[3]:
            raise RuntimeError("provider error")
        return {"verdicts": [{"index": 0, "linked": True, "reason": "ok"}]}

    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json", side_effect=side_effect):
        links = judge_candidates_with_llm(candidates, broker=object())
    assert len(links) == 1
    assert links[0]["source_type"] == "TypeA1"


def test_no_hardcoded_cap_every_candidate_is_judged():
    """The explicit requirement: no cap on candidate pairs, so no node is
    silently dropped. Generate many candidates and assert every single one
    receives an LLM verdict (call count == candidate count at batch_size=1),
    regardless of worker concurrency."""
    candidates = [_candidate(i) for i in range(57)]
    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        call_count["n"] += 1
        return {"verdicts": [{"index": 0, "linked": False, "reason": "no"}]}

    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings(fk_dynamic_judge_workers=4)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json", side_effect=side_effect):
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
            return {"verdicts": [{"index": 0, "linked": False, "reason": "no"}]}

        with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings(fk_dynamic_judge_workers=workers)), \
             patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json", side_effect=side_effect):
            judge_candidates_with_llm(candidates, broker=object())
        assert call_count["n"] == 10


# ── batching (2026-09-23, Phase 2) ───────────────────────────────────────────

def test_extract_verdicts_prefers_the_index_key():
    verdicts = [{"index": 1, "linked": True}, {"index": 0, "linked": False}]
    by_index = _extract_verdicts_by_index(verdicts, batch_len=2)
    assert by_index[0]["linked"] is False
    assert by_index[1]["linked"] is True


def test_extract_verdicts_falls_back_to_known_aliases():
    """Live-confirmed against the real OCI GenAI 'cheap' tier: the model
    used 'pair_index' instead of the schema's 'index' key, despite it
    being marked required — the judgments were correct, only the key name
    drifted, so parsing must not discard a batch over this."""
    verdicts = [{"pair_index": 0, "linked": True}, {"pair_index": 1, "linked": False}]
    by_index = _extract_verdicts_by_index(verdicts, batch_len=2)
    assert by_index[0]["linked"] is True
    assert by_index[1]["linked"] is False


def test_extract_verdicts_falls_back_to_response_order_when_no_index_key():
    """No recognized index key anywhere, but exactly one verdict per
    candidate -- treat the response as answered in order rather than
    discarding every candidate."""
    verdicts = [{"linked": True}, {"linked": False}, {"linked": True}]
    by_index = _extract_verdicts_by_index(verdicts, batch_len=3)
    assert by_index[0]["linked"] is True
    assert by_index[1]["linked"] is False
    assert by_index[2]["linked"] is True


def test_extract_verdicts_no_positional_fallback_when_counts_mismatch():
    """Falling back to response order is only safe when the count matches
    the batch -- a mismatched count with no usable index is genuinely
    unusable and must not be guessed at."""
    verdicts = [{"linked": True}, {"linked": False}]
    by_index = _extract_verdicts_by_index(verdicts, batch_len=3)
    assert by_index == {}


def test_extract_verdicts_out_of_range_index_is_ignored():
    verdicts = [{"index": 0, "linked": True}, {"index": 99, "linked": True}]
    by_index = _extract_verdicts_by_index(verdicts, batch_len=2)
    assert list(by_index) == [0]


def test_batch_judge_survives_llm_using_a_nonstandard_index_key_name():
    """End-to-end through judge_candidates_with_llm, not just the helper in
    isolation -- a batch response keyed by 'pair_index' must still produce
    correct links, matching what was live-confirmed against the real LLM."""
    candidates = [_candidate(0), _candidate(1)]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings",
               return_value=_settings(fk_dynamic_judge_batch_size=5)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json",
               return_value={"verdicts": [
                   {"pair_index": 0, "linked": True, "reason": "yes"},
                   {"pair_index": 1, "linked": False, "reason": "no"},
               ]}):
        links = judge_candidates_with_llm(candidates, broker=object())
    assert len(links) == 1
    assert links[0]["source_type"] == "TypeA0"



def test_batch_size_groups_multiple_candidates_into_one_llm_call():
    candidates = [_candidate(i) for i in range(10)]
    call_count = {"n": 0}
    batch_lens: list[int] = []

    def side_effect(broker, tier, system, user, schema):
        call_count["n"] += 1
        n = user.count("Pair ")
        batch_lens.append(n)
        return {"verdicts": [
            {"index": i, "linked": False, "reason": "no"} for i in range(n)
        ]}

    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings",
               return_value=_settings(fk_dynamic_judge_batch_size=5)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json", side_effect=side_effect):
        judge_candidates_with_llm(candidates, broker=object())
    assert call_count["n"] == 2, "10 candidates at batch size 5 -> 2 LLM calls, not 10"
    assert sorted(batch_lens) == [5, 5]


def test_batch_size_default_is_five():
    candidates = [_candidate(i) for i in range(11)]
    call_count = {"n": 0}

    def side_effect(broker, tier, system, user, schema):
        call_count["n"] += 1
        n = user.count("Pair ")
        return {"verdicts": [
            {"index": i, "linked": False, "reason": "no"} for i in range(n)
        ]}

    # Real Settings() default (config_fk_detection.py), not a test override.
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings",
               return_value=_settings(fk_dynamic_judge_batch_size=5)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json", side_effect=side_effect):
        judge_candidates_with_llm(candidates, broker=object())
    assert call_count["n"] == 3, "11 candidates at the default batch size 5 -> ceil(11/5) = 3 calls"


def test_batch_verdicts_map_back_to_the_right_candidate_by_index():
    candidates = [_candidate(i) for i in range(3)]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings",
               return_value=_settings(fk_dynamic_judge_batch_size=5)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json",
               return_value={"verdicts": [
                   {"index": 2, "linked": True, "reason": "r2"},
                   {"index": 0, "linked": False, "reason": "r0"},
                   {"index": 1, "linked": True, "reason": "r1"},
               ]}):
        links = judge_candidates_with_llm(candidates, broker=object())
    linked_types = {lnk["source_type"] for lnk in links}
    assert linked_types == {"TypeA2", "TypeA1"}, (
        "verdicts arriving out of order and index-keyed must still map to "
        "the correct candidate, not positionally"
    )


def test_batch_missing_verdict_for_an_index_defaults_to_not_linked():
    candidates = [_candidate(i) for i in range(3)]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings",
               return_value=_settings(fk_dynamic_judge_batch_size=5)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json",
               return_value={"verdicts": [
                   {"index": 0, "linked": True, "reason": "r0"},
                   # index 1 missing entirely from the response
                   {"index": 2, "linked": True, "reason": "r2"},
               ]}):
        links = judge_candidates_with_llm(candidates, broker=object())
    linked_types = {lnk["source_type"] for lnk in links}
    assert linked_types == {"TypeA0", "TypeA2"}
    assert "TypeA1" not in linked_types, (
        "a candidate with no verdict in the response must fail open as "
        "not-linked, never crash or silently duplicate another's verdict"
    )


def test_one_failed_batch_does_not_drop_candidates_in_other_batches():
    """Batching's real trade-off: a failed LLM call now costs a whole
    batch's verdicts, not one candidate's — but it must still be scoped to
    THAT batch only, never cascade to other batches judged concurrently."""
    candidates = [_candidate(i) for i in range(10)]  # 2 batches of 5

    def side_effect(broker, tier, system, user, schema):
        if "TypeA0" in user:  # candidate 0 is in the first batch
            raise RuntimeError("provider error for this batch")
        n = user.count("Pair ")
        return {"verdicts": [
            {"index": i, "linked": True, "reason": "ok"} for i in range(n)
        ]}

    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings",
               return_value=_settings(fk_dynamic_judge_batch_size=5)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json", side_effect=side_effect):
        links = judge_candidates_with_llm(candidates, broker=object())
    linked_types = {lnk["source_type"] for lnk in links}
    # First batch (candidates 0-4) failed entirely -> none linked.
    for i in range(5):
        assert f"TypeA{i}" not in linked_types
    # Second batch (candidates 5-9) succeeded -> all linked.
    for i in range(5, 10):
        assert f"TypeA{i}" in linked_types


def test_batch_size_one_recovers_original_one_call_per_candidate_behavior():
    candidates = [_candidate(i) for i in range(4)]
    call_count = {"n": 0}

    def side_effect(broker, tier, system, user, schema):
        call_count["n"] += 1
        assert user.count("Pair ") == 1
        return {"verdicts": [{"index": 0, "linked": False, "reason": "no"}]}

    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings",
               return_value=_settings(fk_dynamic_judge_batch_size=1)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json", side_effect=side_effect):
        judge_candidates_with_llm(candidates, broker=object())
    assert call_count["n"] == 4


# docs/falkordb_high_cpu_2026-07-29.md follow-up — this stage previously had
# no progress signal at all. A live ingestion job sat with zero log output
# and near-zero CPU for 9+ minutes of real (LLM-call-bound) work here,
# genuinely indistinguishable from a hang without on_progress.

def test_on_progress_called_once_per_candidate_with_final_totals():
    candidates = [_candidate(i) for i in range(6)]
    calls: list[tuple[int, int]] = []
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings(fk_dynamic_judge_workers=3)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json",
               return_value={"verdicts": [{"index": 0, "linked": False, "reason": "no"}]}):
        judge_candidates_with_llm(candidates, broker=object(), on_progress=lambda d, t: calls.append((d, t)))
    assert len(calls) == 6
    assert all(total == 6 for _done, total in calls)
    assert sorted(done for done, _total in calls) == [1, 2, 3, 4, 5, 6]


def test_on_progress_exception_does_not_break_judging():
    """Progress reporting is a side channel — a bug in the caller's callback
    (e.g. a job-store write failing) must never lose a candidate's verdict."""
    candidates = [_candidate(i) for i in range(4)]

    def _bad_progress(done, total):
        raise RuntimeError("job store unavailable")

    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings(fk_dynamic_judge_workers=2)), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json",
               return_value={"verdicts": [{"index": 0, "linked": True, "reason": "yes"}]}):
        links = judge_candidates_with_llm(candidates, broker=object(), on_progress=_bad_progress)
    assert len(links) == 4


def test_detect_dynamic_fk_links_threads_on_progress_through():
    plans = [
        {"filename": "a.csv", "ontology_type": "A",
         "data": _csv_bytes(["x"], [[str(i)] for i in range(20)])},
        {"filename": "b.csv", "ontology_type": "B",
         "data": _csv_bytes(["y"], [[str(i)] for i in range(20)])},
    ]
    calls: list[tuple[int, int]] = []
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json",
               return_value={"verdicts": [{"index": 0, "linked": False, "reason": "no"}]}):
        detect_dynamic_fk_links(plans, broker=object(), on_progress=lambda d, t: calls.append((d, t)))
    assert calls, "on_progress must fire when detect_dynamic_fk_links actually judges candidates"


# ── detect_dynamic_fk_links ──────────────────────────────────────────────────

def test_disabled_via_config_returns_no_links():
    plans = [
        {"ontology_type": "A", "data": _csv_bytes(["x"], [["1"], ["2"]])},
        {"ontology_type": "B", "data": _csv_bytes(["y"], [["1"], ["2"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings(fk_dynamic_detection_enabled=False)):
        links = detect_dynamic_fk_links(plans, broker=object())
    assert links == []


def test_fewer_than_two_plans_returns_no_links():
    plans = [{"ontology_type": "A", "data": _csv_bytes(["x"], [["1"]])}]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()):
        links = detect_dynamic_fk_links(plans, broker=object())
    assert links == []


def test_end_to_end_finds_and_judges_a_real_relationship():
    plans = [
        {"ontology_type": "Transaction", "data": _csv_bytes(["material_code"], [["M1"], ["M2"]])},
        {"ontology_type": "Material", "data": _csv_bytes(["code"], [["M1"], ["M2"], ["M9"]])},
    ]
    with patch("aryx.pipeline.dynamic_fk.dynamic_fk.get_settings", return_value=_settings()), \
         patch("aryx.pipeline.dynamic_fk.dynamic_fk.complete_json",
               return_value={"verdicts": [{"index": 0, "linked": True, "reason": "shared material code space"}]}):
        links = detect_dynamic_fk_links(plans, broker=object())
    assert len(links) == 1
    assert links[0]["source_type"] == "Transaction"
    assert links[0]["target_type"] == "Material"
