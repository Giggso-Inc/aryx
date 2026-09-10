"""Rest-ingest API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "RestIngestRequest": "rest_ingest_models",
    "RestPreviewRequest": "rest_ingest_models",
    "_run_rest": "rest_ingest_job",
    "_type_from_url": "rest_ingest_job",
    "rest_ingest_router": "rest_ingest_api",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.rest_ingest.{mod_name}")
    return getattr(mod, name)
