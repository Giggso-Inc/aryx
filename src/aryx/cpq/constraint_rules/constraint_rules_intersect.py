"""Shared value-intersection helpers for ``apply_constraint_rules``
(Phase 4, one of the 8 previously-deferred oversized `CpqEngine`
methods, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Used by both
the main declarative/script rule loop and the narrowing_rec_rules loop.
"""

from __future__ import annotations

from typing import Any


def normalize(target: Any, allowed: list[str]) -> list[str]:
    """docs/config_consistency_issues_2026-07-30.md — a raw catalog
    rule's own authored allowed-value list can carry different
    letter-casing than the attribute's real menu item_value
    (confirmed live: the declarative rule "Constrain for
    APXNEXTSINGLE & APXNEXTXNSINGLE" lists "700/800 MHz" while
    every real menu item for this attribute is "700/800 MHZ" —
    a genuine source-catalog authoring inconsistency, not a bug
    in this parsing). Left uncorrected, this made a brand-new,
    completely default APX NEXT Single Band order fail its own
    BOM-gate stale-constraint check on the very first confirm,
    every time — the default value was never actually invalid,
    it just didn't case-exact-match the rule's own typo.
    Normalize each allowed value back to its real catalog
    item_value (case-insensitive lookup) before comparing/
    intersecting, so a same-value-different-case rule entry
    behaves exactly like the correctly-cased one would.
    """
    by_lower_item_value = {o.item_value.lower(): o.item_value for o in target.options}
    return [by_lower_item_value.get(v.lower(), v) for v in allowed]


def intersect(
    constrained: dict[int, list[str]],
    contributions: dict[int, list[tuple[frozenset, list[str], str]]],
    target: Any,
    allowed: list[str],
    condition_key: frozenset,
    rule_name: str,
) -> None:
    """Intersect `allowed` into `constrained[target.entity_id]` (AND
    semantics across every rule targeting the same attr), recording the
    contribution for the empty-intersection fallback in
    `constraint_rules_fallback.py`.
    """
    normalized = normalize(target, allowed)
    contributions.setdefault(target.entity_id, []).append(
        (condition_key, normalized, rule_name))
    if target.entity_id in constrained:
        existing = set(constrained[target.entity_id])
        constrained[target.entity_id] = [v for v in normalized if v in existing]
    else:
        constrained[target.entity_id] = list(normalized)
