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
import multiprocessing as mp
import re
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from aryx import llm_runtime
from aryx.broker import Broker
from aryx.broker.governor import TokenGovernor
from aryx.config import get_settings
from aryx.connectors.csv_source import CsvConnector
from aryx.connectors.doc_router import DocumentRouterConnector
from aryx.connectors.json_source import JsonConnector
from aryx.connectors.records_source import RecordsConnector
from aryx.ontology.extract import OnProgress
from aryx.pipeline.orchestrate import relate_isolated, run_pipeline
from aryx.store.chunk_store import ChunkStore

logger = logging.getLogger(__name__)

DOC_EXTS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".rtf", ".html", ".htm",
            ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"}
DATA_EXTS = {".json", ".csv", ".xlsx", ".xml"}

_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")
_TAG_RE = re.compile(r"\{[^}]*\}")  # strip XML namespace braces from tag names


def _sheet_slug(title: str) -> str:
    """Collapse a sheet title into a filename-safe slug (Order Items! -> Order_Items)."""
    return _SLUG_RE.sub("_", title).strip("_") or "Sheet"


def xlsx_to_csvs(data: bytes, stem: str) -> list[tuple[bytes, str]]:
    """Split an .xlsx workbook into one CSV per visible, non-empty sheet.

    Each sheet becomes its own ``{stem}__{sheet_slug}.csv`` — from there it's
    just another tabular "file" to the rest of the pipeline (type inference,
    cross-file FK linking, run_pipeline), same as any uploaded .csv.
    """
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        out: list[tuple[bytes, str]] = []
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            rows_iter = ws.iter_rows(values_only=True)
            try:
                header_row = next(rows_iter)
            except StopIteration:
                continue  # empty sheet
            header = [str(h).strip() if h is not None else "" for h in header_row]
            if not any(header):
                continue  # no real header row
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(header)
            row_count = 0
            for row in rows_iter:
                if row is None or all(v is None for v in row):
                    continue
                writer.writerow(["" if v is None else v for v in row])
                row_count += 1
            if row_count == 0:
                continue  # header-only / template sheet
            csv_name = f"{stem}__{_sheet_slug(ws.title)}.csv"
            out.append((buf.getvalue().encode("utf-8"), csv_name))
        return out
    finally:
        wb.close()


def expand_xlsx(items: list[tuple[bytes, str]]) -> list[tuple[bytes, str]]:
    """Replace each .xlsx entry with its per-sheet CSVs; pass everything else through."""
    out: list[tuple[bytes, str]] = []
    for data, name in items:
        if Path(name).suffix.lower() == ".xlsx":
            sheets = xlsx_to_csvs(data, Path(name).stem)
            if not sheets:
                logger.warning("xlsx %s had no usable sheets — skipping", name)
                continue
            out.extend(sheets)
        else:
            out.append((data, name))
    return out


def _chunk_csv_bytes(data: bytes, chunk_rows: int) -> list[bytes]:
    """Split CSV bytes into chunks of at most ``chunk_rows`` data rows, repeating the header.

    Streams rows via ``itertools.islice`` so the full file is never
    materialised into a list — only one batch is held in memory at a time.
    Returns ``[data]`` unchanged when chunking is disabled or the file has no
    parseable header row.
    """
    import itertools

    if chunk_rows <= 0:
        return [data]
    reader = csv.reader(io.StringIO(data.decode("utf-8", "ignore")))
    try:
        header = next(reader)
    except StopIteration:
        return [data]
    chunks: list[bytes] = []
    while True:
        batch = list(itertools.islice(reader, chunk_rows))
        if not batch:
            break
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)
        writer.writerows(batch)
        chunks.append(buf.getvalue().encode("utf-8"))
    return chunks or [data]


def expand_data_files(items: list[tuple[bytes, str]]) -> list[tuple[bytes, str]]:
    """Replace .xlsx/.xml entries with their derived per-sheet/per-type CSVs.

    Everything downstream (type inference, cross-file FK linking,
    ``run_pipeline``) only ever sees flat CSV/JSON "files" — it never needs to
    know a workbook or an XML document was involved.
    """
    out: list[tuple[bytes, str]] = []
    for data, name in items:
        suffix = Path(name).suffix.lower()
        if suffix == ".xlsx":
            sheets = xlsx_to_csvs(data, Path(name).stem)
            if not sheets:
                logger.warning("xlsx %s had no usable sheets — skipping", name)
                continue
            out.extend(sheets)
        elif suffix == ".xml":
            tables = _xml_to_csvs(data, Path(name).stem)
            if not tables:
                logger.warning("xml %s had no detectable entity rows — skipping", name)
                continue
            out.extend(tables)
        else:
            out.append((data, name))
    return out


def _xml_element_tag(el) -> str:
    return _TAG_RE.sub("", el.tag)


def _xml_to_csvs(data: bytes, stem: str) -> list[tuple[bytes, str]]:
    """Extract repeating XML elements into one CSV per detected entity type.

    An element tag is treated as an "entity type" when it repeats 2+ times
    under the same parent — each occurrence becomes one row, its child
    elements/attributes become columns, and a ``{parent_tag}_id`` column is
    injected using the parent's own identifying attribute/child (falling back
    to a synthetic running index) so cross-type foreign keys survive into the
    flat CSV world the rest of the pipeline understands.

    Bounded by ``settings.xml_max_entity_types``/``xml_max_rows_per_type`` so
    a pathological or deeply-nested document can't blow up the batch.
    """
    from xml.etree import ElementTree as ET

    settings = get_settings()
    try:
        root = ET.fromstring(data)
    except Exception:  # noqa: BLE001
        logger.warning("xml %s failed to parse — skipping structured extraction", stem)
        return []

    # tag -> list of (element, parent_key) rows
    groups: dict[str, list[tuple[Any, str]]] = {}

    def _row_key(el, fallback: str) -> str:
        for attr in ("id", "Id", "ID", "code", "Code", "name", "Name"):
            if attr in el.attrib:
                return el.attrib[attr]
        for child in list(el):
            if not len(child) and (child.text or "").strip():
                return child.text.strip()
        return fallback

    def _walk(el, parent_key: str) -> None:
        children_by_tag: dict[str, list] = {}
        for child in list(el):
            children_by_tag.setdefault(_xml_element_tag(child), []).append(child)
        for tag, kids in children_by_tag.items():
            if len(kids) >= 2:
                for i, kid in enumerate(kids):
                    row_key = _row_key(kid, f"{parent_key}:{tag}:{i}")
                    groups.setdefault(tag, []).append((kid, parent_key))
                    _walk(kid, row_key)
            else:
                _walk(kids[0], parent_key)

    _walk(root, _row_key(root, "root"))

    # Keep the biggest groups first — those are the real repeating entities.
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))[: settings.xml_max_entity_types]
    out: list[tuple[bytes, str]] = []
    for tag, rows in ranked:
        rows = rows[: settings.xml_max_rows_per_type]
        fieldnames: list[str] = []
        records: list[dict[str, str]] = []
        for el, parent_key in rows:
            record: dict[str, str] = {}
            for k, v in el.attrib.items():
                record[k] = v
            for child in list(el):
                if not len(child):
                    record[_xml_element_tag(child)] = (child.text or "").strip()
            if (el.text or "").strip() and not len(el):
                record["value"] = el.text.strip()
            record["parent_id"] = parent_key
            for k in record:
                if k not in fieldnames:
                    fieldnames.append(k)
            records.append(record)
        if not records:
            continue
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(records)
        out.append((buf.getvalue().encode("utf-8"), f"{stem}_{_sheet_slug(tag)}.csv"))
    return out


_GENERIC = {"table", "row", "record", "data", "file", "entity", "item", "object", "dataset"}


def _infer_type(sample: str, filename: str, context: str) -> dict[str, Any]:
    sys = ("You name the real-world thing each ROW of a data file represents, "
           "for a knowledge graph.")
    user = (f"Goal: {context or 'general knowledge graph'}\nFile: {filename}\n"
            f"Sample rows:\n{sample[:600]}\n\nWhat real-world entity is each row? "
            "Use a concrete singular noun like Customer, Company, Product, Order — "
            "NEVER generic words like Table, Row, Record, or Data. Reply ONLY as JSON "
            '{"ontology_type":"SingularPascalCase","match_keys":["the 1-2 columns '
            'that name/identify a row"]}.')
    fallback = Path(filename).stem.replace("_", " ").title().replace(" ", "")
    try:
        txt = llm_runtime.chat("menial", sys, user)[0]
        s, e = txt.find("{"), txt.rfind("}")
        d = json.loads(txt[s:e + 1])
        otype = (d.get("ontology_type") or "").strip()
        if not otype or otype.lower() in _GENERIC:
            otype = fallback
        return {"ontology_type": otype, "match_keys": _clean_keys(d.get("match_keys"))}
    except Exception:  # noqa: BLE001
        return {"ontology_type": fallback, "match_keys": ["name"]}


def _clean_keys(raw: Any) -> list[str]:
    """Coerce a model's match_keys to a flat list of non-empty column strings.

    The small local model sometimes returns a bare string or a nested list;
    an unhashable element (a list) later blows up ``payload.get(key)`` with
    'unhashable type: list'. Flatten one level, keep only scalar names.
    """
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ["name"]
    keys: list[str] = []
    for k in raw:
        for item in (k if isinstance(k, list) else [k]):
            if isinstance(item, (str, int, float)) and str(item).strip():
                keys.append(str(item).strip())
    return keys or ["name"]


def _singular_stem(type_name: str) -> str:
    """Lowercase singular stem of a type name for FK-column name matching."""
    t = type_name.lower()
    if t.endswith("ies"):
        return t[:-3]          # Companies -> compan(y)
    if t.endswith("s") and not t.endswith("ss"):
        return t[:-1]          # Customers -> customer
    return t


def infer_fk_links(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Discover foreign-key links across ingested tabular files by value overlap.

    Deterministic — no LLM (small local models return unstable column names and
    directions). A link ``src.col -> tgt.col`` is proposed when:
      * the target column is a candidate key (all values distinct, ≥2 rows),
      * most of the source column's values are contained in it, and
      * the source column name references the target type (typical FK naming,
        e.g. ``CustomerID`` -> ``Customer``), which also fixes direction so a
        shared natural key (``Company`` on both sides) links only one way.
    ``link_by_attribute`` still materializes edges only on exact value matches,
    so the proposal can never create a spurious edge.

    Args:
        files: One dict per file with ``ontology_type`` and ``colvals``
            (mapping column name -> list of that column's raw values).

    Returns:
        A list of ``{source_type, source_attr, target_type, target_attr,
        name}`` specs (possibly empty).
    """
    if len(files) < 2:
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for src in files:
        for tgt in files:
            if src is tgt:
                continue
            tstem = _singular_stem(tgt["ontology_type"])
            for tcol, tvals in (tgt.get("colvals") or {}).items():
                tset = {v for v in tvals if v}
                # Target column must be a candidate key: distinct, non-trivial.
                if len(tset) < 2 or len(tset) != len([v for v in tvals if v]):
                    continue
                for scol, svals in (src.get("colvals") or {}).items():
                    sset = {v for v in svals if v}
                    if not sset or len(sset & tset) / len(sset) < 0.6:
                        continue
                    # Direction via FK naming: the source column names the
                    # target entity (CustomerID->Customer, Company->Company).
                    if len(tstem) < 3 or tstem not in scol.lower().replace("_", ""):
                        continue
                    key = (src["ontology_type"], scol, tgt["ontology_type"], tcol)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "source_type": src["ontology_type"], "source_attr": scol,
                        "target_type": tgt["ontology_type"], "target_attr": tcol,
                        "name": f"{src['ontology_type']}_{tgt['ontology_type']}".upper(),
                    })
    logger.info("discovered %d fk-link(s)", len(out))
    return out


def read_files(doc_paths: list[Path], tabular: list[tuple[bytes, str]],
               broker: Broker, context: str,
               on_progress: OnProgress | None = None) -> dict[str, Any]:
    """Read everything; return {mentions, tabular, summary} without committing.

    on_progress: optional (completed, total, new_records) callback fired as
    document chunks finish extracting, so a caller (e.g. a job store) can
    report/persist progress incrementally on large documents instead of only
    once reading finishes.
    """
    settings = get_settings()
    tabular = expand_xlsx(tabular)
    mentions = []
    if doc_paths:
        connector = DocumentRouterConnector(
            paths=doc_paths, system="document", broker=broker,
            chunk_store=ChunkStore(settings.rdb_dsn), chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap, expected_embed_dim=settings.embed_dim,
            context=context, on_progress=on_progress)
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


def _connector_for_tabular_file(fname: str, plan: dict[str, Any]):
    """Build the right connector for one approved tabular file's plan."""
    if Path(fname).suffix.lower() == ".json":
        tmp = NamedTemporaryFile(suffix=".json", delete=False)
        tmp.write(plan["data"])
        tmp.close()
        return JsonConnector(Path(tmp.name), system="json")
    return CsvConnector(plan["data"], system="csv", dataset=Path(fname).stem)


def _run_one_tabular_file(fname: str, plan: dict[str, Any], settings, broker: Broker,
                          workspace_id: int, skip_graph: bool) -> None:
    conn = _connector_for_tabular_file(fname, plan)
    run_pipeline(connector=conn, dsn=settings.rdb_dsn,
                 system=Path(fname).suffix.lstrip("."), dataset=Path(fname).stem,
                 ontology_type=plan["ontology_type"], match_keys=plan["match_keys"],
                 graph_url=settings.graph_url, broker=broker, workspace_id=workspace_id,
                 skip_graph=skip_graph)


def _build_pool(max_workers: int) -> ProcessPoolExecutor:
    """Default pool factory for ingest_confirmed()'s concurrent tabular-file
    batch. Pinned to the "spawn" start method explicitly rather than relying
    on the platform default. Overridable via ingest_confirmed's private
    _pool_factory param — tests inject a ThreadPoolExecutor instead, since a
    real ProcessPoolExecutor requires every submitted arg to be picklable
    and runs in a fresh interpreter that never sees unittest.mock.patch()
    substitutions made in the test process."""
    return ProcessPoolExecutor(max_workers=max_workers, mp_context=mp.get_context("spawn"))


def _submit_batch(pool: ThreadPoolExecutor | ProcessPoolExecutor,
                  non_last: list[tuple[str, dict[str, Any]]], settings, broker: Broker,
                  workspace_id: int, failures: list[str],
                  _target=_run_one_tabular_file) -> None:
    """Submit every non-last file to `pool` and collect (not raise) failures.

    _target is overridable for testing: a real ProcessPoolExecutor requires
    a picklable, importable-by-name callable, and _run_one_tabular_file
    reaches real Postgres/FalkorDB — a test exercising only the cross-process
    budget-sharing plumbing (see _run_non_last_batch) substitutes a trivial
    module-level stand-in instead.
    """
    futures = {
        pool.submit(_target, fname, plan, settings, broker,
                   workspace_id, True): fname
        for fname, plan in non_last
    }
    for fut in as_completed(futures):
        fname = futures[fut]
        try:
            fut.result()
        except Exception as exc:  # noqa: BLE001 — isolate one bad file, don't sink the batch
            logger.warning("ingest_confirmed: file %s failed: %s", fname, exc)
            failures.append(f"{fname}: {exc}")


def _run_non_last_batch(pool: ThreadPoolExecutor | ProcessPoolExecutor,
                        non_last: list[tuple[str, dict[str, Any]]], settings, broker: Broker,
                        workspace_id: int, failures: list[str],
                        _target=_run_one_tabular_file) -> None:
    """Run the non-last-file batch against `pool`.

    If `pool` is a real ProcessPoolExecutor, `broker` gets pickled into each
    worker — including its own copy of broker._governor, whose _spent
    counter would then silently stop being shared, letting the per-job
    token budget be exceeded by up to `ingest_workers`x (each worker starts
    unspent). So the broker handed to the batch is rebuilt with a
    multiprocessing.Manager()-backed governor first: a Manager dict/lock
    pickles as a proxy back to the one manager process, so charge() from
    any worker still lands in a single real shared counter. The batch's
    final spend is folded back into the original (real, in-process)
    governor once every future has resolved, so a caller using the
    original broker afterward (e.g. ingest_confirmed's last file) sees it.

    A same-process pool (e.g. a test double) skips all of this — broker
    already shares memory, no governor rebuild needed.
    """
    if isinstance(pool, ProcessPoolExecutor):
        with mp.Manager() as manager:
            shared_governor = TokenGovernor(
                broker.governor.budgets,
                spent=manager.dict(broker.governor.spend_snapshot()),
                lock=manager.Lock(),
            )
            batch_broker = broker.with_governor(shared_governor)
            _submit_batch(pool, non_last, settings, batch_broker, workspace_id, failures, _target)
            broker.governor.replace_spend(dict(shared_governor.spend_snapshot()))
    else:
        _submit_batch(pool, non_last, settings, broker, workspace_id, failures, _target)


def ingest_confirmed(data: dict[str, Any], approved_types: list[str],
                     approved_files: list[str], broker: Broker, jobs, job_id: str,
                     workspace_id: int = 1, _pool_factory=_build_pool) -> None:
    """Resolve + project the approved discovered types and tabular files.

    Tabular files run land+resolve concurrently (ARYX_INGEST_WORKERS worker
    processes) — all but the last file skip the FalkorDB projection stage
    (skip_graph=True) since project_graph() rebuilds the ENTIRE workspace
    graph and two concurrent calls would race and corrupt each other. The
    last file runs afterward, once every concurrent file has finished
    landing its entities in Postgres, and does the single graph projection
    that picks up everyone's data (EntityStore.list_entities() is
    workspace-scoped, not run-scoped, so one projection after the fact is
    correct regardless of how many files fed into it).

    The concurrent batch runs in a ProcessPoolExecutor, not threads: land+
    resolve (blocking, pairwise scoring, clustering, survivorship) is
    CPU-bound Python, which under a ThreadPoolExecutor just pegs one core on
    GIL contention instead of actually parallelizing. Passing `broker`
    across a process boundary means each worker gets its own pickled copy —
    including its own copy of broker._governor, whose _spent counter would
    then silently stop being shared, letting the per-job token budget be
    exceeded by up to `ingest_workers`x (each worker starts unspent). So the
    broker handed to the concurrent batch is rebuilt with a
    multiprocessing.Manager()-backed governor first: a Manager dict/lock
    pickles as a proxy back to the one manager process, so charge() from any
    worker still lands in a single real shared counter. The batch's final
    spend is folded back into the original (real, in-process) governor
    before the last file runs, so it sees the combined total.
    """
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

    valid_files: list[tuple[str, dict[str, Any]]] = []
    for fname in approved_files:
        step += 1
        plan = next((p for p in data["tabular"] if p["filename"] == fname), None)
        if plan is not None:
            valid_files.append((fname, plan))

    # Collected, not raised immediately: one bad file must not sink the rest
    # of a concurrent batch, and relate_isolated below still needs to run for
    # whatever DID land. But the job must not silently report "complete" if
    # an approved file was dropped — see the raise at the end of this
    # function, which surfaces every failure to the caller so the job is
    # correctly marked failed instead of a false-positive success.
    failures: list[str] = []
    if valid_files:
        non_last, last = valid_files[:-1], valid_files[-1]
        if non_last:
            jobs.update_stage(job_id, f"{total}/{total}", int((total - 1) * 90 / total),
                              f"Adding {len(non_last)} file(s) in parallel")
            with _pool_factory(settings.ingest_workers) as pool:
                _run_non_last_batch(pool, non_last, settings, broker, workspace_id, failures)
        last_fname, last_plan = last
        jobs.update_stage(job_id, f"{total}/{total}", 90, f"Adding {last_fname}")
        try:
            _run_one_tabular_file(last_fname, last_plan, settings, broker, workspace_id, False)
        except Exception as exc:  # noqa: BLE001 — still run relate_isolated for whatever landed
            logger.warning("ingest_confirmed: file %s failed: %s", last_fname, exc)
            failures.append(f"{last_fname}: {exc}")

    # Deliberately unconditional — guarantees no entity from this confirm
    # batch is left with zero relationships.
    if approved_types or approved_files:
        jobs.update_stage(job_id, "Link", 95, "Checking for isolated entities")
        relate_isolated(settings.rdb_dsn, settings.graph_url, workspace_id, broker)

    if failures:
        raise RuntimeError(
            f"{len(failures)} of {len(valid_files)} approved file(s) failed to ingest: "
            + "; ".join(failures)
        )
