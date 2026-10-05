"""Recommendation scripts that only look a value up in a reference table.

Some recommendation rules compute their value with a BMQL lookup that the
deterministic evaluator cannot run, for example::

    rec = bmql("select RTTE,nonRTTE,TA from <table> where countryCode=$<attribute>");
    for r in rec { if(upper(get(r,"RTTE"))=="YES"){ returnVal ="RTTE"; } elif ... }

When the selected columns are exactly the flag columns of an ingested RTTE/TA
reference table (plan F5, flag ``cpq_country_region_table_enabled``), the value
is read from that table instead. Everything is taken from the script and the
table: the column labels, the attribute whose value keys the lookup, and the
rows. No attribute, table or country is named here.
"""
from __future__ import annotations

import re
from typing import Any

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_geo import resolve_rtte_flag
from aryx.cpq.data_table.data_table_shapes import RTTE_FLAG_COLUMNS

_LOOKUP_RE = re.compile(
    r'bmql\s*\(\s*"\s*select\s+(?P<cols>[\w\s,]+?)\s+from\s+\w+\s+where\s+\w+\s*=\s*\$(?P<var>\w+)\s*"\s*\)',
    re.IGNORECASE,
)
_BRANCH_RE = re.compile(
    r'"(?P<col>\w+)"\s*\)\s*\)\s*==\s*"YES"\s*\)\s*\{\s*returnVal\s*=\s*"(?P<label>[^"]*)"',
    re.IGNORECASE,
)
_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def parse_flag_lookup(script: str | None) -> tuple[str, dict[str, str]] | None:
    """(key attribute, {flag column: label}) when `script` is the flag lookup
    shape described above, else None."""
    if not script:
        return None
    text = _COMMENT_RE.sub("", script)
    lookup = _LOOKUP_RE.search(text)
    if lookup is None:
        return None
    cols = {c.strip().lower() for c in lookup.group("cols").split(",") if c.strip()}
    if cols != {c.lower() for c in RTTE_FLAG_COLUMNS}:
        return None
    wanted = {c.lower(): c for c in RTTE_FLAG_COLUMNS}
    labels = {wanted[m.group("col").lower()]: m.group("label")
              for m in _BRANCH_RE.finditer(text) if m.group("col").lower() in wanted}
    return (lookup.group("var"), labels) if labels else None


def lookup_script_value(
    script: str | None, filled: dict[str, str], workspace_id: int | None,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> str | None:
    """The table-derived value of a flag-lookup script, or None (flag off,
    other script shape, key attribute unfilled, or no row/flag for it)."""
    if workspace_id is None or not get_settings().cpq_country_region_table_enabled:
        return None
    parsed = parse_flag_lookup(script)
    if parsed is None:
        return None
    key_vn, labels = parsed
    key = (filled.get(key_vn) or "").strip()
    return resolve_rtte_flag(key, workspace_id, catalog_prefix, cache, labels) if key else None
