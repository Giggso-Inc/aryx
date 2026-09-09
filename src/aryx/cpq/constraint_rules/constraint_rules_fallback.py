"""Empty-intersection fallback for ``apply_constraint_rules`` (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from
the original inline pass.

docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_05.md's "Known
remaining issue" (explicit product decision 2026-08-05): confirmed live
that some catalogs carry a genuine authoring gap -- a constraint rule
never given a counterpart for a newer product variant, unconditionally
colliding with that variant's own (correct) constraint and zeroing the
intersection. When that happens, rules that fired are grouped by their
condition attribute set; each candidate group is scored by how many
rules catalog-wide (the full `rules` list, not just those active this
turn) reference that same condition attribute -- confirmed live this
cleanly separates a catalog's backbone discriminator
(productSelectionProduct_all, 478 references in one real catalog) from
an incidentally-referenced peripheral one
(additionalSystemEnhancementFeatureType_astro, 3 references). Dropping
the single group with the strictly lowest score resolves the conflict;
a tie for lowest, or 2+ groups whose removal would each independently
resolve it, is genuinely ambiguous and left empty rather than guessed.
Never applied to script-backed rules (their conditions aren't a
declarative attr set to group or score).
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import logger


def resolve_empty_intersections(
    rules: list[Any],
    by_rule_id: dict[int, Any],
    constrained: dict[int, list[str]],
    contributions: dict[int, list[tuple[frozenset, list[str], str]]],
) -> None:
    """Mutates `constrained` in place, filling in a resolved candidate
    set for any attr whose real active rules intersected to empty.
    """
    # How catalog-wide "central" each condition attribute is to THIS
    # constraint ruleset -- counted from the full `rules` list (every
    # declarative condition attr this ConstraintRule set ever
    # references), not just the ones that fired this turn.
    attr_ref_count: dict[int, int] = {}
    for r in rules:
        ids = (
            {a for a, _v, _op in r.conditions} if r.conditions
            else ({r.condition_attr_id} if r.condition_script is None and r.script is None else set())
        )
        for attr_id in ids:
            attr_ref_count[attr_id] = attr_ref_count.get(attr_id, 0) + 1

    def _centrality(condition_key: frozenset) -> int:
        return max((attr_ref_count.get(a, 0) for a in condition_key), default=0)

    for entity_id, rows in contributions.items():
        if constrained.get(entity_id) or len(rows) < 2:
            continue
        groups: dict[frozenset, list[tuple[list[str], str]]] = {}
        for condition_key, normalized, rule_name in rows:
            groups.setdefault(condition_key, []).append((normalized, rule_name))
        if len(groups) < 2:
            continue  # everything shares one condition -- genuinely all-or-nothing
        resolved_by_dropping: list[tuple[frozenset, list[str]]] = []
        for dropped_key in groups:
            kept_sets = [
                set(normalized)
                for key, entries in groups.items() if key != dropped_key
                for normalized, _rule_name in entries
            ]
            candidate = set.intersection(*kept_sets) if kept_sets else set()
            if candidate:
                resolved_by_dropping.append((dropped_key, sorted(candidate)))
        if not resolved_by_dropping:
            continue
        # Prefer dropping whichever candidate group's condition
        # attribute is LEAST central catalog-wide -- only when that
        # minimum is unambiguous (a strict minimum, not tied with
        # another candidate group). A tie means two structurally
        # equally-plausible resolutions exist; never guess between them.
        scored = sorted(
            ((_centrality(key), key, candidate) for key, candidate in resolved_by_dropping),
        )
        target_name = by_rule_id[entity_id].variable_name if entity_id in by_rule_id else entity_id
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            logger.warning(
                "cpq: constraint intersection for %s is empty and 2+ "
                "equally-central rule-groups could each resolve it — "
                "ambiguous, left empty rather than guessing which one wins",
                target_name,
            )
            continue
        _score, dropped_key, candidate = scored[0]
        dropped_names = sorted({rule_name for _normalized, rule_name in groups[dropped_key]})
        logger.warning(
            "cpq: constraint intersection for %s was empty across all "
            "active rules; dropped least catalog-central conflicting "
            "rule(s) %s (condition attrs %s, %d catalog-wide reference(s)) "
            "to resolve to %s — docs/CPQ_MULTISELECT_AUTOFILL_"
            "OVERSELECTION_PLAN_2026_08_05.md empty-intersection fallback",
            target_name, dropped_names, sorted(dropped_key), _score, candidate,
        )
        constrained[entity_id] = candidate
