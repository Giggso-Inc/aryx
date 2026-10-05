"""Port of Oracle CPQ's ``util.getConstraintVals`` (APX_util_library.xml,
bm_lib_func 39185090) over the ingested whitelist + attrSequence tables (plan
F1, docs/oci-oracle/CONFIG_DATA_REQUIRED_FIELDS_INGEST_AND_FIX_PLAN_2026-10-05.md).

Differs from ``resolve_whitelist_values`` (plain AND-equality over attr2..N,
target only in attr1) in exactly the ways the real util does:

* the target may sit in ANY whitelist column of a row;
* another column filters the row only when its attribute is EARLIER in the UI
  sequence than the target (an attribute missing from the sequence counts as 0);
* a filter attribute with no value rejects the row;
* a filter value may be multi-select, split on ``~`` or ``,``;
* an ``R`` flag on the target, or any returned value in ``CHECK_VALUES``, removes
  the blank option (``blank_allowed`` False).

``None`` means "unknown" (no sequence rows for the model/base model, or no whitelist
row names the target): the caller keeps its existing fallback. Callers gate on
``Settings.cpq_getconstraintvals_port_enabled``.
"""
from __future__ import annotations

import re
from typing import Any

from aryx.cpq.data_table.data_table_loader import _load_all_tables

# Read from the util script text (its `checkValues` list).
CHECK_VALUES = frozenset({"NO CHARGER", "NO MICROPHONE", "N/A"})
_SPLIT_RE = re.compile(r"[~,]")


def _ui_sequence(
    sequence_rows: list[dict[str, Any]], cpq_model: str, base_model: str,
) -> dict[str, tuple[int, str]]:
    """attr -> (UI sequence number, optionOrReqFlag) for one CPQModel + BaseModel."""
    out: dict[str, tuple[int, str]] = {}
    for row in sequence_rows:
        if row.get("CPQModel") != cpq_model or row.get("BaseModel") != base_model:
            continue
        try:
            number = int(float(row.get("Seq")))
        except (TypeError, ValueError):
            continue
        out.setdefault(str(row.get("AttrName") or ""), (number, str(row.get("optionOrReqFlag") or "")))
    return out


def _columns(row: dict[str, Any]) -> list[tuple[str, str]]:
    cols, n = [], 1
    while f"attr{n}" in row and f"val{n}" in row:
        if row.get(f"attr{n}"):
            cols.append((str(row[f"attr{n}"]), str(row.get(f"val{n}") or "")))
        n += 1
    return cols


def _filter_matches(have: str, want: str) -> bool:
    options = [x.strip() for x in _SPLIT_RE.split(have)] if _SPLIT_RE.search(have) else [have]
    return want in options


def get_constraint_vals(
    cpq_model: str, base_model: str, target: str, filled: dict[str, str],
    workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple, Any] | None = None,
) -> dict[str, Any] | None:
    """{"values": [...], "blank_allowed": bool, "required": bool} or None (unknown)."""
    constraint_rows, sequence_rows, *_ = _load_all_tables(workspace_id, catalog_prefix, cache)
    seq = _ui_sequence(sequence_rows, cpq_model, base_model)
    if not seq:
        return None
    if target not in seq:
        return {"values": [], "blank_allowed": True, "required": False}
    target_seq, flag = seq[target]
    named, values = False, []
    for row in constraint_rows:
        if row.get("CPQModel") != cpq_model or row.get("BaseModel") not in (base_model, "ALL"):
            continue
        cols = _columns(row)
        returned = next((v for a, v in cols if a == target), None)
        if returned is None:
            continue
        named = True
        keep = True
        for attr, want in cols:
            if attr == target or seq.get(attr, (0, ""))[0] >= target_seq:
                continue
            have = str(filled.get(attr) or "").strip()
            if not have or not _filter_matches(have, want):
                keep = False
                break
        if keep and returned and returned not in values:
            values.append(returned)
    if not named:
        return None
    required = flag == "R" or any(v in CHECK_VALUES for v in values)
    return {"values": values, "blank_allowed": not required, "required": required}
