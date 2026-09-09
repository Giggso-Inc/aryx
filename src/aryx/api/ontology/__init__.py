"""Ontology API package (Phase 8a folder restructuring,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Split out of
`api/ontology_*.py`'s flat files in `src/aryx/api/` into their own
package; every name re-exported here so any caller that imports from
the package root instead of a specific submodule keeps working.
"""

from aryx.api.ontology.ontology_api import ontology_router
from aryx.api.ontology.ontology_api_export import _load_bundle, export_graph_response
from aryx.api.ontology.ontology_api_models import (
    OntologyConfigRequest,
    OntologyImportRequest,
)
from aryx.api.ontology.ontology_assist_api import (
    SuggestAttrsRequest,
    ontology_assist_router,
)
from aryx.api.ontology.ontology_browse import (
    add_type,
    approve,
    delete_type,
    import_doc,
    list_browse,
    set_parent,
)

__all__ = [
    "ontology_router",
    "_load_bundle",
    "export_graph_response",
    "OntologyConfigRequest",
    "OntologyImportRequest",
    "SuggestAttrsRequest",
    "ontology_assist_router",
    "add_type",
    "approve",
    "delete_type",
    "import_doc",
    "list_browse",
    "set_parent",
]
