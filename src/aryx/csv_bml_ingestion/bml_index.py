"""Step 2 — build the XML graph and index BML scripts by the tables they query.

The XML is projected with the existing ``cpq_ingestion`` raw-graph projector
(one node per element, nesting as CONTAINS edges). Each ``script_text`` node
is a BML script; its parent element (``bm_function``) carries the script's
``id`` / ``guid`` / ``java_class_name`` as sibling leaf nodes. The index is
built once per XML and queried once per CSV, so ingesting many CSVs against
one XML re-parses nothing.

Matching rule: the table named in a BMQL query and the target table name are
both lowercased before comparison (exact match — ``attrToPart_pcrDev`` is a
different table from ``attrToPart``; such near-misses are only reported).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from aryx.cpq_ingestion.raw_graph.models import RawGraphProjection
from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph
from aryx.csv_bml_ingestion.bmql import BmqlQuery, extract_queries
from aryx.csv_bml_ingestion.errors import XmlSourceError

SCRIPT_TAG = "script_text"
_IDENTITY_TAGS = ("id", "guid", "java_class_name")


@dataclass(frozen=True, slots=True)
class BmlMatch:
    """One BML script that queries the target table."""

    table: str
    script_node_id: int
    script_id: str
    script_guid: str
    java_class_name: str
    queries: tuple[BmqlQuery, ...]  # only the queries that read ``table``


@dataclass(frozen=True, slots=True)
class BmlLookup:
    """Result of looking a table up in the index."""

    table: str
    matches: tuple[BmlMatch, ...]
    near_misses: tuple[str, ...] = field(default=())  # other tables sharing the name as a prefix


class BmlIndex:
    """``lowercase table -> BML scripts that query it`` for one XML document."""

    def __init__(self) -> None:
        self._by_table: dict[str, list[BmlMatch]] = {}
        self.node_count = 0
        self.script_count = 0

    @classmethod
    def from_projection(cls, projection: RawGraphProjection) -> "BmlIndex":
        """Index every ``script_text`` node of an already-projected XML graph."""
        index = cls()
        index.node_count = len(projection.nodes)
        parent_of = {e.target_id: e.source_id for e in projection.edges}
        children: dict[int, list[int]] = {}
        for child, parent in parent_of.items():
            children.setdefault(parent, []).append(child)
        by_id = {n.id: n for n in projection.nodes}
        for node in projection.nodes:
            if node.tag != SCRIPT_TAG:
                continue
            index.script_count += 1
            text = str(node.properties.get("text", ""))
            queries = extract_queries(text)
            if not queries:
                continue
            ident = _identity(by_id, children.get(parent_of.get(node.id, -1), ()))
            by_table: dict[str, list[BmqlQuery]] = {}
            for q in queries:
                for table in {t.lower() for t in q.tables}:
                    by_table.setdefault(table, []).append(q)
            for table, qs in by_table.items():
                index._by_table.setdefault(table, []).append(BmlMatch(
                    table=table, script_node_id=node.id, script_id=ident["id"],
                    script_guid=ident["guid"], java_class_name=ident["java_class_name"],
                    queries=tuple(qs),
                ))
        return index

    @classmethod
    def from_xml_bytes(cls, data: bytes) -> "BmlIndex":
        """Project ``data`` to the raw XML graph and index it."""
        try:
            return cls.from_projection(project_xml_to_raw_graph(data))
        except Exception as exc:  # noqa: BLE001 -- defusedxml/ET raise a variety of parse errors
            raise XmlSourceError(f"could not parse XML into a graph: {exc}") from exc

    @classmethod
    def from_xml_file(cls, path: str | Path) -> "BmlIndex":
        """Read ``path`` and index it."""
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            raise XmlSourceError(f"could not read XML file {path}: {exc}") from exc
        return cls.from_xml_bytes(data)

    def lookup(self, table: str) -> BmlLookup:
        """Find the BML scripts that query ``table`` (compared in lowercase)."""
        key = table.lower()
        near = tuple(sorted(t for t in self._by_table if t != key and t.startswith(key)))
        return BmlLookup(table=key, matches=tuple(self._by_table.get(key, ())), near_misses=near)

    @property
    def tables(self) -> list[str]:
        """Every (lowercased) table name any BML script queries."""
        return sorted(self._by_table)


def _identity(by_id: dict, sibling_ids: object) -> dict[str, str]:
    """Pull id/guid/java_class_name from the leaf siblings of a script_text node."""
    ident = {tag: "" for tag in _IDENTITY_TAGS}
    for sid in sibling_ids:  # type: ignore[attr-defined]
        sib = by_id[sid]
        if sib.tag in ident:
            ident[sib.tag] = str(sib.properties.get("text", ""))
    return ident
