"""Rule-join fetch/target-resolution plus the native-UI layout cluster --
tier detection, UI scope, component parsing, display-order maps, and the
flow-scoped narrowing built on top of them (Phase 4 step 5 extraction from
``cpq/engine.py`` -- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Grouped together because the layout functions and the rule-join fetch are
the two halves of the same "load the catalog's own structural truth" step,
and the rule-key/target helpers share the join data's id conventions.
Re-exports every function so ``from aryx.cpq.layout_and_join_data import
<name>`` works regardless of which submodule actually defines it.
"""

from __future__ import annotations

from aryx.cpq.layout_and_join_data.always_ask import (
    resolve_always_ask_skips,
    resolve_layout_hidden_anchor_skips,
    resolve_primary_layout_section_vns,
)
from aryx.cpq.layout_and_join_data.components import (
    _load_layout_components,
    _walk_layout_components,
)
from aryx.cpq.layout_and_join_data.display_order import (
    _load_layout_full_order,
    load_layout_display_order,
    load_layout_hidden_vns,
)
from aryx.cpq.layout_and_join_data.flow_exclusions import (
    model_context_mirror_vns,
    payload_flow_exclusions,
)
from aryx.cpq.layout_and_join_data.rule_join import _load_rule_join_data
from aryx.cpq.layout_and_join_data.rule_targets import (
    _condition_has_operator_collision,
    _resolve_targets,
    _rule_key,
)
from aryx.cpq.layout_and_join_data.tier import (
    _detect_layout_tier,
    _find_country_anchor_attr_id,
    _is_country_anchor_var,
)
from aryx.cpq.layout_and_join_data.ui_scope import resolve_ui_layout_scope

__all__ = [
    "_condition_has_operator_collision",
    "_detect_layout_tier",
    "_find_country_anchor_attr_id",
    "_is_country_anchor_var",
    "_load_layout_components",
    "_load_layout_full_order",
    "_load_rule_join_data",
    "_resolve_targets",
    "_rule_key",
    "_walk_layout_components",
    "load_layout_display_order",
    "load_layout_hidden_vns",
    "model_context_mirror_vns",
    "payload_flow_exclusions",
    "resolve_always_ask_skips",
    "resolve_layout_hidden_anchor_skips",
    "resolve_primary_layout_section_vns",
    "resolve_ui_layout_scope",
]
