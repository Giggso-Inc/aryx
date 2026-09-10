"""Doc-discover API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "ConfirmRequest": "doc_discover_api",
    "_build_read_progress": "doc_discover_read_job",
    "_confirm_job": "doc_discover_confirm_job",
    "_read_job": "doc_discover_read_job",
    "_reset_discovery_status": "doc_discover_confirm_job",
    "_save_tmp": "doc_discover_read_job",
    "doc_discover_router": "doc_discover_api",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.doc_discover.{mod_name}")
    return getattr(mod, name)
