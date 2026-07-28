"""Request/response schemas for the Aryx bridge (ask + document ingestion)."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AryxAskRequest(BaseModel):
    """A question routed to Aryx's knowledge graph for one Shay thread."""
    thread_id: str = Field(..., min_length=1, description="Shay thread id — keys Aryx-side chat history")
    question: str = Field(..., min_length=1)


class AryxAskResponse(BaseModel):
    """Mirrors Aryx's POST /admin/shay/chats/ask response verbatim."""
    shay_thread_id: str
    shay_workspace_id: str
    aryx_workspace_id: int
    answer: str
    terms: List[str] = []
    tools_called: List[str] = []
    usage: Dict[str, Any] = {}
    grounding: Optional[Dict[str, Any]] = None
    citations: List[Dict[str, Any]] = []


class AryxDocsReadResponse(BaseModel):
    """Mirrors Aryx's POST /admin/docs/read response."""
    discovery_id: str


class AryxDiscoveredType(BaseModel):
    type: str
    count: int
    examples: List[str] = []


class AryxDiscoveredFile(BaseModel):
    filename: str
    ontology_type: str


class AryxDocsSummaryResponse(BaseModel):
    """Mirrors Aryx's GET /admin/docs/summary/{discovery_id} response."""
    types: List[AryxDiscoveredType] = []
    files: List[AryxDiscoveredFile] = []


class AryxDocsConfirmRequest(BaseModel):
    approved_types: List[str] = []
    approved_files: List[str] = []


class AryxDocsConfirmResponse(BaseModel):
    """Mirrors Aryx's POST /admin/docs/confirm response."""
    status: str
    job_id: str


class AryxJobStatusResponse(BaseModel):
    """Mirrors Aryx's GET /admin/jobs/{job_id} response."""
    job_id: str
    source_system: str
    source_dataset: str
    status: str
    stage: Optional[str] = None
    pct: Optional[int] = None
    detail: Optional[str] = None
    run_id: Optional[int] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    finished_at: Optional[str] = None
    workspace_id: int
