"""Pure query discovery in script text: which tables do embedded SQL queries read?

No I/O and **no assumption about the script language or the XML layout**. A
query is recognised by its shape — a string literal (or ``"a" + "b"``
concatenation of literals) that is a ``SELECT ... FROM ...`` statement —
wherever it appears, so it works whether the script calls it ``BMQL(...)``,
``query(...)``, ``db.execute(...)`` or assigns it to a variable first.

Table references after ``FROM``/``JOIN`` may be literal (``attrSeq``) or a
variable (``$name``, ``${name}``, ``:name``, ``{name}``); a variable resolves to
every string literal assigned to that name anywhere in the same script
(``name = "attrSequence";``). Comments are ignored. A query built at run time
from non-literal pieces cannot be resolved statically and is skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SQL_RE = re.compile(r"^\s*select\b.+?\bfrom\b", re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(r"\b(?:from|join)\s+([$:{]*[A-Za-z_][A-Za-z0-9_]*\}?)", re.IGNORECASE)
_QUOTE_RE = re.compile(r"[\"']")
_ASSIGN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([\"'])")
_STR_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\"}


@dataclass(frozen=True, slots=True)
class SqlQuery:
    """One SQL query found in a script."""

    sql: str
    tables: tuple[str, ...]  # table names after variable resolution, original case


def strip_comments(script: str) -> str:
    """Blank out ``//`` and ``/* */`` comments, leaving string literals intact."""
    out: list[str] = []
    i, n = 0, len(script)
    while i < n:
        ch = script[i]
        if ch in "\"'":
            j = _skip_string(script, i)
            out.append(script[i:j])
            i = j
        elif script.startswith("//", i):
            j = script.find("\n", i)
            i = n if j < 0 else j
        elif script.startswith("/*", i):
            j = script.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _skip_string(text: str, start: int) -> int:
    """Index just past the string literal opening at ``text[start]``."""
    quote, i, n = text[start], start + 1, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
        elif text[i] == quote:
            return i + 1
        else:
            i += 1
    return n


def _read_string(text: str, start: int) -> tuple[str, int]:
    """Decode the string literal at ``start``; returns (value, index after it)."""
    end = _skip_string(text, start)
    raw = text[start + 1:end - 1]
    return re.sub(r"\\(.)", lambda m: _STR_ESCAPES.get(m.group(1), m.group(1)), raw), end


def _literal_chain(text: str, pos: int) -> tuple[str, int]:
    """Read ``"a" + "b" + ...`` starting at the quote at ``pos``; returns (joined value, end)."""
    value, end = _read_string(text, pos)
    parts, n = [value], len(text)
    while True:
        j = end
        while j < n and text[j].isspace():
            j += 1
        if j >= n or text[j] != "+":
            return "".join(parts), end
        j += 1
        while j < n and text[j].isspace():
            j += 1
        if j >= n or text[j] not in "\"'":
            return "".join(parts), end
        value, end = _read_string(text, j)
        parts.append(value)


def literal_assignments(script: str) -> dict[str, set[str]]:
    """Map ``variable -> every string literal assigned to it`` (case-sensitive names)."""
    found: dict[str, set[str]] = {}
    for m in _ASSIGN_RE.finditer(script):
        value, _ = _read_string(script, m.start(2))
        found.setdefault(m.group(1), set()).add(value)
    return found


def _resolve(raw: str, assigns: dict[str, set[str]]) -> list[str]:
    name = raw.lstrip("$:{").rstrip("}")
    if name == raw:
        return [raw]
    return sorted(assigns.get(name, ()))


def extract_queries(script_text: str) -> list[SqlQuery]:
    """Return every statically-resolvable ``SELECT ... FROM`` query in ``script_text``."""
    if "select" not in script_text.lower():
        return []
    clean = strip_comments(script_text)
    assigns = literal_assignments(clean)
    queries: list[SqlQuery] = []
    if _SQL_RE.match(clean):  # the text itself is a query (an attribute or <sql> element), not code
        return [_query(clean, assigns)]
    pos = 0
    while (m := _QUOTE_RE.search(clean, pos)):
        value, pos = _literal_chain(clean, m.start())
        if _SQL_RE.match(value):
            queries.append(_query(value, assigns))
    return queries


def _query(sql: str, assigns: dict[str, set[str]]) -> SqlQuery:
    tables: list[str] = []
    for raw in _TABLE_RE.findall(sql):
        tables.extend(_resolve(raw, assigns))
    return SqlQuery(sql=" ".join(sql.split()), tables=tuple(tables))
