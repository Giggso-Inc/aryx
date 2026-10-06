"""Oracle ``condition_expression`` evaluation over ``rule_input_index`` rows.

A rule's declarative condition is a boolean expression over its numbered
input rows, for example ``(1 AND 15) AND (2 OR (3 AND 4)) AND 10`` (AND binds
tighter than OR). ``evaluate_declarative_conditions`` otherwise groups rows by
attribute (same attribute OR, different attributes AND), which gives the wrong
answer for expressions that mix attributes or use different operators on one
attribute. The rows stay a plain list of ``(attr_id, value, operator)``
tuples (so every existing consumer keeps working); ``ExprConditions`` is that
list plus the expression and the per-row index.

Three-valued logic: a row whose attribute is not filled yet is unknown, and
unknown only decides the result when no known operand already does.
"""
from __future__ import annotations

import re
from typing import Iterable

from aryx.cpq.bml.bml_declarative import _operator_hit

_TOKEN_RE = re.compile(r"\s*(\d+|\(|\)|AND\b|OR\b)", re.IGNORECASE)


class ExprConditions(list):
    """Condition rows plus the rule's expression and each row's index."""

    expression: str = ""
    indexes: list[int]

    def __init__(
        self, rows: Iterable[tuple[int, str, str]] = (), expression: str = "",
        indexes: Iterable[int] = (),
    ) -> None:
        super().__init__(rows)
        self.expression = expression
        self.indexes = list(indexes)


def copy_conditions(conditions: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    """A copy of `conditions` that keeps the expression metadata, if any."""
    if isinstance(conditions, ExprConditions):
        return ExprConditions(conditions, conditions.expression, conditions.indexes)
    return list(conditions)


def _tokens(expression: str) -> list[str]:
    out, pos = [], 0
    text = expression.strip()
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if not match:
            raise ValueError(f"unsupported token at {pos} in {expression!r}")
        out.append(match.group(1).upper())
        pos = match.end()
    return out


def _and(left: bool | None, right: bool | None) -> bool | None:
    if left is False or right is False:
        return False
    return None if left is None or right is None else True


def _or(left: bool | None, right: bool | None) -> bool | None:
    if left is True or right is True:
        return True
    return None if left is None or right is None else False


class _Parser:
    def __init__(self, tokens: list[str], atom_value) -> None:
        self.tokens, self.pos, self.atom_value = tokens, 0, atom_value

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _take(self) -> str:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse(self) -> bool | None:
        value = self._or()
        if self._peek() is not None:
            raise ValueError("trailing tokens")
        return value

    def _or(self) -> bool | None:
        value = self._and()
        while self._peek() == "OR":
            self._take()
            value = _or(value, self._and())
        return value

    def _and(self) -> bool | None:
        value = self._atom()
        while self._peek() == "AND":
            self._take()
            value = _and(value, self._atom())
        return value

    def _atom(self) -> bool | None:
        if self._peek() is None:
            raise ValueError("unexpected end")
        token = self._take()
        if token == "(":
            value = self._or()
            if self._peek() != ")":
                raise ValueError("missing )")
            self._take()
            return value
        if token.isdigit():
            return self.atom_value(int(token))
        raise ValueError(f"unexpected {token!r}")


def evaluate_condition_expression(
    conditions: ExprConditions, variables_by_id: dict[int, str],
) -> tuple[bool | None, bool]:
    """(True|False, False) when decided; (None, True) when an unfilled
    attribute leaves the result open. Raises ValueError for an expression
    this evaluator does not support (the caller falls back)."""
    by_index = dict(zip(conditions.indexes, conditions))

    def atom_value(index: int) -> bool | None:
        row = by_index.get(index)
        if row is None:
            raise ValueError(f"expression names missing row {index}")
        attr_id, value, operator = row
        actual = variables_by_id.get(attr_id)
        if actual is None:
            return None
        return _operator_hit(actual, [value], operator)

    result = _Parser(_tokens(conditions.expression), atom_value).parse()
    return (result, False) if result is not None else (None, True)
