"""Data-Table-conflict helper cluster (Phase 4 step 1 extraction from
``cpq/engine.py`` -- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Re-exports every function so ``from aryx.cpq.data_table_bridge import
<name>`` works regardless of which submodule actually defines it.
"""

from __future__ import annotations

from aryx.cpq.data_table_bridge.candidates import (
    _DEFAULT_CPQ_MODEL_CANDIDATES,
    _cpq_model_candidates,
)
from aryx.cpq.data_table_bridge.conflicts import (
    _CONFIRMED_SOURCES,
    _invalidate_inconsistent_paired_values,
    _resolve_narrowed_legal_values,
    _resolve_via_data_tables,
    find_confirmed_data_table_conflicts,
)
from aryx.cpq.data_table_bridge.attr_governance import (
    _CONFIRMED_DEAD_ATTRS,
    _NEVER_SUPPRESS_FRAGMENTS,
    _suppress_ungoverned_attrs,
)
from aryx.cpq.data_table_bridge.hidden_master_string import _compute_hidden_master_string
from aryx.cpq.data_table_bridge.series_mapping import _apply_series_mapping_exclusions

__all__ = [
    "_DEFAULT_CPQ_MODEL_CANDIDATES",
    "_cpq_model_candidates",
    "_CONFIRMED_SOURCES",
    "_invalidate_inconsistent_paired_values",
    "_resolve_narrowed_legal_values",
    "_resolve_via_data_tables",
    "find_confirmed_data_table_conflicts",
    "_CONFIRMED_DEAD_ATTRS",
    "_NEVER_SUPPRESS_FRAGMENTS",
    "_apply_series_mapping_exclusions",
    "_compute_hidden_master_string",
    "_suppress_ungoverned_attrs",
]
