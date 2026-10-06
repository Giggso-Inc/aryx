"""Build the BM function id -> script text map, with a CONTAINS-link fallback.

A function's script normally sits on the function entity itself
(``attributes.script_text``). When the XML ingest did not fold the
``<script_text>`` leaf onto its ``<bm_function>`` parent, the script landed as
its own ``...ScriptText`` entity instead, linked from the function by a
``CONTAINS`` row in ``aryx_relationship`` (confirmed on workspace 1126,
2026-10-06: 929 functions, 0 with script_text, 929 CONTAINS links to 666
ScriptText entities -- identical scripts are merged into one entity).

The fallback reads the script from that linked entity in ``aryx_entity``,
never from the graph tables, which clip strings to 200 characters
(_GRAPH_ATTR_STR_MAX in graph/oracle_graph_store_helpers.py).
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.rdb.rdb_helpers import _as_int

FUNCTION_SUFFIX = "bmfunction"
SCRIPT_TEXT_SUFFIX = "scripttext"
CONTAINS = "CONTAINS"
# Keys a script can be stored under: on the function entity, and on an
# unfolded ScriptText entity (the raw XML element text key, RAW_PROP_TEXT).
_FUNCTION_KEYS = ("script_text", "script")
_LINKED_KEYS = ("text", "script_text", "script")


def _first_text(attrs: dict[str, Any], keys: tuple[str, ...]) -> str:
    """First non-blank string value under `keys`, or ""."""
    for key in keys:
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def own_function_scripts(
    functions: list[tuple[int, dict[str, Any]]],
) -> tuple[dict[int, str], dict[int, int]]:
    """Scripts carried on the function entities themselves.

    Args:
        functions: (entity_id, attributes) rows of the BmFunction type.

    Returns:
        (scripts, missing): scripts maps BM function id -> script text;
        missing maps entity_id -> BM function id for functions that have a
        BM id but no script of their own.
    """
    scripts: dict[int, str] = {}
    missing: dict[int, int] = {}
    for eid, attrs in functions:
        fn_id = _as_int(attrs.get("id") or attrs.get("bm_function_id"))
        if not fn_id:
            continue
        script = _first_text(attrs, _FUNCTION_KEYS)
        if script:
            scripts[fn_id] = script
        else:
            missing[eid] = fn_id
    return scripts, missing


def mixed_text_entities(member_rows: list[tuple[int, dict[str, Any]]]) -> set[int]:
    """Entity ids whose merged member records carry more than one distinct text.

    Entity resolution merges ScriptText records into one entity (929 -> 666
    on ws 1126). The match key for this tag is LLM-chosen, so the merge is
    not guaranteed to be exact-text; an entity whose members disagree holds
    one survivor text that is wrong for some of the functions linked to it.
    Conflict rows cannot prove this either way: they are only written when a
    survivorship policy is set (resolution/run.py _materialize).

    Args:
        member_rows: (entity_id, landed payload) per merged member record.

    Returns:
        Ids of entities whose members disagree on the script text.
    """
    texts: dict[int, set[str]] = {}
    for eid, payload in member_rows:
        texts.setdefault(eid, set()).add(_first_text(payload, _LINKED_KEYS))
    return {eid for eid, seen in texts.items() if len(seen) > 1}


def linked_scripts_by_function(
    linked: list[tuple[int, int, dict[str, Any]]],
    mixed: set[int],
) -> tuple[dict[int, str], int]:
    """Script per linking (function) entity, skipping mixed-text targets.

    Args:
        linked: (source_entity_id, target_entity_id, target attributes) rows,
            ordered by source then target so the pick is deterministic.
        mixed: target entity ids that must not be used (see mixed_text_entities).

    Returns:
        (by_source, skipped): by_source maps source entity id -> script;
        skipped counts link rows ignored because their target is mixed.
    """
    by_source: dict[int, str] = {}
    skipped = 0
    for source_eid, target_eid, attrs in linked:
        if target_eid in mixed:
            skipped += 1
            continue
        script = _first_text(attrs, _LINKED_KEYS)
        if script and source_eid not in by_source:
            by_source[source_eid] = script
    return by_source, skipped


def add_linked_scripts(
    scripts: dict[int, str],
    missing: dict[int, int],
    by_source: dict[int, str],
) -> int:
    """Fill `scripts` for `missing` functions from their linked script.

    Args:
        scripts: BM function id -> script, updated in place.
        missing: entity_id -> BM function id of functions without a script.
        by_source: function entity id -> linked script (linked_scripts_by_function).

    Returns:
        How many functions got their script from a link.
    """
    filled = 0
    for eid, fn_id in missing.items():
        script = by_source.get(eid)
        if script and fn_id not in scripts:
            scripts[fn_id] = script
            filled += 1
    return filled
