"""Regression coverage for ingest_confirmed()'s parallel file processing.

Before this fix, approved tabular files were resolved strictly one at a
time — 10 files/sheets meant 10 fully serial discover->resolve->project
pipeline runs. This ports enterprise's design: all but the last file run
concurrently with skip_graph=True (no FalkorDB write, since project_graph()
rebuilds the entire workspace graph and concurrent calls would race), and
the last file alone runs afterward with skip_graph=False, doing the single
projection that picks up every file's entities (workspace-scoped, not
run-scoped).
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from aryx.pipeline.doc_discovery import ingest_confirmed


def _make_jobs():
    jobs = MagicMock()
    jobs.update_stage = MagicMock()
    return jobs


def _tabular_plan(fname, ontology_type="Widget"):
    return {"filename": fname, "data": b"a,b\n1,2\n",
            "ontology_type": ontology_type, "match_keys": ["a"]}


class TestParallelFileProcessing:
    def test_all_but_last_file_get_skip_graph_true(self):
        fnames = [f"f{i}.csv" for i in range(4)]
        data = {"mentions": [], "tabular": [_tabular_plan(f) for f in fnames]}

        calls = []

        def fake_run_pipeline(**kwargs):
            calls.append((kwargs["dataset"], kwargs["skip_graph"]))
            return {}

        with patch("aryx.pipeline.doc_discovery.run_pipeline", side_effect=fake_run_pipeline), \
             patch("aryx.pipeline.doc_discovery.relate_isolated"), \
             patch("aryx.pipeline.doc_discovery.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "dsn"
            mock_cfg.return_value.graph_url = "graph"
            mock_cfg.return_value.ingest_workers = 3
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1")

        assert len(calls) == 4
        skip_graph_flags = dict(calls)
        # Exactly one call (the last file, f3) must NOT skip the graph.
        non_skipped = [d for d, sg in calls if not sg]
        assert non_skipped == ["f3"]
        assert skip_graph_flags["f0"] is True
        assert skip_graph_flags["f1"] is True
        assert skip_graph_flags["f2"] is True

    def test_last_file_runs_only_after_all_others_complete(self):
        """Ordering guarantee project_graph correctness depends on: the
        un-skipped (last) call must not start until every concurrent call
        has already returned."""
        fnames = [f"f{i}.csv" for i in range(3)]
        data = {"mentions": [], "tabular": [_tabular_plan(f) for f in fnames]}

        completed_non_last = []
        last_started_after_all_non_last = []

        def fake_run_pipeline(**kwargs):
            skip = kwargs["skip_graph"]
            if skip:
                time.sleep(0.05)
                completed_non_last.append(kwargs["dataset"])
            else:
                last_started_after_all_non_last.append(len(completed_non_last))
            return {}

        with patch("aryx.pipeline.doc_discovery.run_pipeline", side_effect=fake_run_pipeline), \
             patch("aryx.pipeline.doc_discovery.relate_isolated"), \
             patch("aryx.pipeline.doc_discovery.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "dsn"
            mock_cfg.return_value.graph_url = "graph"
            mock_cfg.return_value.ingest_workers = 3
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1")

        assert len(completed_non_last) == 2
        assert last_started_after_all_non_last == [2]

    def test_single_file_batch_has_no_parallel_stage_just_runs_unskipped(self):
        fnames = ["only.csv"]
        data = {"mentions": [], "tabular": [_tabular_plan("only.csv")]}
        calls = []

        def fake_run_pipeline(**kwargs):
            calls.append(kwargs["skip_graph"])
            return {}

        with patch("aryx.pipeline.doc_discovery.run_pipeline", side_effect=fake_run_pipeline), \
             patch("aryx.pipeline.doc_discovery.relate_isolated"), \
             patch("aryx.pipeline.doc_discovery.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "dsn"
            mock_cfg.return_value.graph_url = "graph"
            mock_cfg.return_value.ingest_workers = 3
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1")

        assert calls == [False]

    def test_one_failed_concurrent_file_does_not_sink_the_batch(self):
        fnames = ["good1.csv", "bad.csv", "good2.csv"]
        data = {"mentions": [], "tabular": [_tabular_plan(f) for f in fnames]}
        ran = []

        def fake_run_pipeline(**kwargs):
            if kwargs["dataset"] == "bad":
                raise RuntimeError("boom")
            ran.append(kwargs["dataset"])
            return {}

        with patch("aryx.pipeline.doc_discovery.run_pipeline", side_effect=fake_run_pipeline), \
             patch("aryx.pipeline.doc_discovery.relate_isolated"), \
             patch("aryx.pipeline.doc_discovery.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "dsn"
            mock_cfg.return_value.graph_url = "graph"
            mock_cfg.return_value.ingest_workers = 3
            # Must not raise — a bad concurrent file is logged and skipped.
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1")

        # good1 (concurrent) and good2 (last, unskipped) both still ran.
        assert "good1" in ran
        assert "good2" in ran

    def test_ingest_workers_setting_controls_pool_size(self):
        from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor

        fnames = [f"f{i}.csv" for i in range(5)]
        data = {"mentions": [], "tabular": [_tabular_plan(f) for f in fnames]}

        with patch("aryx.pipeline.doc_discovery.run_pipeline", return_value={}), \
             patch("aryx.pipeline.doc_discovery.relate_isolated"), \
             patch("aryx.pipeline.doc_discovery.get_settings") as mock_cfg, \
             patch("aryx.pipeline.doc_discovery.ThreadPoolExecutor",
                   wraps=RealThreadPoolExecutor) as spy_pool_cls:
            mock_cfg.return_value.rdb_dsn = "dsn"
            mock_cfg.return_value.graph_url = "graph"
            mock_cfg.return_value.ingest_workers = 7
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1")

        spy_pool_cls.assert_called_once_with(max_workers=7)
