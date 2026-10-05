"""ALLOW / DISALLOW mode of a constraint action script (plan F2).

Some constraint rules do not return an allowed list: their action script calls
the platform function ``setConstraintValuesInSession(<attribute>, <values>,
"ALLOW"|"DISALLOW" [+ suffix])`` with a literal value list, optionally inside
an ``if(<variable> <> "")`` guard. The mode and the list are read from the
script text only (no attribute, model or value names in code). Anything that is
not a plain literal list returns ``None`` and the rule stays on the old path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
_CALL_RE = re.compile(
    r'setConstraintValuesInSession\s*\(\s*"[^"]+"\s*,\s*(?P<val>"[^"]*"|\w+)\s*,\s*"(?P<mode>ALLOW|DISALLOW)"',
    re.IGNORECASE,
)
_GUARD_RE = re.compile(
    r'if\s*\(\s*(?P<var>\w+)\s*<>\s*""\s*\)\s*\{[^{}]*setConstraintValuesInSession', re.IGNORECASE | re.DOTALL,
)
_STRINGS_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class ConstraintMode:
    mode: str                 # "ALLOW" or "DISALLOW"
    values: list[str]
    guard_var: str = ""       # variable that must be non-empty for the call to run
    blank: bool = False       # the literal list contains the empty string (blank itself is allowed/disallowed)


def _split_values(raw: list[str]) -> list[str]:
    out: list[str] = []
    for item in raw:
        out.extend(p.strip() for p in re.split(r"\|\^\||~", item) if p.strip())
    return out


def _assigned_literals(script: str, var: str) -> list[str] | None:
    """Strings of the last ``var = "x"`` / ``var = string[]{"x","y"}`` assignment."""
    pattern = re.compile(
        rf'\b{re.escape(var)}\s*=\s*(?:string\[\]\s*)?\{{?\s*((?:"(?:[^"\\]|\\.)*"\s*,?\s*)+)\}}?\s*;', re.IGNORECASE,
    )
    found = None
    for match in pattern.finditer(script):
        found = [m.group(1) for m in _STRINGS_RE.finditer(match.group(1))]
    return found


def parse_constraint_mode(script: str | None) -> ConstraintMode | None:
    """Mode, literal values and guard of a ``setConstraintValuesInSession``
    call, or None when the script has no such call or its list is not a
    literal."""
    if not script:
        return None
    text = _COMMENT_RE.sub("", script)
    call = _CALL_RE.search(text)
    if call is None:
        return None
    raw = call.group("val")
    literals = [raw.strip('"')] if raw.startswith('"') else _assigned_literals(text, raw)
    blank = any(not item.strip() for item in (literals or []))
    values = _split_values(literals or [])
    if not values and not blank:
        return None
    guard = _GUARD_RE.search(text)
    return ConstraintMode(call.group("mode").upper(), values, guard.group("var") if guard else "", blank)
