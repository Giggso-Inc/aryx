"""File-ingest API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_chunk_csv_bytes": "file_ingest_run",
    "_get_executor": "file_ingest_api",
    "make_should_stop": "file_ingest_run",
    "_run_files": "file_ingest_run",
    "_save_tmp": "file_ingest_run",
    "file_ingest_router": "file_ingest_api",
    "shutdown_executor": "file_ingest_api",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.file_ingest.{mod_name}")
    return getattr(mod, name)
