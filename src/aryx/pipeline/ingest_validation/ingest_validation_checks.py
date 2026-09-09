"""Runs the zero-loss validation checks against a live workspace: landed
completeness, member coverage, entity counts, id fidelity, FK/relationship
coverage, isolation audit, and (FalkorDB backends) projection parity.

Split out of `pipeline/ingest_validation.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

from typing import Any

from aryx.pipeline.ingest_validation.ingest_validation_types import CheckResult, GroundTruth, ValidationReport
from aryx.store.pool import get_pool

_SAMPLE_CAP = 10  # max dangling values echoed per FK check


def _dataset_type_map(cur: Any, workspace_id: int) -> dict[str, str]:
    """dataset -> ontology_type from what was actually ingested (audit L2:
    never recompute type names — LLM-chosen ones would mismatch)."""
    cur.execute(
        """
        SELECT DISTINCT l.source_dataset, e.ontology_type
        FROM aryx_entity e
        JOIN aryx_entity_member m ON m.entity_id = e.id AND m.workspace_id = e.workspace_id
        JOIN aryx_landed_record l ON l.id = m.landed_record_id
        WHERE e.workspace_id = %s
        """,
        (workspace_id,),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def validate_workspace(workspace_id: int, gt: GroundTruth, dsn: str,
                       graph_url: str | None = None) -> ValidationReport:
    """Run the seven zero-loss checks against a workspace. Read-only."""
    report = ValidationReport(workspace_id=workspace_id)
    if not gt.datasets or all(t.rows == 0 for t in gt.datasets.values()):
        report.checks.append(CheckResult(
            "ground_truth", "FAIL", "non-empty ground truth", "ground_truth_empty",
            "no datasets/rows in ground truth — wrong XML or empty source; aborting"))
        return report

    pool = get_pool(dsn)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # 1. Landed completeness per dataset.
            cur.execute(
                "SELECT source_dataset, count(*) FROM aryx_landed_record "
                "WHERE workspace_id = %s GROUP BY source_dataset",
                (workspace_id,),
            )
            landed = {r[0]: r[1] for r in cur.fetchall()}
            for dataset, truth in gt.datasets.items():
                actual = landed.get(dataset, 0)
                report.checks.append(CheckResult(
                    f"landed_completeness[{dataset}]",
                    "PASS" if actual == truth.rows else "FAIL",
                    truth.rows, actual))

            # 2. Member coverage — every landed record belongs to an entity.
            cur.execute(
                """
                SELECT l.source_dataset, count(*)
                FROM aryx_landed_record l
                LEFT JOIN aryx_entity_member m ON m.landed_record_id = l.id
                    AND m.workspace_id = l.workspace_id
                WHERE l.workspace_id = %s AND m.id IS NULL
                GROUP BY l.source_dataset
                """,
                (workspace_id,),
            )
            uncovered = {r[0]: r[1] for r in cur.fetchall()}
            report.checks.append(CheckResult(
                "member_coverage", "PASS" if not uncovered else "FAIL",
                "0 unaccounted landed records", uncovered or 0))

            # dataset -> type mapping via provenance (audit L2).
            ds_type = _dataset_type_map(cur, workspace_id)

            # 3+4. Entity counts and id fidelity per dataset.
            for dataset, truth in gt.datasets.items():
                otype = ds_type.get(dataset)
                if otype is None:
                    report.checks.append(CheckResult(
                        f"entity_count[{dataset}]", "FAIL",
                        "dataset mapped to an ontology type", "type_mapping_failed",
                        "no ingested entities trace back to this dataset"))
                    continue
                cur.execute(
                    "SELECT count(*) FROM aryx_entity "
                    "WHERE workspace_id = %s AND ontology_type = %s",
                    (workspace_id, otype),
                )
                n_entities = cur.fetchone()[0]
                expected_entities = (len(truth.id_values)
                                     if truth.id_column else truth.rows)
                dup_merged = truth.rows - expected_entities
                report.checks.append(CheckResult(
                    f"entity_count[{dataset}]",
                    "PASS" if n_entities == expected_entities else "FAIL",
                    expected_entities, n_entities,
                    f"type={otype}"
                    + (f" true_duplicate_rows_merged={dup_merged}" if dup_merged else "")))

                if truth.id_column and truth.id_values:
                    cur.execute(
                        "SELECT attributes->>%s FROM aryx_entity "
                        "WHERE workspace_id = %s AND ontology_type = %s",
                        (truth.id_column, workspace_id, otype),
                    )
                    entity_ids = {str(r[0]).strip() for r in cur.fetchall() if r[0]}
                    missing = truth.id_values - entity_ids
                    report.checks.append(CheckResult(
                        f"id_fidelity[{dataset}]",
                        "PASS" if not missing else "FAIL",
                        f"all {len(truth.id_values)} source ids present",
                        f"{len(missing)} missing",
                        f"sample_missing={sorted(missing)[:_SAMPLE_CAP]}" if missing else ""))

            # 5. Relationship coverage per FK pair, filtered by FK edge name.
            for fk in gt.fk_refs:
                child_t = ds_type.get(fk.child_dataset)
                parent_t = ds_type.get(fk.parent_dataset)
                if not child_t or not parent_t:
                    report.checks.append(CheckResult(
                        f"fk_coverage[{fk.child_dataset}.{fk.fk_column}]", "FAIL",
                        "both datasets mapped to types", "type_mapping_failed"))
                    continue
                edge_name = f"{parent_t.upper()}_HAS_{child_t.upper()}"
                cur.execute(
                    "SELECT count(*) FROM aryx_relationship "
                    "WHERE workspace_id = %s AND name = %s",
                    (workspace_id, edge_name),
                )
                actual_edges = cur.fetchone()[0]
                expected = len(fk.resolvable_child_ids)
                status = ("PASS" if actual_edges == expected
                          else ("WARN" if actual_edges > expected else "FAIL"))
                detail = f"edge={edge_name}"
                if fk.dangling_values:
                    detail += (f" dangling_fk_values={len(fk.dangling_values)} "
                               f"sample={sorted(fk.dangling_values)[:_SAMPLE_CAP]}")
                report.checks.append(CheckResult(
                    f"fk_coverage[{fk.child_dataset}.{fk.fk_column}->{fk.parent_dataset}]",
                    status, expected, actual_edges, detail))

            # 7. Isolation audit (Postgres-side, backend-independent).
            referencing = {fk.child_dataset for fk in gt.fk_refs if fk.resolvable_child_ids}
            referenced = {fk.parent_dataset for fk in gt.fk_refs if fk.resolvable_child_ids}
            connected_datasets = referencing | referenced
            cur.execute(
                """
                SELECT e.ontology_type, count(*)
                FROM aryx_entity e
                WHERE e.workspace_id = %s
                  AND NOT EXISTS (SELECT 1 FROM aryx_relationship r
                                  WHERE r.workspace_id = e.workspace_id
                                    AND (r.source_entity_id = e.id OR r.target_entity_id = e.id))
                GROUP BY e.ontology_type
                """,
                (workspace_id,),
            )
            isolated = {r[0]: r[1] for r in cur.fetchall()}
            type_ds = {v: k for k, v in ds_type.items()}
            unexpected = {t: n for t, n in isolated.items()
                          if type_ds.get(t) in connected_datasets}
            report.checks.append(CheckResult(
                "isolation_audit",
                "PASS" if not unexpected else "FAIL",
                "isolated entities only in datasets with no resolvable FK refs",
                {"isolated_by_type": isolated} if isolated else 0,
                (f"UNEXPECTED (dataset has resolvable refs): {unexpected}"
                 if unexpected else "all isolation justified by source")))

    # 6. Projection parity (FalkorDB backends; skipped otherwise, visibly).
    _check_projection_parity(report, workspace_id, dsn, graph_url, ds_type)

    # Tier-2 raw XML cross-check (CLI only).
    if gt.raw_xml_counts is None:
        report.checks.append(CheckResult(
            "raw_xml_check", "SKIP", "-", "-",
            "skipped (CLI-only — raw XML unavailable during auto-validation)"))
    else:
        for dataset, truth in gt.datasets.items():
            if not truth.element_tag:
                continue
            raw = gt.raw_xml_counts.get(truth.element_tag)
            if raw is None:
                continue
            if raw > truth.rows:
                report.checks.append(CheckResult(
                    f"raw_xml_check[{dataset}]", "WARN", raw, truth.rows,
                    "extraction capped rows (ARYX_XML_MAX_ROWS_PER_TYPE) — raise cap to ingest all"))
            elif raw != truth.rows:
                report.checks.append(CheckResult(
                    f"raw_xml_check[{dataset}]", "FAIL", raw, truth.rows,
                    "extracted rows do not match raw XML element count"))
            else:
                report.checks.append(CheckResult(
                    f"raw_xml_check[{dataset}]", "PASS", raw, truth.rows))
    return report


def _check_projection_parity(report: ValidationReport, workspace_id: int, dsn: str,
                             graph_url: str | None, ds_type: dict[str, str]) -> None:
    """Check 6: FalkorDB node/edge counts == Postgres, nodes carry attrs."""
    from aryx.config import get_settings
    settings = get_settings()
    if settings.effective_graph_backend() == "oci_graph" or not graph_url:
        report.checks.append(CheckResult(
            "projection_parity", "SKIP", "-", "-",
            "non-FalkorDB backend or no graph_url — parity check not implemented here"))
        return
    try:
        from aryx.graph.reader import GraphReader
        from aryx.naming import ws_graph
        reader = GraphReader(graph_url, ws_graph(workspace_id))
        node_rows = reader._query("MATCH (e:Entity) RETURN e.type, count(*)")  # noqa: SLF001
        graph_by_type = {r[0]: r[1] for r in node_rows}
        edge_rows = reader._query("MATCH ()-[r:REL]->() RETURN count(r)")  # noqa: SLF001
        graph_edges = edge_rows[0][0] if edge_rows else 0
        # Attributes are individual native node properties (post-lift), so a
        # node "carrying attrs" means it has at least one property beyond the
        # projection internals (id/type/name/iri). Legacy graphs carry the old
        # stringified blob under `attrs`, which also counts.
        no_attrs = reader._query(  # noqa: SLF001
            "MATCH (e:Entity) "
            "WHERE size([k IN keys(e) WHERE NOT k IN ['id','type','name','iri']]) = 0 "
            "RETURN count(e)")
        n_no_attrs = no_attrs[0][0] if no_attrs else 0

        pool = get_pool(dsn)
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ontology_type, count(*) FROM aryx_entity "
                    "WHERE workspace_id = %s GROUP BY ontology_type",
                    (workspace_id,),
                )
                pg_by_type = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute(
                    "SELECT count(*) FROM aryx_relationship WHERE workspace_id = %s",
                    (workspace_id,),
                )
                pg_edges = cur.fetchone()[0]

        mismatched = {t: (pg_by_type.get(t, 0), graph_by_type.get(t, 0))
                      for t in set(pg_by_type) | set(graph_by_type)
                      if pg_by_type.get(t, 0) != graph_by_type.get(t, 0)}
        report.checks.append(CheckResult(
            "projection_parity[nodes]", "PASS" if not mismatched else "FAIL",
            sum(pg_by_type.values()), sum(graph_by_type.values()),
            f"mismatched_types={mismatched}" if mismatched else ""))
        report.checks.append(CheckResult(
            "projection_parity[edges]", "PASS" if graph_edges == pg_edges else "FAIL",
            pg_edges, graph_edges))
        report.checks.append(CheckResult(
            "node_attributes", "PASS" if n_no_attrs == 0 else "FAIL",
            "0 nodes without attrs", n_no_attrs))
    except Exception as exc:  # noqa: BLE001 — parity is best-effort, must not mask other checks
        report.checks.append(CheckResult(
            "projection_parity", "FAIL", "graph reachable", f"error: {exc}"))
