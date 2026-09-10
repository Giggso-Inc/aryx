"""
Thread-level dedup-by-filename pagination for GET / (list datasources)
when thread_id is set.

Private module: split out of list_datasources.py (Raven style-compliance,
wave B4). Same file can appear in multiple emails; this keeps one row per
filename (preferring an embedding-completed row, else the latest) so the
thread view has no duplicates, then paginates in-memory over that
deduplicated set.
"""

from typing import List, Tuple


def dedupe_thread_datasources(all_datasources: List, page: int, size: int) -> Tuple[int, List]:
    """Dedup by filename, then paginate. Returns (total_count, page_of_datasources)."""

    # Sort: embedding_status==2 (completed) first, then by created_at desc, then id desc
    # So per filename we keep: completed row if any, else the latest row
    def _thread_ds_sort_key(ds) -> Tuple[int, float, str]:
        ts = ds.created_at.timestamp() if ds.created_at else 0
        return (0 if (ds.embedding_status == 2) else 1, -ts, str(ds.id or ""))

    all_datasources_sorted = sorted(all_datasources, key=_thread_ds_sort_key)
    seen_filenames = {}
    unique_datasources = []
    for ds in all_datasources_sorted:
        filename_key = (ds.filename or ds.name or "unknown").strip() or "unknown"
        if filename_key not in seen_filenames:
            seen_filenames[filename_key] = True
            unique_datasources.append(ds)

    total_count = len(unique_datasources)
    start_idx = (page - 1) * size
    end_idx = start_idx + size
    return total_count, unique_datasources[start_idx:end_idx]
