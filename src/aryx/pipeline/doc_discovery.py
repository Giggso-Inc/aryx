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
import xml.etree.ElementTree as ET
from collections import Counter
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
            ".html", ".htm",
            ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
DATA_EXTS = {".json", ".csv", ".xml"}


_GENERIC = {"table", "row", "record", "data", "file", "entity", "item", "object",
            "dataset", "export", "import", "report", "sheet", "upload", "dump",
            "output", "input", "sample", "test"}


def _singular(word: str) -> str:
    """Naive singularisation for FK pattern matching (Customers→Customer, etc.)."""
    if word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 2 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


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
        if s == -1 or e <= s:
            raise ValueError("LLM response contained no JSON object")
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


def _xml_to_csv_bytes(data: bytes) -> bytes:
    """Single-type XML → CSV (kept for file_ingest_api backward compat)."""
    results = _xml_to_csvs(data, "data")
    return results[0][0] if results else data


def _xml_to_csvs(data: bytes, stem: str) -> list[tuple[bytes, str]]:
    """Parse XML and emit one CSV per top-3 most-frequent element type.

    Each CSV gets a ``{parent_tag}_id`` column so that _detect_fk_links can
    wire parent→child relationships deterministically, and each entity carries
    its element tag name as ``_element_type`` so the LLM has semantic context
    for relationship inference.  Falls back to a single CSV when the XML has
    fewer than two distinct repeating element types.
    """
    def _strip_ns(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return [(data, stem + ".csv")]

    counts: Counter = Counter()

    def _walk(elem: ET.Element) -> None:
        for child in elem:
            counts[_strip_ns(child.tag)] += 1
            _walk(child)

    _walk(root)
    if not counts:
        return [(data, stem + ".csv")]

    # Pick up to 3 tags that appear at least twice — enough for cross-type links.
    top_tags = [tag for tag, cnt in counts.most_common(5) if cnt >= 2][:3]
    if not top_tags:
        return [(data, stem + ".csv")]

    def _collect_tag(
        elem: ET.Element, tag: str,
        parent_tag: str, parent_attribs: dict,
    ) -> list[dict]:
        """Recursively collect all elements matching *tag*, embedding parent FK.

        The injected column is always named ``{parent_tag}_id`` regardless of
        which parent attribute supplies the value — this guarantees that
        ``_detect_fk_links`` can find the FK by the ``{type}_id`` pattern.
        """
        records: list[dict] = []
        for child in elem:
            ctag = _strip_ns(child.tag)
            if ctag == tag:
                row: dict = {"_element_type": tag}
                # Resolve the best FK value from parent (standard keys first,
                # then fall back to the first available attribute so that XML
                # elements with arbitrary attribute names still get linked).
                fk_val = None
                for pk in ("id", "name", "key", "code"):
                    pv = parent_attribs.get(pk)
                    if pv is not None:
                        fk_val = pv
                        break
                if fk_val is None and parent_attribs:
                    fk_val = next(iter(parent_attribs.values()))
                if fk_val is not None:
                    # Always use {parent_tag}_id so _detect_fk_links matches it.
                    row[f"{parent_tag}_id"] = fk_val
                for k, v in child.attrib.items():
                    row[_strip_ns(k)] = v
                if child.text and child.text.strip():
                    row["_text"] = child.text.strip()
                if len(row) > 1:
                    records.append(row)
            child_attribs = {_strip_ns(k): v for k, v in child.attrib.items()}
            records.extend(_collect_tag(child, tag, _strip_ns(child.tag), child_attribs))
        return records

    root_attribs = {_strip_ns(k): v for k, v in root.attrib.items()}
    root_tag = _strip_ns(root.tag)

    results: list[tuple[bytes, str]] = []
    for target_tag in top_tags:
        records = _collect_tag(root, target_tag, root_tag, root_attribs)
        if not records:
            continue
        all_keys: list[str] = []
        seen_keys: set[str] = set()
        for rec in records:
            for k in rec:
                if k not in seen_keys:
                    all_keys.append(k)
                    seen_keys.add(k)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        csv_name = f"{stem}_{target_tag}.csv"
        results.append((buf.getvalue().encode("utf-8"), csv_name))

    return results if results else [(data, stem + ".csv")]


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

    # XML files: expand into one CSV per top-3 element type so that
    # _detect_fk_links can wire cross-type relationships automatically.
    converted_tabular = []
    for d, n in tabular:
        if Path(n).suffix.lower() == ".xml":
            for csv_bytes, csv_name in _xml_to_csvs(d, Path(n).stem):
                converted_tabular.append((csv_bytes, csv_name))
        else:
            converted_tabular.append((d, n))

    tab_plans = [{"filename": n, "data": d,
                  **_infer_type(d[:800].decode("utf-8", "ignore"), n, context)}
                 for d, n in converted_tabular]

    by_type: dict[str, list[str]] = {}
    for m in mentions:
        by_type.setdefault(m.payload["type"], []).append(m.payload["name"])
    types = [{"type": t, "count": len(v), "examples": list(dict.fromkeys(v))[:5]}
             for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))]
    files = [{"filename": p["filename"], "ontology_type": p["ontology_type"]} for p in tab_plans]
    return {"mentions": mentions, "tabular": tab_plans,
            "summary": {"types": types, "files": files}}


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
                # Edge direction in link_by_attribute: target_type → source_type
                # (parent has-child semantics). Name reflects that direction.
                links.append({
                    "source_type": plan_a["ontology_type"],
                    "source_attr": col,
                    "target_type": type_b,
                    "target_attr": target_attr,
                    "name": f"{type_b.upper()}_HAS_{src_upper}",
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
                         workspace_id=workspace_id, relate=True)

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
        tmp_path: Path | None = None
        if Path(fname).suffix.lower() == ".json":
            tmp = NamedTemporaryFile(suffix=".json", delete=False)
            tmp.write(plan["data"])
            tmp.close()
            tmp_path = Path(tmp.name)
            conn = JsonConnector(tmp_path, system="json")
        else:
            conn = CsvConnector(plan["data"], system="csv", dataset=Path(fname).stem)
        # FK links are passed only on the last file: by that point all prior
        # entities are in Postgres so link_by_attribute can match across CSVs.
        is_last = (idx == len(valid_plans) - 1)
        try:
            run_pipeline(connector=conn, dsn=settings.rdb_dsn,
                         system=Path(fname).suffix.lstrip("."), dataset=Path(fname).stem,
                         ontology_type=plan["ontology_type"], match_keys=plan["match_keys"],
                         graph_url=settings.graph_url, broker=broker, workspace_id=workspace_id,
                         fk_links=auto_fk if is_last else None, relate=True)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
