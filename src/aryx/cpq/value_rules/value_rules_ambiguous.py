"""Ambiguous multi-value constraint-or-default resolution (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md), split out of
`_load_value_rules`'s per-row bucketing loop. Logic unchanged from the
original inline block.
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.cpq.value_rules.value_rules_state import RuleLoadState

logger = logging.getLogger(__name__)


def resolve_ambiguous_multivalue_action(
    state: RuleLoadState, eid: int, aid: int, rule_name: str, set_type: int,
    parts: list[str], restrict_by_target: dict[int, list[str]],
) -> None:
    """docs/CPQ_BUG2_CONSTRAINT_DISPATCH_MISCLASSIFICATION_
    IMPLEMENTATION_PLAN_2026-08-14.md (v2) — a multi-
    value, set_type != -1 action is genuinely ambiguous
    between two DIFFERENT intents: "assign all N values
    as the default selection" vs. "narrow this field's
    valid choices to exactly these N values" (a
    constraint). Verified live against real ingested
    data (apx-cpq-test + workspace 19, 62 real rows)
    that NEITHER the target's select_type NOR any BM-
    native constraint-shaped field (constrain_all,
    constraint_type, filter_attribute, action_type,
    value_type) varies AT ALL across this whole rule
    set — there is no structural signal in the ingested
    schema that resolves this. Never guessed in code
    (D2) — a wrong automatic guess here would ship a
    customer configuration with features they never
    chose, worse than today's silent skip. Routed to a
    human via aryx_ingest_question, asking the actual
    question (constraint vs. assign-all) instead of the
    old "which ONE is the default" framing, which was
    incoherent for every one of these rules (their
    targets are all multi-select fields, verified live
    — "pick exactly one" was never a valid framing). A
    distinct job_id/kind from the old ambiguous-
    recommendation question avoids misreading any prior
    answer under the old (wrong) question semantics —
    confirmed live that none of the 62 real rows were
    ever answered, so this is a clean cutover.
    Raven review of PR #198 — a malformed/case-mismatched
    answer (e.g. "Constraint", stray whitespace) must
    never permanently strand the rule with only a
    manual DB fix as recovery. Normalize before
    comparing, and if the LATEST question in this
    rule's job_id chain was answered with neither
    recognized value, mint the NEXT one in the chain so
    a fresh, pending, answerable question appears
    automatically — the stale answered row is left
    alone (harmless history), never re-used or deleted.
    """
    base_job_id = f"cpq-rule-{eid}-{aid}-constraint-or-default"
    job_id = base_job_id
    chain_n = 2
    while f"{base_job_id}-r{chain_n}" in state.existing_questions:
        job_id = f"{base_job_id}-r{chain_n}"
        chain_n += 1
    existing = state.existing_questions.get(job_id)
    answered_unrecognized = False
    if existing and existing.get("status") == "answered":
        answer = (existing.get("answer") or "").strip().lower()
        if answer == "constraint":
            restrict_by_target.setdefault(aid, []).extend(parts)
            return
        if answer == "assign_all":
            # Not yet applicable — RecommendationRule.
            # recommended_value (state.py:111) holds a
            # single value; assigning N simultaneous
            # values needs a separate model change
            # (list-valued recommendations wired into
            # filled_multi). Logged as blocked, never
            # silently guessed or partially applied.
            state.assign_all_answers_blocked += 1
            logger.info(
                "cpq: rule %r answered 'assign_all' for "
                "target=%d (%r), but multi-value "
                "recommendation assignment isn't "
                "supported yet — blocked pending a "
                "separate fix", rule_name, aid, parts)
            return
        # Unrecognized answer — mint the next job_id in
        # the chain so the enqueue below creates a fresh,
        # pending question instead of leaving this rule
        # permanently stuck behind an unusable answer.
        answered_unrecognized = True
        state.unrecognized_answers_requeued += 1
        job_id = f"{base_job_id}-r{chain_n}"
        existing = None
    state.ambiguous_recommendations_skipped += 1
    logger.info(
        "cpq: rule %r has a multi-value action "
        "(set_type=%r) for target=%d (%r) — no "
        "structural signal distinguishes constraint "
        "from assign-all, %s", rule_name, set_type, aid,
        parts,
        "prior answer was unrecognized (expected "
        "'constraint' or 'assign_all') — a fresh "
        "question has been queued" if answered_unrecognized
        else "awaiting human answer (already queued)" if existing
        else "queued for human answer")
    if not existing and state.ingest_store is not None:
        try:
            state.ingest_store.enqueue(
                state.workspace_id, job_id=job_id,
                kind="cpq_multivalue_constraint_or_default",
                prompt=(
                    f"Rule '{rule_name}' offers {parts} "
                    f"for attribute {aid}. Should this "
                    "NARROW the field's valid choices to "
                    "exactly these values (reply "
                    "'constraint'), or ASSIGN all of "
                    "them as the default selection "
                    "(reply 'assign_all')?"),
                options=["constraint", "assign_all"],
                suggested="")
            state.existing_questions[job_id] = {"status": "pending"}
        except Exception:
            logger.debug(
                "cpq: failed to enqueue constraint-or-"
                "default ingest question", exc_info=True)
