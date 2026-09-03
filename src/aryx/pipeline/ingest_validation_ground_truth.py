"""Derives Tier-1 ground truth (what the source data itself proves must
exist post-ingest) from the discovery plans actually being ingested.

Split out of `pipeline/ingest_validation.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from aryx.pipeline.ingest_validation_types import DatasetTruth, FkTruth, GroundTruth

_ID_COLUMNS = ("id", "guid", "uuid")


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
