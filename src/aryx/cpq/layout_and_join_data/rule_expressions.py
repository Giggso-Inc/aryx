"""Attach each rule's ``condition_expression`` and input indexes to its
condition rows (plan F3). Only used when ``cpq_condition_expression_enabled``
is on; ``rule_join._load_rule_join_data`` calls it after the plain fetch.

The rows keep their original order (legacy code reads the LAST row) and stay
plain ``(attr_id, value, operator)`` tuples; the index of each row is found by
matching the tuple against the indexed fetch. A rule whose rows cannot be
matched one-to-one is left as a plain list (attribute grouping applies).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from aryx.cpq.bml.bml_condition_expression import ExprConditions


def attach_expressions(
    rdb: Any, workspace_id: int, catalog_prefix: str,
    inputs_by_rule: dict[int, list[tuple[int, str, str]]],
) -> dict[int, list[tuple[int, str, str]]]:
    """`inputs_by_rule` with an ``ExprConditions`` for every rule that has an
    expression and fully matched indexed rows."""
    expressions = rdb.fetch_rule_condition_expressions(workspace_id, catalog_prefix)
    if not expressions:
        return inputs_by_rule
    pool: dict[int, dict[tuple[int, str, str], list[int]]] = defaultdict(lambda: defaultdict(list))
    for rid, aid, val, op, idx in rdb.fetch_rule_input_indexes(workspace_id, catalog_prefix):
        pool[rid][(aid, val, op)].append(idx)
    out: dict[int, list[tuple[int, str, str]]] = {}
    for rid, rows in inputs_by_rule.items():
        expression = expressions.get(rid)
        free = pool.get(rid)
        if not expression or not free:
            out[rid] = rows
            continue
        free = {key: list(idxs) for key, idxs in free.items()}
        indexes: list[int] = []
        for row in rows:
            bucket = free.get(row)
            if not bucket:
                indexes = []
                break
            indexes.append(bucket.pop(0))
        out[rid] = ExprConditions(rows, expression, indexes) if indexes and len(indexes) == len(rows) else rows
    return out
