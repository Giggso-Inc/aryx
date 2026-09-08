"""Normalizing a bm_catalog model-leaf name for comparison, split out of
`_run_cpq_turn_inner`'s model-leaf disambiguation block (Phase 10/11-
phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md). Originally a nested closure local to that block (no outer
captures beyond `re`); kept as a plain module-level function since it
has none to unwind. Logic unchanged from the original inline
definition.
"""

from __future__ import annotations

import re


def _norm_leaf(s: str) -> str:
    n = re.sub(r"[^a-z0-9]", "", s.lower())
    return n[:-3] if n.endswith("bom") else n
