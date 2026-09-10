"""Pure naming helper shared by the Shay bridge mixins.

Split out of `store/shay_bridge_store.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations


def _aryx_workspace_name(name: str, shay_workspace_id: str) -> str:
    label = (name or "Workspace").strip() or "Workspace"
    return f"shay::{label}::{shay_workspace_id[:8]}"
