"""BML ``find(<attr|literal>, "<text>") <op> <number>`` support for the Tier-1
condition grammar (plan F14, flag ``cpq_find_function_enabled``).

BML ``find`` returns the 0-based index of the substring, or -1 when absent,
so ``find(x,"T") > -1`` means "contains" and ``find(x,"T") == -1`` "does not
contain". The clause is packed into the existing ``(var, op, expected)``
condition shape (op ``FIND``) so the parsers/evaluators in
``bml_conditions`` / ``bml_tier1`` stay the single evaluation path.

Matching is case-sensitive (BML ``find`` is). Every entry point is gated by
the flag; flag off => nothing here is ever produced (byte-identical).
"""
from __future__ import annotations

import re

from aryx.config import get_settings

FIND_OP = "FIND"
_PACK = "\x1f"  # ASCII unit separator; cannot occur in a BML string literal

_FIND_RE = re.compile(
    r'^\s*find\s*\(\s*(?:(?P<var>[A-Za-z_]\w*)|"(?P<lit>[^"]*)")\s*,\s*'
    r'"(?P<needle>[^"]*)"\s*\)\s*(?P<op>==|<>|!=|>=|<=|>|<)\s*(?P<num>-?\d+)\s*$',
    re.IGNORECASE,
)


def find_enabled() -> bool:
    """True when the F14 flag is on."""
    return bool(get_settings().cpq_find_function_enabled)


def nested_if_enabled() -> bool:
    """True when a branch body that is itself an if-chain may be walked.

    Its own flag (``cpq_bml_nested_if_enabled``, on by default) or F14, which
    first introduced nested-chain walking, turns it on.
    """
    settings = get_settings()
    return bool(getattr(settings, "cpq_bml_nested_if_enabled", True)) or find_enabled()


def match_find(cond: str) -> tuple[str, str, str] | None:
    """Match one ``find(...) <op> <n>`` clause -> ``(var, FIND_OP, packed)``.

    ``var`` is the haystack attribute ("" for a literal haystack, carried in
    ``packed``). None when the flag is off or the clause is not that shape.
    """
    if not find_enabled():
        return None
    m = _FIND_RE.match(cond)
    if not m:
        return None
    packed = _PACK.join((m.group("lit") or "", m.group("needle"), m.group("op"), m.group("num")))
    return m.group("var") or "", FIND_OP, packed


def find_haystack(variables: dict[str, str], var: str, packed: str) -> str | None:
    """The haystack text, or None when the attribute is not filled (blocked)."""
    if var:
        return variables.get(var)
    return packed.split(_PACK)[0]


def find_hit(haystack: str, packed: str) -> bool:
    """Evaluate the packed comparison against `haystack`."""
    _lit, needle, op, num = packed.split(_PACK)
    idx, n = haystack.find(needle), int(num)
    return {
        "==": idx == n, "<>": idx != n, "!=": idx != n,
        ">": idx > n, ">=": idx >= n, "<": idx < n, "<=": idx <= n,
    }[op]


# --- sequential / nested if-with-literal-return chains (plan F14) ----------
# `if(A){return "X";} if(B){return "Y";} else {return "Z";}` is exactly the
# else-if chain `if(A){X} else if(B){Y} else {Z}` because an earlier body
# returns unconditionally. A trailing bare `return "<literal>";` is the
# implicit else. Both only apply when every earlier body is a plain literal
# return, so no side effect is ever skipped.
_PLAIN_RETURN_BODY_RE = re.compile(r'^\s*return\s+(?:"[^"]*"|true|false)\s*;?\s*$', re.IGNORECASE)
_TAIL_RETURN_RE = re.compile(r'^\s*return\s+(?:"[^"]+"|true|false)\s*;?\s*$', re.IGNORECASE)
_NESTED_IF_RE = re.compile(r'^\s*if\s*\(', re.IGNORECASE)


def is_plain_return(body: str) -> bool:
    """Body is exactly one `return <literal>;` (string, true or false)."""
    return bool(_PLAIN_RETURN_BODY_RE.match(body))


def is_tail_return(rest: str) -> bool:
    """Remaining script is exactly one `return <non-empty literal>;`."""
    return bool(_TAIL_RETURN_RE.match(rest))


def starts_with_if(body: str) -> bool:
    """Body is itself an if-chain (a nested if)."""
    return bool(_NESTED_IF_RE.match(body))
