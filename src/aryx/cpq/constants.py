"""Shared, dependency-free CPQ constants (CPQ_Hardcode_Audit_dev_oci_
2026-09-25.md T10's original fix proposal: one module for cross-cutting
literals like this instead of each usage site re-declaring its own copy
and silently drifting). Deliberately has zero imports from the rest of
``cpq`` so any module can import it without circular-import risk.
"""
from __future__ import annotations

# The engine's own literal placeholder for a customer's deliberate
# "clear"/no-selection, used in CpqSession.display_filled across auto_fill's
# single- and multi-select "already answered, nothing to show" paths and
# the ask_handle_*/ask_step9_decline_multiselect confirm-side equivalents.
# Was independently re-declared as a bare "(none)" string literal at ~10
# call sites with no shared import -- in sync today by discipline, not
# enforcement.
NONE_DISPLAY_PLACEHOLDER = "(none)"
