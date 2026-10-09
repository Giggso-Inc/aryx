"""The rule_type=11 half of ``load_hiding_rules`` -- split out of
``loader.py`` purely to keep both files under the 150-line style limit
(Phase 4 step 4 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Needs the ``CpqEngine``
instance for the shared rule-join fetch and the rule-key/target-
resolution helpers, so it takes an explicit ``engine`` first parameter.
"""

from __future__ import annotations

import time

from aryx.config import get_settings
from aryx.cpq.bml.bml_condition_expression import copy_conditions
from aryx.cpq.engine import logger
from aryx.cpq.state import HidingRule

# Live-confirmed (2026-09-21, docs/APX900_Hybrid_Combiner_Missing_Script_
# Issue.md): the "Hide Optional Peripherals 900 MHz Hybrid Combiner For G
# Series If No Value Available" hiding rule's own BmFunction script was
# never ingested -- this loader would otherwise drop it entirely
# (script_missing branch below), leaving op900MHzHybridCombiner_astro asked
# unconditionally with a blind-filled default for every product in this
# family, including APX 900 configurations where it genuinely has no legal
# value yet. The rule's own name states its real condition plainly ("if no
# value available"), which is exactly the distinction resolve_whitelist_
# values already makes ([] = confirmed no legal value under this context,
# None = no Data Table coverage at all, real list = a legal value exists) --
# so this rule is kept (not dropped) with dt_whitelist_substitute=True,
# letting apply_hiding_rules substitute that real Data Table check for the
# missing script instead of guessing. Narrow, named allowlist -- NOT a
# generic substitution for every "...If No Value(s) Available" rule with a
# missing script (dozens exist in this catalog); each would need its own
# live confirmation before joining this set, same discipline as
# _CONFIRMED_DEAD_ATTRS (aryx.cpq.data_table_bridge.attr_governance).
_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES: frozenset[str] = frozenset({
    "Hide Optional Peripherals 900 MHz Hybrid Combiner For G Series If No Value Available",
})


def _load_type11_hiding_rules(
    engine, workspace_id: int, catalog_prefix: str, _t0: float,
    product_name: str = "",
) -> list[HidingRule]:
    """Load and classify the native rule_type=11 hiding rules only.

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

    `product_name` (2026-09-25, CPQ_Hardcode_Audit_dev_oci_2026-09-25.md
    T6 Phase 3): resolves the `_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_
    NAMES` membership check below through model_policy for the
    session's actual CPQ model, falling back to the hardcoded constant
    when unavailable. Defaults to "" (legacy behavior byte-identical)
    so every existing caller keeps working unchanged.
    """
    from aryx.cpq.model_policy import (  # noqa: PLC0415
        resolve_dt_whitelist_substitute_hiding_rule_name_membership,
    )

    rules: list[HidingRule] = []
    script_missing = 0
    unresolved = 0
    operator_collisions = 0
    scope_unsafe_unconditional = 0
    try:
        rdb, inputs, actions, marked, chain = engine._load_rule_join_data(
            workspace_id, catalog_prefix)
        scripts = rdb.fetch_function_scripts(workspace_id, catalog_prefix)
        # active_only=True (docs/config_consistency_issues_2026-07-30.md,
        # Issue 5 follow-up): live-confirmed real harm from the
        # previously-deliberate byte-for-byte-unaffected choice noted in
        # fetch_rules' own docstring — a DISABLED (status=3) hiding rule,
        # "Hide Frequency Band & Extend Range if Product is selected as
        # APX Enhanced" (script condition reads modelSelectionFrequency
        # BandMsl_astro's OWN just-set value and hides it right back),
        # was still being loaded and evaluated, wiping a customer's
        # Frequency Band answer on the very same turn it was recorded.
        # rule_type="6" flow rules already opted into this exact filter
        # for the identical reason (dead/superseded rules alongside live
        # ones); hiding rules never had — this closes that gap.
        from aryx.cpq import rule_scope  # noqa: PLC0415
        _scope = rule_scope.rule_scope_enabled()
        # review of #503 (2026-10-09): the always=True guard below needs
        # ref_id whenever F10 is on, independent of `_scope` -- it is a
        # structural check, not conditioned on cpq_rule_scope_filter_
        # enabled's current value (see that guard's own comment for why).
        _f10 = bool(get_settings().cpq_empty_condition_rule_true_enabled)
        _need_ref_id = _scope or _f10
        _rkw = {"with_ref_id": True} if _need_ref_id else {}
        _marks: list[tuple[int, str]] = []
        for row in rdb.fetch_rules(
            workspace_id, "11", catalog_prefix, active_only=True, **_rkw,
        ):
            eid, src_id, rule_name, fn_id = row[:4]
            ref_id = str(row[4] or "") if _need_ref_id else ""
            if _scope:
                _marks.append((len(rules), ref_id))
            key = engine._rule_key(eid, src_id, inputs, actions, marked)
            targets = engine._resolve_targets(key, actions, marked, chain)
            if not targets:
                unresolved += 1
                logger.info(
                    "cpq: hiding rule %r (id=%s) has no resolvable target "
                    "via action/marked_attr/chain — excluded, not "
                    "silently guessed", rule_name, key)
                continue
            if fn_id != -1:
                script = scripts.get(fn_id)
                if not script:
                    script_missing += 1
                    if resolve_dt_whitelist_substitute_hiding_rule_name_membership(
                        rule_name, product_name, workspace_id, catalog_prefix,
                    ):
                        # Confirmed narrow carve-out (see that set's own
                        # docstring) -- substitute a real Data Table
                        # whitelist check for the missing script instead
                        # of dropping the rule (apply_hiding_rules
                        # handles dt_whitelist_substitute=True).
                        for target_attr_id, _action_type in targets:
                            rules.append(HidingRule(
                                rule_name=rule_name or str(eid),
                                condition_attr_id=0,
                                condition_value="",
                                target_attr_id=target_attr_id,
                                dt_whitelist_substitute=True,
                            ))
                        continue
                    logger.warning(
                        "cpq: hiding rule %r references function_id=%d "
                        "but no BmFunction script was found", rule_name, fn_id)
                    continue
                for target_attr_id, _action_type in targets:
                    rules.append(HidingRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=0,
                        condition_value="",
                        target_attr_id=target_attr_id,
                        script=script,
                    ))
                continue
            inp_list = inputs.get(key)
            if not inp_list:
                if _f10:
                    # plan F10: a declarative rule with no condition rows is
                    # always true (e.g. an "always hide" rule), not unknown.
                    # Review of #503 (2026-10-09): deliberately NOT
                    # conditioned on cpq_rule_scope_filter_enabled's current
                    # value -- a real (non-unbound) ref_id means this rule
                    # was authored for a SPECIFIC BmCatalog node, and this
                    # loader runs once per workspace/catalog (cached, shared
                    # across every turn and every product), with no per-turn
                    # model context to check that node against. Whether the
                    # scope filter happens to be on, and whether a later
                    # turn's resolved model even has a non-empty scope to
                    # check it against, are both unknowable here -- so a
                    # node-scoped rule with zero conditions is refused
                    # structurally, every time, the same "excluded, not
                    # silently guessed" treatment as an unresolved target.
                    # Only a genuinely UNBOUND rule (no ref_id at all) has
                    # nothing to misapply and may become always=True.
                    if ref_id and ref_id != "-1":
                        scope_unsafe_unconditional += 1
                        logger.info(
                            "cpq: hiding rule %r (id=%s) is unconditional "
                            "and scoped to ref_id=%r -- refusing to load it "
                            "as always=True (no per-turn scope check "
                            "available at load time)", rule_name, key, ref_id)
                        continue
                    for target_attr_id, action_type in targets:
                        rules.append(HidingRule(
                            rule_name=rule_name or str(eid),
                            condition_attr_id=0, condition_value="",
                            target_attr_id=target_attr_id,
                            hide=(int(action_type or 2) == 2), always=True,
                        ))
                    continue
                unresolved += 1
                continue
            # docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md
            # — a declarative condition checking the SAME attribute
            # with 2+ different operators cannot yet be evaluated
            # correctly by evaluate_declarative_conditions (it
            # collapses to the first row's operator+value, silently
            # dropping the rest). No single combining rule is
            # confirmed safe for every such shape yet — skip rather
            # than load with a guessed combining rule, same treatment
            # as the value-less-hide/constraint/recommendation/
            # validation branches in _load_value_rules.
            if engine._condition_has_operator_collision(inp_list):
                operator_collisions += 1
                continue
            cond_attr_id, cond_value, cond_operator = inp_list[-1]
            for target_attr_id, action_type in targets:
                rules.append(HidingRule(
                    rule_name=rule_name or str(eid),
                    condition_attr_id=cond_attr_id,
                    condition_value=cond_value,
                    condition_operator=cond_operator,
                    target_attr_id=target_attr_id,
                    hide=(int(action_type or 2) == 2),
                    conditions=copy_conditions(inp_list),
                ))
        if _scope:
            rule_scope.tag_ref_ids(rules, _marks)
    except Exception:
        logger.debug("cpq: hiding rule load failed", exc_info=True)

    script_backed = sum(1 for r in rules if r.script is not None)
    logger.info(
        "cpq: loaded %d hiding rules (%d declarative, %d script-backed, "
        "%d missing script, %d unresolved, %d skipped: same-attribute "
        "operator collision, docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_"
        "PLAN_2026_08_05.md, %d unconditional+scoped refused: no per-turn "
        "scope check available at load time) elapsed_s=%.3f",
        len(rules), len(rules) - script_backed, script_backed,
        script_missing, unresolved, operator_collisions,
        scope_unsafe_unconditional, time.monotonic() - _t0)
    return rules
