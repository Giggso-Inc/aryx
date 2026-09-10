"""Ontology API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "OntologyConfigRequest": "ontology_api_models",
    "OntologyImportRequest": "ontology_api_models",
    "SuggestAttrsRequest": "ontology_assist_api",
    "_load_bundle": "ontology_api_export",
    "add_type": "ontology_browse",
    "approve": "ontology_browse",
    "delete_type": "ontology_browse",
    "export_graph_response": "ontology_api_export",
    "import_doc": "ontology_browse",
    "list_browse": "ontology_browse",
    "ontology_assist_router": "ontology_assist_api",
    "ontology_router": "ontology_api",
    "set_parent": "ontology_browse",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ontology.{mod_name}")
    return getattr(mod, name)
