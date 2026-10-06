"""Post-ingest health check of one CPQ workspace (read-only).

Answers, from what is stored, whether an XML + data-table ingest left the workspace in
the shape the CPQ engine reads. Each check returns PASS / WARN / FAIL / SKIP with a
one-line reason, so a degraded ingest is visible right after upload instead of when Ask
asks the wrong question. Names come from the engine's own readers (BigMachines function,
attribute and data-table shapes); the thresholds are the only policy here.

Checks:
* function_scripts   -- BmFunction rows that carry their script text (the engine reads it
                         from the function row only).
* leaf_wrapper_types -- entity types with no ``Bm<Tag>`` marker whose rows hold only text:
                         a plain-text tag that landed as its own entity instead of on its parent.
* attribute_names    -- attribute rows that carry a name (Ask shows names, not ids).
* data_tables        -- rows that match a data-table shape (whitelist, attrSequence, region
                         mapping, series mapping, hierarchy). SKIP when the workspace cannot be read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aryx.cpq.catalog_naming import _catalog_prefix
from aryx.cpq.data_table.data_table_shapes import _detect_shape

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
_SCRIPT_FULL, _SCRIPT_PARTIAL = 0.9, 0.0     # share of functions with a script: PASS above full, FAIL at 0
_NAME_FULL, _NAME_PARTIAL = 0.9, 0.5
_CONTAINER_SUFFIX = "children"                # the XML `_children` container, never a leaf wrapper


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _share_check(name: str, with_value: int, total: int, full: float, floor: float, what: str) -> Check:
    if total == 0:
        return Check(name, SKIP, f"no {what} rows in this workspace")
    share = with_value / total
    detail = f"{with_value}/{total} {what} rows ({share:.0%})"
    if with_value == 0 or share <= floor:
        return Check(name, FAIL, detail)
    return Check(name, PASS if share >= full else WARN, detail)


def check_function_scripts(rdb: Any, workspace_id: int, catalog_prefix: str) -> Check:
    rows = rdb.fetch_entities_by_type(workspace_id, "bmfunction", catalog_prefix)
    with_script = sum(
        1 for _eid, attrs in rows
        if isinstance(attrs.get("script_text") or attrs.get("script"), str)
        and (attrs.get("script_text") or attrs.get("script")).strip())
    return _share_check("function_scripts", with_script, len(rows), _SCRIPT_FULL, _SCRIPT_PARTIAL,
                        "function")


def _is_text_only(attrs: dict[str, Any]) -> bool:
    keys = {k for k in attrs if not str(k).startswith("_")}
    return bool(keys) and keys <= {"text"}


def check_leaf_wrapper_types(rdb: Any, workspace_id: int) -> Check:
    leaked: dict[str, int] = {}
    for otype in rdb.list_ontology_types(workspace_id):
        if _catalog_prefix(otype) or otype.lower().endswith(_CONTAINER_SUFFIX):
            continue                       # a Bm<Tag> entity type, or the container
        rows = rdb.fetch_entities_by_exact_type(workspace_id, otype)
        if rows and all(_is_text_only(attrs) for _eid, attrs in rows):
            leaked[otype] = len(rows)
    if leaked:
        listed = ", ".join(f"{t} ({n})" for t, n in sorted(leaked.items(), key=lambda kv: -kv[1])[:8])
        return Check("leaf_wrapper_types", FAIL, f"text-only leaf tags landed as entities: {listed}")
    return Check("leaf_wrapper_types", PASS, "no text-only leaf entity types")


def check_attribute_names(rdb: Any, workspace_id: int, catalog_prefix: str) -> Check:
    rows = rdb.fetch_entities_by_type(workspace_id, "bmconfigattr", catalog_prefix)
    named = sum(1 for _eid, attrs in rows if str(attrs.get("name") or "").strip())
    return _share_check("attribute_names", named, len(rows), _NAME_FULL, _NAME_PARTIAL, "attribute")


def check_data_tables(rdb: Any, workspace_id: int) -> Check:
    try:
        grouped = rdb.fetch_all_entities_grouped_by_type(workspace_id)
    except Exception as exc:  # noqa: BLE001 -- the read itself can fail (e.g. unreadable JSON encoding)
        return Check("data_tables", SKIP, f"workspace could not be read: {type(exc).__name__}")
    counts: dict[str, int] = {}
    for entities in grouped.values():
        for _eid, attrs in entities:
            shape = _detect_shape(set(attrs.keys()))
            if shape:
                counts[shape] = counts.get(shape, 0) + 1
    if not grouped:
        return Check("data_tables", SKIP, "workspace returned no rows (empty, or the read failed)")
    if not counts:
        return Check("data_tables", FAIL, "no data-table rows (whitelist, attrSequence, region, series)")
    listed = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    missing = [s for s in ("sequence", "constraint", "region_rule") if s not in counts]
    status = WARN if missing else PASS
    return Check("data_tables", status, listed + (f"; missing: {', '.join(missing)}" if missing else ""))


def evaluate_workspace_health(rdb: Any, workspace_id: int, catalog_prefix: str = "") -> list[Check]:
    """All checks for one workspace (a check that raises becomes a SKIP, never a crash)."""
    runners = (
        ("function_scripts", lambda: check_function_scripts(rdb, workspace_id, catalog_prefix)),
        ("leaf_wrapper_types", lambda: check_leaf_wrapper_types(rdb, workspace_id)),
        ("attribute_names", lambda: check_attribute_names(rdb, workspace_id, catalog_prefix)),
        ("data_tables", lambda: check_data_tables(rdb, workspace_id)),
    )
    out: list[Check] = []
    for name, run in runners:
        try:
            out.append(run())
        except Exception as exc:  # noqa: BLE001
            out.append(Check(name, SKIP, f"check failed: {type(exc).__name__}"))
    return out


def worst_status(checks: list[Check]) -> str:
    order = {PASS: 0, SKIP: 0, WARN: 1, FAIL: 2}
    return max((c.status for c in checks), key=lambda s: order[s], default=PASS)
