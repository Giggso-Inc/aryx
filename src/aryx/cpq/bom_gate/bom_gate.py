"""Final BOM gate — constraint re-check + provenance hard-fail.

Before any Step-8 payload is returned to the client:
1. Re-run constraint rules against the filled config.
2. Every {variable_name: item_value} must trace to a catalog option
   (DB-backed ConfigAttr.options from Postgres/FalkorDB load) OR a
   confirmed user/hint source with utterance evidence.
3. On failure: hard-fail with a catch message — never emit the payload.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split
across `bom_gate_types.py` (result dataclasses), `bom_gate_noise.py`
(shared noise-var detection), `bom_gate_provenance.py` (check_provenance),
`bom_gate_required.py` (find_missing_required_fields), and
`bom_gate_constraints.py` (recheck_constraints) — all re-imported here.
Zero whitebox test patches exist anywhere against `aryx.cpq.bom_gate.bom_gate.*`
(confirmed via grep; every caller uses direct-name imports), so the split
was purely mechanical. `validate_before_payload` — the Step-8 orchestrator
tying all of the above together — stays here.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.cpq.bom_gate.bom_gate_constraints import recheck_constraints
from aryx.cpq.bom_gate.bom_gate_provenance import check_provenance
from aryx.cpq.bom_gate.bom_gate_required import find_missing_required_fields
from aryx.cpq.bom_gate.bom_gate_types import BomGateResult, StaleConstraintViolation
from aryx.cpq.state import ConfigAttr, CpqSession
from aryx.raven_log import raven_log

__all__ = [
    "BomGateResult",
    "StaleConstraintViolation",
    "check_provenance",
    "find_missing_required_fields",
    "recheck_constraints",
    "validate_before_payload",
]

logger = logging.getLogger(__name__)


def validate_before_payload(
    engine: Any,
    attrs: list[ConfigAttr],
    session: CpqSession,
    con_rules: list,
    bml_eval: Any,
) -> BomGateResult:
    """Full Step-8 gate. ok=False → never emit payload.

    Two distinct failure classes, deliberately handled differently
    (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §11):
    - Provenance failures (an invented/hallucinated value with no catalog
      or utterance backing) are a real integrity problem — hard-fail,
      same as always.
    - Stale constraint violations (a real, previously-valid value that a
      later selection has now made invalid) are NOT hard-failed — the
      caller auto-clears and re-asks instead, since the engine knows
      what's wrong but not what the replacement should be.

    An unexpected error DURING the constraint recheck itself (§12) is a
    third case, deliberately treated as a hard fail — same "never guess"
    discipline as a provenance failure, not silently treated as "no
    violations found."

    A fourth case, added 2026-08-08: a currently-visible attr the catalog
    marks `required` with no value at all — confirmed live, this could
    previously reach this gate with no check catching it at all (docs/
    CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2c's ask/skip behavior can
    leave a required, non-decision attr silently unfilled). Hard-failed,
    same as provenance — the engine has no value to guess from here either.
    """
    missing_required = find_missing_required_fields(attrs, session)
    _gate_ctx = {
        "actor": "customer", "requested_action": "approve_quote",
        "resource": getattr(session, "product_name", "") or "", "required_permission": "bom_gate",
        "policy_version": "bom_gate_v1", "run_id": session.run_id or "",
        "fields_count": len(session.filled) + len(session.filled_multi),
    }
    if missing_required:
        labels = [
            f"{a.display_label} ({a.variable_name})" for a in missing_required
        ]
        logger.warning(
            "bom_gate: MISSING REQUIRED run_id=%s fields=%s",
            session.run_id or "-", [a.variable_name for a in missing_required],
        )
        raven_log(
            "WARN", "P3", "ask.bom_gate.decision blocked, required fields missing",
            error_code="ARYX_ASK_BOM_MISSING_REQUIRED",
            context={**_gate_ctx, "decision": "fail", "reason_code": "MISSING_REQUIRED",
                     "missing_fields": [a.variable_name for a in missing_required][:20]},
        )
        catch = (
            "⚠️ **Configuration gate blocked the BOM payload.**\n\n"
            "The following required fields have no value: "
            + ", ".join(f"**{l}**" for l in labels)
            + ".\n\nNo payload was emitted. Provide these fields, or say "
            "**undo** to restore the previous snapshot."
        )
        return BomGateResult(
            ok=False,
            errors=[f"missing required: {a.variable_name}" for a in missing_required],
            catch_message=catch,
        )
    try:
        stale = recheck_constraints(engine, attrs, session, con_rules, bml_eval)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bom_gate: constraint recheck failed: %r", exc)
        raven_log(
            "WARN", "P3", "ask.bom_gate.decision blocked, constraint recheck failed",
            error_code="ARYX_ASK_BOM_RECHECK_FAILED",
            context={**_gate_ctx, "decision": "fail", "reason_code": "RECHECK_FAILED",
                     "error_class": type(exc).__name__},
        )
        catch = (
            "⚠️ **Configuration gate blocked the BOM payload.**\n\n"
            f"Constraint verification failed unexpectedly ({exc}) — "
            "this can't be verified as valid, so nothing was emitted.\n\n"
            "Try **confirm** again, or say **undo** to restore the "
            "previous snapshot."
        )
        return BomGateResult(
            ok=False, errors=[f"constraint recheck error: {exc}"],
            catch_message=catch,
        )
    errors = check_provenance(attrs, session)

    if errors:
        logger.warning(
            "bom_gate: HARD FAIL run_id=%s errors=%s",
            session.run_id or "-", errors[:10],
        )
        raven_log(
            "WARN", "P3", "ask.bom_gate.decision blocked, provenance hard fail",
            error_code="ARYX_ASK_BOM_HARD_FAIL",
            context={**_gate_ctx, "decision": "fail", "reason_code": "PROVENANCE_HARD_FAIL",
                     "error_count": len(errors)},
        )
        catch = (
            "⚠️ **Configuration gate blocked the BOM payload.**\n\n"
            "One or more values could not be verified against the catalog "
            "or your stated answers:\n"
            + "\n".join(f"- {e}" for e in errors[:8])
            + "\n\nNo payload was emitted. Fix the fields above, or say "
            "**undo** to restore the previous snapshot."
        )
        return BomGateResult(ok=False, errors=errors, catch_message=catch)

    if stale:
        logger.info(
            "bom_gate: STALE CONSTRAINT run_id=%s attrs=%s",
            session.run_id or "-", [v.attr.variable_name for v in stale],
        )
        raven_log("INFO", "P4", "ask.bom_gate.decision stale constraint violations, re-ask", context={
            **_gate_ctx, "decision": "fail", "reason_code": "STALE_CONSTRAINT",
            "stale_fields": [v.attr.variable_name for v in stale][:20],
        })
        return BomGateResult(ok=False, errors=[], stale_violations=stale)

    logger.info("bom_gate: PASS run_id=%s fields=%d",
                session.run_id or "-", len(session.filled) + len(session.filled_multi))
    raven_log("INFO", "P4", "ask.bom_gate.decision pass", context={
        **_gate_ctx, "decision": "pass", "reason_code": "ALL_CHECKS_PASSED",
    })
    return BomGateResult(ok=True, errors=[])
