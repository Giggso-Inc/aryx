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
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for src in files:
        for tgt in files:
            if src is tgt or src["ontology_type"] == tgt["ontology_type"]:
                continue
            for tcol, tvals in (tgt.get("colvals") or {}).items():
                tset = {v for v in tvals if v}
                # Target column must be a candidate key: distinct, non-trivial.
                if len(tset) < _MIN_DISTINCT or len(tset) != len([v for v in tvals if v]):
                    continue
                for scol, svals in (src.get("colvals") or {}).items():
                    sset = {v for v in svals if v}
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
