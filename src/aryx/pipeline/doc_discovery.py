"""Document self-discovery: read files, surface discovered types, ingest on OK.

Reading runs the document pipeline (chunk → PII → embed → extract) and keeps
each mention's *own* discovered type instead of pinning one. Tabular files
(JSON/CSV) get a single type inferred from a sample. Nothing lands until the
user confirms which types to keep.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from aryx import llm_runtime
from aryx.broker import Broker
from aryx.config import get_settings
from aryx.connectors.csv_source import CsvConnector
from aryx.connectors.doc_router import DocumentRouterConnector
from aryx.connectors.json_source import JsonConnector
from aryx.connectors.records_source import RecordsConnector
from aryx.pipeline.orchestrate import run_pipeline
from aryx.store.chunk_store import ChunkStore

logger = logging.getLogger(__name__)

DOC_EXTS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf",
            ".xml", ".html", ".htm",
            ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
DATA_EXTS = {".json", ".csv"}


_GENERIC = {"table", "row", "record", "data", "file", "entity", "item", "object",
            "dataset", "export", "import", "report", "sheet", "upload", "dump",
            "output", "input", "sample", "test"}


def _stem_type(filename: str) -> str:
    """Derive a PascalCase singular type name from the filename stem.

    support_tickets.csv  ->  SupportTicket
    customers.csv        ->  Customer
    """
    words = Path(filename).stem.replace("-", "_").split("_")
    return "".join(_singular(w).title() for w in words if w)


def _infer_type(sample: str, filename: str, context: str) -> dict[str, Any]:
    # Filename is a reliable signal for the entity type; use it unless it's generic.
    stype = _stem_type(filename)
    use_filename_type = bool(stype) and stype.lower() not in _GENERIC
    fallback = stype or "Entity"
    sys = ("You identify which columns uniquely identify each row in a CSV file "
           "that will be loaded into a knowledge graph.")
    user = (f"Goal: {context or 'general knowledge graph'}\nFile: {filename}\n"
            f"Sample rows:\n{sample[:600]}\n\n"
            "Which 1-2 columns UNIQUELY IDENTIFY each row (the natural key or ID)?\n"
            'Reply ONLY as JSON: {"ontology_type":"SingularPascalCase",'
            '"match_keys":["col1"]}.')
    try:
        txt = llm_runtime.chat("menial", sys, user)[0]
        s, e = txt.find("{"), txt.rfind("}")
        d = json.loads(txt[s:e + 1])
        # Trust the filename-derived type; only fall back to LLM when filename
        # is too generic (e.g. data.csv, export.csv).
        llm_otype = (d.get("ontology_type") or "").strip()
        otype = stype if use_filename_type else (llm_otype or fallback)
        if not otype or otype.lower() in _GENERIC:
            otype = fallback
        return {"ontology_type": otype, "match_keys": d.get("match_keys") or ["name"]}
    except Exception:  # noqa: BLE001
        return {"ontology_type": fallback, "match_keys": ["name"]}


def read_files(doc_paths: list[Path], tabular: list[tuple[bytes, str]],
               broker: Broker, context: str) -> dict[str, Any]:
    """Read everything; return {mentions, tabular, summary} without committing."""
    settings = get_settings()
    mentions = []
    if doc_paths:
        connector = DocumentRouterConnector(
            paths=doc_paths, system="document", broker=broker,
            chunk_store=ChunkStore(settings.rdb_dsn), chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap, expected_embed_dim=settings.embed_dim,
            context=context)
        mentions = list(connector.extract())

    tab_plans = [{"filename": n, "data": d,
                  **_infer_type(d[:800].decode("utf-8", "ignore"), n, context)}
                 for d, n in tabular]

    by_type: dict[str, list[str]] = {}
    for m in mentions:
        by_type.setdefault(m.payload["type"], []).append(m.payload["name"])
    types = [{"type": t, "count": len(v), "examples": list(dict.fromkeys(v))[:5]}
             for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))]
    files = [{"filename": p["filename"], "ontology_type": p["ontology_type"]} for p in tab_plans]
    return {"mentions": mentions, "tabular": tab_plans,
            "summary": {"types": types, "files": files}}


def _singular(word: str) -> str:
    """Naive singularisation for FK pattern matching (Customers→Customer, etc.)."""
    if word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 2 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _detect_fk_links(plans: list[dict]) -> list[dict]:
    """Detect FK-style joins between tabular plans by column name patterns.

    For each pair of plans (A, B), looks for columns in A whose names follow
    the pattern ``{TypeB}_id`` or ``{TypeB}_name`` (case-insensitive, singular
    or plural form) and builds a ``fk_links`` spec understood by
    ``run_pipeline``.  Only one edge spec is emitted per (source, target) pair.
    """
    if len(plans) < 2:
        return []

    def _headers(data: bytes) -> list[str]:
        try:
            line = data.split(b"\n")[0].decode("utf-8", "ignore")
            return next(csv.reader(io.StringIO(line)))
        except Exception:  # noqa: BLE001
            return []

    plan_headers = [_headers(p["data"]) for p in plans]
    seen: set[tuple[str, str]] = set()
    links: list[dict] = []

    for i, plan_a in enumerate(plans):
        for j, plan_b in enumerate(plans):
            if i == j:
                continue
            pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
            if pair_key in seen:
                continue
            type_b = plan_b["ontology_type"]
            type_b_l = type_b.lower()
            singular_b = _singular(type_b_l)
            headers_b = plan_headers[j]
            id_col = next((c for c in headers_b if c.lower() in ("id", "uuid", "key")), None)
            name_col = next((c for c in headers_b if c.lower() in ("name", "full_name", "title")), None)
            mk0 = plan_b["match_keys"][0] if plan_b.get("match_keys") else None

            for col in plan_headers[i]:
                col_l = col.lower()
                target_attr: str | None = None
                if col_l in (f"{type_b_l}_id", f"{singular_b}_id"):
                    target_attr = id_col or mk0
                elif col_l in (f"{type_b_l}_name", f"{singular_b}_name"):
                    target_attr = name_col or mk0
                elif col_l in (type_b_l, singular_b) and (id_col or name_col):
                    target_attr = id_col or name_col
                if not target_attr:
                    continue
                seen.add(pair_key)
                src_upper = plan_a["ontology_type"].upper()
                links.append({
                    "source_type": plan_a["ontology_type"],
                    "source_attr": col,
                    "target_type": type_b,
                    "target_attr": target_attr,
                    "name": f"{src_upper}_HAS_{type_b.upper()}",
                })
                break

    return links


def ingest_confirmed(data: dict[str, Any], approved_types: list[str],
                     approved_files: list[str], broker: Broker, jobs, job_id: str,
                     workspace_id: int = 1) -> None:
    """Resolve + project the approved discovered types and tabular files."""
    settings = get_settings()
    total = max(len(approved_types) + len(approved_files), 1)
    step = 0
    for otype in approved_types:
        step += 1
        jobs.update_stage(job_id, f"{step}/{total}", int(step * 90 / total), f"Adding {otype}")
        recs = [m for m in data["mentions"] if m.payload.get("type") == otype]
        if recs:
            run_pipeline(connector=RecordsConnector(recs), dsn=settings.rdb_dsn,
                         system="document", dataset=otype, ontology_type=otype,
                         match_keys=["name"], graph_url=settings.graph_url, broker=broker,
                         workspace_id=workspace_id)

    # Collect valid plans in approval order so FK detection sees the full picture.
    valid_plans = [p for p in
                   (next((p for p in data["tabular"] if p["filename"] == fn), None)
                    for fn in approved_files)
                   if p is not None]
    auto_fk = _detect_fk_links(valid_plans)
    if auto_fk:
        logger.info("auto-detected %d fk-link spec(s): %s", len(auto_fk), auto_fk)

    for idx, plan in enumerate(valid_plans):
        fname = plan["filename"]
        step += 1
        jobs.update_stage(job_id, f"{step}/{total}", int(step * 90 / total), f"Adding {fname}")
        if Path(fname).suffix.lower() == ".json":
            tmp = NamedTemporaryFile(suffix=".json", delete=False)
            tmp.write(plan["data"])
            tmp.close()
            conn = JsonConnector(Path(tmp.name), system="json")
        else:
            conn = CsvConnector(plan["data"], system="csv", dataset=Path(fname).stem)
        # FK links are passed only on the last file: by that point all prior
        # entities are in Postgres so link_by_attribute can match across CSVs.
        is_last = (idx == len(valid_plans) - 1)
        run_pipeline(connector=conn, dsn=settings.rdb_dsn,
                     system=Path(fname).suffix.lstrip("."), dataset=Path(fname).stem,
                     ontology_type=plan["ontology_type"], match_keys=plan["match_keys"],
                     graph_url=settings.graph_url, broker=broker, workspace_id=workspace_id,
                     fk_links=auto_fk if is_last else None)
