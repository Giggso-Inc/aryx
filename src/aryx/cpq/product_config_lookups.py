"""`load_product_config`'s array-set membership and rule-target-id
lookups (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md), split
out of the Step 4 setup block. Logic unchanged from the original inline
blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aryx.cpq.engine import get_cpq_rdb


@dataclass
class ArraySetLookups:
    array_set_id_by_attr_id: dict[int, int] = field(default_factory=dict)
    role_by_attr_id: dict[int, str] = field(default_factory=dict)
    order_by_attr_id: dict[int, int] = field(default_factory=dict)
    wrapper_key_by_attr_id: dict[int, str] = field(default_factory=dict)


def build_array_set_lookups(workspace_id: int, resolved_catalog_prefix: str) -> ArraySetLookups:
    # Step 3c — array-set membership (docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md):
    # bm_config_attr_set/bm_config_attr_set_assoc define BigMachines'
    # composite "array set" construct (a driver/control attr + ordered
    # member columns, e.g. Mounting Type's selector+quantity pair) —
    # confirmed real, previously completely unread by this pipeline.
    # role_by_attr_id/order_by_attr_id/wrapper_key_by_attr_id are keyed
    # by the BM-native attribute id (source_id), the same id every
    # other rule/set join in this method already cross-references by.
    lookups = ArraySetLookups()
    array_sets = get_cpq_rdb().fetch_attr_set_assoc(workspace_id, resolved_catalog_prefix)
    for set_id, sdef in array_sets.items():
        driver_id = sdef["driver_attr_id"]
        lookups.array_set_id_by_attr_id[driver_id] = set_id
        lookups.role_by_attr_id[driver_id] = "driver"
        lookups.wrapper_key_by_attr_id[driver_id] = f"_set{sdef['variable_name']}"
        for member_id, order in sdef["members"]:
            lookups.array_set_id_by_attr_id[member_id] = set_id
            lookups.role_by_attr_id[member_id] = "member"
            lookups.order_by_attr_id[member_id] = order
    return lookups


def compute_rule_target_ids(engine: Any, workspace_id: int, resolved_catalog_prefix: str) -> set[int]:
    # Rule-target ids — computed once here so Step 4's hidden/no-default
    # drop below can exempt attrs that are dynamically populated by a
    # rule action rather than a static default (Amendment 13,
    # docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md). Live-confirmed gap:
    # hiddenHidingRuleMasterStringForCommandCentral_swSoln (hidden=1,
    # empty default_value, but the ACTION-target of a
    # util.getConstraintVals-style recommendation rule) was being
    # dropped before rule evaluation ever ran, so it could never be
    # filled — and every downstream script checking it (e.g. "Hide 'of
    # Video Streaming Devices' if No value available for command and
    # control") always saw it blank, permanently defeating that
    # catalog's own visibility mechanism. Rule references use the
    # BM-native id (pg["id"]/attribute_id/bm_config_rule_id), not the
    # aryx entity_id — both are checked where the target id is used,
    # since either can appear as a rule action's target.
    try:
        rule_actions_by_rule = engine._load_rule_join_data(
            workspace_id, resolved_catalog_prefix)[2]
        return {
            aid for acts in rule_actions_by_rule.values() for aid, *_rest in acts
        }
    except Exception:
        return set()
