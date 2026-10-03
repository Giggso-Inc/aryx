"""``load_hiding_rules`` -- the complete hiding-rule set for a workspace
(Phase 4 step 4 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Needs the ``CpqEngine``
instance (rule-join fetch, ``_load_value_rules``), so it takes an
explicit ``engine`` first parameter.
"""

from __future__ import annotations

import time

from aryx.cpq import rule_scope
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.engine import logger
from aryx.cpq.hiding_rules.type11 import _load_type11_hiding_rules
from aryx.cpq.state import HidingRule


def load_hiding_rules(
    engine, workspace_id: int, catalog_prefix: str = "", product_name: str = "",
) -> list[HidingRule]:
    """Load hiding rules (rule_type=11) from the RDB.

    Declarative rules become HidingRule objects with condition_attr_id/
    condition_value/hide set. Script-backed rules (condition_function_id
    != -1) ALSO become HidingRule objects, with `script` set instead —
    confirmed live that 119 of 191 real hiding rules (62%) in this
    catalog are script-backed (e.g. "Hide HW Version unless region=NA OR
    country=KY OR customerType=FEDERAL"), so skipping them silently, as
    this method previously did, meant most of the source system's real
    show/hide dependencies never took effect here at all. Their target(s)
    are resolved the same way as declarative rules (via
    _resolve_targets); only the CONDITION differs, and is evaluated at
    apply time by BmlEvaluator.should_hide (see apply_hiding_rules).

    catalog_prefix — scopes to one ingested catalog (see
    _load_rule_join_data) when the workspace holds more than one
    product's XML export. "" preserves the original workspace-wide load.

    product_name (2026-09-25, CPQ_Hardcode_Audit_dev_oci_2026-09-25.md
    T6 Phase 3) — passed through to `_load_type11_hiding_rules` for its
    `_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES` model_policy
    resolution. "" (the default) preserves the original hardcoded-only
    behavior for every caller not yet updated to pass it.
    """
    _t0 = time.monotonic()
    logger.info(
        "cpq_step: load_hiding_rules start workspace_id=%s catalog_prefix=%r",
        workspace_id, catalog_prefix,
    )
    rules = _load_type11_hiding_rules(
        engine, workspace_id, catalog_prefix, _t0, product_name,
    )
    rules = rule_scope.scope_rules_by_ancestry(
        rules, "hiding_rules", workspace_id, catalog_prefix)

    # docs/CPQ_VALUELESS_HIDE_ACTION_LOADING_GAP_PLAN_2026_08_05.md — a
    # real, separate class of "hide" rule authored OUTSIDE rule_type=11
    # (a declarative action with no literal value1, e.g. "Associated rec
    # rule to Hide Frequency Band for Single Band") that _load_value_
    # rules already classifies correctly but the rest of the codebase
    # only ever asked for hiding rules from THIS method. Merged in here,
    # not by changing load_recommendation_and_constraint_rules' return
    # arity (that method is monkeypatched with a bare (rec, con) 2-tuple
    # across the test suite) — every existing caller of load_hiding_
    # rules() gets the complete set automatically, with zero call-site
    # changes anywhere.
    try:
        _rec, _con, _val, extra_hiding = engine._load_value_rules(
            workspace_id, catalog_prefix)
    except Exception as exc:
        logger.debug("cpq: value-less hiding rule load failed", exc_info=True)
        fill_log.log_load_failed("hiding_rules_valueless", exc, "VALUELESS_HIDING_LOAD_FAILED",
                                 workspace_id=workspace_id, catalog_prefix=catalog_prefix)
        extra_hiding = []
    if extra_hiding:
        logger.info("cpq: loaded %d additional value-less-action hiding rules",
                    len(extra_hiding))
    fill_log.log_load("hiding_rules", workspace_id=workspace_id, catalog_prefix=catalog_prefix,
                      type11_count=len(rules), valueless_count=len(extra_hiding), empty=not (rules or extra_hiding))
    logger.info(
        "cpq_step: load_hiding_rules done elapsed_s=%.3f total_rules=%d",
        time.monotonic() - _t0, len(rules) + len(extra_hiding),
    )
    return rules + extra_hiding
