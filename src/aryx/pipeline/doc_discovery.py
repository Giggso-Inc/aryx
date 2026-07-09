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
import re
import xml.etree.ElementTree as ET
import defusedxml.ElementTree as defused_ET
from collections import Counter
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from aryx import llm_runtime
from concurrent.futures import ThreadPoolExecutor, as_completed

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.connectors.csv_source import CsvConnector
from aryx.connectors.doc_router import DocumentRouterConnector
from aryx.connectors.json_source import JsonConnector
from aryx.connectors.records_source import RecordsConnector
from aryx.pipeline.orchestrate import run_pipeline
from aryx.store.chunk_store import ChunkStore
from aryx.store.datasource_store import DatasourceStore
from aryx.store.ontology_store import OntologyStore
from aryx.source_catalog import (
    restore_generic_source_entry,
    upsert_xml_catalog_entry,
    xml_asset_record,
)

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


_KEY_SUFFIXES = ("_code", "_id", "_key", "_num", "_ref", "_no", "_cage")


def _guess_key_col(sample: str) -> str:
    """Heuristic: return the most likely natural-key column from a CSV header.

    Checks the first few columns for common ID/code suffixes before defaulting
    to the first column, which is almost always the primary key in structured
    tabular exports.
    """
    try:
        first_line = sample.split("\n")[0]
        headers = next(csv.reader(io.StringIO(first_line)))
        for h in headers[:6]:
            if any(h.lower().endswith(sfx) for sfx in _KEY_SUFFIXES):
                return h
        return headers[0] if headers else "name"
    except Exception:  # noqa: BLE001
        return "name"


def _id_priority_mk(sample: str, mk: list[str]) -> list[str]:
    """Promote an explicit 'id'/'uuid'/'guid' column to primary match_key.

    When a CSV has an explicit PK column the LLM sometimes picks a FK column
    (e.g. bm_config_rule_id) instead.  In Pass 2 FK detection that causes
    sibling entities sharing the same parent FK to appear as parent-child pairs,
    creating thousands of false edges.  Returning 'id' early avoids this because
    short keys like 'id' have mk_stem length < 3 and are skipped by Pass 2.
    """
    if mk and mk[0].lower() in ("id", "uuid", "guid"):
        return mk
    try:
        hdr_line = sample.split("\n")[0]
        hdrs = next(csv.reader(io.StringIO(hdr_line)), [])
        id_hdr = next((h for h in hdrs[:8] if h.lower() in ("id", "uuid", "guid")), None)
        if id_hdr:
            return [id_hdr]
    except Exception:  # noqa: BLE001
        pass
    return mk


def _infer_type(sample: str, filename: str, context: str, did: str | None = None) -> dict[str, Any]:
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
        mk = d.get("match_keys")
        if not mk:
            mk = [_guess_key_col(sample)]
        result = {"ontology_type": otype, "match_keys": _id_priority_mk(sample, mk)}
        logger.info("infer_type did=%s file=%s otype=%s match_keys=%s source=%s",
                    did, filename, result["ontology_type"], result["match_keys"],
                    "filename" if use_filename_type else "llm")
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("infer_type did=%s file=%s LLM inference failed, falling back to otype=%s: %s",
                        did, filename, fallback, exc)
        return {"ontology_type": fallback,
                "match_keys": _id_priority_mk(sample, [_guess_key_col(sample)])}


def _xml_to_csvs(data: bytes, stem: str, log_id: str | None = None) -> list[tuple[bytes, str]]:
    """Parse XML → one CSV per discovered entity element type.

    Handles three common XML patterns that the naive approach misses:
    - ``_children`` wrapper tags (transparent containers, not entity types)
    - Multilingual CDATA fields (``<name><en><![CDATA[...]]></en>...</name>``)
    - Data stored in child element text rather than XML element attributes

    Entity type detection: an element is classified as an entity when it has
    ≥2 distinct non-container child element types.  This excludes scalar leaf
    elements (``<id>123</id>``) and locale-wrapper elements (``<name>``).

    Each entity row gets a ``{parent_tag}_id`` FK column injected so that
    ``_detect_fk_links`` can wire parent→child edges automatically.
    """
    # ISO locale tags used as multilingual value wrappers — not entity types.
    _LOCALE_TAGS: frozenset[str] = frozenset({
        "en", "de", "fr", "es", "it", "da", "nl", "sv", "no", "fi", "pl", "cs",
        "ru", "tr", "ar", "he",
        # bare 2-letter codes used by Oracle CPQ / BigMachines exports
        "ja", "ko", "zh", "pt",
        "ja_JP", "zh_CN", "zh_HK", "zh_TW", "zh_SG", "ko_KR", "da_DK",
        "pt_BR", "pt_PT", "fr_CA", "es_CO",
    })
    # HTML/embedded tags whose text content must never become entity fields or
    # entity types — script/style bodies are code, not data.
    _SKIP_TAGS: frozenset[str] = frozenset({
        "script", "style", "head", "meta", "link", "noscript",
    })

    def _strip_ns(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    def _is_container(tag: str) -> bool:
        """True for transparent wrapper tags that are not entity types."""
        return tag.startswith("_") or tag in _LOCALE_TAGS

    def _extract_field(child: ET.Element) -> str | None:
        """Extract a scalar string from a child element.

        If the element has locale sub-children (multilingual field), prefer
        ``<en>`` CDATA; fall back to the first non-empty locale value.
        Otherwise return the element's own text content.
        """
        sub = list(child)
        if sub:
            sub_tags = {_strip_ns(c.tag) for c in sub}
            if sub_tags & _LOCALE_TAGS:
                en = next((c for c in sub if _strip_ns(c.tag) == "en"), None)
                if en is not None and en.text and en.text.strip():
                    return en.text.strip()
                for c in sub:
                    if c.text and c.text.strip():
                        return c.text.strip()
                return None
            return None  # non-locale children → nested entity, not a scalar value
        if _strip_ns(child.tag) in _SKIP_TAGS:
            return None
        return child.text.strip() if child.text and child.text.strip() else None

    def _elem_id(elem: ET.Element) -> str | None:
        """Return the best ID value for ``elem`` (check child elements first)."""
        for pk in ("id", "guid"):
            for c in elem:
                if _strip_ns(c.tag) == pk:
                    v = _extract_field(c)
                    if v:
                        return v
            v = elem.attrib.get(pk)
            if v:
                return v
        return None

    def _is_entity(elem: ET.Element) -> bool:
        """True when ``elem`` represents a data record.

        Complex entities: ≥2 distinct non-container child element types.
        Attribute-only leaf entities: no child elements AND ≥1 XML attribute
        (e.g. ``<Widget id="1" name="alpha"/>``).

        Text-only nodes (e.g. ``<id>123</id>``, ``<date_modified>...``) are
        deliberately excluded — they are scalar field values of their parent
        entity, not stand-alone records.  Counting them as entities inflates
        row counts by tens of thousands and breaks type selection.
        """
        child_tags = {_strip_ns(c.tag) for c in elem if not _is_container(_strip_ns(c.tag))}
        if child_tags:
            return len(child_tags) >= 2
        return len(elem.attrib) >= 1

    try:
        root = defused_ET.fromstring(data)
    except ET.ParseError as exc:
        logger.warning("xml_to_csvs log_id=%s stem=%s parse failed, treating as raw upload: %s",
                        log_id, stem, exc)
        return [(data, stem + ".csv")]

    # Candidate fields to use as entity name when no ``name`` field exists.
    # Ordered by priority; first non-trivial value wins.  Generic fields
    # come first; the ``bm_*`` / CPQ-specific entries are additive hints
    # that match BigMachines exports and are silently skipped on other data.
    _NAME_CANDIDATES = (
        "variable_name", "var_name",
        "item_text", "item_value",
        "prop_value", "property_value", "prop_type",
        "label", "file_name", "relative_path",
        # CPQ/BigMachines-specific — degrade gracefully on non-BM data:
        "bm_variable_name", "bm_name", "func_name", "rule_name",
        "java_class_name",
    )
    _NAME_CANDIDATE_SET: frozenset[str] = frozenset(_NAME_CANDIDATES) | {"name"}
    _TRIVIAL = frozenset({"0", "1", "2", "true", "false", ""})

    def _alias_name(row: dict) -> None:
        """Set ``row['name']`` from the best available display field if absent."""
        if row.get("name"):
            return
        for cand in _NAME_CANDIDATES:
            val = row.get(cand)
            if val and str(val) not in _TRIVIAL:
                row["name"] = val
                return

    counts: Counter = Counter()
    type_has_name: dict[str, bool] = {}
    root_tag = _strip_ns(root.tag)

    def _check_name(elem: ET.Element, tag: str) -> None:
        """Set type_has_name[tag]=True once any element carries a name-candidate field."""
        if not type_has_name.get(tag, False):
            has = any(
                _strip_ns(c.tag) in _NAME_CANDIDATE_SET
                for c in elem
                if not _is_container(_strip_ns(c.tag))
            )
            if not has:
                has = any(k in _NAME_CANDIDATE_SET for k in elem.attrib)
            if has:
                type_has_name[tag] = True
            else:
                type_has_name.setdefault(tag, False)

    if _is_entity(root):
        counts[root_tag] += 1
        _check_name(root, root_tag)

    def _walk(elem: ET.Element) -> None:
        for child in elem:
            ctag = _strip_ns(child.tag)
            if ctag in _SKIP_TAGS:
                continue
            if _is_container(ctag):
                _walk(child)
            elif _is_entity(child):
                counts[ctag] += 1
                _check_name(child, ctag)
                _walk(child)

    _walk(root)
    if not counts:
        logger.warning(
            "xml_to_csvs log_id=%s stem=%s no entity elements detected "
            "(all leaves/containers), falling back to raw upload", log_id, stem)
        return [(data, stem + ".csv")]

    # Prefer entity types that carry a human-readable name field over pure
    # junction tables (id-only FKs).  Named types first by frequency, then
    # unnamed to fill remaining slots.  Cap is configurable via
    # ARYX_XML_MAX_ENTITY_TYPES (default 20) so large CPQ/ERP exports with
    # 20+ entity types are not silently truncated.
    _settings = get_settings()
    _xml_max_types = _settings.xml_max_entity_types
    _xml_max_rows = _settings.xml_max_rows_per_type
    _all_by_freq = [t for t, _ in counts.most_common()]
    _named = [t for t in _all_by_freq if type_has_name.get(t, False)]
    _unnamed = [t for t in _all_by_freq if not type_has_name.get(t, False)]
    top_tags = (_named + _unnamed)[:_xml_max_types]

    def _collect_tag(
        elem: ET.Element, tag: str, parent_tag: str, parent_id: str | None,
    ) -> list[dict]:
        """Recursively collect all elements matching *tag* with parent FK."""
        records: list[dict] = []
        for child in elem:
            ctag = _strip_ns(child.tag)
            if _is_container(ctag):
                # Transparent container: recurse with the same parent context so
                # that ``_children`` wrappers do not reset the FK lineage.
                records.extend(_collect_tag(child, tag, parent_tag, parent_id))
            elif ctag == tag:
                my_id = _elem_id(child)
                row: dict = {"_element_type": tag}
                if parent_id is not None:
                    row[f"{parent_tag}_id"] = parent_id
                # XML element attributes (e.g. <elem attr="val"/>)
                for k, v in child.attrib.items():
                    row[_strip_ns(k)] = v
                # Child element text values (e.g. <id>123</id>, multilingual)
                for sub in child:
                    stag = _strip_ns(sub.tag)
                    if _is_container(stag) or stag in _SKIP_TAGS:
                        continue
                    val = _extract_field(sub)
                    if val is not None:
                        row[stag] = val
                # Ensure every entity has a human-readable ``name`` field.
                _alias_name(row)
                if len(row) > 1:
                    records.append(row)
                # Recurse into this element's subtree for nested same-type entities.
                records.extend(_collect_tag(child, tag, ctag, my_id))
            else:
                # Different entity type: recurse, updating the parent context.
                child_id = _elem_id(child)
                records.extend(_collect_tag(child, tag, ctag, child_id))
        return records

    # Do NOT fall back to root_tag when root has no real id: injecting
    # {root_tag}_id = root_tag (a constant non-id string) into all child rows
    # creates a spurious FK column that link_by_attribute can never satisfy,
    # making child entities appear as candidates for FK joining but producing
    # zero edges.  Leaving root_id=None means no FK column is injected for
    # direct children of a root with no id, which is the correct behaviour.
    root_id = _elem_id(root)
    results: list[tuple[bytes, str]] = []
    total_rows = 0

    for target_tag in top_tags:
        if target_tag == root_tag:
            # Root element itself is the entity — extract one row directly.
            row: dict = {"_element_type": root_tag}
            for k, v in root.attrib.items():
                row[_strip_ns(k)] = v
            for sub in root:
                stag = _strip_ns(sub.tag)
                if _is_container(stag):
                    continue
                val = _extract_field(sub)
                if val is not None:
                    row[stag] = val
            _alias_name(row)
            records = [row] if len(row) > 1 else []
        else:
            records = _collect_tag(root, target_tag, root_tag, root_id)

        if not records:
            continue
        if len(records) > _xml_max_rows:
            logger.warning(
                "xml log_id=%s: %s has %d rows, capping at %d (set ARYX_XML_MAX_ROWS_PER_TYPE to change)",
                log_id, target_tag, len(records), _xml_max_rows,
            )
            records = records[:_xml_max_rows]
        total_rows += len(records)
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

    if not results:
        logger.warning(
            "xml_to_csvs log_id=%s stem=%s %d candidate type(s) considered but 0 rows "
            "collected, falling back to raw upload", log_id, stem, len(top_tags))
        return [(data, stem + ".csv")]
    logger.info(
        "xml_to_csvs log_id=%s stem=%s detected_types=%d capped_to=%d output_csvs=%d rows_total=%d",
        log_id, stem, len(counts), len(top_tags), len(results), total_rows)
    return results


def _consolidate_csv_names(data: bytes, did: str | None = None) -> bytes:
    """Merge multi-part name columns into a single ``name`` field.

    Handles patterns like COMPANY_NAME / COMPANY_NAME_2 … COMPANY_NAME_5
    produced by government/defense data exports where a long name is split
    across several continuation columns.  The first part column becomes
    ``name``; continuation parts are appended (space-separated) then dropped.
    """
    try:
        text = data.decode("utf-8", "ignore")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return data
        headers = list(reader.fieldnames)

        # Find multi-part name groups: columns whose names differ only by a
        # trailing _2 / _3 / _4 / _5 suffix (e.g. COMPANY_NAME, COMPANY_NAME_2).
        base_names: dict[str, list[str]] = {}
        for h in headers:
            m = re.match(r"^(.+?)(?:_[2-9]|_\d{2,})$", h)
            if m:
                base = m.group(1)
                if base in headers:
                    base_names.setdefault(base, []).append(h)

        if not base_names:
            return data

        rows = list(reader)
        out_headers = [h for h in headers if not any(h in parts for parts in base_names.values())]
        if "name" not in [h.lower() for h in out_headers]:
            # Insert 'name' right after the base column
            for base in base_names:
                if base in out_headers:
                    idx = out_headers.index(base)
                    out_headers.insert(idx + 1, "name")
                    break

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=out_headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            for base, continuations in base_names.items():
                parts = [row.get(base, "").strip()]
                for cont in continuations:
                    v = row.get(cont, "").strip()
                    if v:
                        parts.append(v)
                full = " ".join(p for p in parts if p)
                row[base] = full
                # Also set 'name' if not already present in this row
                if "name" not in row or not row["name"]:
                    row["name"] = full
            writer.writerow(row)
        logger.info("consolidate_csv_names did=%s merged_groups=%d columns=%s rows=%d",
                    did, len(base_names), list(base_names.keys()), len(rows))
        return buf.getvalue().encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("consolidate_csv_names did=%s failed, returning original data unmodified: %s",
                        did, exc)
        return data


def read_files(doc_paths: list[Path], tabular: list[tuple[bytes, str]],
               broker: Broker, context: str, did: str | None = None) -> dict[str, Any]:
    """Read everything; return {mentions, tabular, summary} without committing."""
    settings = get_settings()
    logger.info("read_files start did=%s doc_files=%d tabular_files=%d context=%r",
                did, len(doc_paths), len(tabular), context)
    mentions = []
    if doc_paths:
        connector = DocumentRouterConnector(
            paths=doc_paths, system="document", broker=broker,
            chunk_store=ChunkStore(settings.rdb_dsn), chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap, expected_embed_dim=settings.embed_dim,
            context=context)
        mentions = list(connector.extract())

    # XML files: expand into one CSV per top-N element type so that
    # _detect_fk_links can wire cross-type relationships automatically.
    # CSV files: apply name-field consolidation for multi-part name columns.
    converted_tabular = []
    for d, n in tabular:
        if Path(n).suffix.lower() == ".xml":
            for csv_bytes, csv_name in _xml_to_csvs(d, Path(n).stem, log_id=did):
                converted_tabular.append((csv_bytes, csv_name, n, d))
        else:
            converted_tabular.append((_consolidate_csv_names(d, did=did), n, None, None))

    tab_plans = []
    for data, filename, source_filename, source_bytes in converted_tabular:
        inferred = _infer_type(data[:800].decode("utf-8", "ignore"), filename, context, did=did)
        plan = {"filename": filename, "data": data, **inferred}
        if source_filename is not None and source_bytes is not None:
            plan["source_filename"] = source_filename
            plan["source_bytes"] = source_bytes
            try:
                headers = next(csv.reader(io.StringIO(data.decode("utf-8", "ignore"))))
            except Exception:  # noqa: BLE001
                headers = []
            if "_text" in headers:
                plan["match_keys"] = ["_text"]
        tab_plans.append(plan)

    by_type: dict[str, list[str]] = {}
    for m in mentions:
        by_type.setdefault(m.payload["type"], []).append(m.payload["name"])
    types = [{"type": t, "count": len(v), "examples": list(dict.fromkeys(v))[:5]}
             for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))]
    files = [{"filename": p["filename"], "ontology_type": p["ontology_type"]} for p in tab_plans]
    logger.info("read_files done did=%s mentions=%d tabular_plans=%d types=%d files=%d",
                did, len(mentions), len(tab_plans), len(types), len(files))
    return {"mentions": mentions, "tabular": tab_plans,
            "summary": {"types": types, "files": files}}


def _detect_fk_links(plans: list[dict], log_id: str | None = None) -> list[dict]:
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

    def _col_is_varying(data: bytes, headers: list[str], col: str,
                        sample: int = 20) -> bool:
        """Return True if *col* has at least 2 distinct non-empty values in the
        first *sample* data rows.  Columns with a single constant value (e.g.
        company_id = "4118171" for every row) are organisational context fields,
        not FK references — linking on them creates cartesian-product false edges."""
        try:
            idx = headers.index(col)
            lines = data.split(b"\n")[1: sample + 1]
            seen_vals: set[str] = set()
            for line in lines:
                row = next(csv.reader(io.StringIO(line.decode("utf-8", "ignore"))), None)
                if row and idx < len(row):
                    v = row[idx].strip()
                    if v:
                        seen_vals.add(v)
                        if len(seen_vals) >= 2:
                            return True
        except Exception:  # noqa: BLE001
            pass
        return False  # 0 or 1 distinct value → constant field, skip

    plan_headers = [_headers(p["data"]) for p in plans]

    # Cardinality cache — _col_is_varying re-parses CSV bytes on every call.
    # Pass 2 runs O(N² × cols) iterations; caching avoids ≈ 24,000 re-parses
    # for a 20-plan XML ingest with 20 columns each.
    _varying_cache: dict[tuple[int, str], bool] = {}

    def _is_varying(plan_idx: int, col: str) -> bool:
        key = (plan_idx, col)
        if key not in _varying_cache:
            _varying_cache[key] = _col_is_varying(
                plans[plan_idx]["data"], plan_headers[plan_idx], col
            )
        return _varying_cache[key]

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
            _words = re.findall(r'[A-Z][a-z0-9]*', type_b)
            tag_word = _words[-1].lower() if _words else type_b_l
            tag_singular = _singular(tag_word)
            headers_b = plan_headers[j]
            id_col = next((c for c in headers_b if c.lower() in ("id", "uuid", "key")), None)
            name_col = next((c for c in headers_b if c.lower() in ("name", "full_name", "title")), None)
            mk0 = plan_b["match_keys"][0] if plan_b.get("match_keys") else None

            for col in plan_headers[i]:
                col_l = col.lower()
                target_attr: str | None = None
                if col_l in (f"{type_b_l}_id", f"{singular_b}_id",
                             f"{tag_word}_id", f"{tag_singular}_id"):
                    target_attr = id_col or mk0
                elif col_l in (f"{type_b_l}_name", f"{singular_b}_name",
                               f"{tag_word}_name", f"{tag_singular}_name"):
                    target_attr = name_col or mk0
                elif col_l in (type_b_l, singular_b) and (id_col or name_col):
                    target_attr = id_col or name_col
                if not target_attr:
                    continue
                seen.add(pair_key)
                src_upper = plan_a["ontology_type"].upper()
                # Edge direction in link_by_attribute: target_type → source_type
                # (parent has-child semantics). Name reflects that direction.
                link = {
                    "source_type": plan_a["ontology_type"],
                    "source_attr": col,
                    "target_type": type_b,
                    "target_attr": target_attr,
                    "name": f"{type_b.upper()}_HAS_{src_upper}",
                }
                links.append(link)
                logger.info("fk-pass1 log_id=%s: %s.%s -> %s.%s (%s)",
                            log_id, plan_a["ontology_type"], col, type_b, target_attr, link["name"])
                break

    # ── Pass 2: code-keyed data (shared-suffix columns) ──────────────────────
    # Handles patterns that Pass 1 misses because they don't follow {type}_id.
    # Three rules, all columns scanned per pair (no break) so multiple relationship
    # columns each generate their own edge spec:
    #   Rule A — shared match key:  same column name in A and B
    #   Rule B — stem reference:    column in A contains B's match-key stem
    #   Rule C — suffix match:      both columns share the same key suffix
    seen2: set[tuple[str, str, str]] = set()  # (src_type, tgt_type, col_l)
    for i, plan_a in enumerate(plans):
        own_mk = (plan_a.get("match_keys") or [None])[0]
        own_mk_l = (own_mk or "").lower()
        for j, plan_b in enumerate(plans):
            if i == j:
                continue
            pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
            if pair_key in seen:
                continue
            mk_b = (plan_b.get("match_keys") or [None])[0]
            if not mk_b:
                continue
            mk_b_l = mk_b.lower()
            # Derive stem by stripping common key suffixes
            mk_stem = mk_b_l
            for sfx in ("_code", "_id", "_num", "_key", "_ref", "_no", "_cage"):
                if mk_b_l.endswith(sfx):
                    mk_stem = mk_b_l[: -len(sfx)]
                    break
            if len(mk_stem) < 3:
                continue

            for col in plan_headers[i]:
                col_l = col.lower()
                col2_key = (plan_a["ontology_type"], plan_b["ontology_type"], col_l)
                if col2_key in seen2:
                    continue
                src_upper = plan_a["ontology_type"].upper()
                # Rule A: column exactly equals B's match key and looks like a code
                # column — catches shared identifier columns across entity types.
                # Guards:
                #   own_mk_l — skip when both A and B are siblings sharing a parent FK
                #   _col_is_varying — skip single-value context fields
                if (col_l == mk_b_l and col_l != own_mk_l
                        and any(col_l.endswith(sfx) for sfx in _KEY_SUFFIXES)
                        and _is_varying(i, col)):
                    seen2.add(col2_key)
                    links.append({
                        "source_type": plan_a["ontology_type"],
                        "source_attr": col,
                        "target_type": plan_b["ontology_type"],
                        "target_attr": mk_b,
                        "name": f"{plan_b['ontology_type'].upper()}_HAS_{src_upper}",
                    })
                    logger.info("fk-pass2-ruleA log_id=%s: %s.%s -> %s.%s",
                                log_id, plan_a["ontology_type"], col, plan_b["ontology_type"], mk_b)
                    continue
                # Rule B: column contains B's match-key stem as a fragment AND has
                # a key suffix — catches hierarchical/reference column patterns
                if (mk_stem in col_l and col_l != mk_b_l
                        and any(col_l.endswith(sfx) for sfx in _KEY_SUFFIXES)
                        and _is_varying(i, col)
                        and _is_varying(j, mk_b)):
                    seen2.add(col2_key)
                    links.append({
                        "source_type": plan_a["ontology_type"],
                        "source_attr": col,
                        "target_type": plan_b["ontology_type"],
                        "target_attr": mk_b,
                        "name": f"{plan_b['ontology_type'].upper()}_HAS_{src_upper}",
                    })
                    logger.info("fk-pass2-ruleB log_id=%s: %s.%s -> %s.%s",
                                log_id, plan_a["ontology_type"], col, plan_b["ontology_type"], mk_b)
                    continue
                # Rule C: same key-suffix — both columns share a suffix like _CODE,
                # signalling a replacement / alternate-entity reference.
                # Target cardinality guard: if the join target column has only one
                # distinct value (e.g. company_id = constant) it cannot produce
                # meaningful per-row joins — only false cartesian-product edges.
                col_sfx = next((s for s in _KEY_SUFFIXES if col_l.endswith(s)), None)
                mk_sfx = next((s for s in _KEY_SUFFIXES if mk_b_l.endswith(s)), None)
                if (col_sfx and mk_sfx and col_sfx == mk_sfx
                        and col_l != mk_b_l and col_l != own_mk_l
                        and _is_varying(i, col)
                        and _is_varying(j, mk_b)):
                    seen2.add(col2_key)
                    links.append({
                        "source_type": plan_a["ontology_type"],
                        "source_attr": col,
                        "target_type": plan_b["ontology_type"],
                        "target_attr": mk_b,
                        "name": f"{plan_b['ontology_type'].upper()}_HAS_{src_upper}",
                    })
                    logger.info("fk-pass2-ruleC log_id=%s: %s.%s -> %s.%s",
                                log_id, plan_a["ontology_type"], col, plan_b["ontology_type"], mk_b)

    # ── Pass 3: XML element-type FK detection ─────────────────────────────────
    # _collect_tag injects {parent_tag}_id columns into child entity rows.
    # Pass 1 misses these because it compares against the full
    # PascalCase ontology type name; Pass 2 misses them when the match key is a
    # short generic like "id".  Here we read the raw XML element type from the
    # _element_type column of each plan and check whether any other plan's headers
    # contain {element_type}_id, which is exactly the parent FK pattern.

    def _first_value(data: bytes, headers: list[str], col: str) -> str | None:
        try:
            idx = headers.index(col)
            lines = data.split(b"\n")
            if len(lines) < 2:
                return None
            row = next(csv.reader(io.StringIO(lines[1].decode("utf-8", "ignore"))), None)
            if row and idx < len(row):
                return row[idx].strip() or None
        except Exception:  # noqa: BLE001
            return None
        return None

    plan_elem_types: list[str | None] = [
        _first_value(plans[k]["data"], plan_headers[k], "_element_type")
        if "_element_type" in plan_headers[k] else None
        for k in range(len(plans))
    ]

    seen3: set[tuple[str, str]] = set()
    for j, plan_b in enumerate(plans):
        elem_b = plan_elem_types[j]
        if not elem_b:
            continue
        fk_col_l = f"{elem_b}_id"
        headers_b = plan_headers[j]
        id_col_b = next((c for c in headers_b if c.lower() in ("id", "uuid", "key")), None)
        mk0_b = plan_b["match_keys"][0] if plan_b.get("match_keys") else None
        target_attr = id_col_b or mk0_b
        if not target_attr:
            continue
        for i, plan_a in enumerate(plans):
            if i == j:
                continue
            pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
            if pair_key in seen or pair_key in seen3:
                continue
            # Find matching column (case-insensitive)
            actual_col = next(
                (c for c in plan_headers[i] if c.lower() == fk_col_l), None
            )
            if actual_col is None:
                continue
            seen3.add(pair_key)
            links.append({
                "source_type": plan_a["ontology_type"],
                "source_attr": actual_col,
                "target_type": plan_b["ontology_type"],
                "target_attr": target_attr,
                "name": f"{plan_b['ontology_type'].upper()}_HAS_{plan_a['ontology_type'].upper()}",
            })
            logger.debug(
                "fk-pass3 log_id=%s: %s.%s → %s.%s",
                log_id, plan_a["ontology_type"], actual_col,
                plan_b["ontology_type"], target_attr,
            )

    logger.info("detect_fk_links log_id=%s plans=%d links_found=%d", log_id, len(plans), len(links))
    return links


def _detect_fk_links_workspace(
    plan: dict, known_types: list[str], seen: set[tuple[str, str]] | None = None,
    job_id: str | None = None,
) -> list[dict]:
    """Detect FK links between one plan and workspace types already in OntologyStore.

    Fires even for single-file confirm jobs where _detect_fk_links returns [].
    For each column header matching {KnownType}_id or {KnownType}_name (case-
    insensitive, singular/plural), emits an FK spec for link_by_attribute.
    """
    seen = seen or set()
    links: list[dict] = []
    try:
        line = plan["data"].split(b"\n")[0].decode("utf-8", "ignore")
        headers = next(csv.reader(io.StringIO(line)), [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("detect_fk_links_workspace job=%s file=%s header parse failed: %s",
                        job_id, plan.get("filename"), exc)
        return []

    src_type = plan.get("ontology_type", "")
    match_key = (plan.get("match_keys") or ["id"])[0]

    for known in known_types:
        if known == src_type:
            continue
        pair_key = (src_type, known)
        if pair_key in seen:
            continue
        known_l = known.lower()
        singular = known_l.rstrip("s")
        candidates = {
            f"{known_l}_id", f"{known_l}_name",
            f"{singular}_id", f"{singular}_name",
        }
        for col in headers:
            if col.lower() in candidates:
                seen.add(pair_key)
                links.append({
                    "source_type": src_type,
                    "source_attr": col,
                    "target_type": known,
                    "target_attr": match_key,
                    "name": f"{known.upper()}_HAS_{src_type.upper()}",
                })
                logger.info("fk-workspace job=%s: %s.%s -> %s.%s",
                            job_id, src_type, col, known, match_key)
                break

    return links


def ingest_confirmed(data: dict[str, Any], approved_types: list[str],
                     approved_files: list[str], broker: Broker, jobs, job_id: str,
                     workspace_id: int = 1) -> None:
    """Resolve + project the approved discovered types and tabular files."""
    settings = get_settings()
    datasource_store = DatasourceStore(settings.rdb_dsn)
    total = max(len(approved_types) + len(approved_files), 1)
    step = 0

    for otype in approved_types:
        step += 1
        jobs.update_stage(job_id, f"{step}/{total}", int(step * 90 / total), f"Adding {otype}")
        recs = [m for m in data["mentions"] if m.payload.get("type") == otype]
        if recs:
            logger.info("confirm job=%s step=%d/%d otype=%s records=%d",
                        job_id, step, total, otype, len(recs))

            def _progress_otype(stage: str, pct: int, detail: str, _otype: str = otype,
                                 _step: int = step) -> None:
                jobs.update_stage(job_id, f"{_step}/{total} · {stage}",
                                  int(_step * 90 / total) + pct // 10, detail)
                logger.info("confirm job=%s otype=%s stage=%s pct=%d %s",
                            job_id, _otype, stage, pct, detail)

            # TODO: pass job_id=job_id once run_pipeline supports it
            run_pipeline(connector=RecordsConnector(recs, label=otype), dsn=settings.rdb_dsn,
                         system="document", dataset=otype, ontology_type=otype,
                         match_keys=["name"], graph_url=settings.graph_url, broker=broker,
                         workspace_id=workspace_id, relate=True, on_progress=_progress_otype)
        else:
            logger.info("confirm job=%s step=%d/%d otype=%s skipped, no matching mentions",
                        job_id, step, total, otype)

    # Collect valid plans in approval order so FK detection sees the full picture.
    valid_plans = [p for p in
                   (next((p for p in data["tabular"] if p["filename"] == fn), None)
                    for fn in approved_files)
                   if p is not None]
    _persist_xml_sources(valid_plans, workspace_id, settings.rdb_dsn)
    auto_fk = _detect_fk_links(valid_plans, log_id=job_id)
    if auto_fk:
        logger.info("confirm job=%s auto-detected %d fk-link spec(s): %s",
                    job_id, len(auto_fk), auto_fk)

    # Detect FK links from the last plan to types already in the workspace.
    # Fires for single-file jobs where _detect_fk_links returns [].
    if valid_plans:
        try:
            onto = OntologyStore(settings.rdb_dsn, workspace_id)
            try:
                known_types = [t.name for t in onto.list_types()]
            finally:
                onto.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("confirm job=%s OntologyStore lookup failed, skipping workspace FK "
                           "detection: %s", job_id, exc, exc_info=True)
            known_types = []
        existing_pairs: set[tuple[str, str]] = {
            (lk["source_type"], lk["target_type"]) for lk in auto_fk
        }
        workspace_fk = _detect_fk_links_workspace(
            valid_plans[-1], known_types, seen=existing_pairs, job_id=job_id
        )
        if workspace_fk:
            auto_fk.extend(workspace_fk)
            logger.info("confirm job=%s workspace FK links detected count=%d specs=%s",
                        job_id, len(workspace_fk), workspace_fk)

    def _run_one_plan(plan: dict, is_last: bool, plan_step: int) -> None:
        """Run a single tabular plan through the pipeline."""
        fname = plan["filename"]
        otype = plan["ontology_type"]
        logger.info("confirm job=%s step=%d/%d file=%s otype=%s is_last=%s",
                    job_id, plan_step, total, fname, otype, is_last)
        jobs.update_stage(job_id, f"{plan_step}/{total} · Discover",
                          int(plan_step * 90 / total), f"Starting {fname}")
        tmp_path: Path | None = None
        if Path(fname).suffix.lower() == ".json":
            tmp = NamedTemporaryFile(suffix=".json", delete=False)
            tmp.write(plan["data"])
            tmp.close()
            tmp_path = Path(tmp.name)
            conn = JsonConnector(tmp_path, system="json")
        else:
            conn = CsvConnector(plan["data"], system="csv", dataset=Path(fname).stem)

        def _progress_plan(stage: str, pct: int, detail: str) -> None:
            # Parallel plans share the job record — cap pct so we don't jump backwards.
            base = int(plan_step * 90 / total)
            jobs.update_stage(job_id, f"{plan_step}/{total} · {stage}",
                              min(base + pct // 10, 90), detail)
            logger.info("confirm job=%s file=%s stage=%s pct=%d %s",
                        job_id, fname, stage, pct, detail)

        try:
            # relate: only the last plan runs LLM inference — it can see ALL
            # entity types that were resolved by prior plans.  Non-last plans
            # run on a partial entity set and would produce spurious/incomplete
            # relationships that the final pass then can't correct.
            # skip_graph=True for non-last plans: project_graph calls graph.clear()
            # then rebuilds the entire workspace graph — concurrent calls race and
            # corrupt each other.  Only the final serial plan projects to FalkorDB;
            # it calls estore.list_entities() which covers ALL workspace entities.
            # TODO: pass job_id=job_id once run_pipeline supports it
            run_pipeline(connector=conn, dsn=settings.rdb_dsn,
                         system=Path(fname).suffix.lstrip("."), dataset=Path(fname).stem,
                         ontology_type=otype, match_keys=plan["match_keys"],
                         graph_url=settings.graph_url, broker=broker, workspace_id=workspace_id,
                         fk_links=auto_fk if is_last else None,
                         relate=is_last and settings.ingest_relate,
                         skip_graph=not is_last,
                         on_progress=_progress_plan)
            suffix = Path(fname).suffix.lower()
            if suffix in {".csv", ".json"}:
                restore_generic_source_entry(
                    datasource_store,
                    workspace_id=workspace_id,
                    source_system=suffix.lstrip("."),
                    source_dataset=Path(fname).stem,
                )
            logger.info("confirm job=%s file=%s done", job_id, fname)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    # Non-last plans run in parallel — they don't apply FK links so ordering
    # between them doesn't matter.  The last plan runs serially after all
    # others complete so that link_by_attribute can see every prior entity.
    non_last = valid_plans[:-1]
    last = valid_plans[-1] if valid_plans else None
    plan_steps = {p["filename"]: step + i + 1 for i, p in enumerate(valid_plans)}

    jobs.update_stage(job_id, f"{step + 1}/{total}", int((step + 1) * 90 / total),
                      f"Ingesting {len(valid_plans)} file(s) ({settings.ingest_workers} parallel)…")
    logger.info("confirm job=%s ingesting files=%s fk_links=%d",
                job_id, [p["filename"] for p in valid_plans], len(auto_fk))

    if non_last:
        with ThreadPoolExecutor(max_workers=settings.ingest_workers) as pool:
            futs = {pool.submit(_run_one_plan, p, False, plan_steps[p["filename"]]): p["filename"]
                    for p in non_last}
            failed: list[str] = []
            for fut in as_completed(futs):
                fname_done = futs[fut]
                try:
                    fut.result()
                    logger.info("confirm job=%s plan complete file=%s", job_id, fname_done)
                except Exception:
                    logger.warning("confirm job=%s plan failed file=%s",
                                   job_id, fname_done, exc_info=True)
                    failed.append(fname_done)
            if failed:
                logger.warning(
                    "confirm job=%s skipping %d failed plan(s): %s — continuing with remaining",
                    job_id, len(failed), failed,
                )

    if last:
        last_step = plan_steps[last["filename"]]
        jobs.update_stage(job_id, f"{last_step}/{total} · FK links",
                          int(last_step * 90 / total), f"Finalising FK links for {last['filename']}…")
        _run_one_plan(last, is_last=True, plan_step=last_step)

    # Zero-loss validation: prove every source record reached the graph.
    # Best-effort by contract — validation surfaces problems, never fails the job.
    if valid_plans:
        try:
            from aryx.pipeline.ingest_validation import (
                ground_truth_from_tabular, validate_workspace,
            )
            gt = ground_truth_from_tabular(valid_plans)
            report = validate_workspace(workspace_id, gt, settings.rdb_dsn,
                                        settings.graph_url)
            logger.info("confirm job=%s validation passed=%s %s",
                        job_id, report.passed, report.summary_line())
            for line in report.failures():
                logger.warning("confirm job=%s validation FAIL %s", job_id, line)
        except Exception as exc:  # noqa: BLE001 — never fail the ingest over validation
            logger.warning("confirm job=%s validation crashed: %s", job_id, exc,
                           exc_info=True)


def _persist_xml_sources(valid_plans: list[dict[str, Any]], workspace_id: int, dsn: str) -> None:
    """Persist XML parent metadata for the source catalog."""
    grouped: dict[str, dict[str, Any]] = {}
    for plan in valid_plans:
        source_filename = plan.get("source_filename")
        source_bytes = plan.get("source_bytes")
        if not source_filename or source_bytes is None:
            continue
        group = grouped.setdefault(source_filename, {"source_bytes": source_bytes, "assets": []})
        group["assets"].append(xml_asset_record(
            filename=plan["filename"],
            dataset=Path(plan["filename"]).stem,
            ontology_type=plan["ontology_type"],
            content_bytes=plan["data"],
        ))
    if not grouped:
        return
    store = DatasourceStore(dsn)
    for source_filename, payload in grouped.items():
        upsert_xml_catalog_entry(
            store,
            workspace_id=workspace_id,
            source_filename=source_filename,
            xml_bytes=payload["source_bytes"],
            assets=payload["assets"],
        )
