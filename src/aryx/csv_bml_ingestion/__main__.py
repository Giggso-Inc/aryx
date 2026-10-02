"""CLI: ``python -m aryx.csv_bml_ingestion``.

    ingest  GRAPH-SOURCE  CSV [CSV ...]   run the full pipeline per CSV
    inspect GRAPH-SOURCE  CSV [CSV ...]   steps 1-2 only: which queries each CSV's table maps to

GRAPH-SOURCE (exactly one):
    --xml FILE            any XML; its graph is generated now (inspect then needs no database)
    --workspace-id N      search the XML knowledge graphs already stored for workspace N

Exit status: 0 when every CSV loaded, 1 when any CSV failed or was skipped.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from aryx.csv_bml_ingestion.bml_index import BmlIndex
from aryx.csv_bml_ingestion.db import oracle_connection_factory
from aryx.csv_bml_ingestion.errors import CsvBmlIngestionError
from aryx.csv_bml_ingestion.llm_client import project_llm_completer
from aryx.csv_bml_ingestion.overflow import OverflowPolicy
from aryx.csv_bml_ingestion.pipeline import ingest_csv
from aryx.csv_bml_ingestion.stored_graph import StoredGraphLookup
from aryx.csv_bml_ingestion.table_name import extract_table_name
from aryx.csv_bml_ingestion.tracking import RunTracker

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m aryx.csv_bml_ingestion", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("ingest", "inspect"):
        s = sub.add_parser(name)
        s.add_argument("--xml", type=Path, help="any XML file; its graph is generated now")
        s.add_argument("--workspace-id", type=int,
                       help="instead of --xml: search the XML knowledge graphs already stored for this workspace")
        s.add_argument("csv", nargs="+", type=Path, help="CSV file(s); filename stem = table name")
        if name == "ingest":
            s.add_argument("--append", action="store_true", help="keep existing rows instead of replacing")
            s.add_argument("--batch-size", type=int, default=500)
            s.add_argument("--on-overflow", choices=[p.value for p in OverflowPolicy], default="reject",
                           help="values too long for their column: reject the row (default), truncate, or fail")
            s.add_argument("--no-author-sql", action="store_true",
                           help="do NOT let an LLM author sql/<table>/ when missing; such CSVs fail instead")
            s.add_argument("--rejects-dir", type=Path, default=None,
                           help="where <table>.rejects.csv is written (default: next to the CSV)")
    return p


def _load_index(args: argparse.Namespace, factory) -> "BmlIndex | StoredGraphLookup | None":
    label = args.xml.name if args.xml else f"workspace={args.workspace_id}"
    tracker = RunTracker(label)
    try:
        index = BmlIndex.from_xml_file(args.xml) if args.xml else StoredGraphLookup(factory, args.workspace_id)
    except CsvBmlIngestionError as exc:
        tracker.error("xml_graph", f"cannot build XML graph: {exc}", error_code=exc.code)
        print(f"ERROR [{exc.code}] {exc}", file=sys.stderr)
        return None
    tracker.info("xml_graph", "XML graph ready", source="xml" if args.xml else "stored_graph",
                 nodes=index.node_count, query_nodes=index.script_count, queried_tables=len(index.tables))
    return index


def _inspect(index: BmlIndex, csvs: list[Path]) -> int:
    bad = 0
    for csv_path in csvs:
        try:
            table = extract_table_name(csv_path)
        except CsvBmlIngestionError as exc:
            print(f"{csv_path}: ERROR [{exc.code}] {exc}")
            bad += 1
            continue
        lookup = index.lookup(table)
        if not lookup.matches:
            hint = f" (near misses: {', '.join(lookup.near_misses)})" if lookup.near_misses else ""
            print(f"{table}: NO QUERY READS THIS TABLE{hint}")
            bad += 1
            continue
        print(f"{table}: {len(lookup.matches)} location(s)")
        for m in lookup.matches:
            print(f"  {m.label}  at {'/'.join(m.path)}/{m.node_tag}.{m.prop}")
            for q in m.queries:
                print(f"    {q.sql}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = _parser()
    args = parser.parse_args(argv)
    if bool(args.xml) == (args.workspace_id is not None):
        parser.error("give exactly one graph source: --xml FILE or --workspace-id N")
    factory = None
    if args.command == "ingest" or args.workspace_id is not None:
        try:
            factory = oracle_connection_factory()
        except CsvBmlIngestionError as exc:
            RunTracker(args.xml.name if args.xml else "cli").error("db", str(exc), error_code=exc.code)
            print(f"ERROR [{exc.code}] {exc}", file=sys.stderr)
            return 1
    index = _load_index(args, factory)
    if index is None:
        return 1
    if args.command == "inspect":
        return _inspect(index, args.csv)
    results = [ingest_csv(c, index, factory, replace=not args.append, batch_size=args.batch_size,
                          overflow=OverflowPolicy(args.on_overflow), rejects_dir=args.rejects_dir,
                          sql_author=None if args.no_author_sql else project_llm_completer())
               for c in args.csv]
    for r in results:
        print(f"{r.source}: {r.status} table={r.table} rows={r.rows_loaded} bad={r.rows_bad} "
              f"rejected={r.rows_rejected} truncated={r.rows_truncated} "
              f"{r.error_code} {r.message} {r.rejects_file}".rstrip())
    return 0 if all(r.status == "loaded" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
