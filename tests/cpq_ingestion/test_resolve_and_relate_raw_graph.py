"""resolve_and_relate_raw_graph -- the orchestration piece wiring together
RawGraphConnector, match-key inference, and containment-edge translation:
one resolve-only run_pipeline() call per XML tag, then a single containment
relate + one final project_workspace_graph() call.

run_pipeline/EntityStore/project_workspace_graph are mocked (real DB calls
are covered by the live integration suite, test_pipeline_integration.py);
group_nodes_by_tag/infer_match_keys_for_tag/translate_containment_edges run
for real, since they're pure and already independently tested.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq.catalog_naming import _catalog_prefix
from aryx.cpq_ingestion.raw_graph.resolve_relate import resolve_and_relate_raw_graph
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode
from aryx.pipeline.doc_discovery.doc_discovery_types import _stem_type
from aryx.pipeline.orchestrate import PipelineCancelled

WORKSPACE_ID = 879
DSN = "postgresql://unused"
GRAPH_URL = "redis://unused"
BROKER = MagicMock()


@pytest.fixture(autouse=True)
def _no_real_llm_calls():
    """LineItem's "Sku" property isn't id-like by default, so match-key
    inference falls through to the LLM path -- never let that reach a real
    network call in these orchestration tests (match_key_inference.py's own
    tests already cover the heuristic/LLM/default logic in isolation)."""
    with patch("aryx.cpq_ingestion.raw_graph.match_key_inference.llm_runtime.chat",
               side_effect=RuntimeError("no LLM in orchestration tests")):
        yield


def _projection() -> RawGraphProjection:
    """PurchaseOrder(0) -CONTAINS-> Customer(1); PurchaseOrder(0) -CONTAINS-> LineItem(2)."""
    return RawGraphProjection(
        nodes=[
            RawNode(id=0, tag="PurchaseOrder", properties={"Id": "PO-1001"}),
            RawNode(id=1, tag="Customer", properties={"Id": "C-42"}),
            RawNode(id=2, tag="LineItem", properties={"Sku": "WIDGET-A"}),
        ],
        edges=[
            RawEdge(source_id=0, target_id=1, name="CONTAINS"),
            RawEdge(source_id=0, target_id=2, name="CONTAINS"),
        ],
    )


def _mock_estore(entity_ids_by_run_side_effect):
    mock_estore = MagicMock()
    mock_estore.entity_ids_by_run.side_effect = entity_ids_by_run_side_effect
    return mock_estore


def test_empty_projection_returns_zero_summary_without_touching_the_db():
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore") as mock_estore_cls, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline:
        result = resolve_and_relate_raw_graph(
            RawGraphProjection(nodes=[], edges=[]),
            workspace_id=WORKSPACE_ID, source_key="f", dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    mock_estore_cls.assert_not_called()
    mock_run_pipeline.assert_not_called()
    assert result == {"tags": 0, "entities": 0, "relationships": 0}


def test_runs_one_resolve_only_pipeline_call_per_distinct_tag():
    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={"entities": 0}):
        mock_run_pipeline.return_value = {"run_id": 1, "entities": 1, "relationships": 0}
        resolve_and_relate_raw_graph(
            _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    assert mock_run_pipeline.call_count == 3  # PurchaseOrder, Customer, LineItem
    for c in mock_run_pipeline.call_args_list:
        assert c.kwargs["relate"] is False
        assert c.kwargs["skip_graph"] is True
        assert c.kwargs["workspace_id"] == WORKSPACE_ID
        assert c.kwargs["dsn"] == DSN
        assert c.kwargs["graph_url"] == GRAPH_URL


def test_ontology_type_and_match_keys_are_inferred_per_tag():
    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        mock_run_pipeline.return_value = {"run_id": 1, "entities": 1, "relationships": 0}
        resolve_and_relate_raw_graph(
            _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    # ontology_type is no longer the raw tag verbatim -- resolve_relate.py
    # derives it via _stem_type(f"{source_key}_{tag}") for naming parity with
    # the old CSV pipeline (see that call site's comment). Compute the
    # expected value the same way rather than hardcoding a second copy of the
    # transform, so this test can't silently drift from the implementation.
    calls_by_dataset = {c.kwargs["dataset"]: c.kwargs for c in mock_run_pipeline.call_args_list}
    assert calls_by_dataset["PurchaseOrder"]["ontology_type"] == _stem_type("po_file_PurchaseOrder")
    assert calls_by_dataset["PurchaseOrder"]["match_keys"] == ["Id"]
    assert calls_by_dataset["Customer"]["ontology_type"] == _stem_type("po_file_Customer")
    assert calls_by_dataset["Customer"]["match_keys"] == ["Id"]
    # LineItem's "Sku" isn't id-like by default -- falls back to LLM, which
    # isn't mocked here, so it degrades to the default (first property key).
    assert calls_by_dataset["LineItem"]["ontology_type"] == _stem_type("po_file_LineItem")
    assert calls_by_dataset["LineItem"]["match_keys"] == ["Sku"]


def test_ontology_type_naming_matches_old_csv_pipelines_catalog_prefix_shape():
    """The actual regression this covers: the Ask feature's _catalog_prefix()
    must be able to parse a real prefix back out of a raw-graph-ingested
    workspace's ontology types, the same way it already does for the old
    CSV-ingestion pipeline's PascalCase "{Stem}Bm{Tag}" types -- otherwise
    list_ingested_families() (and every other _catalog_prefix() consumer)
    silently sees nothing ingested, even though real curated data exists
    (confirmed live against workspace 1084, "quote for SVX")."""
    mock_estore = _mock_estore(lambda run_id: {})
    projection = RawGraphProjection(
        nodes=[RawNode(id=0, tag="bm_prd_family", properties={"name": "SVX Video"})],
        edges=[],
    )
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        mock_run_pipeline.return_value = {"run_id": 1, "entities": 1, "relationships": 0}
        resolve_and_relate_raw_graph(
            projection, workspace_id=WORKSPACE_ID, source_key="ApxNextConfig",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    ontology_type = mock_run_pipeline.call_args.kwargs["ontology_type"]
    # _stem_type title-cases each "_"-separated word (lowercasing interior
    # caps the same way str.title() always does), so "ApxNextConfig" ->
    # "Apxnextconfig" -- not a perfect re-derivation of the original filename,
    # but it IS byte-identical to what the old CSV pipeline would have
    # produced for the same source_key, which is the actual contract here.
    assert _catalog_prefix(ontology_type) == "Apxnextconfig"


def test_dotted_source_key_does_not_collapse_the_tag_into_the_stem():
    """PR #435 review, High: _stem_type does Path(filename).stem, which
    strips everything after the LAST "." in the string. The old CSV
    pipeline's input was always "{stem}_{tag}.csv", so .stem only ever ate
    the ".csv" extension -- a source filename containing its own dot (a
    version number, a date) never lost anything. Passing f"{source_key}_
    {tag}" with no extension strips at THAT dot instead, eating part of
    the tag and collapsing every tag in that file onto one ontology_type.
    Compares resolve_relate.py's actual derivation directly against the
    OLD pipeline's own form (_stem_type(f"{stem}_{tag}.csv")) for a
    dotted source_key -- the two must match byte-for-byte."""
    mock_estore = _mock_estore(lambda run_id: {})
    source_key = "export_2026.10.05"
    projection = RawGraphProjection(
        nodes=[
            RawNode(id=0, tag="bm_prd_family", properties={"name": "x"}),
            RawNode(id=1, tag="bm_catalog", properties={"name": "y"}),
        ],
        edges=[],
    )
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        mock_run_pipeline.return_value = {"run_id": 1, "entities": 1, "relationships": 0}
        resolve_and_relate_raw_graph(
            projection, workspace_id=WORKSPACE_ID, source_key=source_key,
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    ontology_types = {c.kwargs["dataset"]: c.kwargs["ontology_type"] for c in mock_run_pipeline.call_args_list}
    assert ontology_types["bm_prd_family"] == _stem_type(f"{source_key}_bm_prd_family.csv")
    assert ontology_types["bm_catalog"] == _stem_type(f"{source_key}_bm_catalog.csv")
    # The actual failure mode this guards against: without the ".csv", both
    # tags collapse onto the SAME wrong name ("Export2026.10").
    assert ontology_types["bm_prd_family"] != ontology_types["bm_catalog"]
    assert _catalog_prefix(ontology_types["bm_prd_family"]) == _catalog_prefix(ontology_types["bm_catalog"])


def test_builds_node_id_to_entity_id_map_and_translates_containment_edges():
    run_ids_by_tag = {"PurchaseOrder": 10, "Customer": 11, "LineItem": 12}
    entity_maps = {
        10: {"po_file:0": 200},
        11: {"po_file:1": 100},
        12: {"po_file:2": 300},
    }

    def _run_pipeline(**kwargs):
        run_id = run_ids_by_tag[kwargs["dataset"]]
        return {"run_id": run_id, "entities": 1, "relationships": 0}

    mock_estore = _mock_estore(lambda run_id: entity_maps[run_id])
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline", side_effect=_run_pipeline), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={"entities": 3}):
        result = resolve_and_relate_raw_graph(
            _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    mock_estore.save_relationships.assert_called_once()
    [saved] = mock_estore.save_relationships.call_args.args
    pairs = {(r.source_entity_id, r.target_entity_id) for r in saved}
    assert pairs == {(200, 100), (200, 300)}
    assert result["relationships"] == 2
    assert result["tags"] == 3
    assert result["entities"] == 3


def test_on_progress_forwarded_into_save_relationships_and_project_workspace_graph():
    """PR review, 2026-10-04: neither call previously received on_progress
    at all, leaving the post-tag-loop phase (containment-edge translation,
    saving relationships, final graph projection) with no heartbeat -- long
    enough, combined with §0's heartbeat-sweep watchdog, to get a healthy
    job killed. Both already support on_progress internally; this pins
    that the call sites actually pass it through now."""
    run_ids_by_tag = {"PurchaseOrder": 10, "Customer": 11, "LineItem": 12}
    entity_maps = {
        10: {"po_file:0": 200}, 11: {"po_file:1": 100}, 12: {"po_file:2": 300},
    }
    on_progress = MagicMock()

    def _run_pipeline(**kwargs):
        run_id = run_ids_by_tag[kwargs["dataset"]]
        return {"run_id": run_id, "entities": 1, "relationships": 0}

    mock_estore = _mock_estore(lambda run_id: entity_maps[run_id])
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline", side_effect=_run_pipeline), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph",
               return_value={"entities": 3}) as mock_project:
        resolve_and_relate_raw_graph(
            _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, on_progress=on_progress,
        )

    _, save_kwargs = mock_estore.save_relationships.call_args
    assert save_kwargs["on_progress"] is on_progress
    _, project_kwargs = mock_project.call_args
    assert project_kwargs["on_progress"] is on_progress


def test_calls_project_workspace_graph_once_and_merges_its_counts():
    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 1, "entities": 0, "relationships": 0}), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph",
               return_value={"entities": 5, "relationships": 4}) as mock_project:
        result = resolve_and_relate_raw_graph(
            _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    # on_progress=None here since this test's caller doesn't pass one --
    # see test_project_workspace_graph_receives_on_progress below for the
    # PR-review fix (heartbeat coverage for the final projection).
    mock_project.assert_called_once_with(DSN, GRAPH_URL, WORKSPACE_ID, mock_estore,
                                         on_progress=None)
    assert result["entities"] == 5
    assert result["relationships"] == 4


def test_estore_closed_even_when_run_pipeline_raises():
    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline", side_effect=RuntimeError("boom")):
        try:
            resolve_and_relate_raw_graph(
                _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
                dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
            )
        except RuntimeError:
            pass

    mock_estore.close.assert_called_once()


# ── should_stop cancellation (PR #425-style, this confirm path previously
# had none at all) ───────────────────────────────────────────────────────

def test_should_stop_true_before_any_tag_raises_before_run_pipeline():
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore") as mock_estore_cls, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph") as mock_project:
        mock_estore_cls.return_value = _mock_estore(lambda run_id: {})
        with pytest.raises(PipelineCancelled):
            resolve_and_relate_raw_graph(
                _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
                dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, should_stop=lambda: True,
            )

    mock_run_pipeline.assert_not_called()
    mock_project.assert_not_called()


def test_should_stop_after_first_tag_stops_before_second_tag_and_projection():
    calls = {"n": 0}

    def _should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # False on the pre-first-tag check, True after

    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 1, "entities": 1, "relationships": 0}) as mock_run_pipeline, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph") as mock_project:
        with pytest.raises(PipelineCancelled):
            resolve_and_relate_raw_graph(
                _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
                dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, should_stop=_should_stop,
            )

    mock_run_pipeline.assert_called_once()  # only the first tag ran
    mock_project.assert_not_called()  # projection never reached
    mock_estore.close.assert_called_once()  # finally still runs on cancel


def test_cancel_mid_loop_deletes_entities_from_already_resolved_tags():
    """PR #429 review M1: a mid-loop cancel must delete the orphaned
    entities from tags that already resolved in THIS attempt -- otherwise
    they have no relationships yet (those are saved once, after the whole
    loop) and surface as permanent isolated nodes once project_workspace_
    graph next rebuilds the graph from the DB."""
    calls = {"n": 0}

    def _should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # False on the pre-first-tag check, True after

    # PurchaseOrder's tag resolves to run_id=10, whose one node (id 0) maps
    # to entity_id 500 -- this is what must get deleted on cancel.
    mock_estore = _mock_estore(lambda run_id: {"po_file:0": 500} if run_id == 10 else {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 10, "entities": 1, "relationships": 0}), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph") as mock_project:
        mock_estore.delete_entities.return_value = 1
        with pytest.raises(PipelineCancelled):
            resolve_and_relate_raw_graph(
                _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
                dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, should_stop=_should_stop,
            )

    mock_estore.delete_entities.assert_called_once_with([500])
    mock_project.assert_not_called()
    mock_estore.save_relationships.assert_not_called()  # never reached -- no relationships to orphan


def test_cancel_from_inside_run_pipeline_also_cleans_up_the_in_flight_tag():
    """PR #429 review M1/N1 (round 2): run_pipeline()'s own should_stop
    checks (orchestrate.py's "relate" checkpoint) can raise PipelineCancelled
    from INSIDE a tag's run_pipeline call, AFTER that tag's own entities are
    already saved (relate fires right after resolve_cluster) -- this is the
    most likely real-world cancellation point. orchestrate.py's
    _check_cancelled now attaches that tag's run_id onto the exception, so
    the except block here can look up and delete ITS entities too, not just
    the already-completed PurchaseOrder tag's -- previously the in-flight
    tag's entities were left behind entirely."""
    def _run_pipeline_side_effect(**kwargs):
        if kwargs["dataset"] == "PurchaseOrder":
            return {"run_id": 10, "entities": 1, "relationships": 0}
        # Customer: cancelled after resolve_cluster already saved its
        # entity -- run_id=11 is attached, same as the real
        # _check_cancelled(should_stop, "relate", run_id=run_id) does.
        raise PipelineCancelled("cancelled inside run_pipeline for Customer", run_id=11)

    entities_by_run = {10: {"po_file:0": 500}, 11: {"po_file:1": 600}}
    # should_stop itself never reports True -- the cancellation comes
    # entirely from inside run_pipeline, proving the pre-tag check alone
    # would have missed it.
    mock_estore = _mock_estore(lambda run_id: entities_by_run.get(run_id, {}))
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               side_effect=_run_pipeline_side_effect), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph") as mock_project:
        mock_estore.delete_entities.return_value = 2
        with pytest.raises(PipelineCancelled):
            resolve_and_relate_raw_graph(
                _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
                dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, should_stop=lambda: False,
            )

    # Both the already-completed PurchaseOrder entity (500) AND the
    # in-flight Customer entity (600) must be cleaned up.
    mock_estore.delete_entities.assert_called_once_with([500, 600])
    mock_project.assert_not_called()


def test_cancel_with_no_run_id_on_the_exception_only_cleans_up_completed_tags():
    """The explicit should_stop() check at the top of the loop raises
    PipelineCancelled with no run_id (nothing is in flight at that point) --
    must behave exactly as before: only already-completed tags' entities
    are cleaned up, no lookup attempted for a nonexistent in-flight run."""
    calls = {"n": 0}

    def _should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    mock_estore = _mock_estore(lambda run_id: {"po_file:0": 500} if run_id == 10 else {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 10, "entities": 1, "relationships": 0}), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph") as mock_project:
        mock_estore.delete_entities.return_value = 1
        with pytest.raises(PipelineCancelled):
            resolve_and_relate_raw_graph(
                _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
                dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, should_stop=_should_stop,
            )

    mock_estore.delete_entities.assert_called_once_with([500])
    mock_project.assert_not_called()


def test_in_flight_run_id_lookup_failure_still_cleans_up_completed_tags():
    """A DB hiccup looking up the in-flight tag's entities must not block
    cleaning up the tags that already fully completed, and must not mask
    the cancellation."""
    def _run_pipeline_side_effect(**kwargs):
        if kwargs["dataset"] == "PurchaseOrder":
            return {"run_id": 10, "entities": 1, "relationships": 0}
        raise PipelineCancelled("cancelled inside run_pipeline for Customer", run_id=11)

    def _entity_ids_by_run(run_id):
        if run_id == 10:
            return {"po_file:0": 500}
        raise RuntimeError("db down")

    mock_estore = _mock_estore(_entity_ids_by_run)
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               side_effect=_run_pipeline_side_effect):
        mock_estore.delete_entities.return_value = 1
        with pytest.raises(PipelineCancelled):
            resolve_and_relate_raw_graph(
                _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
                dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, should_stop=lambda: False,
            )

    # PurchaseOrder's entity still gets cleaned up despite the failed
    # lookup for Customer's in-flight run_id.
    mock_estore.delete_entities.assert_called_once_with([500])


def test_cancel_before_any_tag_has_nothing_to_clean_up():
    """should_stop=True on the very first (pre-first-tag) check means no
    entities exist yet -- cleanup must be a no-op, not an error."""
    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline:
        with pytest.raises(PipelineCancelled):
            resolve_and_relate_raw_graph(
                _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
                dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, should_stop=lambda: True,
            )

    mock_run_pipeline.assert_not_called()
    mock_estore.delete_entities.assert_not_called()


def test_cleanup_failure_is_logged_and_does_not_mask_the_cancellation():
    """A DB hiccup while deleting orphans must not hide the cancel itself
    behind a different exception -- PipelineCancelled still propagates."""
    mock_estore = _mock_estore(lambda run_id: {"po_file:0": 500})
    mock_estore.delete_entities.side_effect = RuntimeError("db unreachable")
    calls = {"n": 0}

    def _should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 10, "entities": 1, "relationships": 0}):
        with pytest.raises(PipelineCancelled):
            resolve_and_relate_raw_graph(
                _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
                dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, should_stop=_should_stop,
            )


def test_should_stop_is_forwarded_into_every_run_pipeline_call():
    def _never_stop() -> bool:
        return False

    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        mock_run_pipeline.return_value = {"run_id": 1, "entities": 1, "relationships": 0}
        resolve_and_relate_raw_graph(
            _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER, should_stop=_never_stop,
        )

    assert mock_run_pipeline.call_count == 3
    for c in mock_run_pipeline.call_args_list:
        assert c.kwargs["should_stop"] is _never_stop


def test_default_should_stop_none_behaves_exactly_as_before():
    """Regression guard: omitting should_stop entirely (every pre-existing
    caller) must behave identically to the pre-cancellation-support code."""
    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 1, "entities": 1, "relationships": 0}) as mock_run_pipeline, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph",
               return_value={"entities": 3}) as mock_project:
        result = resolve_and_relate_raw_graph(
            _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    assert mock_run_pipeline.call_count == 3
    for c in mock_run_pipeline.call_args_list:
        assert c.kwargs["should_stop"] is None
    mock_project.assert_called_once()
    assert result["tags"] == 3


def test_no_relationships_saved_when_no_edges_resolve():
    mock_estore = _mock_estore(lambda run_id: {})  # nothing ever resolves
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 1, "entities": 0, "relationships": 0}), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        result = resolve_and_relate_raw_graph(
            _projection(), workspace_id=WORKSPACE_ID, source_key="po_file",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    mock_estore.save_relationships.assert_not_called()
    assert result["relationships"] == 0


# ── xml_bytes / streaming path (§3b, 2026-10-04) ─────────────────────────────

XML_EQUIVALENT_TO_PROJECTION = (
    b'<PurchaseOrder Id="PO-1001">'
    b'<Customer Id="C-42"/>'
    b'<LineItem Sku="WIDGET-A"/>'
    b'</PurchaseOrder>'
)


def _settings_stub(**overrides):
    base = dict(
        cpq_structural_leaf_fold_enabled=True,
        cpq_locale_wrapper_fold_enabled=True,
        cpq_force_exact_enabled=True,
        cpq_streaming_projection_enabled=False,
    )
    base.update(overrides)
    return MagicMock(**base)


def test_projection_and_xml_bytes_both_given_raises():
    with pytest.raises(ValueError):
        resolve_and_relate_raw_graph(
            _projection(), xml_bytes=XML_EQUIVALENT_TO_PROJECTION,
            workspace_id=WORKSPACE_ID, source_key="f", dsn=DSN,
            graph_url=GRAPH_URL, broker=BROKER,
        )


def test_neither_projection_nor_xml_bytes_given_raises():
    with pytest.raises(ValueError):
        resolve_and_relate_raw_graph(
            workspace_id=WORKSPACE_ID, source_key="f", dsn=DSN,
            graph_url=GRAPH_URL, broker=BROKER,
        )


def test_xml_bytes_with_streaming_disabled_falls_back_to_eager_path():
    """Default (flag off): xml_bytes still works, but via
    project_xml_to_raw_graph -- not the streaming generator. should_stop
    must still reach the parse itself (PR #429 review: the full parse runs
    before resolve_and_relate_raw_graph's own per-tag checks can help, so
    it needs should_stop too, regardless of which path builds by_tag --
    this moved here, from doc_discovery.py's own direct call, in §3b)."""
    mock_estore = _mock_estore(lambda run_id: {})
    should_stop = lambda: False  # noqa: E731
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.get_settings",
               return_value=_settings_stub(cpq_streaming_projection_enabled=False)), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_xml_to_raw_graph") as mock_eager, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.iter_raw_graph") as mock_stream, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 1, "entities": 1, "relationships": 0}), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        mock_eager.return_value = _projection()
        resolve_and_relate_raw_graph(
            xml_bytes=XML_EQUIVALENT_TO_PROJECTION,
            workspace_id=WORKSPACE_ID, source_key="f", dsn=DSN,
            graph_url=GRAPH_URL, broker=BROKER, should_stop=should_stop,
        )

    mock_eager.assert_called_once()
    mock_stream.assert_not_called()
    _, eager_kwargs = mock_eager.call_args
    assert eager_kwargs["should_stop"] is should_stop


def test_xml_bytes_with_streaming_enabled_uses_the_generator_not_the_eager_path():
    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.get_settings",
               return_value=_settings_stub(cpq_streaming_projection_enabled=True)), \
         patch("aryx.csv_bml_ingestion.config.csv_bml_enabled", return_value=False), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_xml_to_raw_graph") as mock_eager, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        mock_run_pipeline.return_value = {"run_id": 1, "entities": 1, "relationships": 0}
        result = resolve_and_relate_raw_graph(
            xml_bytes=XML_EQUIVALENT_TO_PROJECTION,
            workspace_id=WORKSPACE_ID, source_key="f", dsn=DSN,
            graph_url=GRAPH_URL, broker=BROKER,
        )

    mock_eager.assert_not_called()
    # Same 3 tags as the eager _projection() fixture -- one resolve-only
    # run_pipeline call each, proving the streaming grouping is equivalent.
    assert mock_run_pipeline.call_count == 3
    tags = {c.kwargs["dataset"] for c in mock_run_pipeline.call_args_list}
    assert tags == {"PurchaseOrder", "Customer", "LineItem"}
    assert result["tags"] == 3


def test_xml_bytes_streaming_forwards_should_stop_into_iter_raw_graph():
    should_stop = lambda: False  # noqa: E731
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.get_settings",
               return_value=_settings_stub(cpq_streaming_projection_enabled=True)), \
         patch("aryx.csv_bml_ingestion.config.csv_bml_enabled", return_value=False), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.iter_raw_graph",
               return_value=iter(())) as mock_stream, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore"), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline"):
        resolve_and_relate_raw_graph(
            xml_bytes=XML_EQUIVALENT_TO_PROJECTION,
            workspace_id=WORKSPACE_ID, source_key="f", dsn=DSN,
            graph_url=GRAPH_URL, broker=BROKER, should_stop=should_stop,
        )

    _, kwargs = mock_stream.call_args
    assert kwargs["should_stop"] is should_stop


def test_xml_bytes_streaming_falls_back_to_eager_when_bml_enabled():
    """ARYX_CSV_BML_ENABLED's query-table enrichment has no streaming
    equivalent -- correctness over memory savings when both are on."""
    mock_estore = _mock_estore(lambda run_id: {})
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.get_settings",
               return_value=_settings_stub(cpq_streaming_projection_enabled=True)), \
         patch("aryx.csv_bml_ingestion.config.csv_bml_enabled", return_value=True), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore", return_value=mock_estore), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_xml_to_raw_graph") as mock_eager, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.iter_raw_graph") as mock_stream, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 1, "entities": 1, "relationships": 0}), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        mock_eager.return_value = _projection()
        resolve_and_relate_raw_graph(
            xml_bytes=XML_EQUIVALENT_TO_PROJECTION,
            workspace_id=WORKSPACE_ID, source_key="f", dsn=DSN,
            graph_url=GRAPH_URL, broker=BROKER,
        )

    mock_eager.assert_called_once()
    mock_stream.assert_not_called()


def test_xml_bytes_streaming_empty_generator_returns_zero_summary():
    """No realistic XML document parses to zero nodes (even an empty root
    element is one node) -- this exercises the defensive by_tag-empty
    branch directly by mocking iter_raw_graph to yield nothing, the same
    way test_empty_projection_returns_zero_summary_without_touching_the_db
    exercises the eager path's equivalent branch with an explicitly empty
    RawGraphProjection."""
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.get_settings",
               return_value=_settings_stub(cpq_streaming_projection_enabled=True)), \
         patch("aryx.csv_bml_ingestion.config.csv_bml_enabled", return_value=False), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.iter_raw_graph", return_value=iter(())), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore") as mock_estore_cls, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline") as mock_run_pipeline:
        result = resolve_and_relate_raw_graph(
            xml_bytes=XML_EQUIVALENT_TO_PROJECTION,
            workspace_id=WORKSPACE_ID, source_key="f", dsn=DSN,
            graph_url=GRAPH_URL, broker=BROKER,
        )

    mock_estore_cls.assert_not_called()
    mock_run_pipeline.assert_not_called()
    assert result == {"tags": 0, "entities": 0, "relationships": 0}


def test_xml_bytes_streaming_restores_id_order_for_self_nesting_tags():
    """PR review N2 (2026-10-04): iter_raw_graph yields in finish
    (post-)order -- fine for sibling order (preserved either way), but a
    tag that recurs at more than one nesting depth in the SAME document
    (e.g. this self-nesting <Category> tree) comes out child-before-parent
    in post-order, while the eager path's id-ordered projection.nodes
    always has the parent (lower id, started first) before the child
    (higher id, started later). The equivalence tests above all use flat
    or differently-tagged nesting, so none of them exercise this. Uses the
    REAL iter_raw_graph (not mocked) against real nested XML, capturing
    RawGraphConnector's own `nodes` argument -- the actual list order
    run_pipeline's connector would see."""
    nested_xml = (
        b'<Root>'
        b'<Category Id="outer">'
        b'<Category Id="inner"/>'
        b'</Category>'
        b'</Root>'
    )
    captured_nodes: dict[str, list] = {}

    class _CaptureConnector:
        def __init__(self, nodes, *, tag, source_key):
            captured_nodes[tag] = nodes

    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.get_settings",
               return_value=_settings_stub(cpq_streaming_projection_enabled=True,
                                           cpq_structural_leaf_fold_enabled=False)), \
         patch("aryx.csv_bml_ingestion.config.csv_bml_enabled", return_value=False), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.RawGraphConnector", _CaptureConnector), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore"), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 1, "entities": 0, "relationships": 0}), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        resolve_and_relate_raw_graph(
            xml_bytes=nested_xml, workspace_id=WORKSPACE_ID, source_key="f",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )

    # outer started first (lower id) -- must come before inner regardless
    # of which one's subtree FINISHED first during the streaming walk.
    category_ids = [n.properties["Id"] for n in captured_nodes["Category"]]
    assert category_ids == ["outer", "inner"]


# ── PR review round 7: structural-leaf fold's effect on real resolve shape ───

# A plain entity-like tag (<Customer>Bob</Customer> -- text only, no
# attributes, no children) and an empty container (<Lines/>) alongside a
# tag that must survive folding either way (<LineItem Sku="..."/> has a
# real attribute). Exercises the REAL project_xml_to_raw_graph ->
# group_nodes_by_tag -> fold_structural_leaf_tags chain (only run_pipeline/
# EntityStore/project_workspace_graph are mocked) -- unlike
# tests/cpq_ingestion/test_structural_leaf.py's unit tests, which construct
# by_tag/edges by hand and never go through a real resolve_and_relate_raw_
# graph call, so neither suite previously confirmed what the flag actually
# does to the SET OF TAGS this function resolves (PR review round 7, High:
# "no test compares entity/relationship counts with the fold on vs off or
# covers an entity-like tag or an empty container").
_FOLD_TEST_XML = (
    b'<PurchaseOrder Id="PO-1">'
    b'<Customer>Bob</Customer>'
    b'<Lines></Lines>'
    b'<LineItem Sku="WIDGET-A"/>'
    b'</PurchaseOrder>'
)


def _run_fold_test_xml(*, fold_enabled: bool):
    captured_nodes: dict[str, list] = {}

    class _CaptureConnector:
        def __init__(self, nodes, *, tag, source_key):
            captured_nodes[tag] = nodes

    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.get_settings",
               return_value=_settings_stub(cpq_structural_leaf_fold_enabled=fold_enabled)), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.RawGraphConnector", _CaptureConnector), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore") as mock_estore_cls, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 1, "entities": 1, "relationships": 0}), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        mock_estore_cls.return_value = _mock_estore(lambda run_id: {})
        result = resolve_and_relate_raw_graph(
            xml_bytes=_FOLD_TEST_XML, workspace_id=WORKSPACE_ID, source_key="f",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )
    return result, captured_nodes


def test_structural_leaf_fold_enabled_drops_entity_like_and_empty_container_tags():
    """Customer (entity-like, text-only) and Lines (empty container) both
    fold onto PurchaseOrder and are never resolved as their own tag/entity
    type when the flag is on -- only PurchaseOrder and LineItem remain."""
    result, captured_nodes = _run_fold_test_xml(fold_enabled=True)

    assert set(captured_nodes) == {"PurchaseOrder", "LineItem"}
    assert result["tags"] == 2
    po_node = captured_nodes["PurchaseOrder"][0]
    assert po_node.properties["Customer"] == "Bob"
    assert po_node.properties["Lines"] == ""


def test_structural_leaf_fold_disabled_keeps_every_tag_as_its_own_entity_type():
    """Same document, flag off: Customer and Lines each resolve as their
    own tag/entity type instead of being folded onto PurchaseOrder --
    confirms the flag is actually load-bearing for tag/entity COUNT, not
    just a cosmetic no-op in this shape of document."""
    result, captured_nodes = _run_fold_test_xml(fold_enabled=False)

    assert set(captured_nodes) == {"PurchaseOrder", "Customer", "Lines", "LineItem"}
    assert result["tags"] == 4
    po_node = captured_nodes["PurchaseOrder"][0]
    assert "Customer" not in po_node.properties
    assert "Lines" not in po_node.properties


# ── locale-wrapper fold + display fields (CPQ_XML_DISPLAY_NAMES_PLAN_2026-10-05) ──
# Real Oracle CPQ shape, confirmed live on workspace 1126: the family's human
# name lives in <label><en>, its variable name in a scalar leaf child.
_CPQ_FAMILY_XML = (
    b'<bm_prd_family id="17691416877">'
    b'<variable_name>aSTRO25_bom</variable_name>'
    b'<label><en>ASTRO\xc2\xae25_BOM</en></label>'
    b'</bm_prd_family>'
)


def _run_cpq_family_xml(*, locale_fold_enabled: bool):
    captured_nodes: dict[str, list] = {}

    class _CaptureConnector:
        def __init__(self, nodes, *, tag, source_key):
            captured_nodes[tag] = nodes

    settings = _settings_stub(cpq_locale_wrapper_fold_enabled=locale_fold_enabled)
    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.get_settings", return_value=settings), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.RawGraphConnector", _CaptureConnector), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.EntityStore") as mock_estore_cls, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.run_pipeline",
               return_value={"run_id": 1, "entities": 1, "relationships": 0}), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.project_workspace_graph", return_value={}):
        mock_estore_cls.return_value = _mock_estore(lambda run_id: {})
        resolve_and_relate_raw_graph(
            xml_bytes=_CPQ_FAMILY_XML, workspace_id=WORKSPACE_ID, source_key="f",
            dsn=DSN, graph_url=GRAPH_URL, broker=BROKER,
        )
    return captured_nodes


def test_locale_wrapper_fold_enabled_resolves_only_the_family_tag():
    assert set(_run_cpq_family_xml(locale_fold_enabled=True)) == {"bm_prd_family"}


def test_locale_wrapper_fold_enabled_family_gets_label_name_and_display_label():
    family = _run_cpq_family_xml(locale_fold_enabled=True)["bm_prd_family"][0]
    assert (family.properties["label"], family.properties["name"],
            family.properties["display_label"]) == ("ASTRO\u00ae25_BOM", "aSTRO25_bom", "ASTRO\u00ae25_BOM")


def test_locale_wrapper_fold_disabled_keeps_label_as_its_own_tag():
    assert "label" in _run_cpq_family_xml(locale_fold_enabled=False)


def test_locale_wrapper_fold_disabled_adds_no_display_fields():
    family = _run_cpq_family_xml(locale_fold_enabled=False)["bm_prd_family"][0]
    assert "name" not in family.properties and "display_label" not in family.properties


def test_promoted_display_fields_are_hidden_from_match_key_inference():
    """Raven review finding 1: name/display_label are synthesized, so they
    must not be offered to match-key inference (an LLM-fallback pick of
    `name` would merge distinct records sharing a display text). They are
    added per tag AFTER the key is chosen; folded wrapper values (label)
    stay visible, same as _xml_to_csvs's columns."""
    from aryx.cpq_ingestion.raw_graph import resolve_relate as rr

    seen: dict[str, dict] = {}
    real_infer = rr.infer_match_keys_for_tag

    def _spy(tag, nodes, context="", log_id=None):
        seen[tag] = dict(nodes[0].properties)
        return real_infer(tag, nodes, context, log_id=log_id)

    with patch("aryx.cpq_ingestion.raw_graph.resolve_relate.infer_match_keys_for_tag", _spy):
        family = _run_cpq_family_xml(locale_fold_enabled=True)["bm_prd_family"][0]
    props_at_inference = seen["bm_prd_family"]
    assert ("name" not in props_at_inference and "display_label" not in props_at_inference
            and props_at_inference.get("label") == "ASTRO\u00ae25_BOM"
            and family.properties["name"] == "aSTRO25_bom")
