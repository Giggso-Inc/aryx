"""Post-ingest validation: prove no source data was lost (zero-loss guarantee).

Generic — works for any tabular/XML-derived ingest, keyed by DATASET name
(the deterministic filename stem recorded in aryx_landed_record.source_dataset)
rather than ontology type names, which can be LLM-chosen and non-reproducible.

Two ground-truth tiers:
- Tier 1 (auto, runs after every confirm): derived from the discovery plans
  actually ingested — the raw XML bytes are NOT available inside
  ingest_confirmed, only the converted CSVs.
- Tier 2 (CLI only): the standalone entry point receives the source XML path
  and cross-checks raw element counts against the extracted rows, surfacing
  cap truncation as a WARNING.

Usage (standalone):
    python -m aryx.pipeline.ingest_validation <xml-file> <workspace_id>
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)

_ID_COLUMNS = ("id", "guid", "uuid")
_SAMPLE_CAP = 10  # max dangling values echoed per FK check


@dataclass
class FkTruth:
    """One deterministic FK reference set between two datasets."""

    child_dataset: str
    fk_column: str
    parent_dataset: str
    resolvable_child_ids: set[str] = field(default_factory=set)
    dangling_values: set[str] = field(default_factory=set)


@dataclass
class DatasetTruth:
    """Expected content for one ingested dataset (CSV stem)."""

    rows: int
    id_column: str | None
    id_values: set[str] = field(default_factory=set)
    element_tag: str | None = None
    headers: list[str] = field(default_factory=list)


@dataclass
class GroundTruth:
    """Everything the source says must exist after ingestion."""

    datasets: dict[str, DatasetTruth] = field(default_factory=dict)
    fk_refs: list[FkTruth] = field(default_factory=list)
    raw_xml_counts: dict[str, int] | None = None  # tier 2 only: element tag -> count


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL | WARN | SKIP
    expected: Any
    actual: Any
    detail: str = ""


@dataclass
class ValidationReport:
    workspace_id: int
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.status != "FAIL" for c in self.checks)

    def summary_line(self) -> str:
        by = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
        for c in self.checks:
            by[c.status] = by.get(c.status, 0) + 1
        return (f"checks={len(self.checks)} pass={by['PASS']} fail={by['FAIL']} "
                f"warn={by['WARN']} skip={by['SKIP']}")

    def failures(self) -> list[str]:
        return [f"{c.name}: expected={c.expected} actual={c.actual} {c.detail}".strip()
                for c in self.checks if c.status == "FAIL"]

    def render(self) -> str:
        lines = [f"=== Ingest validation — workspace {self.workspace_id} ===",
                 self.summary_line(), ""]
        for c in self.checks:
            lines.append(f"[{c.status}] {c.name}")
            lines.append(f"    expected: {c.expected}")
            lines.append(f"    actual:   {c.actual}")
            if c.detail:
                lines.append(f"    detail:   {c.detail}")
        lines.append("")
        lines.append(f"RESULT: {'PASSED' if self.passed else 'FAILED'}")
        return "\n".join(lines)


def _parse_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Header + rows from CSV bytes (utf-8, errors ignored)."""
    text = data.decode("utf-8", "ignore")
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    rows = [dict(r) for r in reader]
    return headers, rows


def ground_truth_from_tabular(plans: list[dict]) -> GroundTruth:
    """Tier-1 ground truth from the discovery plans actually being ingested.

    Dataset-keyed (deterministic filename stem). FK inventory mirrors the
    ``{parent_tag}_id`` convention that _xml_to_csvs injects and
    _detect_fk_links resolves: a column ``X_id`` references the dataset whose
    ``_element_type`` tag equals X (exact first, unique-endswith fallback).
    """
    gt = GroundTruth()
    parsed: dict[str, tuple[list[str], list[dict[str, str]]]] = {}

    for plan in plans:
        dataset = Path(plan["filename"]).stem
        headers, rows = _parse_csv(plan["data"])
        parsed[dataset] = (headers, rows)
        id_col = next((c for c in headers if c.lower() in _ID_COLUMNS), None)
        id_values = ({str(r.get(id_col, "")).strip() for r in rows} - {""}
                     if id_col else set())
        tag = rows[0].get("_element_type") if rows and "_element_type" in headers else None
        gt.datasets[dataset] = DatasetTruth(
            rows=len(rows), id_column=id_col, id_values=id_values,
            element_tag=tag, headers=headers,
        )

    tag_to_dataset = {t.element_tag: ds for ds, t in gt.datasets.items() if t.element_tag}

    def _target_for(col_tag: str) -> str | None:
        if col_tag in tag_to_dataset:
            return tag_to_dataset[col_tag]
        matches = [ds for tag, ds in tag_to_dataset.items() if tag.endswith(col_tag)]
        return matches[0] if len(matches) == 1 else None  # ambiguous -> skip

    seen_pairs: set[tuple[str, str]] = set()
    for dataset, truth in gt.datasets.items():
        headers, rows = parsed[dataset]
        for col in headers:
            col_l = col.lower()
            if not col_l.endswith("_id") or col_l in _ID_COLUMNS:
                continue
            parent = _target_for(col_l[:-3])
            if parent is None or parent == dataset:
                continue
            pair = (dataset, parent)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            parent_ids = gt.datasets[parent].id_values
            child_id_col = truth.id_column
            fk = FkTruth(child_dataset=dataset, fk_column=col, parent_dataset=parent)
            for r in rows:
                val = str(r.get(col, "")).strip()
                if not val or val == "-1":
                    # "-1" is BM's own "not set" convention (mirrors the
                    # condition_function_id == -1 checks elsewhere) — not a
                    # broken reference, so it must not count as dangling.
                    continue
                if val in parent_ids:
                    child_id = str(r.get(child_id_col, "")).strip() if child_id_col else ""
                    if child_id:
                        fk.resolvable_child_ids.add(child_id)
                else:
                    fk.dangling_values.add(val)
            gt.fk_refs.append(fk)
    return gt


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


def _raw_xml_counts(xml_bytes: bytes, tags: set[str]) -> dict[str, int]:
    """Tier 2: count raw occurrences of each extracted element tag in the XML."""
    import defusedxml.ElementTree as defused_ET
    root = defused_ET.fromstring(xml_bytes)
    counts = {t: 0 for t in tags}

    def _strip_ns(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    if _strip_ns(root.tag) in counts:
        counts[_strip_ns(root.tag)] += 1
    for elem in root.iter():
        t = _strip_ns(elem.tag)
        if t in counts and elem is not root:
            counts[t] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    """Standalone: re-derive ground truth from an XML file and validate a workspace."""
    import argparse

    from aryx.config import get_settings
    from aryx.pipeline.doc_discovery import _xml_to_csvs

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_file", help="Source XML file the workspace was ingested from")
    parser.add_argument("workspace_id", type=int)
    args = parser.parse_args(argv)

    data = Path(args.xml_file).read_bytes()
    stem = Path(args.xml_file).stem
    plans = [{"filename": name, "data": csv_bytes}
             for csv_bytes, name in _xml_to_csvs(data, stem, log_id="validation-cli")]
    gt = ground_truth_from_tabular(plans)
    tags = {t.element_tag for t in gt.datasets.values() if t.element_tag}
    gt.raw_xml_counts = _raw_xml_counts(data, tags)

    settings = get_settings()
    report = validate_workspace(args.workspace_id, gt, settings.rdb_dsn, settings.graph_url)
    print(report.render())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
