"""Request models for the workspace management API.

Split out of `api/workspace_api.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero test patches against this module — confirmed via
grep.
"""
from __future__ import annotations

from pydantic import BaseModel


class WorkspaceRequest(BaseModel):
    name: str
    description: str = ""
    context: str = ""


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class ContextRequest(BaseModel):
    context: str = ""


class BriefRequest(BaseModel):
    """Knowledge-modelling brief — 5 METHONTOLOGY-style competency questions."""

    domain: str = ""
    aim: str = ""
    objectives: list[str] = []
    scope: str = ""
    roles: list[str] = []
