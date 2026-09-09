"""Applying the new value for a STEP-6 cascade change, split out of
`_handle_cascade` (Phase 4/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling
`ask_handle_cascade.py` under the line cap. Logic unchanged from the
original inline block. `_cpq_engine`, `logger`,
`_extract_replacement_clause`, and `_constrain_excluding_rejected` are
read through the ask_api MODULE object (not imported by name) since
ask_api tests patch several of its own module-level names by dotted
path, and this avoids depending on their definition order relative to
this import.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_scope_and_pending.ask_change_decline_and_scope_memory import _constrain_excluding_rejected, _extract_replacement_clause


def _apply_cascade_new_value(
    session: Any, changed_attr: Any, new_value_hint: str, hc_allowed: list[str] | None,
) -> tuple:
    """Extracts the WANTED value from a replacement-style utterance
    ("X instead of Y") and applies it — excluding the rejected option via
    the freshly recomputed `hc_allowed` (not a possibly-stale param) so
    fuzzy match cannot re-pick it even if residual text leaks through.
    Locks the new value onto `session` when a match is found. Returns
    (result, apply_constrained) — `result` is None on no-match, in which
    case the caller must build the "couldn't match" retry response.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    wanted_clause, rejected_clause = _extract_replacement_clause(new_value_hint)
    apply_hint = wanted_clause if wanted_clause else new_value_hint
    apply_constrained = _constrain_excluding_rejected(
        changed_attr, rejected_clause, hc_allowed,
    )
    if wanted_clause or rejected_clause:
        _ask_api_module.logger.info(
            "cpq_replacement: attr=%s wanted=%r rejected=%r apply_hint=%r "
            "constrained_excl=%s",
            getattr(changed_attr, "variable_name", None),
            wanted_clause, rejected_clause, apply_hint,
            apply_constrained is not None and apply_constrained != hc_allowed,
        )

    # Lock in the new value for the changed attr
    if changed_attr.select_type == "multi":
        # UNION every mentioned option with the current selection — a
        # post-completion "include Locking Molle Mount" ADDS a row, it
        # doesn't wipe rows already chosen (and a previously DECLINED
        # empty grid simply becomes the new rows). apply_multi_answer
        # extracts all named options, not just the best single match.
        # docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §12 — the
        # constrained set must reach the multi-select matcher too, not just
        # the single-select apply_answer path below. PROMPT 6: apply_hint
        # is wanted-only; apply_constrained excludes rejected option.
        mentioned = _cpq_engine.apply_multi_answer(
            changed_attr, apply_hint, apply_constrained,
        )
        result = ("", "") if not mentioned else mentioned[0]
        if mentioned:
            existing = session.filled_multi.get(changed_attr.variable_name, [])
            merged = list(existing) + [iv for iv, _dn in mentioned if iv not in existing]
            session.filled_multi[changed_attr.variable_name] = merged
            session.display_filled[changed_attr.variable_name] = ", ".join(
                next((o.display_name for o in changed_attr.options if o.item_value == v), v)
                for v in merged
            )
            session.filled_source[changed_attr.variable_name] = "user"
        else:
            result = None
    else:
        result = _cpq_engine.apply_answer(
            changed_attr, apply_hint, apply_constrained,
        )
        if result:
            session.filled[changed_attr.variable_name] = result[0]
            session.display_filled[changed_attr.variable_name] = result[1]
            session.filled_source[changed_attr.variable_name] = "user"
    return result, apply_constrained
