"""Orchestrator for `_load_value_rules`'s per-catalog rule fetch + row loop
(Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Cache lookup/
write and `IngestQuestionStore` setup stay in `CpqEngine._load_value_rules`
itself — both are patched by name at `aryx.cpq.engine.*` in tests. Logic
unchanged from the original inline loop.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.cpq.engine import logger
from aryx.cpq.value_rules_row import process_value_rule_row
from aryx.cpq.value_rules_state import RuleLoadState


def load_value_rules(
    engine: Any, workspace_id: int, catalog_prefix: str, ingest_store: Any,
    existing_questions: dict[str, Any], t0: float,
) -> tuple[list[Any], list[Any], list[Any], list[Any]]:
    state = RuleLoadState(
        ingest_store=ingest_store, existing_questions=existing_questions,
        workspace_id=workspace_id,
    )
    try:
        rdb, inputs, actions, _marked, _chain = engine._load_rule_join_data(
            workspace_id, catalog_prefix)
        scripts = rdb.fetch_function_scripts(workspace_id, catalog_prefix)
        for eid, src_id, rule_name, _rule_type, fn_id in rdb.fetch_value_rules(
            workspace_id, catalog_prefix, active_only=True,
        ):
            key = engine._rule_key(eid, src_id, inputs, actions)
            inp_list = inputs.get(key)
            acts = actions.get(key, [])
            process_value_rule_row(
                engine, state, eid, rule_name, fn_id, inp_list, acts, scripts)
    except Exception:
        logger.debug("cpq: value-rule load failed", exc_info=True)

    logger.info(
        "cpq: loaded %d recommendation rules, %d constraint rules, "
        "%d value-less hide rules "
        "(%d script-backed constraints, %d script-backed recommendations "
        "wired, %d script-condition rules gating a declarative action, "
        "%d script-condition rules skipped, %d multi-value actions "
        "awaiting a constraint-or-assign-all human answer, %d 'assign_all' "
        "answers blocked (multi-value recommendation not yet supported), "
        "%d unrecognized answers auto-requeued with a fresh question, "
        "%d/%d/%d recommendation/constraint/hide skipped: same-attribute "
        "operator collision, "
        "docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md)",
        len(state.rec_rules), len(state.con_rules), len(state.hiding_rules),
        state.script_constraints, state.script_recommendations_wired,
        state.script_condition_gated, state.cond_script_skipped,
        state.ambiguous_recommendations_skipped, state.assign_all_answers_blocked,
        state.unrecognized_answers_requeued, state.recommendation_collisions_skipped,
        state.constraint_collisions_skipped, state.hiding_collisions_skipped)
    logger.info(
        "cpq: loaded %d validation (warning-message) rules "
        "(%d skipped: same-attribute operator collision, "
        "docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md)",
        len(state.validation_rules), state.validation_collisions_skipped)
    logger.info(
        "cpq_step: _load_value_rules done elapsed_s=%.3f rec=%d con=%d "
        "validation=%d extra_hiding=%d",
        time.monotonic() - t0, len(state.rec_rules), len(state.con_rules),
        len(state.validation_rules), len(state.hiding_rules),
    )
    return state.rec_rules, state.con_rules, state.validation_rules, state.hiding_rules
