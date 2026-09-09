"""Low-level, string/comment-safe text utilities for BML script parsing.

Split out of `cpq/bml.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). Pure text functions with no dependency on any other bml_*
module -- confirmed zero whitebox patches on this module anywhere in the
test suite before splitting, so this and every other bml_* split carries
no patch-retargeting risk at all.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _strip_line_comments(text: str) -> str:
    """Strip `// ...` line comments, but never inside a quoted string
    literal (a `"http://..."` value must survive intact).

    Every Tier-1 regex scanner (`_ASSIGN_RE`, `_BOOL_RETURN_RE`, `_IF_RE`,
    `_CMP_RE` via _parse_condition) previously scanned the RAW script text,
    including comments — so an author's own commented-out scratch line
    (e.g. `//returnVal = "APX NEXT Enhanced";`) matched BEFORE the real,
    live statement right after it (`returnVal = "APX NEXT ENHANCED";`),
    confirmed live: a real "Default APX Next Enhanced based on HW version"
    recommendation script returned the commented-out (wrong-cased) string
    instead of its actual executed assignment. _parse_branches strips
    comments once at entry so every downstream scan (bodies/conditions
    sliced from that same text) sees comment-free source.
    """
    out: list[str] = []
    in_str = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)

def _strip_block_comments(text: str) -> str:
    """Strip `/* ... */` block comments, but never inside a quoted string
    literal — same string-awareness as `_strip_line_comments`, which only
    handles `//` and leaves `/* */` untouched.

    Live-confirmed bug (2026-07-28): a real constraint script
    ("Restrict APX Next Product Selection based on HW Version selection")
    wraps a dead scratch block in `/* ... */` referencing `usersessionget`/
    `util.*` — both `_TIER1_BLOCKERS` triggers. Because this comment was
    never stripped, its dead reference alone rejected an otherwise
    trivially Tier-1-parseable if/else script, forcing every evaluation of
    it into the shared, per-turn-capped Tier-2 LLM path for no reason.
    """
    out: list[str] = []
    in_str = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                break
            i = j + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)

def _find_block(text: str, open_idx: int) -> tuple[str, int] | None:
    """Return (block_body, index_after_close) for the {...} starting at open_idx."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i], i + 1
    return None

def _strip_wrapping_parens(text: str) -> str:
    """Strip one layer of enclosing parens, e.g. `(a=="b")` -> `a=="b"`, but
    only when the leading `(` closes at the very end (not e.g. `(a) OR (b)`
    sliced mid-way, which must be left alone). Real BML condition chains
    commonly wrap every clause in its own parens
    (`(x=="A") OR (y=="B")`) — confirmed live in a real hiding-rule
    script — which the bare _CMP_RE anchor match would otherwise reject."""
    text = text.strip()
    if not (text.startswith("(") and text.endswith(")")):
        return text
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text if i != len(text) - 1 else text[1:-1].strip()
    return text

def _split_top_level(text: str, keyword_re: re.Pattern) -> list[str] | None:
    """Split `text` at occurrences of `keyword_re` sitting at paren-depth 0
    and outside any "..." quoted string. Returns None when no such
    occurrence exists (there may still be matches nested inside parens or a
    quoted value, which must NOT trigger a split)."""
    depth = 0
    in_quotes = False
    parts: list[str] = []
    last = 0
    i = 0
    n = len(text)
    found = False
    while i < n:
        ch = text[i]
        if ch == '"':
            in_quotes = not in_quotes
            i += 1
            continue
        if in_quotes:
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0:
            m = keyword_re.match(text, i)
            if m:
                parts.append(text[last:i])
                last = m.end()
                i = m.end()
                found = True
                continue
        i += 1
    if not found:
        return None
    parts.append(text[last:])
    return parts

def _split_statements(text: str) -> list[str]:
    """Split BML source on `;` that are NOT inside a quoted string literal.

    A plain `text.split(';')` corrupts any statement whose literal text
    itself contains a semicolon — confirmed live: the real "Set HelpTtext
    info" script's own literal is `"color:#FF0000; font-size:8pt;"`, which
    a naive split fractures into three bogus statements.
    """
    stmts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == ";" and not in_quotes:
            stmts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        stmts.append("".join(buf))
    return stmts

def _split_on_plus_outside_quotes(expr: str) -> list[str]:
    """Split on `+` that is NOT inside a quoted string literal — a literal
    like `"a+b"` must survive as one token, not split into `"a` / `b"`."""
    tokens: list[str] = []
    buf: list[str] = []
    in_quotes = False
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == '"' and (i == 0 or expr[i - 1] != "\\"):
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "+" and not in_quotes:
            tokens.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        tokens.append("".join(buf))
    return tokens
