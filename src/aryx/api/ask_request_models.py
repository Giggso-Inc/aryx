"""Ask API request/response Pydantic models.

Pure data classes, zero behavior — split out of `ask_api.py` per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md Phase 4 step 1. Re-exported
from `ask_api.py` so `from aryx.api.ask_api import AskRequest` (used across
many test files) keeps working unchanged.
"""
from __future__ import annotations

from pydantic import BaseModel


class Turn(BaseModel):
    role: str
    text: str


class AskRequest(BaseModel):
    question: str
    history: list[Turn] = []
    workspace_id: int = 1
    session_data: dict = {}  # CPQ session state echoed back from prior turn


class LlmConfigRequest(BaseModel):
    provider: str = ""
    menial_model: str = ""
    answer_model: str = ""
    endpoint: str = ""
    api_key: str = ""
