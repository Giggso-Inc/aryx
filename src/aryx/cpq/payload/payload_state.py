"""Shared mutable context for `build_payload`'s multi-stage assembly
(Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). One
`PayloadContext` is built once per `build_payload` call (`payload_setup.
build_context`) and threaded through the scalar/multi/array-set/ordering
stages in `payload_scalar.py`/`payload_multi.py`/`payload_array_sets.py`/
`payload_order.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PayloadContext:
    sources: dict[str, str]
    attr_by_vn: dict[str, Any]
    hidden: set[str]
    out: dict[str, Any] = field(default_factory=dict)
    array_control_count: int | None = None
    grid_links: dict[str, dict[str, str]] = field(default_factory=dict)
    # per-option qty vn -> owning qty-member vn
    array_set_qty_source: dict[str, str] = field(default_factory=dict)
    consumed_by_array_set: set[str] = field(default_factory=set)
    # set_id -> {member_variable_name: [selected values]}
    array_set_rows: dict[int, dict[str, list[str]]] = field(default_factory=dict)
    exclude_anchor_vns: frozenset[str] = frozenset()
    rule_forced_active_vns: frozenset[str] = frozenset()
    data_table_forced_vns: frozenset[str] = frozenset()
    # plan F6: the derived required set (None = flag off / not computed)
    derived_required_vns: frozenset[str] | None = None
    # docs/CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3 — threaded through to
    # engine._is_mandatory_input_attr's Hardware Version applicability check
    # (`_hardware_version_confirmed_not_applicable`); `None`/`""` (the
    # defaults, for every caller that doesn't opt in) keep that check a
    # no-op, preserving Tier A's HW branch exactly as before.
    workspace_id: int | None = None
    catalog_prefix: str = ""
    product_anchor_hint: str | None = None
    dt_cache: dict[tuple[int, str], tuple] | None = None


CUSTOMER_ENTERED_SOURCES: frozenset[str] = frozenset({"user"})


def config_data_sources(ctx: PayloadContext, default: frozenset[str]) -> frozenset[str]:
    """Sources whose values may enter config_data: with the derived required set
    driving, only what the customer entered (derived hidden values stay out unless
    the set itself names them); otherwise the existing wider set."""
    return default if ctx.derived_required_vns is None else CUSTOMER_ENTERED_SOURCES
