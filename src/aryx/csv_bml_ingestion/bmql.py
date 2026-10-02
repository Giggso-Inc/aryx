"""Pure BML script analysis: find ``BMQL("...")`` queries and the tables they read.

No I/O. Operates on one BML script's text. Handles the three shapes seen in
real CPQ XML exports:

* a literal table:            ``BMQL("SELECT a FROM attrToPDNonFrequency WHERE ...")``
* a variable table:           ``BMQL("SELECT a FROM $attrSeqTableName WHERE ...")`` with
  ``attrSeqTableName = "attrSequence";`` earlier in the same script — every
  literal assignment to that variable is a candidate table name;
* multi-line / ``"..." + "..."`` concatenated query literals.

A ``BMQL(someVar)`` call whose argument is not a literal is skipped (it
cannot be resolved statically).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CALL_RE = re.compile(r"\bbmql\s*\(", re.IGNORECASE)
_TABLE_RE = re.compile(r"\b(?:from|join)\s+(\$?[A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_STR_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\"}


@dataclass(frozen=True, slots=True)
class BmqlQuery:
    """One BMQL statement found in a script."""

    sql: str
    tables: tuple[str, ...]  # table names after $variable resolution, original case


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


def _literal_argument(text: str, pos: int) -> str | None:
    """Read ``"a" + "b" + ...`` at ``pos``; None if the argument is not purely literals."""
    parts: list[str] = []
    n = len(text)
    while True:
        while pos < n and text[pos].isspace():
            pos += 1
        if pos >= n or text[pos] not in "\"'":
            return None
        value, pos = _read_string(text, pos)
        parts.append(value)
        while pos < n and text[pos].isspace():
            pos += 1
        if pos < n and text[pos] == "+":
            pos += 1
            continue
        return "".join(parts) if pos < n and text[pos] in ",)" else None


def literal_assignments(script: str) -> dict[str, set[str]]:
    """Map ``variable -> every string literal assigned to it`` (case-sensitive names)."""
    found: dict[str, set[str]] = {}
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([\"'])", script):
        value, _ = _read_string(script, m.start(2))
        found.setdefault(m.group(1), set()).add(value)
    return found


def extract_queries(script_text: str) -> list[BmqlQuery]:
    """Return every statically-resolvable BMQL query in ``script_text``."""
    clean = strip_comments(script_text)
    assigns = literal_assignments(clean)
    queries: list[BmqlQuery] = []
    for call in _CALL_RE.finditer(clean):
        sql = _literal_argument(clean, call.end())
        if sql is None:
            continue
        tables: list[str] = []
        for raw in _TABLE_RE.findall(sql):
            if raw.startswith("$"):
                tables.extend(sorted(assigns.get(raw[1:], ())))
            else:
                tables.append(raw)
        queries.append(BmqlQuery(sql=" ".join(sql.split()), tables=tuple(tables)))
    return queries
