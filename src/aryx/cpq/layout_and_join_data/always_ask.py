"""Flow-scoped narrowing built on ``resolve_ui_layout_scope``: the always-ask
skip set (§3c) and the primary configuration-screen section (Phase 4 step 5
extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Both call back onto ``CpqEngine.resolve_ui_layout_scope`` (widely replaced on
the instance in tests), so each takes an explicit ``engine`` first parameter.
``get_cpq_rdb`` goes through the engine module object -- it is patched by
dotted path in several tests.
"""

from __future__ import annotations

from aryx.cpq import engine as _engine_module
from aryx.cpq.state import ConfigAttr


def resolve_always_ask_skips(
    engine, workspace_id: int, catalog_prefix: str, attrs: list[ConfigAttr],
) -> set[str]:
    """Variable names whose is_decision_attr always-ask override
    (auto_fill's skip_always_ask param, §3c) should be SKIPPED because
    the real native UI never shows them for this catalog's active
    configuration flow.

    Deliberately conservative — only acts when resolve_ui_layout_scope
    resolves to EXACTLY ONE active flow (tier 1, len(flows) == 1).
    Ambiguous catalogs (e.g. APX Next's 2 simultaneously-active flows)
    return an empty set, leaving today's unconditional always-ask
    behavior completely unchanged — see
    docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5/§6.
    """
    scope = engine.resolve_ui_layout_scope(workspace_id, catalog_prefix)
    if not scope or scope["tier"] != 1 or len(scope["flows"]) != 1:
        return set()
    the_flow = next(iter(scope["flows"].values()))
    in_flow_ids = the_flow["all"]
    skips: set[str] = set()
    for attr in attrs:
        if attr.variable_name != "productSelectionProduct_all":
            continue
        if attr.entity_id not in in_flow_ids:
            skips.add(attr.variable_name)
    return skips


def resolve_primary_layout_section_vns(
    engine, workspace_id: int, catalog_prefix: str, attrs: list[ConfigAttr],
) -> set[str] | None:
    """Variable names genuinely shown on the native UI's own configuration
    screen(s) — the country-anchor's own layout "section" (see
    resolve_ui_layout_scope), scoped to a single, deterministically-
    chosen flow when 2+ active flows exist.

    docs/config_consistency_issues_2026-07-30.md items 1/2: a real
    staging screenshot showed the native UI's Model Configuration panel
    surfacing ~10 fields for one screen, while Aryx's payload/summary
    carried 80-90 attributes total. This catalog's own ingested layout
    data doesn't resolve to per-SCREEN granularity (the finest grouping
    available is a ~35-attr "section" spanning several screens) — this
    is the ceiling of what's derivable without guessing a finer split
    the data doesn't contain.

    Flow disambiguation (APX Next ships 2 simultaneously-active
    rule_type=6 flows — resolve_ui_layout_scope's own docstring already
    flags this as unresolved): prefers the flow whose name does NOT end
    in "_sysConfig" (confirmed live: the two flows here are named
    "Configuration Flow For Astro Devices (Portable)" and
    "...Astro Devices (Portable)_sysConfig" — the suffixed one reads as
    a secondary/system-config variant, not the primary customer-facing
    flow). Falls back to the lowest flow_id for a stable, deterministic
    choice when no name is unsuffixed either way — never a random pick.

    Returns None (no narrowing — caller keeps existing full behavior)
    when: no layout data at all (tier 3), or the chosen flow has no
    resolvable country-anchor section. Never guesses a subset when the
    catalog's own data doesn't support one.
    """
    scope = engine.resolve_ui_layout_scope(workspace_id, catalog_prefix)
    if not scope or not scope["flows"]:
        return None
    flow_ids = list(scope["flows"].keys())
    if len(flow_ids) == 1:
        chosen_id = flow_ids[0]
    else:
        rdb = _engine_module.get_cpq_rdb()
        names = {
            src_id: (name or "")
            for _eid, src_id, name, _fn
            in rdb.fetch_rules(workspace_id, "6", catalog_prefix, active_only=True)
            if src_id is not None
        }
        unsuffixed = [
            fid for fid in flow_ids
            if not names.get(fid, "").strip().lower().endswith("_sysconfig")
        ]
        chosen_id = min(unsuffixed) if unsuffixed else min(flow_ids)
    section = scope["flows"][chosen_id].get("section")
    if not section:
        return None
    by_entity_id = {a.entity_id: a.variable_name for a in attrs}
    return {
        by_entity_id[aid] for aid in section if aid in by_entity_id
    }
