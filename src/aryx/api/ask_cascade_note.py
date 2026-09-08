"""Building the cascade-change notice text shown at the top of a STEP-6
cascade response, split out of `_handle_cascade` (Phase 4/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md)
purely to keep the sibling `ask_handle_cascade.py` under the line cap.
Logic unchanged from the original inline block. `_cpq_engine` is read
through the ask_api MODULE object (not imported by name) since at least
one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _build_cascade_note(
    session: Any, attrs: list, changed_attr: Any, new_value_hint: str,
    dependent_labels: list[str], dropped_multi: dict[str, list[str]],
    user_value_overridden: bool, requested_display: str | None,
) -> str:
    """Amendment (2026-07-28), docs/CPQ_LLM_INTENT_FIRST_PLAN.md: uses the
    disambiguated label, not the raw shared one — several attrs in this
    catalog carry the identical display_label "Service Type", and when
    more than one changes value in the same turn (the user's own change
    plus an independently-firing recommendation rule elsewhere) the raw
    label made every line read as the same fact repeated.
    """
    _changed_label = _ask_api_module._cpq_engine.disambiguated_label(changed_attr, attrs)
    if user_value_overridden:
        cascade_note = (
            f"Your choice for **{_changed_label}** "
            f"(**{requested_display}**) isn't valid given the rest of this "
            f"configuration — please choose a different value:"
        )
    else:
        changed_disp = session.display_filled.get(changed_attr.variable_name, new_value_hint)
        cascade_note = f"Updated **{_changed_label}** → **{changed_disp}**."
    if dependent_labels and not user_value_overridden:
        # Plain-English framing, not a raw label dump — "This invalidated:
        # X, Y — re-evaluating." read as internal/mechanical shorthand
        # rather than something a sales rep could act on. Names WHY (the
        # change just made) and WHAT is happening (fresh values being
        # computed), singular/plural phrased so one dependent doesn't read
        # oddly as a list.
        if len(dependent_labels) == 1:
            cascade_note += (
                f" Because **{_changed_label}** changed, "
                f"**{dependent_labels[0]}** depends on it and needs a fresh "
                f"value — recalculating now."
            )
        else:
            dep_list = ", ".join(f"**{lbl}**" for lbl in dependent_labels)
            cascade_note += (
                f" Because **{_changed_label}** changed, these "
                f"depend on it and need fresh values: {dep_list} — "
                f"recalculating now."
            )
    for dvar, dvals in dropped_multi.items():
        dattr = next((a for a in attrs if a.variable_name == dvar), None)
        dlabel = dattr.display_label if dattr else dvar
        cascade_note += (
            f" Removed **{', '.join(dvals)}** from **{dlabel}** — "
            f"no longer valid after this change."
        )
    return cascade_note
