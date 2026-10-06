"""Locale-wrapper folding + display fields for the raw-graph CPQ XML path.

Ports two rules the legacy ``_xml_to_csvs`` path (``pipeline/doc_discovery/
doc_discovery_xml.py``) always applied but PR #400's raw-graph bridge never
carried over (docs/ingestion/CPQ_XML_DISPLAY_NAMES_PLAN_2026-10-05.md):

1. Locale wrappers are values, not entities. Oracle CPQ stores display text
   as ``<label><en>ASTRO®25_BOM</en></label>``. ``fold_structural_leaf_tags``
   (pass 1) folds ``<en>`` onto ``<label>`` but ``<label>`` itself had a child,
   so it is never a structural leaf and stays its own entity -- leaving the
   owning ``bm_prd_family`` / ``bm_catalog`` / ``bm_config_attr`` with no name.
   ``fold_value_wrapper_tags`` (pass 2) folds those now value-only nodes onto
   their parent under the wrapper's own tag, ``en`` first, else the first
   locale in ``LOCALE_TAGS`` order, else plain ``text`` -- the same precedence
   as ``_xml_to_csvs._extract_field``.
2. ``name`` promotion. ``_xml_to_csvs._alias_name`` filled an absent ``name``
   from ``variable_name`` ... ``bm_variable_name`` (skipping trivial values like
   ``"0"``); every CPQ Ask lookup (``catalog_naming``, ``ingested_product_alias_map``,
   ``model_leaves``) is built on that variable-name-shaped ``name``.
   ``apply_display_fields`` restores it and adds ``display_label`` (the human
   ``label`` / ``bm_name`` text) for prompts that show names to users.

``LOCALE_TAGS`` / ``NAME_CANDIDATES`` / ``TRIVIAL_NAMES`` are copied verbatim from
``_xml_to_csvs``'s function-local definitions (they can't be imported from
there); ``test_value_wrapper_fold.py`` pins the behaviour.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.cpq_ingestion.constants import RAW_PROP_TEXT
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawNode
from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)

#: ISO / Oracle CPQ locale tags used as multilingual value wrappers, in
#: fallback order after ``en``. Same set and order as ``_xml_to_csvs``.
LOCALE_TAGS: tuple[str, ...] = (
    "en", "de", "fr", "es", "it", "da", "nl", "sv", "no", "fi", "pl", "cs",
    "ru", "tr", "ar", "he",
    "ja", "ko", "zh", "pt",
    "ja_JP", "zh_CN", "zh_HK", "zh_TW", "zh_SG", "ko_KR", "da_DK",
    "pt_BR", "pt_PT", "fr_CA", "es_CO",
)
_LOCALE_KEYS: frozenset[str] = frozenset(LOCALE_TAGS)
_VALUE_KEYS: frozenset[str] = _LOCALE_KEYS | {RAW_PROP_TEXT}

#: Fields promoted to ``name`` when it is absent, in priority order
#: (``_xml_to_csvs._NAME_CANDIDATES``).
NAME_CANDIDATES: tuple[str, ...] = (
    "variable_name", "var_name",
    "item_text", "item_value",
    "prop_value", "property_value", "prop_type",
    "label", "file_name", "relative_path",
    "bm_variable_name", "bm_name", "func_name", "rule_name",
    "java_class_name",
)
#: Values never promoted to ``name`` (``_xml_to_csvs._TRIVIAL``).
TRIVIAL_NAMES: frozenset[str] = frozenset({"0", "1", "2", "true", "false", ""})
#: Human-readable display sources for ``display_label``, in priority order.
DISPLAY_LABEL_SOURCES: tuple[str, ...] = ("label", "bm_name")
DISPLAY_LABEL_KEY = "display_label"


def _first_str(value: Any) -> str:
    """First non-blank string in a scalar-or-list property value, else ""."""
    values = value if isinstance(value, list) else [value]
    for v in values:
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def wrapper_value(properties: dict[str, Any]) -> str:
    """The value a locale wrapper stands for: en, then other locales, then text."""
    for key in LOCALE_TAGS:
        val = _first_str(properties.get(key))
        if val:
            return val
    return _first_str(properties.get(RAW_PROP_TEXT))


def _is_value_node(node: RawNode, has_children: set[int]) -> bool:
    """True when a node is just a value holder: only text/locale keys, no children."""
    return is_value_only(node.properties) and node.id not in has_children


def is_value_only(properties: dict[str, Any]) -> bool:
    """True when properties hold nothing but text/locale keys.

    Empty counts: an empty ``<label/>`` beside ``<label><en>..`` siblings is
    still a wrapper (folds as ""). A tag that is empty EVERYWHERE never
    qualifies anyway -- callers also require ``has_locale_key`` on >=1 node.
    """
    return set(properties) <= _VALUE_KEYS


def has_locale_key(properties: dict[str, Any]) -> bool:
    """True when at least one key is a locale tag (a real locale wrapper)."""
    return bool(set(properties) & _LOCALE_KEYS)


def accumulate(props: dict[str, Any], key: str, value: str) -> None:
    """Same collision rule as pass 1: never overwrite, accumulate a list.

    Idempotent on an already-seen value: re-running the fold against a
    parent that already carries ``value`` (e.g. ``display_backfill.py``
    replanning after ``--keep-wrappers``, or after a wrapper-delete chunk
    failed partway) must not turn a scalar/list into a duplicate entry --
    confirmed live, this was silently corrupting re-run output before this
    guard existed.
    """
    existing = props.get(key)
    if existing is None:
        props[key] = value
    elif isinstance(existing, list):
        if value not in existing:
            existing.append(value)
    elif existing != value:
        props[key] = [existing, value]


def fold_value_wrapper_tags(
    edges: list[RawEdge],
    by_tag: dict[str, list[RawNode]],
    *, log_id: str | None = None, source_key: str = "",
) -> dict[str, list[RawNode]]:
    """Fold every value-only locale-wrapper tag onto its parent; drop it from by_tag.

    Runs after ``fold_structural_leaf_tags``; all-or-nothing per tag (as in
    pass 1); parentless nodes keep their tag; mutates parent properties in place.
    """
    if not by_tag:
        return by_tag
    remaining_ids = {n.id for nodes in by_tag.values() for n in nodes}
    has_children = {e.source_id for e in edges if e.target_id in remaining_ids}
    # A tag qualifies only if it IS a locale wrapper somewhere (>=1 node has a
    # locale key) -- a purely text-only tag is a structural leaf and stays
    # pass 1's call, so its own opt-out flag keeps meaning what it says.
    wrapper_tags = {
        tag: nodes for tag, nodes in by_tag.items()
        if nodes and all(_is_value_node(n, has_children) for n in nodes)
        and any(has_locale_key(n.properties) for n in nodes)
    }
    if not wrapper_tags:
        return by_tag

    wrapper_ids = {n.id for nodes in wrapper_tags.values() for n in nodes}
    parent_of = {e.target_id: e.source_id for e in edges if e.target_id in wrapper_ids}
    needed = set(parent_of.values())
    nodes_by_id = {n.id: n for nodes in by_tag.values() for n in nodes if n.id in needed}

    result = {tag: nodes for tag, nodes in by_tag.items() if tag not in wrapper_tags}
    folded: list[str] = []
    for tag, nodes in wrapper_tags.items():
        parents = [nodes_by_id.get(parent_of.get(n.id, -1)) for n in nodes]
        if any(p is None for p in parents):
            result[tag] = nodes
            logger.info("value wrapper fold: tag=%s kept, %d node(s) have no parent",
                        tag, sum(p is None for p in parents))
            continue
        for node, parent in zip(nodes, parents):
            accumulate(parent.properties, tag, wrapper_value(node.properties))
        folded.append(tag)
    if folded:
        raven_log("INFO", "P4", "ingest.raw_graph.value_wrapper_folded locale wrapper tags folded onto parents",
                  context={"log_id": log_id, "source_key": source_key, "tags_folded": len(folded),
                           "folded_tag_names": folded, "tags_remaining": len(result),
                           "selected_option": "fold", "available_options": ["fold", "resolve"],
                           "reason_code": "VALUE_ONLY_WRAPPER_TAG"})
    return result


def promote_display_fields(props: dict[str, Any]) -> tuple[bool, bool]:
    """Fill an absent ``name`` and ``display_label`` in place.

    Returns (name_promoted, display_label_set). ``name`` keeps the
    variable-name shape CPQ matching depends on (``aPXNext_BOM``);
    ``display_label`` carries the human text (``APX™ NEXT``) and is only set
    when a ``label``/``bm_name`` exists.
    """
    promoted = labelled = False
    if not _first_str(props.get("name")):
        for cand in NAME_CANDIDATES:
            val = _first_str(props.get(cand))
            if val and val not in TRIVIAL_NAMES:
                props["name"] = val
                promoted = True
                break
    if DISPLAY_LABEL_KEY not in props:
        for src in DISPLAY_LABEL_SOURCES:
            val = _first_str(props.get(src))
            if val:
                props[DISPLAY_LABEL_KEY] = val
                labelled = True
                break
    return promoted, labelled


def apply_display_fields(by_tag: dict[str, list[RawNode]]) -> None:
    """Run ``promote_display_fields`` on every node's properties."""
    promoted = labelled = 0
    for nodes in by_tag.values():
        for node in nodes:
            p, lab = promote_display_fields(node.properties)
            promoted += p
            labelled += lab
    if promoted or labelled:
        logger.info("display fields: name promoted on %d node(s), display_label on %d",
                    promoted, labelled)
