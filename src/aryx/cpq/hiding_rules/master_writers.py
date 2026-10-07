"""Plan F9: find the rules that WRITE a master string, from rule/script data.

A writer is a recommendation rule whose action script runs a BMQL query of
the shape ``SELECT [distinct] <cols> FROM $<table> WHERE CPQModel=... [and
BaseModel IN (...)]`` (script SYNTAX only -- no attribute/variable/table
names are baked in). The master variable is the writer's action TARGET
attribute, resolved by the caller through the rule's ``target_attr_id``.
Active only with ``cpq_master_string_hide_enabled``.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any

from aryx.config import get_settings
from aryx.cpq.bml.bml_text import _strip_block_comments, _strip_line_comments

_BMQL_RE = re.compile(
    r'BMQL\s*\(\s*"\s*SELECT\s+(?:DISTINCT\s+)?(?P<cols>[\w\s,]+?)\s+'
    r'FROM\s+\$?\w+\s+WHERE\s+(?P<where>[^"]*)"', re.IGNORECASE)
_PRED_SPLIT_RE = re.compile(r'\s+and\s+', re.IGNORECASE)
_CPQ_PRED_RE = re.compile(r"^CPQModel\s*=\s*'?\$?(\w+)'?$", re.IGNORECASE)
_BASE_PRED_RE = re.compile(r"^BaseModel\s*(?:=|IN)\s*\(?\s*(?P<items>[^()]*?)\s*\)?$", re.IGNORECASE)
_SPLIT_READ_RE = re.compile(r'\bSPLIT\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)', re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class WriterQuery:
    """What a writer's BMQL selects and how it is scoped.

    `base_items` are `("var", name)` / `("lit", text)` pairs; `simple` is
    False when the WHERE has any predicate beyond CPQModel/BaseModel.
    """
    columns: tuple[str, ...]
    cpq_var: str
    base_items: tuple[tuple[str, str], ...]
    simple: bool
    script: str


def master_hide_enabled() -> bool:
    """True when the F9 flag is on."""
    return bool(get_settings().cpq_master_string_hide_enabled)


def hide_index_alias_enabled() -> bool:
    """True when hide scripts that test an index variable they never assigned are evaluated as if it were the
    findinarray result (flag cpq_hide_index_alias_enabled)."""
    return bool(get_settings().cpq_hide_index_alias_enabled)


def clean_script(script: str) -> str:
    """Script text with // and block comments removed."""
    return _strip_block_comments(_strip_line_comments(script))


def parse_writer_query(script: str | None) -> WriterQuery | None:
    """The BMQL query of a writer script, or None when it is not one."""
    if not script:
        return None
    text = clean_script(script)
    m = _BMQL_RE.search(text)
    if not m:
        return None
    cols = tuple(c.strip().lower() for c in m.group("cols").split(",") if c.strip())
    cpq_var, base_items, simple = "", [], True
    for pred in (p.strip() for p in _PRED_SPLIT_RE.split(m.group("where"))):
        cm, bm = _CPQ_PRED_RE.match(pred), _BASE_PRED_RE.match(pred)
        if cm and not cpq_var:
            cpq_var = cm.group(1)
        elif bm and not base_items:
            for item in (i.strip() for i in bm.group("items").split(",")):
                lit = re.fullmatch(r"'([^']*)'", item)
                base_items.append(("lit", lit.group(1)) if lit else ("var", item.lstrip("$")))
        else:
            simple = False
    if not cpq_var:
        return None
    return WriterQuery(cols, cpq_var, tuple(base_items), simple, text)


def find_master_writers(rec_rules: list[Any]) -> list[Any]:
    """Recommendation rules whose action script is a master-string writer."""
    return [r for r in rec_rules or [] if parse_writer_query(getattr(r, "script", None))]


def read_master(script: str | None) -> tuple[str, str] | None:
    """`(master_var, separator_var)` of the first SPLIT(master, sep) read."""
    m = _SPLIT_READ_RE.search(clean_script(script or ""))
    return (m.group(1), m.group(2)) if m else None


def annotate_hiding_rules(hiding_rules: list[Any], rec_rules: list[Any]) -> int:
    """Attach the writer rules to every script-backed hiding rule that reads
    a SPLIT master. Returns the number annotated. No-op with the flag off."""
    if not master_hide_enabled():
        return 0
    writers = find_master_writers(rec_rules)
    if not writers:
        return 0
    count = 0
    for rule in hiding_rules:
        if getattr(rule, "script", None) and read_master(rule.script):
            rule.master_writers = writers
            count += 1
    return count
