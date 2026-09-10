"""Layout-tier detection and the D1 country-anchor helpers
``resolve_ui_layout_scope`` builds its "section" grouping on (Phase 4 step 5
extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

``_detect_layout_tier`` touches nothing on the instance, so it takes no
``engine`` parameter; the two anchor helpers call back onto instance methods
(``_is_noise_var`` / ``_is_country_anchor_var``) and so take ``engine``.
Engine-module globals go through the module object -- ``get_cpq_rdb`` and
``_LAYOUT_TIER_CACHE`` are both patched/reassigned by dotted path in tests.
"""

from __future__ import annotations

from aryx.cpq import engine as _engine_module


def _detect_layout_tier(workspace_id: int, catalog_prefix: str = "") -> int:
    """docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md §2 — one cheap existence
    check per catalog, cached process-wide (same lifetime/reasoning as
    bml.py's _SHARED_SCRIPT_CACHE / _FLAG_KEYWORD_INDEX_CACHE):
    1 = rule_type=6 "Configuration Flow" rules exist AND are referenced
        by BmConfigLayoutAttrAssoc (verified on 3 independent catalogs).
    2 = no rule_type=6 flow rule, but layout placement data exists
        anyway — still real UI-truth, just unscoped to one flow.
    3 = no layout data at all — callers must fall back to today's
        existing hidden/required + rule-based behavior unchanged; free,
        no new code needed for this tier.
    """
    cache = _engine_module._LAYOUT_TIER_CACHE
    key = (workspace_id, catalog_prefix)
    if key in cache:
        return cache[key]
    rdb = _engine_module.get_cpq_rdb()
    assoc = rdb.fetch_layout_attr_assoc(workspace_id, catalog_prefix)
    if not assoc:
        tier = 3
    else:
        flow_ids = {
            src_id for _eid, src_id, _name, _fn
            in rdb.fetch_rules(workspace_id, "6", catalog_prefix, active_only=True)
            if src_id is not None
        }
        tier = 1 if any(rid in flow_ids for rid, _a, _l in assoc) else 2
    cache[key] = tier
    return tier


def _is_country_anchor_var(engine, variable_name: str) -> bool:
    """The D1 country anchor specifically — NOT any "country"-fragment
    match. A plain substring check collides with real, distinct attrs
    confirmed live in this catalog: CRM_BILL_COUNTRY/CRM_SHIP_COUNTRY
    (noise-shaped integration fields) and isUltimateDestinationCountryCA_astro
    (a genuine but DIFFERENT boolean attr, "country" mid-name not at the
    end). Requiring BOTH "ends with country" (excludes the CA-suffixed
    boolean) AND not noise-shaped (excludes the two CRM_* fields)
    isolates exactly ultimateDestinationCountry in this catalog — same
    two-guard pattern auto_fill already uses elsewhere for fragment
    matches that would otherwise over-collide.
    """
    vn_flat = variable_name.lower().replace("_", "")
    return vn_flat.endswith("country") and not engine._is_noise_var(variable_name)


def _find_country_anchor_attr_id(
    engine, workspace_id: int, catalog_prefix: str = "",
) -> int | None:
    """Native id of this catalog's country-anchor ConfigAttr, or None."""
    rdb = _engine_module.get_cpq_rdb()
    for _eid, attrs in rdb.fetch_entities_by_type(workspace_id, "bmconfigattr", catalog_prefix):
        vn = attrs.get("variable_name") or ""
        if engine._is_country_anchor_var(vn):
            try:
                return int(str(attrs.get("id")).strip())
            except (TypeError, ValueError):
                continue
    return None
