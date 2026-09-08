"""Rendering the numbered pending-clarify candidate prompt, split out of
`api/ask_api.py` (Phase 2/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original
inline definition. `_cpq_engine` is read through the ask_api MODULE
object (not imported by name) since at least one test replaces the whole
singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from aryx.api import ask_api as _ask_api_module


def _grounded_clarify_prompt(candidates: list, attrs: list) -> str:
    """Numbered catalog-label list — never LLM-invented example names."""
    if not candidates:
        return "Which field did you mean? Please name the attribute."
    lines = [
        "Which attribute did you mean? Reply with the name or the number:",
    ]
    for i, a in enumerate(candidates, start=1):
        label = _ask_api_module._cpq_engine.disambiguated_label(a, attrs)
        lines.append(f"{i}. **{label}** (`{a.variable_name}`)")
    return "\n".join(lines)
