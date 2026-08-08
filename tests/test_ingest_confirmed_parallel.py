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
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from aryx.pipeline.doc_discovery import ingest_confirmed


def _make_jobs():
    jobs = MagicMock()
    jobs.update_stage = MagicMock()
    return jobs


def _thread_pool_factory(max_workers):
    """Test double for ingest_confirmed's _pool_factory.

    ingest_confirmed's default pool is a real ProcessPoolExecutor, which
    requires every submitted arg to be picklable and runs the target in a
    fresh interpreter that never sees these tests' unittest.mock.patch()
    substitutions (run_pipeline, relate_isolated, get_settings) — those
    only exist in this test process's memory. A ThreadPoolExecutor shares
    this process's memory, so the same MagicMock-based mocking this file
    already used keeps working, while still exercising the real
    orchestration logic (ordering, skip_graph flags, failure isolation)."""
    return ThreadPoolExecutor(max_workers=max_workers)


def _tabular_plan(fname, ontology_type="Widget"):
    return {"filename": fname, "data": b"a,b\n1,2\n",
            "ontology_type": ontology_type, "match_keys": ["a"]}


def _charge_only(fname, plan, settings, broker, workspace_id, skip_graph):
    """Module-level (picklable) stand-in for _run_one_tabular_file — a real
    ProcessPoolExecutor needs an importable-by-name target, and the real
    target reaches Postgres/FalkorDB. Used only to exercise the
    cross-process budget-sharing plumbing itself, in isolation from the
    actual land+resolve pipeline."""
    broker.charge("cheap", 100)


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
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1",
                             _pool_factory=_thread_pool_factory)

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
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1",
                             _pool_factory=_thread_pool_factory)

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
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1",
                             _pool_factory=_thread_pool_factory)

        assert calls == [False]

    def test_one_failed_concurrent_file_does_not_sink_the_batch_but_is_reported(self):
        """A bad file must not crash the other concurrent files or skip
        relate_isolated (isolation), but the caller MUST still learn about
        the failure (no silent "complete" on partial success) — Raven
        review finding: this used to only log.warning and swallow it."""
        fnames = ["good1.csv", "bad.csv", "good2.csv"]
        data = {"mentions": [], "tabular": [_tabular_plan(f) for f in fnames]}
        ran = []
        relate_isolated_called = []

        def fake_run_pipeline(**kwargs):
            if kwargs["dataset"] == "bad":
                raise RuntimeError("boom")
            ran.append(kwargs["dataset"])
            return {}

        with patch("aryx.pipeline.doc_discovery.run_pipeline", side_effect=fake_run_pipeline), \
             patch("aryx.pipeline.doc_discovery.relate_isolated",
                   side_effect=lambda *a, **k: relate_isolated_called.append(True)), \
             patch("aryx.pipeline.doc_discovery.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "dsn"
            mock_cfg.return_value.graph_url = "graph"
            mock_cfg.return_value.ingest_workers = 3
            try:
                ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1",
                             _pool_factory=_thread_pool_factory)
                raised = False
            except RuntimeError as exc:
                raised = True
                message = str(exc)

        # good1 (concurrent) and good2 (last, unskipped) both still ran —
        # isolation held.
        assert "good1" in ran
        assert "good2" in ran
        # relate_isolated still ran for whatever landed successfully.
        assert relate_isolated_called == [True]
        # But the failure must be surfaced, not silently swallowed.
        assert raised is True
        assert "bad.csv" in message
        assert "boom" in message

    def test_no_failures_means_no_raise(self):
        fnames = ["good1.csv", "good2.csv"]
        data = {"mentions": [], "tabular": [_tabular_plan(f) for f in fnames]}

        with patch("aryx.pipeline.doc_discovery.run_pipeline", return_value={}), \
             patch("aryx.pipeline.doc_discovery.relate_isolated"), \
             patch("aryx.pipeline.doc_discovery.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "dsn"
            mock_cfg.return_value.graph_url = "graph"
            mock_cfg.return_value.ingest_workers = 3
            # Must not raise when every file succeeds.
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1",
                             _pool_factory=_thread_pool_factory)

    def test_last_file_failure_is_also_surfaced(self):
        """A failure in the (unskipped) last file — not just the concurrent
        batch — must also be reported, not silently swallowed."""
        fnames = ["good1.csv", "bad_last.csv"]
        data = {"mentions": [], "tabular": [_tabular_plan(f) for f in fnames]}

        def fake_run_pipeline(**kwargs):
            if kwargs["dataset"] == "bad_last":
                raise RuntimeError("last file exploded")
            return {}

        with patch("aryx.pipeline.doc_discovery.run_pipeline", side_effect=fake_run_pipeline), \
             patch("aryx.pipeline.doc_discovery.relate_isolated"), \
             patch("aryx.pipeline.doc_discovery.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "dsn"
            mock_cfg.return_value.graph_url = "graph"
            mock_cfg.return_value.ingest_workers = 3
            try:
                ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1",
                             _pool_factory=_thread_pool_factory)
                assert False, "expected a RuntimeError"
            except RuntimeError as exc:
                assert "bad_last.csv" in str(exc)
                assert "last file exploded" in str(exc)

    def test_ingest_workers_setting_controls_pool_size(self):
        """ingest_confirmed's real (non-test-double) pool factory."""
        from concurrent.futures import ProcessPoolExecutor

        from aryx.pipeline.doc_discovery import _build_pool

        with _build_pool(7) as pool:
            assert isinstance(pool, ProcessPoolExecutor)
            assert pool._max_workers == 7

    def test_custom_pool_factory_receives_ingest_workers_setting(self):
        """ingest_confirmed() must call its pool factory with
        settings.ingest_workers, whatever factory is in play."""
        fnames = [f"f{i}.csv" for i in range(5)]
        data = {"mentions": [], "tabular": [_tabular_plan(f) for f in fnames]}
        seen_max_workers = []

        def spy_factory(max_workers):
            seen_max_workers.append(max_workers)
            return _thread_pool_factory(max_workers)

        with patch("aryx.pipeline.doc_discovery.run_pipeline", return_value={}), \
             patch("aryx.pipeline.doc_discovery.relate_isolated"), \
             patch("aryx.pipeline.doc_discovery.get_settings") as mock_cfg:
            mock_cfg.return_value.rdb_dsn = "dsn"
            mock_cfg.return_value.graph_url = "graph"
            mock_cfg.return_value.ingest_workers = 7
            ingest_confirmed(data, [], fnames, MagicMock(), _make_jobs(), "job1",
                             _pool_factory=spy_factory)

        assert seen_max_workers == [7]


class TestCrossProcessBudgetSharing:
    """Exercises _run_non_last_batch against a REAL ProcessPoolExecutor (via
    the real _build_pool default), not the ThreadPoolExecutor test double
    used above — this is the one code path (broker.governor.budgets /
    spend_snapshot / with_governor / replace_spend, wired together inside
    doc_discovery itself) that the ThreadPoolExecutor-injected tests above
    never touch, since they only ever hit the same-process `else` branch."""

    def test_charges_from_real_worker_processes_land_in_shared_budget(self):
        from aryx.broker import Broker
        from aryx.broker.governor import TokenGovernor
        from aryx.broker.registry import Registry
        from aryx.broker.secrets import EnvSecretProvider
        from aryx.pipeline.doc_discovery import _build_pool, _run_non_last_batch

        broker = Broker(Registry(), TokenGovernor({"cheap": 1_000_000}),
                        EnvSecretProvider(), {})
        non_last = [(f"f{i}.csv", _tabular_plan(f"f{i}.csv")) for i in range(6)]
        failures: list[str] = []

        with _build_pool(3) as pool:
            _run_non_last_batch(pool, non_last, None, broker, 1, failures,
                                _target=_charge_only)

        assert failures == []
        # If each worker had its own unshared copy of the governor (the bug
        # this fix closes), this would read {} or a partial total — every
        # charge landed in a private copy that vanished with its process.
        assert broker.governor.spend_snapshot() == {"cheap": 600}
