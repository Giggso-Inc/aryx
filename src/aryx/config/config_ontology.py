"""Ontology-interchange settings — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class OntologySettingsMixin(BaseSettings):
    ontology_enabled: bool = Field(
        default=False,
        description="Enable ontology interchange (RDF/OWL) export.",
    )
    ontology_formats: str = Field(
        default="",
        description="Comma-separated export formats (turtle, json-ld, xml, n-triples). Empty = defaults.",
    )
    ontology_base_uri: str = Field(
        default="https://aryx.local/",
        description="Base URI for ontology namespace and export.",
    )
    ontology_export_max_entities: int = Field(
        default=50_000,
        description=(
            "Max entity count in a workspace above which GET /ontology/export "
            "rejects with 413 instead of running the synchronous export. "
            "Serialising a very large workspace can run long enough for a "
            "reverse proxy's read timeout to kill the connection first, "
            "which the client sees as a bare 502 Bad Gateway with no useful "
            "detail. Set to 0 to disable the cap. "
            "Override with ARYX_ONTOLOGY_EXPORT_MAX_ENTITIES."
        ),
    )
