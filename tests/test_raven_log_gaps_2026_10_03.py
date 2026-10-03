"""Raven logging for the remaining ingestion gaps and the ref_id plumbing (2026-10-03).

Covers: tag_fields, embed_chunks, screen_chunks, ProfileAccumulator, schema agent,
_resolve_exact, project_auto's bad ARYX_PROJECT_DIRTY_MAX, the Falkor index helper,
the Postgres RDB read-failure helper, and that every rule-based record_fire call
site passes the rule's ref_id.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import aryx.raven_log as rl
from aryx.models import FieldProfile, FieldTag

SRC = Path(__file__).resolve().parents[1] / "src" / "aryx"


@pytest.fixture(autouse=True)
def _debug_level(monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_LEVEL", "DEBUG")
    rl.reload_config()
    rl.bind_run_id("job-7")
    yield
    rl.bind_run_id("")
    monkeypatch.delenv("ARYX_RAVEN_LOG_LEVEL", raising=False)
    rl.reload_config()


def _recs(capsys) -> list[dict]:
    return [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]


def _ev(recs, event):
    return [r for r in recs if r["message"].split(" ")[0] == event]


# ------------------------------------------------------------------ tag_fields

def _profiles(n):
    return [FieldProfile(field=f"f{i}", non_null=1, distinct=1, distinct_capped=False,
                         samples=["SENTINEL_SAMPLE_VALUE"]) for i in range(n)]


def test_tag_empty_logs_skip_and_never_logs_samples(capsys):
    from aryx.pipeline.tag import tag_fields
    assert tag_fields([], MagicMock()) == []
    recs = _recs(capsys)
    assert _ev(recs, "ingest.tag.skipped")[0]["context"]["reason_code"] == "NO_PROFILES"


def test_tag_incomplete_is_warn_and_ok_is_debug(capsys, monkeypatch):
    import aryx.pipeline.tag as tag
    monkeypatch.setattr(tag, "complete_json", lambda *a, **k: {"tags": [
        {"field": "f0", "semantic_type": "email", "is_pii": True}]})
    out = tag.tag_fields(_profiles(2), MagicMock())
    assert len(out) == 1
    recs = _recs(capsys)
    warn = _ev(recs, "ingest.tag.incomplete")[0]
    assert warn["level"] == "WARN" and warn["error_code"] == "ARYX_ING_TAG_INCOMPLETE"
    assert warn["context"]["untagged"] == 1 and warn["context"]["pii_fields"] == 1
    assert warn["trace_id"] == "job-7"
    assert "SENTINEL_SAMPLE_VALUE" not in json.dumps(recs)
    monkeypatch.setattr(tag, "complete_json", lambda *a, **k: {"tags": [
        {"field": "f0", "semantic_type": "x", "is_pii": False},
        {"field": "f1", "semantic_type": "y", "is_pii": False}]})
    tag.tag_fields(_profiles(2), MagicMock())
    assert _ev(_recs(capsys), "ingest.tag.completed")[0]["level"] == "DEBUG"


def test_tag_failure_logs_error_and_reraises(capsys, monkeypatch):
    import aryx.pipeline.tag as tag

    def boom(*a, **k):
        raise TimeoutError("llm down")
    monkeypatch.setattr(tag, "complete_json", boom)
    with pytest.raises(TimeoutError):
        tag.tag_fields(_profiles(1), MagicMock())
    err = _ev(_recs(capsys), "ingest.tag.failed")[0]
    assert err["level"] == "ERROR" and err["error_code"] == "ARYX_ING_TAG_FAILED"
    assert err["context"]["error_class"] == "TimeoutError"


# ---------------------------------------------------------------- embed_chunks

def _chunks(n):
    return [SimpleNamespace(text=f"t{i}", chunk_index=i, doc_id="d1") for i in range(n)]


def test_embed_no_model_logs_error_and_raises(capsys):
    from aryx.pipeline.embed import embed_chunks
    broker = SimpleNamespace(embed_model_id="", embed=lambda t: [])
    with pytest.raises(RuntimeError):
        embed_chunks(_chunks(2), broker)
    err = _ev(_recs(capsys), "ingest.embed.no_model")[0]
    assert err["error_code"] == "ARYX_ING_EMBED_NO_MODEL" and err["level"] == "ERROR"


def test_embed_empty_and_dim_mismatch_and_completed(capsys):
    from aryx.pipeline.embed import embed_chunks
    assert embed_chunks([], MagicMock()) == []
    assert _ev(_recs(capsys), "ingest.embed.skipped")
    broker = SimpleNamespace(embed_model_id="m1", embed=lambda texts: [[0.1, 0.2]] * len(texts))
    with pytest.raises(RuntimeError):
        embed_chunks(_chunks(2), broker, expected_dim=3)
    mismatch = _ev(_recs(capsys), "ingest.embed.dim_mismatch")[0]
    assert mismatch["error_code"] == "ARYX_ING_EMBED_DIM_MISMATCH"
    assert mismatch["context"]["dim"] == 2 and mismatch["context"]["expected_dim"] == 3
    out = embed_chunks(_chunks(3), broker)
    assert len(out) == 3
    recs = _recs(capsys)
    done = _ev(recs, "ingest.embed.completed")[0]
    assert done["level"] == "INFO" and done["context"]["chunks"] == 3 and done["context"]["dim"] == 2
    assert _ev(recs, "ingest.embed.batch")


def test_embed_empty_vectors_logs_error(capsys):
    from aryx.pipeline.embed import embed_chunks
    broker = SimpleNamespace(embed_model_id="m1", embed=lambda texts: [])
    with pytest.raises(RuntimeError):
        embed_chunks(_chunks(1), broker)
    assert _ev(_recs(capsys), "ingest.embed.empty")[0]["error_code"] == "ARYX_ING_EMBED_EMPTY"


# ---------------------------------------------------------------- screen_chunks

class _Chunk(SimpleNamespace):
    def model_copy(self, update=None):
        return _Chunk(**{**self.__dict__, **(update or {})})


def test_pii_engine_failure_is_fail_closed_and_logged(capsys, monkeypatch):
    import aryx.pipeline.pii as pii

    def no_engine():
        raise ImportError("presidio missing")
    monkeypatch.setattr(pii, "_engines", no_engine)
    with pytest.raises(ImportError):
        pii.screen_chunks([_Chunk(text="x", chunk_index=0)])
    err = _ev(_recs(capsys), "ingest.pii.engine_failed")[0]
    assert err["error_code"] == "ARYX_ING_PII_ENGINE_FAILED" and err["context"]["chunks"] == 1


def test_pii_summary_counts_types_and_never_logs_text(capsys, monkeypatch):
    import aryx.pipeline.pii as pii
    analyzer = SimpleNamespace(analyze=lambda text, language: (
        [SimpleNamespace(entity_type="EMAIL_ADDRESS")] if "@" in text else []))
    anonymizer = SimpleNamespace(anonymize=lambda text, analyzer_results, operators: SimpleNamespace(text="<X>"))
    monkeypatch.setattr(pii, "_engines", lambda: (analyzer, anonymizer))
    monkeypatch.setattr(pii, "_operator_config", lambda et, pol: None)
    out = pii.screen_chunks([_Chunk(text="jane@example.com SECRET", chunk_index=0),
                             _Chunk(text="clean", chunk_index=1)])
    assert [c.text for c in out] == ["<X>", "clean"]
    recs = _recs(capsys)
    done = _ev(recs, "ingest.pii.completed")[0]
    assert done["context"]["chunks_with_pii"] == 1
    assert done["context"]["entities_by_type"] == {"EMAIL_ADDRESS": 1}
    assert done["context"]["actions"] == {"hash": 1}
    assert "jane@example.com" not in json.dumps(recs) and "SECRET" not in json.dumps(recs)


# ----------------------------------------------------------------- profile

def test_profile_distinct_cap_warns_once_per_field(capsys, monkeypatch):
    from importlib import import_module
    prof = import_module("aryx.pipeline.profile")  # `import aryx.pipeline.profile as` yields the function
    monkeypatch.setattr(prof, "_DISTINCT_CAP", 3)
    acc = prof.ProfileAccumulator()
    for v in ["a", "b", "c", "d", "e"]:
        acc.add(SimpleNamespace(payload={"f": v}))
    res = acc.result()
    recs = _recs(capsys)
    warns = _ev(recs, "ingest.profile.distinct_capped")
    assert len(warns) == 1 and warns[0]["error_code"] == "ARYX_ING_PROFILE_DISTINCT_CAPPED"
    assert warns[0]["context"]["field"] == "f" and res[0].distinct_capped is True
    assert _ev(recs, "ingest.profile.result")[0]["context"]["capped_fields"] == ["f"]


# ------------------------------------------------------------ schema agent

def test_schema_agent_llm_failure_falls_back_and_logs(capsys, monkeypatch):
    import aryx.pipeline.schema_agent as sa

    def boom(*a, **k):
        raise TimeoutError("slow")
    monkeypatch.setattr(sa.llm_runtime, "chat", boom)
    schema = [{"table": "orders", "columns": ["id"], "pk": ["id"], "fks": []}]
    out = sa.discover_mappings(schema, "goal")
    assert out["tables"]
    recs = _recs(capsys)
    warn = _ev(recs, "ingest.schema_agent.llm_failed")[0]
    assert warn["error_code"] == "ARYX_ING_SCHEMA_AGENT_LLM_FAILED"
    assert warn["context"]["recovery_selected"] == "heuristic_mapping"
    assert _ev(recs, "ingest.schema_agent.completed")[0]["context"]["used_heuristic"] is True


# ----------------------------------------------------------------- run_exact

def test_resolve_exact_empty_text_is_warn(capsys):
    from aryx.resolution.cluster import UnionFind
    from aryx.resolution.run_exact import _resolve_exact
    recs_in = [SimpleNamespace(text="A-1", record_id=1), SimpleNamespace(text="A-1", record_id=2),
               SimpleNamespace(text="  ", record_id=3)]
    uf = UnionFind()
    for rec in recs_in:
        uf.add(rec.record_id)
    merged = _resolve_exact(recs_in, uf, {}, 55)
    assert merged == 1
    warn = _ev(_recs(capsys), "ingest.resolve.empty_match_text")[0]
    assert warn["level"] == "WARN" and warn["error_code"] == "ARYX_ING_RESOLVE_EMPTY_MATCH_TEXT"
    assert warn["context"]["empty_text"] == 1 and warn["context"]["pipeline_run_id"] == 55
    uf2 = UnionFind()
    uf2.add(9)
    _resolve_exact([SimpleNamespace(text="Z", record_id=9)], uf2, {}, 56)
    assert _ev(_recs(capsys), "ingest.resolve.exact_grouped")


# --------------------------------------------------------------------- project

def test_project_dirty_max_invalid_warns_and_uses_default(capsys, monkeypatch):
    import aryx.project as proj
    monkeypatch.setenv("ARYX_PROJECT_DIRTY_MAX", "not-a-number")
    monkeypatch.setattr(proj, "project_graph", lambda *a, **k: {"entities": 0})
    pstore = MagicMock()
    pstore.watermark.return_value = None
    proj.project_auto(MagicMock(), pstore, MagicMock())
    warn = _ev(_recs(capsys), "ingest.project.dirty_max_invalid")[0]
    assert warn["error_code"] == "ARYX_ING_PROJECT_DIRTY_MAX_INVALID"
    assert warn["context"]["recovery_selected"] == "use_default_threshold"
    assert warn["context"]["fallback_target"] == 0.3


# ---------------------------------------------------------------------- falkor

def test_falkor_index_failure_is_warn(capsys):
    pytest.importorskip("falkordb")
    from aryx.graph.falkor_store import _index_failed
    _index_failed("Entity.id", RuntimeError("no"), "full_scan_merge")
    warn = _ev(_recs(capsys), "ingest.graph.index_failed")[0]
    assert warn["error_code"] == "ARYX_ING_GRAPH_INDEX_FAILED" and warn["context"]["index"] == "Entity.id"


# ------------------------------------------------------------ postgres rdb

def test_postgres_rdb_read_failure_logs_error(capsys):
    from aryx.cpq.rdb.rdb_postgres import _read_failed
    try:
        raise ConnectionError("db down")
    except ConnectionError:
        _read_failed("fetch_rules")
    err = _ev(_recs(capsys), "ask.rdb.read_failed")[0]
    assert err["level"] == "ERROR" and err["error_code"] == "ARYX_ASK_RDB_READ_FAILED"
    assert err["context"]["dependency_name"] == "postgres" and err["context"]["error_class"] == "ConnectionError"


# ------------------------------------------------------------ ref_id plumbing

RULE_FILES = [
    "cpq/hiding_rules/apply.py",
    "cpq/recommendation_and_constraint_rules/apply_recommendations.py",
    "cpq/constraint_rules/constraint_rules_apply.py",
    "cpq/constraint_rules/constraint_rules_narrowing.py",
]


@pytest.mark.parametrize("rel", RULE_FILES)
def test_every_rule_based_record_fire_passes_ref_id(rel):
    """Calls that name a rule via rule.rule_name must also pass the rule's ref_id."""
    tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
    sites = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "record_fire":
            kws = {k.arg for k in node.keywords}
            rid = next((k.value for k in node.keywords if k.arg == "rule_id"), None)
            if isinstance(rid, ast.Attribute) and rid.attr == "rule_name":
                sites += 1
                assert "ref_id" in kws, f"{rel}:{node.lineno} record_fire lacks ref_id"
    assert sites >= 1
