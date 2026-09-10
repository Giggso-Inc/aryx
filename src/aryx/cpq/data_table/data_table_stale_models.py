"""Detects stale/legacy CPQModel codes never purged from the source Oracle
CPQ export, so callers scanning ingested Data Table rows for real candidate
CPQModel codes don't treat dead ones as live.

Split out of `cpq/data_table_resolver.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

# Real ingested rows can carry stale/legacy CPQModel codes never purged from
# the source Oracle CPQ export -- confirmed live (2026-08-08): rows tagged
# "...-btaDelete-<timestamp>-<n>" (deleted-but-never-purged), "..._PO-<n>"
# (one-off, order-specific snapshots), "...-DEL", and "...-remove" all sit
# alongside the real, current catalog codes for the exact same BaseModel/
# attribute. Never treat these as real candidates -- they'd reintroduce
# exactly the kind of conflicting/dead data this module exists to filter
# out, AND (confirmed live) needlessly multiply the cost of every
# candidate-scoped lookup that iterates over discovered CPQModel codes.
_STALE_CPQ_MODEL_MARKERS: tuple[str, ...] = ("btadelete", "_po-")

# Checked as SUFFIXES, not substrings -- "-del"/"-remove" are short enough
# that a substring check risks a false positive on a real code that just
# happens to contain them (e.g. a hypothetical "...-DELTA" variant). Both
# confirmed live only ever appear as a trailing marker.
_STALE_CPQ_MODEL_SUFFIXES: tuple[str, ...] = ("-del", "-remove")


def _is_stale_cpq_model(cpq_model: str) -> bool:
    lowered = (cpq_model or "").lower()
    return (
        any(marker in lowered for marker in _STALE_CPQ_MODEL_MARKERS)
        or any(lowered.endswith(suffix) for suffix in _STALE_CPQ_MODEL_SUFFIXES)
    )
