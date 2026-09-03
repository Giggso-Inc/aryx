"""Ontology-type + match-key inference for a tabular file, from filename and
column-name conventions.

Split out of `pipeline/doc_discovery.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03). `_infer_type` is directly whitebox-patched
(`aryx.pipeline.doc_discovery._infer_type` in `test_doc_discovery.py`) —
its only caller, `read_files`, stays in `doc_discovery.py` and imports it
from here, so the patch keeps intercepting it unchanged.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any

from aryx import llm_runtime
from aryx.config import get_settings

logger = logging.getLogger(__name__)

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


def _key_suffixes() -> tuple[str, ...]:
    """Config-driven column-name suffixes treated as generic key/code
    indicators — domain-agnostic naming conventions, not specific to any
    one dataset. Override with ARYX_FK_KEY_SUFFIXES."""
    return tuple(
        s.strip() for s in get_settings().fk_key_suffixes.split(",") if s.strip()
    )


def _id_like_names() -> frozenset[str]:
    """Config-driven column names treated as a generic opaque-identifier
    signal. Override with ARYX_ID_LIKE_COLUMN_NAMES."""
    return frozenset(
        s.strip().lower() for s in get_settings().id_like_column_names.split(",")
        if s.strip()
    )


def _name_like_names() -> frozenset[str]:
    """Config-driven column names treated as a generic display-name
    signal. Override with ARYX_NAME_LIKE_COLUMN_NAMES."""
    return frozenset(
        s.strip().lower() for s in get_settings().name_like_column_names.split(",")
        if s.strip()
    )


def _guess_key_col(sample: str) -> str:
    """Heuristic: return the most likely natural-key column from a CSV header.

    Checks the first few columns for common ID/code suffixes before defaulting
    to the first column, which is almost always the primary key in structured
    tabular exports.
    """
    try:
        first_line = sample.split("\n")[0]
        headers = next(csv.reader(io.StringIO(first_line)))
        suffixes = _key_suffixes()
        for h in headers[:6]:
            if any(h.lower().endswith(sfx) for sfx in suffixes):
                return h
        return headers[0] if headers else "name"
    except Exception:  # noqa: BLE001
        return "name"


def _id_priority_mk(sample: str, mk: list[str]) -> list[str]:
    """Promote an explicit id-like column (see ARYX_ID_LIKE_COLUMN_NAMES) to
    primary match_key.

    When a CSV has an explicit PK column the LLM sometimes picks a FK column
    (e.g. bm_config_rule_id) instead.  In Pass 2 FK detection that causes
    sibling entities sharing the same parent FK to appear as parent-child pairs,
    creating thousands of false edges.  Returning 'id' early avoids this because
    short keys like 'id' have mk_stem length < 3 and are skipped by Pass 2.
    """
    id_names = _id_like_names()
    if mk and mk[0].lower() in id_names:
        return mk
    try:
        hdr_line = sample.split("\n")[0]
        hdrs = next(csv.reader(io.StringIO(hdr_line)), [])
        id_hdr = next((h for h in hdrs[:8] if h.lower() in id_names), None)
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
