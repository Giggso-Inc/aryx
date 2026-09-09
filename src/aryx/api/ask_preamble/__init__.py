"""Pre-STEP-1 preamble of `_run_cpq_turn_inner` (Phase 8a folder
restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Split
out of `api/ask_preamble_*.py`'s flat files in `src/aryx/api/` into
their own package; every name re-exported here so any caller that
imports from the package root instead of a specific submodule keeps
working.
"""

from aryx.api.ask_preamble.ask_preamble_country_change import _preamble_country_change_gate
from aryx.api.ask_preamble.ask_preamble_hints_and_country import _preamble_extract_hints_and_resolve_country
from aryx.api.ask_preamble.ask_preamble_quantity_background import (
    _preamble_capture_quantity_background,
    _preamble_quantity_no_quote_gate,
)
from aryx.api.ask_preamble.ask_preamble_quantity_gate import _preamble_dedicated_quantity_gate
from aryx.api.ask_preamble.ask_preamble_quantity_target_resolve import _preamble_resolve_quantity_target
from aryx.api.ask_preamble.ask_preamble_run import _preamble_run
from aryx.api.ask_preamble.ask_preamble_session_and_shortcuts import (
    _preamble_init_session,
    _preamble_shortcut_gates,
    _preamble_undo_gate,
)

__all__ = [
    "_preamble_country_change_gate",
    "_preamble_extract_hints_and_resolve_country",
    "_preamble_capture_quantity_background",
    "_preamble_quantity_no_quote_gate",
    "_preamble_dedicated_quantity_gate",
    "_preamble_resolve_quantity_target",
    "_preamble_run",
    "_preamble_init_session",
    "_preamble_shortcut_gates",
    "_preamble_undo_gate",
]
