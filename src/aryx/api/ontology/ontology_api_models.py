"""Request models for the ontology interchange API.

Split out of `api/ontology_api.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero test patches against this module — confirmed via
grep.
"""
from __future__ import annotations

from pydantic import BaseModel


class OntologyConfigRequest(BaseModel):
    """Settings payload for the interchange plugin (all fields optional)."""

    enabled: bool | None = None
    formats: list[str] | None = None
    base_uri: str | None = None
    include_provenance: bool | None = None


class OntologyImportRequest(BaseModel):
    """An uploaded ontology document to parse into proposed types."""

    content: str
    format: str = ""
    filename: str = ""
    workspace_id: int = 1
