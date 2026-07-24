"""Regression tests for the isolated-nodes-on-CSV-ingest bug.

Root cause: _relate_isolated() — the only mechanism that guarantees zero
isolated entities in the graph — was gated behind the same `relate` flag as
the best-effort pairwise _relate() LLM stage, which is documented and
reproduced to stall on large payloads with no bounded timeout. When that
stage stalled (or ARYX_INGEST_RELATE was disabled to dodge the stall), the
safety net never ran and isolated nodes reappeared.

Fix: _relate_isolated() now runs unconditionally in run_pipeline() (it is
self-contained and a safe no-op when nothing is isolated), and both it and
_relate() bound their per-pair LLM waits via the shared _drain_with_timeout()
helper instead of blocking indefinitely on a stuck call.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from aryx.pipeline.enrich import _drain_with_timeout, _relate, _relate_isolated


# ── _drain_with_timeout: the shared bounded-wait primitive ──────────────────

def test_drain_with_timeout_abandons_a_stuck_future_without_blocking():
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        fast = pool.submit(lambda: "ok")
        stuck = pool.submit(time.sleep, 5)  # simulates a stalled LLM call
        futures = {fast: "fast-pair", stuck: "stuck-pair"}

        start = time.monotonic()
        results = list(_drain_with_timeout(futures, idle_timeout=0.3, label="test"))
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, "must abandon the stuck future, not wait out its full duration"
        assert [key for _fut, key in results] == ["fast-pair"]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def test_drain_with_timeout_yields_everything_when_nothing_stalls():
    pool = ThreadPoolExecutor(max_workers=3)
    try:
        futures = {pool.submit(lambda i=i: i): i for i in range(3)}
        results = list(_drain_with_timeout(futures, idle_timeout=2.0, label="test"))
        assert sorted(key for _fut, key in results) == [0, 1, 2]
    finally:
        pool.shutdown(wait=True)


# ── _relate(): must not hang the pipeline on one stuck pair ─────────────────

def _fake_store(entities):
    store = MagicMock()
    store.list_entities_typed_sample.return_value = entities
    return store


def test_relate_completes_and_skips_a_stuck_pair_instead_of_hanging(monkeypatch):
    monkeypatch.setenv("ARYX_RELATE_PAIR_TIMEOUT", "0.3")
    from aryx.config import get_settings
    get_settings.cache_clear()

    entities = [
        (1, "Customer", {"name": "Acme"}),
        (2, "Order", {"amount": "10"}),
    ]
    store = _fake_store(entities)

    def stuck_infer_relationship(*args, **kwargs):
        time.sleep(5)  # simulates the real-world stall observed in testing
        return "SHOULD_NOT_ARRIVE", 0.9

    with patch("aryx.pipeline.enrich.infer_relationship", side_effect=stuck_infer_relationship):
        start = time.monotonic()
        count = _relate(store, broker=MagicMock(), max_pairs=5)
        elapsed = time.monotonic() - start

    assert elapsed < 3.0, "a stuck relate pair must not block the ingest run"
    assert count == 0  # the stuck pair was abandoned, not counted as a relationship
    get_settings.cache_clear()


def test_relate_still_finds_relationships_when_llm_is_healthy(monkeypatch):
    monkeypatch.setenv("ARYX_RELATE_PAIR_TIMEOUT", "5")
    from aryx.config import get_settings
    get_settings.cache_clear()

    entities = [
        (1, "Customer", {"name": "Acme"}),
        (2, "Order", {"amount": "10"}),
    ]
    store = _fake_store(entities)

    with patch("aryx.pipeline.enrich.infer_relationship", return_value=("HAS_ORDER", 0.95)):
        count = _relate(store, broker=MagicMock(), max_pairs=5)

    assert count == 1
    store.save_relationships.assert_called_once()
    saved = store.save_relationships.call_args[0][0]
    assert saved[0].name == "HAS_ORDER"
    get_settings.cache_clear()


# ── _relate_isolated(): the safety net itself must not hang or crash ────────

def test_relate_isolated_skips_a_stuck_type_instead_of_hanging(monkeypatch):
    monkeypatch.setenv("ARYX_RELATE_PAIR_TIMEOUT", "0.3")
    from aryx.config import get_settings
    get_settings.cache_clear()

    store = MagicMock()
    store.list_isolated_entities.return_value = [(3, "Invoice", {"num": "INV-1"})]
    store.list_entities_typed_sample.return_value = [
        (1, "Customer", {"name": "Acme"}),
        (3, "Invoice", {"num": "INV-1"}),
    ]

    with patch("aryx.pipeline.enrich.infer_relationship", side_effect=lambda *a: (_ for _ in ()).throw(TimeoutError)):
        start = time.monotonic()
        count = _relate_isolated(store, broker=MagicMock())
        elapsed = time.monotonic() - start

    assert elapsed < 2.0
    assert count == 0
    get_settings.cache_clear()


def test_relate_isolated_is_noop_when_nothing_is_isolated():
    store = MagicMock()
    store.list_isolated_entities.return_value = []
    store.list_entities_typed_sample.return_value = [
        (1, "Customer", {"name": "Acme"}), (2, "Order", {"amount": "10"}),
    ]
    assert _relate_isolated(store, broker=MagicMock()) == 0


# ── orchestrate.run_pipeline: the safety net must fire even when relate=False ──

def test_relate_isolated_runs_even_when_relate_flag_is_false():
    """The actual regression: previously `if relate and not runner.skip(...)`
    meant disabling ARYX_INGEST_RELATE (or a stalled _relate() pass) silently
    skipped the only mechanism guaranteeing zero isolated nodes."""
    mock_runner = MagicMock()
    mock_runner.skip.return_value = False
    mock_cfg = MagicMock()
    mock_cfg.rdb_dsn = "postgresql://x"
    mock_cfg.graph_url = "redis://x"
    mock_cfg.rules_db_warn_threshold = 20
    mock_cfg.max_relate_pairs = 5

    with patch("aryx.pipeline.orchestrate.get_settings", return_value=mock_cfg), \
         patch("aryx.pipeline.orchestrate._relate") as mock_relate, \
         patch("aryx.pipeline.orchestrate._relate_isolated", return_value=0) as mock_relate_isolated, \
         patch("aryx.pipeline.orchestrate.discover", return_value=1), \
         patch("aryx.pipeline.orchestrate.resolve_run", return_value=5), \
         patch("aryx.pipeline.orchestrate.project_graph", return_value={}), \
         patch("aryx.pipeline.orchestrate.StageRunner", return_value=mock_runner), \
         patch("aryx.pipeline.orchestrate.StageTracker"), \
         patch("aryx.pipeline.orchestrate.PostgresStore"), \
         patch("aryx.pipeline.orchestrate.EntityStore"), \
         patch("aryx.pipeline.orchestrate.FalkorStore"), \
         patch("aryx.pipeline.orchestrate.OntologyStore"), \
         patch("aryx.pipeline.orchestrate._build_type_ancestors", return_value={}), \
         patch("aryx.workspaces.ws_graph", return_value="ws_1"):
        from aryx.pipeline.orchestrate import run_pipeline
        run_pipeline(
            connector=MagicMock(), dsn="postgresql://x",
            system="sys", dataset="ds", ontology_type="T",
            match_keys=["name"], graph_url="redis://x",
            broker=MagicMock(), relate=False,  # ARYX_INGEST_RELATE=false / disabled
        )

    mock_relate.assert_not_called()  # best-effort stage correctly skipped
    mock_relate_isolated.assert_called_once()  # safety net still runs


def test_done_progress_reports_real_entity_count_not_always_zero():
    """Regression: the "Done" progress message read counts.get("vertices", 0),
    a key project_graph() never returns (it returns entities/provenance/
    relationships), so it always reported "0 graph nodes" even when the
    graph was populated correctly. It must now read the real "entities" key."""
    mock_runner = MagicMock()
    mock_runner.skip.return_value = False
    mock_cfg = MagicMock()
    mock_cfg.rdb_dsn = "postgresql://x"
    mock_cfg.graph_url = "redis://x"
    mock_cfg.rules_db_warn_threshold = 20
    mock_cfg.max_relate_pairs = 5

    progress_messages = []

    def on_progress(stage, pct, detail):
        progress_messages.append((stage, detail))

    with patch("aryx.pipeline.orchestrate.get_settings", return_value=mock_cfg), \
         patch("aryx.pipeline.orchestrate._relate_isolated", return_value=0), \
         patch("aryx.pipeline.orchestrate.discover", return_value=1), \
         patch("aryx.pipeline.orchestrate.resolve_run", return_value=5), \
         patch("aryx.pipeline.orchestrate.project_graph",
               return_value={"entities": 1, "provenance": 32, "relationships": 0}), \
         patch("aryx.pipeline.orchestrate.StageRunner", return_value=mock_runner), \
         patch("aryx.pipeline.orchestrate.StageTracker"), \
         patch("aryx.pipeline.orchestrate.PostgresStore"), \
         patch("aryx.pipeline.orchestrate.EntityStore"), \
         patch("aryx.pipeline.orchestrate.FalkorStore"), \
         patch("aryx.pipeline.orchestrate.OntologyStore"), \
         patch("aryx.pipeline.orchestrate._build_type_ancestors", return_value={}), \
         patch("aryx.workspaces.ws_graph", return_value="ws_1"):
        from aryx.pipeline.orchestrate import run_pipeline
        run_pipeline(
            connector=MagicMock(), dsn="postgresql://x",
            system="sys", dataset="ds", ontology_type="T",
            match_keys=["name"], graph_url="redis://x",
            broker=MagicMock(), relate=False, on_progress=on_progress,
        )

    done_detail = dict(progress_messages)["Done"]
    assert "0 graph nodes" not in done_detail
    assert "1 graph nodes" in done_detail
