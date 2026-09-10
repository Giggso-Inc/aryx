"""Parse an XML upload into one CSV per discovered entity element type.

Split out of `pipeline/doc_discovery.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

import csv
import io
import logging
import xml.etree.ElementTree as ET
from collections import Counter

import defusedxml.ElementTree as defused_ET

from aryx.config import get_settings

logger = logging.getLogger(__name__)


def _xml_to_csvs(data: bytes, stem: str, log_id: str | None = None) -> list[tuple[bytes, str]]:
    """Parse XML → one CSV per discovered entity element type.

    Handles three common XML patterns that the naive approach misses:
    - ``_children`` wrapper tags (transparent containers, not entity types)
    - Multilingual CDATA fields (``<name><en><![CDATA[...]]></en>...</name>``)
    - Data stored in child element text rather than XML element attributes

    Entity type detection: an element is classified as an entity when it has
    ≥2 distinct non-container child element types.  This excludes scalar leaf
    elements (``<id>123</id>``) and locale-wrapper elements (``<name>``).

    Each entity row gets a ``{parent_tag}_id`` FK column injected so that
    ``_detect_fk_links`` can wire parent→child edges automatically.
    """
    # ISO locale tags used as multilingual value wrappers — not entity types.
    _LOCALE_TAGS: frozenset[str] = frozenset({
        "en", "de", "fr", "es", "it", "da", "nl", "sv", "no", "fi", "pl", "cs",
        "ru", "tr", "ar", "he",
        # bare 2-letter codes used by Oracle CPQ / BigMachines exports
        "ja", "ko", "zh", "pt",
        "ja_JP", "zh_CN", "zh_HK", "zh_TW", "zh_SG", "ko_KR", "da_DK",
        "pt_BR", "pt_PT", "fr_CA", "es_CO",
    })
    # HTML/embedded tags whose text content must never become entity fields or
    # entity types — script/style bodies are code, not data.
    _SKIP_TAGS: frozenset[str] = frozenset({
        "script", "style", "head", "meta", "link", "noscript",
    })

    def _strip_ns(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    def _is_container(tag: str) -> bool:
        """True for transparent wrapper tags that are not entity types."""
        return tag.startswith("_") or tag in _LOCALE_TAGS

    def _extract_field(child: ET.Element) -> str | None:
        """Extract a scalar string from a child element.

        If the element has locale sub-children (multilingual field), prefer
        ``<en>`` CDATA; fall back to the first non-empty locale value.
        Otherwise return the element's own text content.
        """
        sub = list(child)
        if sub:
            sub_tags = {_strip_ns(c.tag) for c in sub}
            if sub_tags & _LOCALE_TAGS:
                en = next((c for c in sub if _strip_ns(c.tag) == "en"), None)
                if en is not None and en.text and en.text.strip():
                    return en.text.strip()
                for c in sub:
                    if c.text and c.text.strip():
                        return c.text.strip()
                return None
            return None  # non-locale children → nested entity, not a scalar value
        if _strip_ns(child.tag) in _SKIP_TAGS:
            return None
        return child.text.strip() if child.text and child.text.strip() else None

    def _elem_id(elem: ET.Element) -> str | None:
        """Return the best ID value for ``elem`` (check child elements first)."""
        for pk in ("id", "guid"):
            for c in elem:
                if _strip_ns(c.tag) == pk:
                    v = _extract_field(c)
                    if v:
                        return v
            v = elem.attrib.get(pk)
            if v:
                return v
        return None

    def _is_entity(elem: ET.Element) -> bool:
        """True when ``elem`` represents a data record.

        Complex entities: ≥2 distinct non-container child element types.
        Attribute-only leaf entities: no child elements AND ≥1 XML attribute
        (e.g. ``<Widget id="1" name="alpha"/>``).

        Text-only nodes (e.g. ``<id>123</id>``, ``<date_modified>...``) are
        deliberately excluded — they are scalar field values of their parent
        entity, not stand-alone records.  Counting them as entities inflates
        row counts by tens of thousands and breaks type selection.
        """
        child_tags = {_strip_ns(c.tag) for c in elem if not _is_container(_strip_ns(c.tag))}
        if child_tags:
            return len(child_tags) >= 2
        return len(elem.attrib) >= 1

    try:
        root = defused_ET.fromstring(data)
    except ET.ParseError as exc:
        logger.warning("xml_to_csvs log_id=%s stem=%s parse failed, treating as raw upload: %s",
                        log_id, stem, exc)
        return [(data, stem + ".csv")]

    # Candidate fields to use as entity name when no ``name`` field exists.
    # Ordered by priority; first non-trivial value wins.  Generic fields
    # come first; the ``bm_*`` / CPQ-specific entries are additive hints
    # that match BigMachines exports and are silently skipped on other data.
    _NAME_CANDIDATES = (
        "variable_name", "var_name",
        "item_text", "item_value",
        "prop_value", "property_value", "prop_type",
        "label", "file_name", "relative_path",
        # CPQ/BigMachines-specific — degrade gracefully on non-BM data:
        "bm_variable_name", "bm_name", "func_name", "rule_name",
        "java_class_name",
    )
    _NAME_CANDIDATE_SET: frozenset[str] = frozenset(_NAME_CANDIDATES) | {"name"}
    _TRIVIAL = frozenset({"0", "1", "2", "true", "false", ""})

    def _alias_name(row: dict) -> None:
        """Set ``row['name']`` from the best available display field if absent."""
        if row.get("name"):
            return
        for cand in _NAME_CANDIDATES:
            val = row.get(cand)
            if val and str(val) not in _TRIVIAL:
                row["name"] = val
                return

    counts: Counter = Counter()
    type_has_name: dict[str, bool] = {}
    root_tag = _strip_ns(root.tag)

    def _check_name(elem: ET.Element, tag: str) -> None:
        """Set type_has_name[tag]=True once any element carries a name-candidate field."""
        if not type_has_name.get(tag, False):
            has = any(
                _strip_ns(c.tag) in _NAME_CANDIDATE_SET
                for c in elem
                if not _is_container(_strip_ns(c.tag))
            )
            if not has:
                has = any(k in _NAME_CANDIDATE_SET for k in elem.attrib)
            if has:
                type_has_name[tag] = True
            else:
                type_has_name.setdefault(tag, False)

    if _is_entity(root):
        counts[root_tag] += 1
        _check_name(root, root_tag)

    def _walk(elem: ET.Element) -> None:
        for child in elem:
            ctag = _strip_ns(child.tag)
            if ctag in _SKIP_TAGS:
                continue
            if _is_container(ctag):
                _walk(child)
            elif _is_entity(child):
                counts[ctag] += 1
                _check_name(child, ctag)
                _walk(child)

    _walk(root)
    if not counts:
        logger.warning(
            "xml_to_csvs log_id=%s stem=%s no entity elements detected "
            "(all leaves/containers), falling back to raw upload", log_id, stem)
        return [(data, stem + ".csv")]

    # Prefer entity types that carry a human-readable name field over pure
    # junction tables (id-only FKs).  Named types first by frequency, then
    # unnamed to fill remaining slots.  Cap is configurable via
    # ARYX_XML_MAX_ENTITY_TYPES (default 20) so large CPQ/ERP exports with
    # 20+ entity types are not silently truncated.
    _settings = get_settings()
    _xml_max_types = _settings.xml_max_entity_types
    _xml_max_rows = _settings.xml_max_rows_per_type
    _all_by_freq = [t for t, _ in counts.most_common()]
    _named = [t for t in _all_by_freq if type_has_name.get(t, False)]
    _unnamed = [t for t in _all_by_freq if not type_has_name.get(t, False)]
    top_tags = (_named + _unnamed)[:_xml_max_types]

    def _collect_tag(
        elem: ET.Element, tag: str, parent_tag: str, parent_id: str | None,
    ) -> list[dict]:
        """Recursively collect all elements matching *tag* with parent FK."""
        records: list[dict] = []
        for child in elem:
            ctag = _strip_ns(child.tag)
            if _is_container(ctag):
                # Transparent container: recurse with the same parent context so
                # that ``_children`` wrappers do not reset the FK lineage.
                records.extend(_collect_tag(child, tag, parent_tag, parent_id))
            elif ctag == tag:
                my_id = _elem_id(child)
                row: dict = {"_element_type": tag}
                if parent_id is not None:
                    row[f"{parent_tag}_id"] = parent_id
                # XML element attributes (e.g. <elem attr="val"/>)
                for k, v in child.attrib.items():
                    row[_strip_ns(k)] = v
                # Child element text values (e.g. <id>123</id>, multilingual)
                for sub in child:
                    stag = _strip_ns(sub.tag)
                    if _is_container(stag) or stag in _SKIP_TAGS:
                        continue
                    val = _extract_field(sub)
                    if val is not None:
                        row[stag] = val
                # Ensure every entity has a human-readable ``name`` field.
                _alias_name(row)
                if len(row) > 1:
                    records.append(row)
                # Recurse into this element's subtree for nested same-type entities.
                records.extend(_collect_tag(child, tag, ctag, my_id))
            else:
                # Different entity type: recurse, updating the parent context.
                child_id = _elem_id(child)
                records.extend(_collect_tag(child, tag, ctag, child_id))
        return records

    # Do NOT fall back to root_tag when root has no real id: injecting
    # {root_tag}_id = root_tag (a constant non-id string) into all child rows
    # creates a spurious FK column that link_by_attribute can never satisfy,
    # making child entities appear as candidates for FK joining but producing
    # zero edges.  Leaving root_id=None means no FK column is injected for
    # direct children of a root with no id, which is the correct behaviour.
    root_id = _elem_id(root)
    results: list[tuple[bytes, str]] = []
    total_rows = 0

    for target_tag in top_tags:
        if target_tag == root_tag:
            # Root element itself is the entity — extract one row directly.
            row: dict = {"_element_type": root_tag}
            for k, v in root.attrib.items():
                row[_strip_ns(k)] = v
            for sub in root:
                stag = _strip_ns(sub.tag)
                if _is_container(stag):
                    continue
                val = _extract_field(sub)
                if val is not None:
                    row[stag] = val
            _alias_name(row)
            records = [row] if len(row) > 1 else []
        else:
            records = _collect_tag(root, target_tag, root_tag, root_id)

        if not records:
            continue
        if len(records) > _xml_max_rows:
            logger.warning(
                "xml log_id=%s: %s has %d rows, capping at %d (set ARYX_XML_MAX_ROWS_PER_TYPE to change)",
                log_id, target_tag, len(records), _xml_max_rows,
            )
            records = records[:_xml_max_rows]
        total_rows += len(records)
        all_keys: list[str] = []
        seen_keys: set[str] = set()
        for rec in records:
            for k in rec:
                if k not in seen_keys:
                    all_keys.append(k)
                    seen_keys.add(k)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        csv_name = f"{stem}_{target_tag}.csv"
        results.append((buf.getvalue().encode("utf-8"), csv_name))

    if not results:
        logger.warning(
            "xml_to_csvs log_id=%s stem=%s %d candidate type(s) considered but 0 rows "
            "collected, falling back to raw upload", log_id, stem, len(top_tags))
        return [(data, stem + ".csv")]
    logger.info(
        "xml_to_csvs log_id=%s stem=%s detected_types=%d capped_to=%d output_csvs=%d rows_total=%d",
        log_id, stem, len(counts), len(top_tags), len(results), total_rows)
    return results
