"""Candidate dimension-column extraction and cardinality filtering.

Split out of `pipeline/dimension_link.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Calls no `get_settings()` and is never itself
patched — zero patch risk, confirmed via grep.
"""
from __future__ import annotations

from collections import defaultdict

from aryx.pipeline.value_normalize import normalize_value

CandidateKey = tuple[str, str]  # (ontology_type, column)
ValueMap = dict[str, list[int]]  # normalized_value -> [entity_id, ...]


def _candidate_columns(
    entities: list[tuple[int, str, dict]],
) -> dict[str, dict[str, ValueMap]]:
    """Group entity ids by (ontology_type, column, normalized_value)."""
    by_type_col_val: dict[str, dict[str, ValueMap]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for eid, etype, attrs in entities:
        if not isinstance(attrs, dict):
            continue
        for col, val in attrs.items():
            if col.startswith("_") or val is None:
                continue
            sval = str(val).strip()
            if not sval:
                continue
            by_type_col_val[etype][col][normalize_value(sval)].append(eid)
    return by_type_col_val


def _is_dimension_column(
    value_map: ValueMap, total_rows: int,
    min_distinct: int, max_cardinality_ratio: float,
) -> bool:
    """A dimension column repeats across many rows (low cardinality) but
    isn't degenerate (at least min_distinct values) — the opposite profile
    of a usable FK key, which dynamic_fk.py already requires to be highly
    selective (near-unique)."""
    distinct = len(value_map)
    if distinct < min_distinct or total_rows <= 0:
        return False
    return (distinct / total_rows) <= max_cardinality_ratio
