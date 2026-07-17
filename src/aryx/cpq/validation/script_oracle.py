"""Small independent BML oracle; unsupported syntax stays explicitly unknown."""
from __future__ import annotations

import re

_IF_ELSE_RE = re.compile(
    r'if\s*\(\s*(\w+)\s*(==|!=|<>)\s*"([^"]*)"\s*\)\s*'
    r'\{([^{}]*)\}\s*else\s*\{([^{}]*)\}',
    re.IGNORECASE | re.DOTALL,
)
_BOOL_RE = re.compile(r"\breturn\s+(true|false)\b", re.IGNORECASE)
_ASSIGN_RE = re.compile(r'return[Vv]al\s*=\s*((?:"[^"]*"\s*\|?\s*)+)', re.DOTALL)
_VALUE_RE = re.compile(r'"([^"]*)"')


class DeterministicBmlOracle:
    """Evaluate only a conservative flat if/else BML subset without an LLM."""

    def hide(self, script: str, filled: dict[str, str]) -> bool | None:
        """Return a hide boolean for a supported script, otherwise None."""
        body = self._selected_body(script, filled)
        if body is None:
            return None
        match = _BOOL_RE.search(body)
        return match.group(1).lower() == "true" if match else None

    def values(self, script: str, filled: dict[str, str]) -> tuple[str, ...] | None:
        """Return deterministic action values for a supported script."""
        body = self._selected_body(script, filled)
        if body is None:
            return None
        match = _ASSIGN_RE.search(body)
        if not match:
            return None
        values = tuple(
            value.strip() for value in _VALUE_RE.findall(match.group(1))
            if value.strip()
        )
        return values or None

    def condition(self, script: str, filled: dict[str, str]) -> bool | None:
        """Evaluate a supported boolean condition script."""
        return self.hide(script, filled)

    @staticmethod
    def supports_hide(script: str) -> bool:
        """True when both branches have deterministic boolean returns."""
        match = _IF_ELSE_RE.fullmatch(script.strip())
        return bool(
            match
            and _BOOL_RE.search(match.group(4))
            and _BOOL_RE.search(match.group(5))
        )

    @staticmethod
    def supports_values(script: str) -> bool:
        """True when both branches have deterministic returnVal assignments."""
        match = _IF_ELSE_RE.fullmatch(script.strip())
        return bool(
            match
            and _ASSIGN_RE.search(match.group(4))
            and _ASSIGN_RE.search(match.group(5))
        )

    def supports_condition(self, script: str) -> bool:
        """Return whether a condition script fits the supported boolean subset."""
        return self.supports_hide(script)

    @staticmethod
    def _selected_body(script: str, filled: dict[str, str]) -> str | None:
        """Select a flat if/else body when its referenced variable is known."""
        match = _IF_ELSE_RE.fullmatch(script.strip())
        if not match:
            return None
        variable, operator, expected, yes_body, no_body = match.groups()
        actual = filled.get(variable)
        if actual is None:
            return None
        equal = actual.strip().lower() == expected.strip().lower()
        condition = equal if operator == "==" else not equal
        return yes_body if condition else no_body
