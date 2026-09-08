"""Reverting single-select overrides and building the combined cascade
notice for a multi-target cascade turn, split out of `_handle_cascade_
multi` (Phase 4/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling `ask_handle_
cascade_multi.py` under the line cap. Logic unchanged from the original
inline block. `_cpq_engine` is read through the ask_api MODULE object
(not imported by name) since at least one test replaces the whole
singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _revert_overridden_multi_singles(
    session: Any, attrs: list, user_requested_single: dict, applied_notes: list[str],
    pending: list,
) -> tuple:
    """D1, docs/CPQ_USER_VALUE_PRECEDENCE_PLAN.md: check every single-
    select change against the outcome — revert any the rule pass silently
    reassigned, in the order the message named them, so each gets the
    honest "isn't valid" wording and is re-asked instead of reported as
    accepted. See `_handle_cascade`'s identical check for the full
    rationale (same live-verified bug: a stably-true recommendation rule
    reasserting its own value over the customer's explicit choice).
    Mutates `applied_notes` in place (appending) and returns the possibly
    updated `pending` list.
    """
    _cpq_engine = _ask_api_module._cpq_engine
    overridden_attrs: list[Any] = []
    for _vn, (_attr, _want_value, _want_display) in user_requested_single.items():
        _attr_label = _cpq_engine.disambiguated_label(_attr, attrs)
        if session.filled.get(_vn) == _want_value:
            changed_disp = session.display_filled.get(_vn, _want_display)
            applied_notes.append(f"Updated **{_attr_label}** → **{changed_disp}**.")
        else:
            session.filled.pop(_vn, None)
            session.display_filled.pop(_vn, None)
            session.filled_source.pop(_vn, None)
            overridden_attrs.append(_attr)
            applied_notes.append(
                f"Your choice for **{_attr_label}** (**{_want_display}**) "
                f"isn't valid given the rest of this configuration — please "
                f"choose a different value."
            )
    if overridden_attrs:
        pending = overridden_attrs + [
            a for a in pending
            if a.variable_name not in {a2.variable_name for a2 in overridden_attrs}
        ]
        session.pending_variables = [a.variable_name for a in pending]
    return pending


def _build_cascade_multi_note(
    attrs: list, applied_notes: list[str], failed_labels: list[str],
    dependent_labels: list[str], dropped_multi: dict[str, list[str]],
) -> str:
    """Builds the combined cascade notice — one line per applied change,
    then one combined "these depend on what changed" note (same
    plain-English framing as the single-change path).
    """
    cascade_note = " ".join(applied_notes)
    if failed_labels:
        # Queued for sequential asks — never dead-end as "left unchanged".
        cascade_note += (
            f" I'll ask about each next"
            f" ({', '.join(f'**{lbl}**' for lbl in failed_labels)})."
        )
    if dependent_labels:
        if len(dependent_labels) == 1:
            cascade_note += (
                f" Because those changed, **{dependent_labels[0]}** depends "
                f"on them and needs a fresh value — recalculating now."
            )
        else:
            dep_list = ", ".join(f"**{lbl}**" for lbl in dependent_labels)
            cascade_note += (
                f" Because those changed, these depend on them and need "
                f"fresh values: {dep_list} — recalculating now."
            )
    for dvar, dvals in dropped_multi.items():
        dattr = next((a for a in attrs if a.variable_name == dvar), None)
        dlabel = dattr.display_label if dattr else dvar
        cascade_note += (
            f" Removed **{', '.join(dvals)}** from **{dlabel}** — "
            f"no longer valid after this change."
        )
    return cascade_note
