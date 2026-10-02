"""Whitelist-narrowing pass for ``apply_constraint_rules`` (D13/D17).

Port of aryxent PR 11: every unanswered attr whose real Whitelist-narrowed
legal set (``_resolve_narrowed_legal_values``) has 2+ values gets that set
intersected into the same ``constrained`` result a ConstraintRule would
populate, so question option lists are narrowed. Only used when the caller
passes ``narrow_from_data_tables=True`` (flag
``cpq_whitelist_narrow_questions_enabled``).
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.constraint_rules.constraint_rules_intersect import intersect, normalize


def apply_data_table_narrowing(
    attrs: list[Any],
    filled: dict[str, str],
    workspace_id: int | None,
    catalog_prefix: str,
    dt_cache: dict[tuple[int, str], tuple] | None,
    constrained: dict[int, list[str]],
    contributions: dict[int, list[tuple[frozenset, list[str], str]]],
) -> None:
    """Mutates `constrained`/`contributions` in place. No-op without a
    workspace_id."""
    if workspace_id is None:
        return
    from aryx.cpq.data_table_bridge.conflicts import _resolve_narrowed_legal_values

    for target in attrs:
        if filled.get(target.variable_name):
            continue
        narrowed = _resolve_narrowed_legal_values(
            target.variable_name, filled, workspace_id, catalog_prefix, dt_cache,
        )
        if narrowed and len(narrowed) >= 2:
            # Runs after resolve_empty_intersections, so an intersection that
            # narrowing itself would empty is never repaired. Narrowing is
            # advisory: when it would contradict an existing rule-derived set,
            # skip it and keep the rule's set.
            existing = constrained.get(target.entity_id)
            if existing is not None and not set(existing) & set(normalize(target, narrowed)):
                continue
            intersect(
                constrained, contributions, target, narrowed,
                frozenset({"data_table_narrowing"}), "data_table_narrowing",
            )
