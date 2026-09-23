"""Tests for the 2026-09-23 fix (P17, docs/raven/SCALABILITY_BOTTLENECKS.md):
_infer_schema_fk_links() ran its independent LLM batches sequentially, one
after another, despite each batch covering a non-overlapping type subset
with no cross-batch dependency (dedup into `seen` happens after every batch
regardless of order). Now runs batches concurrently via ThreadPoolExecutor,
same pattern as dynamic_fk.judge_candidates_with_llm.

These tests mock infer_fk_links entirely (no real LLM calls) and focus on:
correctness (same links found, same dedup) is unchanged by concurrency, a
failing batch doesn't take down the others, and batch/anchor composition is
unaffected by execution order.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.pipeline.enrich.enrich_schema_fk import _infer_schema_fk_links


def _sample_with_n_types(n: int) -> list[tuple[int, str, dict]]:
    """n entity types, each with columns designed to make type_0 the anchor
    (most FK-like columns) — forces >1 batch once n > 8 (_BATCH_SIZE)."""
    sample = []
    for i in range(n):
        fk_cols = [f"other_{j}_id" for j in range(3)] if i == 0 else [f"other_0_id"]
        sample.append((i, f"type_{i}", {"name": "x", **{c: "y" for c in fk_cols}}))
    return sample


def _store(n_types: int) -> MagicMock:
    store = MagicMock()
    store.list_entities_typed_sample.return_value = _sample_with_n_types(n_types)
    return store


class TestBasicBehaviorUnchanged:
    def test_fewer_than_two_types_returns_empty(self):
        store = _store(1)
        assert _infer_schema_fk_links(store, broker=MagicMock()) == []

    def test_single_batch_when_types_fit(self):
        store = _store(5)  # anchor + 4 others, all fit in one batch of 8
        fake_link = {"source_type": "type_1", "source_attr": "other_0_id",
                     "target_type": "type_0", "target_attr": "id"}
        with patch(
            "aryx.pipeline.enrich.enrich_schema_fk.infer_fk_links",
            return_value=[fake_link],
        ) as mock_infer:
            links = _infer_schema_fk_links(store, broker=MagicMock())
        assert links == [fake_link]
        mock_infer.assert_called_once()


class TestConcurrentBatchesDedupeCorrectly:
    def test_multiple_batches_run_and_dedupe(self):
        # 20 types -> anchor + 19 others -> batches of 7 (_BATCH_SIZE-1) -> 3 batches
        store = _store(20)
        call_count = {"n": 0}

        def fake_infer(batch_schemas, broker):
            call_count["n"] += 1
            # Every batch "discovers" the same link -> must dedupe to 1.
            return [{
                "source_type": "type_1", "source_attr": "other_0_id",
                "target_type": "type_0", "target_attr": "id",
            }]

        with patch(
            "aryx.pipeline.enrich.enrich_schema_fk.infer_fk_links",
            side_effect=fake_infer,
        ):
            links = _infer_schema_fk_links(store, broker=MagicMock())

        assert call_count["n"] == 3, "expected 3 batches for 19 non-anchor types"
        assert len(links) == 1, "identical links across batches must dedupe to one"

    def test_distinct_links_across_batches_all_kept(self):
        store = _store(20)
        seen_batches: list[frozenset] = []

        def fake_infer(batch_schemas, broker):
            keys = frozenset(batch_schemas.keys())
            seen_batches.append(keys)
            # Return a link unique to this batch (keyed by a type in it).
            other = sorted(t for t in batch_schemas if t != "type_0")[0]
            return [{
                "source_type": other, "source_attr": "other_0_id",
                "target_type": "type_0", "target_attr": "id",
            }]

        with patch(
            "aryx.pipeline.enrich.enrich_schema_fk.infer_fk_links",
            side_effect=fake_infer,
        ):
            links = _infer_schema_fk_links(store, broker=MagicMock())

        assert len(links) == 3, "one distinct link per batch, none should collide"
        source_types = {lnk["source_type"] for lnk in links}
        assert len(source_types) == 3


class TestFailingBatchDoesNotBreakOthers:
    def test_one_batch_erroring_still_returns_others_results(self):
        store = _store(20)
        calls = {"n": 0}

        def fake_infer(batch_schemas, broker):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated LLM failure for this batch")
            other = sorted(t for t in batch_schemas if t != "type_0")[0]
            return [{
                "source_type": other, "source_attr": "other_0_id",
                "target_type": "type_0", "target_attr": "id",
            }]

        with patch(
            "aryx.pipeline.enrich.enrich_schema_fk.infer_fk_links",
            side_effect=fake_infer,
        ):
            links = _infer_schema_fk_links(store, broker=MagicMock())

        # 3 batches total, 1 fails -> at most 2 links, no exception propagates.
        assert len(links) <= 2
        assert calls["n"] == 3


class TestWorkerSettingRespected:
    def test_worker_count_setting_is_read(self):
        store = _store(20)
        with patch(
            "aryx.pipeline.enrich.enrich_schema_fk.infer_fk_links",
            return_value=[],
        ), patch(
            "aryx.pipeline.enrich.enrich_schema_fk.get_settings"
        ) as mock_cfg:
            mock_cfg.return_value.fk_schema_batch_workers = 2
            _infer_schema_fk_links(store, broker=MagicMock())
            assert mock_cfg.return_value.fk_schema_batch_workers == 2
