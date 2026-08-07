"""Name-agnostic foreign-key detection by pure value overlap.

``doc_discovery.infer_fk_links`` requires the source column's *name* to
reference the target type (``CustomerID`` -> ``Customer``). That misses real
relationships across independently-authored spreadsheets where the linking
columns are named nothing alike (e.g. ``EBS LSN List.xlsx``'s ``Ref Code``
column pointing at ``DLA DS SCRAP FY25.xlsx``'s ``Scrap Code``). This module
fills that gap with a stricter value-overlap-only pass — no naming
requirement — used as a second pass after the name-based one.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Higher than infer_fk_links's 0.6 threshold since there's no column-name
# signal to help rule out coincidental overlap (e.g. two unrelated boolean
# or status columns that happen to share a small value set).
_MIN_OVERLAP = 0.85
_MIN_DISTINCT = 3


def detect_dynamic_fk_links(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Discover foreign-key links across files by value overlap alone.

    Args:
        files: One dict per file with ``ontology_type`` and ``colvals``
            (mapping column name -> list of that column's raw values), same
            shape as ``doc_discovery.infer_fk_links`` expects.

    Returns:
        A list of ``{source_type, source_attr, target_type, target_attr,
        name}`` specs (possibly empty).
    """
    if len(files) < 2:
        return []

    # Precompute each file's per-column value-set (and candidate-key flag)
    # ONCE, up front. The naive triple-nested loop below previously rebuilt
    # a column's value-set from scratch for every OTHER file it was compared
    # against — for a fixed (file, column) pair that set never changes, so
    # at 20-35+ files/sheets (real multi-file batches this pipeline already
    # sees) that's O(files) redundant rebuilds per column instead of one.
    col_cache: list[dict[str, tuple[set[str], bool]]] = []
    for f in files:
        cols: dict[str, tuple[set[str], bool]] = {}
        for col, vals in (f.get("colvals") or {}).items():
            nonempty = [v for v in vals if v]
            vset = set(nonempty)
            is_key = len(vset) >= _MIN_DISTINCT and len(vset) == len(nonempty)
            cols[col] = (vset, is_key)
        col_cache.append(cols)

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for src_idx, src in enumerate(files):
        for tgt_idx, tgt in enumerate(files):
            if src is tgt or src["ontology_type"] == tgt["ontology_type"]:
                continue
            for tcol, (tset, is_key) in col_cache[tgt_idx].items():
                # Target column must be a candidate key: distinct, non-trivial.
                if not is_key:
                    continue
                for scol, (sset, _) in col_cache[src_idx].items():
                    if len(sset) < _MIN_DISTINCT:
                        continue
                    overlap = len(sset & tset) / len(sset)
                    if overlap < _MIN_OVERLAP:
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
    if out:
        logger.info("dynamic fk detection found %d value-overlap link(s)", len(out))
    return out
