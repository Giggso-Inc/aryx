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

from aryx.cpq_ingestion.raw_graph.resolve_relate import resolve_and_relate_raw_graph
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode

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

    calls_by_dataset = {c.kwargs["dataset"]: c.kwargs for c in mock_run_pipeline.call_args_list}
    assert calls_by_dataset["PurchaseOrder"]["ontology_type"] == "PurchaseOrder"
    assert calls_by_dataset["PurchaseOrder"]["match_keys"] == ["Id"]
    assert calls_by_dataset["Customer"]["ontology_type"] == "Customer"
    assert calls_by_dataset["Customer"]["match_keys"] == ["Id"]
    # LineItem's "Sku" isn't id-like by default -- falls back to LLM, which
    # isn't mocked here, so it degrades to the default (first property key).
    assert calls_by_dataset["LineItem"]["ontology_type"] == "LineItem"
    assert calls_by_dataset["LineItem"]["match_keys"] == ["Sku"]


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

    mock_project.assert_called_once_with(DSN, GRAPH_URL, WORKSPACE_ID, mock_estore)
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
