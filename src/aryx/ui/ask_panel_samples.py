"""Suggested-question chips + entity-id extraction for the Ask panel.

Split out of `ui/ask_panel.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import re

import streamlit as st

from aryx.ui import api

_GENERIC_SAMPLES = [
    "List the entity types in this workspace",
    "Show 5 random entities and how they connect",
    "Which entities have the most relationships?",
    "Summarise what this graph is about",
]


def _entity_ids_from(resp: dict) -> list[int]:
    """Pull entity ids out of the response (tools_called + plain answer)."""
    ids: set[int] = set()
    for blob in resp.get("tools_called", []) or []:
        for m in re.findall(r"\bid[\s:=]+(\d+)", str(blob)):
            ids.add(int(m))
        for m in re.findall(r"\bentit(?:y|ies)[^0-9]*(\d+)", str(blob), re.I):
            ids.add(int(m))
    text = resp.get("answer", "") or ""
    for m in re.findall(r"#(\d+)\b", text):
        ids.add(int(m))
    return sorted(ids)[:25]


def _samples_for(types: list[str]) -> list[str]:
    """Workspace-aware suggested questions based on observed entity types."""
    if not types:
        return _GENERIC_SAMPLES
    head = types[0]
    out = [
        f"List all {head}s",
        f"Who is connected to a {head}?",
        f"Show 5 random {head}s",
    ]
    if len(types) >= 2:
        out.append(f"How are {types[0]}s related to {types[1]}s?")
    return out


def _sample_chips() -> None:
    """Render clickable suggested questions; clicking auto-submits."""
    try:
        ents = api.full_graph().get("entities", []) or []
    except Exception:
        ents = []
    types = sorted({e.get("type") for e in ents if e.get("type")})
    samples = _samples_for(types)
    st.caption("Try one of these:")
    cols = st.columns(len(samples))
    for i, q in enumerate(samples):
        if cols[i].button(q, key=f"chip_{i}", use_container_width=True):
            st.session_state.queued_question = q
            st.rerun()
