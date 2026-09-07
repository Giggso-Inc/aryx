"""Payload-building cluster -- the standalone (non-conversational) BOM
payload entry point plus the two Data-Table-derived attribute sets that
decide which values `build_payload` treats as genuine Mandatory user
input (Phase 4 step 8 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Grouped as the "what actually goes into the payload" layer:
`build_standalone_payload` runs the full rules loop a live turn would
have run and then assembles the payload; `mandatory_tier_c_vns` is the
additive include set (`optionOrReqFlag == "R"` attrs the catalog does
NOT auto-resolve) and `_data_table_resolved_anchor_vns` is its
subtractive inverse (Tier A "basemodel"/"selectmodel" anchors the
region-rule table fully derives). `build_payload` itself and
`_is_mandatory_input_attr`, the two consumers, remain in ``engine.py``
pending their own dedicated decomposition -- the moved code calls them
back through the `engine` instance.

Every ``engine.py`` module-level name used here
(`_cpq_model_candidates`, `dt_resolve_whitelist_values`,
`dt_resolve_region_allow_value`,
`dt_governed_required_attr_names_for_base_model`,
`_COUNTRY_TO_REGION`) is reached through the engine MODULE object rather
than ``from ... import``, both to defer lookups past ``engine.py``'s own
import order and so the dotted-path patches several tests apply to those
names stay honored.

Re-exports every function so ``from aryx.cpq.payload_building import
<name>`` works regardless of which submodule actually defines it.
"""

from __future__ import annotations

from aryx.cpq.payload_building.anchor_exclusions import (
    _data_table_resolved_anchor_vns,
)
from aryx.cpq.payload_building.mandatory_tiers import mandatory_tier_c_vns
from aryx.cpq.payload_building.standalone import build_standalone_payload

__all__ = [
    "_data_table_resolved_anchor_vns",
    "build_standalone_payload",
    "mandatory_tier_c_vns",
]
