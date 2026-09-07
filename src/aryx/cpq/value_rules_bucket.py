"""Per-target bucketing of declarative value-rule actions (restrict vs.
recommend vs. hide), split out of `_load_value_rules`'s per-row loop body
(Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). The genuinely
ambiguous multi-value case delegates to `value_rules_ambiguous.py`. Logic
unchanged from the original inline block.
"""

from __future__ import annotations

from aryx.cpq.value_rules_ambiguous import resolve_ambiguous_multivalue_action
from aryx.cpq.value_rules_state import RuleLoadState


def bucket_declarative_actions(
    state: RuleLoadState, eid: int, rule_name: str, acts: list[tuple],
) -> tuple[dict[int, list[str]], dict[int, str], set[int]]:
    """BigMachines packs multiple allowed values for one action
    into a single value1 field, tilde-delimited (confirmed live:
    "DEVICE RENTAL~DEVICE INSTALLATION~DEVICE PROGRAMMING" for
    one rule_action row) — split before use or the whole glued
    string gets treated as one (non-existent) option, leaving
    the target with zero real valid values.

    docs/CPQ_VALUELESS_HIDE_ACTION_LOADING_GAP_PLAN_2026_08_05.md
    — a declarative action with NO literal value1 (function_id
    =-1) is a genuine "hide" for set_type in (1, 3): confirmed
    via cross-catalog rule-name sampling (1,096 such actions
    across 4 ingested catalogs), e.g. "Associated rec rule to
    Hide Frequency Band for Single Band" — hiding needs no
    value to assign, unlike a recommendation/constraint. Scoped
    to (1, 3) specifically: set_type=2's real names are
    genuinely mixed (some "Show...", some "Set X to blank" —
    a third, distinct semantic), and set_type=-1's real names
    are mostly unrelated format/range validation ("Restrict
    value of Astro System Id to 4 hexadecimal chars") — never
    guessed without separate confirmation (D2).
    """
    restrict_by_target: dict[int, list[str]] = {}
    recommend_by_target: dict[int, str] = {}
    hide_targets: set[int] = set()
    for aid, _at, val, act_fn, set_type, _comments in acts:
        if act_fn != -1:
            continue
        if not val:
            if set_type in (1, 3):
                hide_targets.add(aid)
            continue
        parts = [p.strip() for p in val.split("~") if p.strip()]
        if set_type == -1:
            restrict_by_target.setdefault(aid, []).extend(parts)
        elif len(parts) == 1:
            recommend_by_target.setdefault(aid, parts[0])
        else:
            resolve_ambiguous_multivalue_action(
                state, eid, aid, rule_name, set_type, parts, restrict_by_target)
    return restrict_by_target, recommend_by_target, hide_targets
