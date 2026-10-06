"""Ingest leaf audit + post-ingest workspace health (synthetic names only)."""
from __future__ import annotations

from collections import defaultdict

import pytest

from aryx.cpq_ingestion import ingest_health as health
from aryx.cpq_ingestion.raw_graph.leaf_audit import (
    REASON_FOLD_DISABLED, REASON_KEPT_AFTER_FOLD, audit_unfolded_leaf_tags, find_unfolded_leaf_tags,
)
from aryx.cpq_ingestion.raw_graph.structural_leaf import fold_structural_leaf_tags
from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph
from aryx.worker import job_partial

XML = b"""<root>
  <rec><id>1</id><note>alpha</note><body><![CDATA[x = 1;]]></body><child><id>10</id></child></rec>
  <rec><id>2</id><note>beta</note><body><![CDATA[x = 2;]]></body><child><id>11</id></child></rec>
</root>"""


def _grouped():
    proj = project_xml_to_raw_graph(XML)
    by_tag = defaultdict(list)
    for node in proj.nodes:
        by_tag[node.tag].append(node)
    return dict(by_tag), proj.edges


def test_unfolded_text_leaf_tags_are_found_and_folded_ones_are_not():
    by_tag, edges = _grouped()
    before = find_unfolded_leaf_tags(by_tag, edges)
    assert {"id", "note", "body"} <= set(before)            # plain text leaves
    assert "rec" not in before and "child" not in before     # have children
    folded = fold_structural_leaf_tags(edges, by_tag)
    assert find_unfolded_leaf_tags(folded, edges) == {}


def test_audit_reports_marks_the_job_partial_and_names_the_reason(caplog):
    by_tag, edges = _grouped()
    job_partial.pop_hidden("job-a")
    with caplog.at_level("WARNING"):
        got = audit_unfolded_leaf_tags(by_tag, edges, fold_enabled=False, log_id="job-a", source_key="f")
    assert "body" in got and job_partial.pop_hidden("job-a") == 1
    assert REASON_FOLD_DISABLED in caplog.text
    job_partial.pop_hidden("job-b")
    audit_unfolded_leaf_tags(by_tag, edges, fold_enabled=True, log_id="job-b", source_key="f")
    assert job_partial.pop_hidden("job-b") == 1
    assert REASON_KEPT_AFTER_FOLD != REASON_FOLD_DISABLED


def test_audit_is_silent_when_everything_folded():
    by_tag, edges = _grouped()
    folded = fold_structural_leaf_tags(edges, by_tag)
    job_partial.pop_hidden("job-c")
    assert audit_unfolded_leaf_tags(folded, edges, fold_enabled=True, log_id="job-c") == {}
    assert job_partial.pop_hidden("job-c") == 0


# ---- workspace health -------------------------------------------------------

class FakeRdb:
    def __init__(self, functions=(), types=None, attrs=(), grouped=None, grouped_error=None):
        self.functions, self.types, self.attrs = list(functions), types or {}, list(attrs)
        self.grouped, self.grouped_error = grouped or {}, grouped_error

    def fetch_entities_by_type(self, ws, suffix, prefix=""):
        return {"bmfunction": self.functions, "bmconfigattr": self.attrs}[suffix]

    def list_ontology_types(self, ws):
        return list(self.types)

    def fetch_entities_by_exact_type(self, ws, otype):
        return self.types[otype]

    def fetch_all_entities_grouped_by_type(self, ws):
        if self.grouped_error:
            raise self.grouped_error
        return self.grouped


def _by_name(checks):
    return {c.name: c for c in checks}


def test_a_broken_ingest_fails_the_script_leaf_and_data_table_checks():
    rdb = FakeRdb(
        functions=[(i, {"id": i}) for i in range(10)],                          # no script_text on any function
        types={"CatXScriptText": [(1, {"text": "a = 1;"})], "CatXBmFunction": [(2, {"id": 1})],
               "CatXChildren": [(3, {"text": "t"})]},
        attrs=[(1, {"name": "A"}), (2, {"name": "B"})],
        grouped={"CatXBmConfigAttr": [(1, {"name": "A"})]})
    checks = _by_name(health.evaluate_workspace_health(rdb, 7))
    assert checks["function_scripts"].status == health.FAIL
    assert checks["leaf_wrapper_types"].status == health.FAIL and "CatXScriptText" in checks["leaf_wrapper_types"].detail
    assert "CatXChildren" not in checks["leaf_wrapper_types"].detail           # the container is never a wrapper
    assert checks["attribute_names"].status == health.PASS
    assert checks["data_tables"].status == health.FAIL
    assert health.worst_status(list(checks.values())) == health.FAIL


def test_a_healthy_workspace_passes_every_check():
    shapes = [(1, {"CPQModel": "M", "BaseModel": "B", "AttrName": "a", "Seq": "1"}),
              (2, {"CPQModel": "M", "BaseModel": "B", "attr1": "a", "val1": "v"}),
              (3, {"model": "M", "value": "v", "region": "R", "ruleType": "ALLOW", "attribute": "a"})]
    rdb = FakeRdb(functions=[(i, {"script_text": "return 1;"}) for i in range(10)],
                  types={"CatXBmFunction": [(1, {"id": 1})]},
                  attrs=[(1, {"name": "A"})], grouped={"CatXDataTable": shapes})
    checks = health.evaluate_workspace_health(rdb, 7)
    assert [c.status for c in checks] == [health.PASS] * 4
    assert health.worst_status(checks) == health.PASS


def test_unreadable_workspace_skips_the_data_table_check_and_a_crashing_check_never_raises():
    rdb = FakeRdb(functions=[], attrs=[], grouped_error=RuntimeError("unreadable"))
    checks = _by_name(health.evaluate_workspace_health(rdb, 7))
    assert checks["data_tables"].status == health.SKIP and "RuntimeError" in checks["data_tables"].detail
    assert checks["function_scripts"].status == health.SKIP
    broken = FakeRdb()
    broken.fetch_entities_by_type = lambda *a, **k: (_ for _ in ()).throw(ValueError("boom"))
    out = _by_name(health.evaluate_workspace_health(broken, 7))
    assert out["function_scripts"].status == health.SKIP and "check failed" in out["function_scripts"].detail


@pytest.mark.parametrize("with_script,total,status", [(0, 10, health.FAIL), (5, 10, health.WARN), (10, 10, health.PASS)])
def test_script_share_thresholds(with_script, total, status):
    rows = [(i, {"script_text": "x;" if i < with_script else ""}) for i in range(total)]
    assert health.check_function_scripts(FakeRdb(functions=rows), 1, "").status == status


# ---- wiring through resolve_and_relate_raw_graph ----------------------------

def _projection_with_text_leaf():
    from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode
    return RawGraphProjection(
        nodes=[RawNode(id=0, tag="Order", properties={"Id": "1"}),
               RawNode(id=1, tag="Note", properties={"text": "hello"})],
        edges=[RawEdge(source_id=0, target_id=1, name="CONTAINS")])


def _run(fold_enabled):
    from unittest.mock import MagicMock, patch
    from aryx.cpq_ingestion.raw_graph import resolve_relate as rr
    settings = MagicMock()
    settings.cpq_structural_leaf_fold_enabled = fold_enabled
    settings.cpq_locale_wrapper_fold_enabled = False
    settings.cpq_streaming_projection_enabled = False
    estore = MagicMock()
    estore.entity_ids_by_run.side_effect = lambda run_id: {}
    with patch.object(rr, "get_settings", return_value=settings), \
         patch.object(rr, "EntityStore", return_value=estore), \
         patch.object(rr, "run_pipeline", return_value={"run_id": 1, "entities": 1, "relationships": 0}), \
         patch.object(rr, "project_workspace_graph", return_value={}), \
         patch("aryx.cpq_ingestion.raw_graph.match_key_inference.llm_runtime.chat", side_effect=RuntimeError("no LLM")):
        return rr.resolve_and_relate_raw_graph(
            _projection_with_text_leaf(), workspace_id=1, source_key="f", dsn="d", graph_url="g",
            broker=MagicMock(), log_id="job-w")


def test_result_reports_unfolded_leaf_tags_only_when_the_fold_left_one_behind():
    job_partial.pop_hidden("job-w")
    assert _run(fold_enabled=False)["unfolded_leaf_tags"] == {"Note": 1}
    assert job_partial.pop_hidden("job-w") == 1
    assert "unfolded_leaf_tags" not in _run(fold_enabled=True)
    assert job_partial.pop_hidden("job-w") == 0


def test_a_failing_audit_never_aborts_the_ingest():
    by_tag, _edges = _grouped()
    assert audit_unfolded_leaf_tags(by_tag, None, fold_enabled=True, log_id="job-x") == {}


def test_readers_that_swallow_errors_and_return_empty_are_never_reported_as_healthy():
    rdb = FakeRdb()                                     # every accessor returns empty, like a failed read
    checks = health.evaluate_workspace_health(rdb, 7)
    assert [c.status for c in checks] == [health.SKIP] * 4
    assert health.worst_status(checks) == health.SKIP and len(health.skipped(checks)) == 4


def test_worst_status_ranks_skip_above_pass_but_below_warn():
    mk = lambda *s: [health.Check("c", x, "") for x in s]
    assert health.worst_status(mk(health.PASS, health.SKIP)) == health.SKIP
    assert health.worst_status(mk(health.SKIP, health.PASS)) == health.SKIP
    assert health.worst_status(mk(health.SKIP, health.WARN)) == health.WARN
