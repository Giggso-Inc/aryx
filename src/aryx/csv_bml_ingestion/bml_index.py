"""Step 2 — index the XML graph by the tables its embedded queries read.

Fully structure-agnostic: no element or attribute name is assumed. Every graph
node's string values are scanned for ``SELECT ... FROM`` queries (``query_extract``), so
any XML whose graph carries query text works — whatever the vendor's tags are
called. A match records *where* the query lives (node id, tag, property, the
chain of ancestor tags) and *who it belongs to*: the short leaf values sitting
next to it in the same parent element (typically an id / guid / name), kept as
a generic ``identity`` dict rather than fixed fields.

The graph is projected on demand from any XML (``graph_source``) with the same
projector the XML ingestion uses, or passed in as an existing projection. The
index is built once per graph and reused for every CSV.

Matching rule: the table in a query and the target table are both lowercased
before comparison (exact match — ``attrToPart_pcrDev`` is a different table from
``attrToPart``; such near-misses are only reported).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aryx.cpq_ingestion.raw_graph.models import RawGraphProjection
from aryx.csv_bml_ingestion.query_extract import SqlQuery, extract_queries
from aryx.csv_bml_ingestion.graph_source import projection_from_xml

MIN_QUERY_TEXT = 15           # shortest string worth scanning
MAX_IDENTITY_VALUES = 8       # sibling leaf values kept per match
MAX_IDENTITY_CHARS = 120      # longer sibling values are not identity (they are content)
PATH_DEPTH = 4                # ancestor tags recorded
LABEL_HINTS = ("id", "guid", "name", "key")   # display only: which identity value names a match


@dataclass(frozen=True, slots=True)
class BmlMatch:
    """One place in the graph whose query text reads the target table."""

    table: str
    node_id: int
    node_tag: str
    prop: str                      # the node property holding the query text
    path: tuple[str, ...]          # ancestor tags, outermost first
    identity: dict[str, str]       # sibling leaf values, e.g. {"id": "...", "guid": "..."}
    label: str                     # short display name derived from identity
    queries: tuple[SqlQuery, ...]  # only the queries that read ``table``


@dataclass(frozen=True, slots=True)
class BmlLookup:
    """Result of looking a table up in the index."""

    table: str
    matches: tuple[BmlMatch, ...]
    near_misses: tuple[str, ...] = field(default=())  # other tables sharing the name as a prefix
    source: str = ""                                   # which graph answered ("curated graph" / "raw graph")


def iter_query_nodes(projection: RawGraphProjection):
    """Yield ``(node, property, queries)`` for every node string value that holds SQL queries.

    Shared by the in-memory index and the XML-ingest enrichment, so both agree on what
    counts as a query.
    """
    for node in projection.nodes:
        for prop, value in node.properties.items():
            if isinstance(value, str) and len(value) >= MIN_QUERY_TEXT:
                queries = extract_queries(value)
                if queries:
                    yield node, prop, queries


class BmlIndex:
    """``lowercase table -> graph locations that query it`` for one XML graph."""

    def __init__(self) -> None:
        self._by_table: dict[str, list[BmlMatch]] = {}
        self.node_count = 0
        self.script_count = 0   # nodes that contained at least one query

    @classmethod
    def from_projection(cls, projection: RawGraphProjection) -> "BmlIndex":
        """Index every node of an already-projected XML graph."""
        index = cls()
        index.node_count = len(projection.nodes)
        parent_of = {e.target_id: e.source_id for e in projection.edges}
        children: dict[int, list[int]] = {}
        for child, parent in parent_of.items():
            children.setdefault(parent, []).append(child)
        by_id = {n.id: n for n in projection.nodes}
        for node, prop, queries in iter_query_nodes(projection):
            index.script_count += 1
            index._add(node, prop, queries, by_id, parent_of, children)
        return index

    @classmethod
    def from_xml_bytes(cls, data: bytes) -> "BmlIndex":
        """Project any XML (bytes) into the raw graph and index it."""
        return cls.from_projection(projection_from_xml(data))

    @classmethod
    def from_xml_file(cls, path) -> "BmlIndex":
        """Project any XML file into the raw graph and index it."""
        return cls.from_projection(projection_from_xml(path))

    def _add(self, node, prop: str, queries: list[SqlQuery], by_id: dict, parent_of: dict,
             children: dict) -> None:
        identity = _identity(node.id, by_id, parent_of, children)
        by_table: dict[str, list[SqlQuery]] = {}
        for q in queries:
            for table in {t.lower() for t in q.tables}:
                by_table.setdefault(table, []).append(q)
        for table, qs in by_table.items():
            self._by_table.setdefault(table, []).append(BmlMatch(
                table=table, node_id=node.id, node_tag=node.tag, prop=prop,
                path=_path(node.id, by_id, parent_of), identity=identity,
                label=make_label(identity, node.tag, node.id), queries=tuple(qs),
            ))

    def lookup(self, table: str) -> BmlLookup:
        """Find the graph locations that query ``table`` (compared in lowercase)."""
        key = table.lower()
        near = tuple(sorted(t for t in self._by_table if t != key and t.startswith(key)))
        return BmlLookup(table=key, matches=tuple(self._by_table.get(key, ())), near_misses=near)

    @property
    def tables(self) -> list[str]:
        """Every (lowercased) table name any query reads."""
        return sorted(self._by_table)


def _identity(node_id: int, by_id: dict, parent_of: dict, children: dict) -> dict[str, str]:
    """Short leaf values next to ``node_id`` in its parent element (generic: any tag names)."""
    out: dict[str, str] = {}
    for sid in children.get(parent_of.get(node_id, -1), ()):
        if sid == node_id or len(out) >= MAX_IDENTITY_VALUES:
            continue
        text = by_id[sid].properties.get("text")
        if isinstance(text, str) and 0 < len(text) <= MAX_IDENTITY_CHARS:
            out.setdefault(by_id[sid].tag, text)
    return out


def _path(node_id: int, by_id: dict, parent_of: dict) -> tuple[str, ...]:
    tags: list[str] = []
    cur = parent_of.get(node_id)
    while cur is not None and len(tags) < PATH_DEPTH:
        tags.append(by_id[cur].tag)
        cur = parent_of.get(cur)
    return tuple(reversed(tags))


def make_label(identity: dict[str, str], tag: str, node_id: int) -> str:
    """Short display name for a match: the first of id/guid/name/key present, else ``tag#node``."""
    for hint in LABEL_HINTS:
        if hint in identity:
            return f"{hint}={identity[hint]}"
    return f"{tag}#{node_id}"
