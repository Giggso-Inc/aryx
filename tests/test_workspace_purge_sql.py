"""Regression coverage for workspace purge SQL table coverage."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_PURGE = ROOT / "src" / "aryx" / "queries" / "purge_workspace_data.sql"
ORACLE_PURGE = ROOT / "src" / "aryx" / "queries" / "oracle" / "purge_workspace_data.sql"

REQUIRED_WORKSPACE_TABLES = {
    "aryx_action_execution",
    "aryx_action",
    "aryx_adjudication",
    "aryx_attribute_conflict",
    "aryx_ask_history",
    "aryx_axiom_violation",
    "aryx_bml_tier2_cache",
    "aryx_datasource",
    "aryx_ingest_question",
    "aryx_llm_call",
    "aryx_projected_entity",
    "aryx_projection_state",
    "aryx_relationship_type",
    "aryx_ontology_axiom",
    "aryx_ontology_change_log",
    "aryx_ontology_rule",
    "aryx_ontology_type",
    "aryx_ontology_version",
    "aryx_field_profile",
    "aryx_field_tag",
    "aryx_run_stage",
    "aryx_match_edge",
    "aryx_block_done",
    "aryx_block_member",
    "aryx_run",
    "aryx_job_event",
    "aryx_job",
}

ORACLE_WORKSPACE_TABLES = REQUIRED_WORKSPACE_TABLES - {
    # These tables/columns are present in the Postgres migrations only today.
    "aryx_bml_tier2_cache",
    "aryx_llm_call",
}

ORACLE_GRAPH_TABLES = {
    "aryx_graph_provenance",
    "aryx_graph_edge",
    "aryx_graph_source",
    "aryx_graph_vertex",
}


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_postgres_purge_deletes_workspace_owned_tables() -> None:
    sql = _sql(POSTGRES_PURGE)

    missing = sorted(table for table in REQUIRED_WORKSPACE_TABLES if table not in sql)

    assert missing == []


def test_postgres_purge_does_not_reference_oracle_graph_tables() -> None:
    sql = _sql(POSTGRES_PURGE)

    assert all(table not in sql for table in ORACLE_GRAPH_TABLES)


def test_oracle_purge_deletes_workspace_owned_and_graph_tables() -> None:
    sql = _sql(ORACLE_PURGE)
    required = ORACLE_WORKSPACE_TABLES | ORACLE_GRAPH_TABLES

    missing = sorted(table for table in required if table not in sql)

    assert missing == []


def test_oracle_purge_skips_postgres_only_workspace_tables() -> None:
    sql = _sql(ORACLE_PURGE)

    assert "aryx_bml_tier2_cache" not in sql
    assert "aryx_llm_call" not in sql


def test_oracle_graph_children_delete_before_graph_vertices() -> None:
    sql = _sql(ORACLE_PURGE)

    assert sql.index("aryx_graph_provenance") < sql.index("aryx_graph_vertex")
    assert sql.index("aryx_graph_edge") < sql.index("aryx_graph_vertex")
