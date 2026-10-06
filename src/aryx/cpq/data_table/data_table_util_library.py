"""Values the ingested Oracle util library marks as "a choice is mandatory".

``util.getConstraintVals`` removes the blank option when one of its returned
values is in its own ``checkValues`` list (a literal inside the library
function's script). The list belongs to ONE specific function (a sibling
function has a different list), so it is read from the ingested library
script at run time, never hardcoded. No ingested library function (or no
``checkValues`` literal) means an empty set: the port then relies on the
attrSequence ``R`` flag alone and never guesses.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

from aryx.cpq.data_table.data_table_loader import _SHAPE_SCAN_CACHES, _SHAPE_SCAN_CACHE_TTL_SECONDS

_CHECK_LITERAL_RE = re.compile(r"checkValues\s*=\s*string\[\]\s*\{([^}]*)\}", re.IGNORECASE)
_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_NAME_SUFFIX_RE = re.compile(r"\s*\(.*\)\s*$")

_CACHE: dict[tuple[int, str], tuple[float, frozenset[str]]] = {}
_LOCK = threading.Lock()
_SHAPE_SCAN_CACHES.append(_CACHE)


def _names_of(attrs: dict[str, Any]) -> set[str]:
    """Lower-cased identifiers a library function entity answers to: its
    name and variable name, without a trailing "(...)" environment tag."""
    out: set[str] = set()
    for key in ("variable_name", "name", "function_name"):
        value = attrs.get(key)
        if isinstance(value, dict):
            value = value.get("en")
        if isinstance(value, str) and value.strip():
            out.add(_NAME_SUFFIX_RE.sub("", value).strip().lower())
    return out


def parse_check_values(script: str) -> frozenset[str]:
    """The strings of the first ``checkValues = string[]{...}`` literal."""
    match = _CHECK_LITERAL_RE.search(script or "")
    if not match:
        return frozenset()
    return frozenset(m.group(1) for m in _QUOTED_RE.finditer(match.group(1)))


def check_values_for_function(
    workspace_id: int, function_name: str, rdb: Any | None = None,
) -> frozenset[str]:
    """``checkValues`` of the ingested library function called `function_name`."""
    key = (int(workspace_id), function_name.lower())
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and now - hit[0] < _SHAPE_SCAN_CACHE_TTL_SECONDS:
            return hit[1]
    if rdb is None:
        from aryx.cpq.rdb import get_cpq_rdb
        rdb = get_cpq_rdb()
    found: frozenset[str] = frozenset()
    for _eid, attrs in rdb.fetch_entities_by_type(workspace_id, "bmlibfunc"):
        if function_name.lower() not in _names_of(attrs):
            continue
        script = attrs.get("script_text") or attrs.get("script") or ""
        found = parse_check_values(script) if isinstance(script, str) else frozenset()
        if found:
            break
    with _LOCK:
        _CACHE[key] = (now, found)
    return found
