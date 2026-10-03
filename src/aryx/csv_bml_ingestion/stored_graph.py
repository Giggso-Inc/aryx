"""Step 2 against the *stored* knowledge graph: find scripts without the XML.

``CuratedFirstLookup`` is what an upload uses: it searches the **curated** graph (the final
projection the XML confirm step builds, scope = the workspace id) and falls back to the raw
graph only when the curated one carries no query lists yet (XML not confirmed, or confirmed
before the lists were recorded). ``StoredGraphLookup`` is the search over one of the two.

``StoredGraphLookup`` has the same ``lookup(table)`` contract as ``BmlIndex`` but reads
a graph an earlier XML ingestion wrote to ``aryx_graph_vertex`` /
``aryx_graph_edge`` (Oracle backend). It looks only at nodes carrying the
``bml_tables`` list added by ``bml_graph`` at ingest time — typically a few dozen
nodes out of hundreds of thousands, found with one JSON query — and searches
**every** XML raw graph of the workspace (each XML has its own derived scope; they
share one contiguous id range per workspace, see ``aryx.cpq_ingestion.naming``), or the
workspace's curated graph (a single scope: the workspace id).
For each match it reads the neighbours in the graph to describe it (identity, path).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.naming import raw_workspace_id
from aryx.csv_bml_ingestion.bml_graph import QUERIES_KEY, QUERY_TABLES_KEY, TABLES_KEY
from aryx.csv_bml_ingestion.bml_index import (
    MAX_IDENTITY_CHARS, MAX_IDENTITY_VALUES, PATH_DEPTH, BmlLookup, BmlMatch, make_label,
)
from aryx.csv_bml_ingestion.db import ConnectionFactory
from aryx.csv_bml_ingestion.query_extract import SqlQuery

logger = logging.getLogger(__name__)

RAW, CURATED = "raw graph", "curated graph"

_ENRICHED_SQL = (
    "SELECT workspace_id, entity_id, type, attributes FROM aryx_graph_vertex "
    "WHERE workspace_id BETWEEN %s AND %s AND JSON_EXISTS(attributes, '$.bml_tables')"
)
_PARENT_SQL = "SELECT src_id FROM aryx_graph_edge WHERE workspace_id = %s AND tgt_id = %s"
_TYPE_SQL = "SELECT type FROM aryx_graph_vertex WHERE workspace_id = %s AND entity_id = %s"
_SIBLINGS_SQL = (
    "SELECT v.type, v.attributes FROM aryx_graph_edge e JOIN aryx_graph_vertex v "
    "ON v.workspace_id = e.workspace_id AND v.entity_id = e.tgt_id "
    "WHERE e.workspace_id = %s AND e.src_id = %s AND e.tgt_id <> %s"
)


def _attrs(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes)) and value:
        try:
            loaded = json.loads(value)
        except ValueError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


class StoredGraphLookup:
    """``lookup(table)`` over the workspace's stored XML knowledge graphs."""

    def __init__(self, factory: ConnectionFactory, workspace_id: int, scope: str = RAW) -> None:
        self._factory = factory
        self.source = scope
        if scope == CURATED:                      # the curated graph lives under the plain workspace id
            self._lo = self._hi = int(workspace_id)
        else:
            offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
            self._lo = raw_workspace_id(workspace_id, offset, "")
            self._hi = raw_workspace_id(workspace_id + 1, offset, "") - 1
        self._rows: list[tuple[int, int, str, dict]] | None = None
        self.node_count = 0   # unknown without scanning the whole graph; kept for interface parity

    def _enriched(self) -> list[tuple[int, int, str, dict]]:
        if self._rows is None:
            with self._factory() as conn:
                cur = conn.cursor()
                cur.execute(_ENRICHED_SQL, (self._lo, self._hi))
                self._rows = [(int(w), int(e), str(t), _attrs(a)) for w, e, t, a in cur.fetchall()]
        return self._rows

    @property
    def script_count(self) -> int:
        """Stored graph nodes that hold queries."""
        return len(self._enriched())

    @property
    def tables(self) -> list[str]:
        """Every table any stored query reads."""
        return sorted({t for *_x, attrs in self._enriched() for t in attrs.get(TABLES_KEY, [])})

    def lookup(self, table: str) -> BmlLookup:
        """Find stored nodes whose queries read ``table`` (compared in lowercase)."""
        key = table.lower()
        near = tuple(sorted(t for t in self.tables if t != key and t.startswith(key)))
        matches = [self._match(key, ws, eid, tag, attrs)
                   for ws, eid, tag, attrs in self._enriched() if key in attrs.get(TABLES_KEY, [])]
        return BmlLookup(table=key, matches=tuple(matches), near_misses=near, source=self.source)

    def _match(self, table: str, ws: int, entity_id: int, tag: str, attrs: dict) -> BmlMatch:
        queries = tuple(
            SqlQuery(sql=sql, tables=tuple(tables.split(",")))
            for sql, tables in zip(attrs.get(QUERIES_KEY, []), attrs.get(QUERY_TABLES_KEY, []))
            if table in tables.split(","))
        identity, path = self._context(ws, entity_id)
        return BmlMatch(table=table, node_id=entity_id, node_tag=tag, prop="text", path=path,
                        identity=identity, label=make_label(identity, tag, entity_id), queries=queries)

    def _context(self, ws: int, entity_id: int) -> tuple[dict[str, str], tuple[str, ...]]:
        """Identity (short sibling leaf values) and ancestor tags, read from the graph."""
        identity: dict[str, str] = {}
        tags: list[str] = []
        with self._factory() as conn:
            cur = conn.cursor()
            cur.execute(_PARENT_SQL, (ws, entity_id))
            row = cur.fetchall()
            parent = int(row[0][0]) if row else None
            if parent is not None:
                cur.execute(_SIBLINGS_SQL, (ws, parent, entity_id))
                for typ, attrs in cur.fetchall():
                    text = _attrs(attrs).get("text")
                    if isinstance(text, str) and 0 < len(text) <= MAX_IDENTITY_CHARS \
                            and len(identity) < MAX_IDENTITY_VALUES:
                        identity.setdefault(str(typ), text)
            cur_id = parent
            while cur_id is not None and len(tags) < PATH_DEPTH:
                cur.execute(_TYPE_SQL, (ws, cur_id))
                t = cur.fetchall()
                tags.append(str(t[0][0]) if t else "?")
                cur.execute(_PARENT_SQL, (ws, cur_id))
                up = cur.fetchall()
                cur_id = int(up[0][0]) if up else None
        return identity, tuple(reversed(tags))


class CuratedFirstLookup:
    """``lookup(table)`` over the workspace's graphs: curated first, raw only as a fallback.

    The curated graph is authoritative whenever it carries query lists: a table it does not
    mention is *not found*, even if an older raw graph mentions it. Only when the curated graph
    has no query lists at all (XML not confirmed yet, or confirmed before the lists were
    recorded) is the raw graph searched instead. The choice is made once per instance (one
    upload job) and logged.
    """

    def __init__(self, factory: ConnectionFactory, workspace_id: int) -> None:
        self.workspace_id = int(workspace_id)
        self.curated = StoredGraphLookup(factory, workspace_id, CURATED)
        self.raw = StoredGraphLookup(factory, workspace_id, RAW)
        self._chosen: StoredGraphLookup | None = None
        self.node_count = 0   # unknown without scanning the whole graph; kept for interface parity

    @property
    def chosen(self) -> StoredGraphLookup:
        """The graph searched for this job."""
        if self._chosen is None:
            if self.curated.script_count:
                self._chosen = self.curated
            else:
                self._chosen = self.raw
                logger.warning(
                    "csv_bml_ingestion: workspace %s has no query lists in its curated graph (XML not confirmed "
                    "yet, or confirmed before this feature); searching the raw graph instead", self.workspace_id)
            logger.info("csv_bml_ingestion: workspace %s step 2 searches the %s", self.workspace_id,
                        self._chosen.source)
        return self._chosen

    @property
    def script_count(self) -> int:
        return self.chosen.script_count

    @property
    def tables(self) -> list[str]:
        return self.chosen.tables

    def lookup(self, table: str) -> BmlLookup:
        return self.chosen.lookup(table)
