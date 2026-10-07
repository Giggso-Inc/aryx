"""Plan F9: evaluate a hide script that searches a MASTER STRING with the
master string COMPUTED the way Oracle would, instead of trusting an
empty/missing value (see ``hiding_rules.master_writers`` for how writers are
found, ``bml_hide_idioms`` for the idioms evaluated).

The master variable is written by a recommendation rule that only fires when
its own declarative condition holds, so: condition True -> the string is
built from the ingested attrSequence rows; condition False -> it is EMPTY
(an attribute missing from it is hidden, per the script's own semantics);
anything unresolvable -> None (caller keeps the old path).
"""
from __future__ import annotations

import re
from typing import Any

from aryx.cpq.bml.bml_declarative import evaluate_declarative_conditions
from aryx.cpq.bml.bml_hide_idioms import (
    evaluate_hide_master_list, evaluate_hide_master_list_unguarded,
)
from aryx.cpq.bml.bml_tier1 import evaluate_hide_tier1
from aryx.cpq.hiding_rules.master_writers import (
    WriterQuery, clean_script, parse_writer_query, read_master,
)


def _blank_defaulted(attrs: list[Any], by_id: dict[int, str]) -> dict[int, str]:
    """`by_id` plus "" for every known attribute not filled yet ("nothing
    selected" -- how a "not blank" writer condition is read)."""
    out = dict(by_id)
    for a in attrs:
        out.setdefault(a.entity_id, "")
        if a.source_id is not None:
            out.setdefault(a.source_id, "")
    return out


def _blank_group_hit(value: str, operator: str) -> bool | None:
    """`attr = ""` / `attr <> ""` ("is blank" / "not blank") -- which the
    generic declarative operator drops (it ignores empty expected values)."""
    if operator == "4":
        return value.strip() == ""
    if operator == "3":
        return value.strip() != ""
    return None


def _condition_results(conds: list[tuple[int, str, str]], by_id: dict[int, str]) -> list[bool | None]:
    """Blank-valued attribute groups are tested locally; everything else goes
    through evaluate_declarative_conditions (same AND-of-groups semantics)."""
    blank_ids = {a for a, _v, _o in conds if all(
        v.strip() == "" for a2, v, _o2 in conds if a2 == a)}
    rest = [c for c in conds if c[0] not in blank_ids]
    out: list[bool | None] = [
        _blank_group_hit(by_id.get(a, ""), next(o for a2, _v, o in conds if a2 == a))
        for a in sorted(blank_ids)]
    if rest:
        res, blocked = evaluate_declarative_conditions(rest, by_id)
        out.append(None if blocked else res)
    return out


def writer_fires(rule: Any, by_id: dict[int, str], variables: dict[str, str]) -> bool | None:
    """Does the writer's own condition hold? True/False/None(unknown)."""
    results: list[bool | None] = []
    if getattr(rule, "condition_script", None):
        res, blocked = evaluate_hide_tier1(rule.condition_script, variables)
        results.append(None if blocked else res)
    conds = rule.conditions or (
        [(rule.condition_attr_id, rule.condition_value, rule.condition_operator)]
        if rule.condition_attr_id in by_id else [])
    if conds:
        results.extend(_condition_results(conds, by_id))
    if not results:
        return None
    if any(r is False for r in results):
        return False
    return True if all(r is True for r in results) else None


def _resolve(var: str, q: WriterQuery, variables: dict[str, str]) -> str | None:
    """Value of a query variable: a literal/ident assigned in the writer
    script (`var = "x";` / `var = other;`), else the variable itself."""
    m = re.search(r'\b' + re.escape(var) + r'\s*=\s*(?:"([^"]*)"|(\w+))\s*;', q.script)
    if m:
        return m.group(1) if m.group(1) is not None else variables.get(m.group(2))
    return variables.get(var)


def compute_master(
    q: WriterQuery, variables: dict[str, str], sep: str, workspace_id: int | None,
    catalog_prefix: str, cache: dict | None, why: list[str] | None = None,
) -> str | None:
    """Master string built from the ingested attrSequence rows, or None when
    it cannot be built soundly (other columns, unresolved scope, no rows).
    `why`, when given, receives one diagnostic reason code for a None result (never affects the result)."""
    def _no(reason: str) -> None:
        if why is not None:
            why.append(reason)
        return None

    if workspace_id is None or q.columns != ("attrname",) or not q.simple:
        return _no("WRITER_QUERY_SHAPE_UNSUPPORTED")
    cpq = _resolve(q.cpq_var, q, variables)
    bases: set[str] = set()
    for kind, v in q.base_items:
        val = v if kind == "lit" else _resolve(v, q, variables)
        if val is None:
            return _no("BASE_SCOPE_VARIABLE_UNRESOLVED")  # scope variable not resolvable -> unknown
        if val:
            bases.add(val)
    if not cpq:
        return _no("MODEL_VARIABLE_UNRESOLVED")
    if q.base_items and not bases:
        return ""  # blank BaseModel scope: the query matches no rows
    from aryx.cpq.data_table.data_table_loader import _load_all_tables  # noqa: PLC0415
    rows = _load_all_tables(workspace_id, catalog_prefix, cache)[1]
    names = {
        r.get("AttrName") for r in rows
        if r.get("CPQModel") == cpq and (not bases or r.get("BaseModel") in bases) and r.get("AttrName")
    }
    if not names:
        return _no("NO_SEQUENCE_ROWS_FOR_SCOPE")
    return "".join(f"{n}{sep}" for n in sorted(names))


def hide_with_master_string(
    rule: Any, attrs: list[Any], by_rule_id: dict[int, Any], filled: dict[str, str],
    filled_by_rule_id: dict[int, str], workspace_id: int | None,
    catalog_prefix: str = "", cache: dict | None = None,
) -> bool | None:
    """Hide decision for a master-string-reading hide script, or None when
    not decidable here (caller then uses the ordinary evaluator)."""
    why: list[str] = []
    result = _hide_with_master_string(rule, attrs, by_rule_id, filled, filled_by_rule_id, workspace_id,
                                      catalog_prefix, cache, why)
    if result is None and why:
        from aryx.cpq.hiding_rules.unknown_log import log_master_unresolved  # noqa: PLC0415 -- diagnostic only
        log_master_unresolved(rule, why[0])
    return result


def _hide_with_master_string(
    rule: Any, attrs: list[Any], by_rule_id: dict[int, Any], filled: dict[str, str],
    filled_by_rule_id: dict[int, str], workspace_id: int | None,
    catalog_prefix: str, cache: dict | None, why: list[str],
) -> bool | None:
    read = read_master(rule.script)
    if not read:
        why.append("MASTER_READ_NOT_PARSED")
        return None
    master_var, sep_var = read
    writers = [w for w in rule.master_writers or []
               if (t := by_rule_id.get(w.target_attr_id)) and t.variable_name == master_var]
    if not writers:
        why.append("NO_WRITER_FOR_MASTER_VARIABLE")
        return None
    by_vn = {a.variable_name: a for a in attrs}
    variables = dict(filled)
    for ident in set(re.findall(r'\w+', clean_script(rule.script))) - set(variables):
        if ident in by_vn:  # known attr, not filled yet: blank ("nothing selected")
            variables[ident] = ""
    sep_attr = by_vn.get(sep_var)
    sep = filled.get(sep_var) or (sep_attr.default_value if sep_attr else "") or ""
    variables[sep_var] = sep
    if not sep:
        why.append("SEPARATOR_UNKNOWN")
        return None
    by_id = _blank_defaulted(attrs, filled_by_rule_id)
    fires = [(w, writer_fires(w, by_id, variables)) for w in writers]
    live = [w for w, f in fires if f is True]
    if live:
        q = parse_writer_query(live[0].script)
        if q is None:
            why.append("WRITER_QUERY_NOT_PARSED")
        master = compute_master(q, variables, sep, workspace_id, catalog_prefix, cache, why) if q else None
    elif all(f is False for _, f in fires):
        master = ""
    else:
        why.append("WRITER_CONDITION_UNKNOWN")
        master = None
    if master is None:
        return None
    variables[master_var] = master
    res, blocked = evaluate_hide_master_list(rule.script, variables)
    if res is None and not blocked:
        res, blocked = evaluate_hide_master_list_unguarded(
            rule.script, variables, trust_empty_master=True)
    if blocked or res is None:
        why.append("MASTER_SCRIPT_EVALUATION_BLOCKED")
    return None if blocked else res
