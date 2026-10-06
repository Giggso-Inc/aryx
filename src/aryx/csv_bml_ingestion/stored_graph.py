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
from typing import Any

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.naming import raw_workspace_id
from aryx.csv_bml_ingestion.bml_graph import QUERIES_KEY, QUERY_TABLES_KEY, SCRIPT_PROPS_KEY, TABLES_KEY
from aryx.csv_bml_ingestion.bml_index import (
    LABEL_HINTS, MAX_IDENTITY_CHARS, MAX_IDENTITY_VALUES, PATH_DEPTH, BmlLookup, BmlMatch, make_label,
)
from aryx.csv_bml_ingestion.constants import (
    CURATED_FALLBACK_CODE, FALLBACK_RECOVERY, FALLBACK_TRIGGER, RESULT_DEGRADED, STEP_BML_LOOKUP,
)
from aryx.csv_bml_ingestion.db import ConnectionFactory
from aryx.csv_bml_ingestion.errors import WorkspaceScopeError
from aryx.csv_bml_ingestion.query_extract import SqlQuery
from aryx.csv_bml_ingestion.tracking import RunTracker

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


_BML_KEYS = {TABLES_KEY, QUERIES_KEY, QUERY_TABLES_KEY, SCRIPT_PROPS_KEY}


def _folded_script_prop(attrs: dict) -> str:
    """Property holding the script body when the leaf fold put it on this vertex, else "" (plain vertex)."""
    tags = attrs.get(SCRIPT_PROPS_KEY)
    return tags[0] if isinstance(tags, list) and tags and isinstance(tags[0], str) else ""


def _own_identity(attrs: dict, text_keys: set[str]) -> dict[str, str]:
    """Short scalar values the matched vertex itself carries (its name, id, ...), excluding its script.

    The keys `make_label` prefers (id/guid/name/key) come first, so they are never crowded out by other
    short properties (flags, types).
    """
    keys = [k for k in LABEL_HINTS if k in attrs] + [k for k in attrs if k not in LABEL_HINTS]
    out: dict[str, str] = {}
    for key in keys:
        value = attrs[key]
        if key in _BML_KEYS or key in text_keys or len(out) >= MAX_IDENTITY_VALUES:
            continue
        if isinstance(value, str) and 0 < len(value) <= MAX_IDENTITY_CHARS:
            out[str(key)] = value
    return out


class StoredGraphLookup:
    """``lookup(table)`` over the workspace's stored XML knowledge graphs."""

    def __init__(self, factory: ConnectionFactory, workspace_id: int, scope: str = RAW) -> None:
        self._factory = factory
        self.source = scope
        offset = get_cpq_ingestion_settings().cpq_raw_workspace_offset
        try:
            wid = int(workspace_id)
        except (TypeError, ValueError):
            raise WorkspaceScopeError(f"workspace id {workspace_id!r} is not an integer") from None
        if wid <= 0 or offset <= 0:
            raise WorkspaceScopeError(
                f"workspace id ({wid}) and the raw-graph id offset ({offset}) must both be positive")
        if scope == CURATED:                      # the curated graph lives under the plain workspace id
            if wid >= offset:                     # ...so it must stay below the raw graphs' id range
                raise WorkspaceScopeError(
                    f"workspace id {wid} is not below the raw-graph id offset {offset}; the curated and "
                    "raw graph scopes would overlap (raise ARYX_CPQ_RAW_WORKSPACE_OFFSET)")
            self._lo = self._hi = wid
        else:
            self._lo = raw_workspace_id(wid, offset, "")
            self._hi = raw_workspace_id(wid + 1, offset, "") - 1
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
        folded = _folded_script_prop(attrs)
        prop = folded or "text"
        if folded:  # the script text is folded onto its function: the vertex describes itself
            identity = _own_identity(attrs, set(attrs.get(SCRIPT_PROPS_KEY, []))) or identity
        return BmlMatch(table=table, node_id=entity_id, node_tag=tag, prop=prop, path=path,
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
    recorded) is the raw graph searched instead; that decision is a Raven record
    (``CBI_CURATED_EMPTY_FALLBACK``) and the answering graph is named in the step-2 log.

    An *error* while checking the curated graph (database down, timeout) is not "no query lists":
    it propagates and fails the upload, so a transient fault can never silently serve a stale
    raw graph. The choice is made once per instance (one upload job); the raw graph's lookup is
    only built if it is needed.
    """

    def __init__(self, factory: ConnectionFactory, workspace_id: int) -> None:
        self.curated = StoredGraphLookup(factory, workspace_id, CURATED)   # validates the workspace id first
        self.workspace_id = int(workspace_id)
        self._factory = factory
        self._raw: StoredGraphLookup | None = None
        self._chosen: StoredGraphLookup | None = None
        self.node_count = 0   # unknown without scanning the whole graph; kept for interface parity

    @property
    def raw(self) -> StoredGraphLookup:
        """The raw-graph lookup (built on first use)."""
        if self._raw is None:
            self._raw = StoredGraphLookup(self._factory, self.workspace_id, RAW)
        return self._raw

    @property
    def chosen(self) -> StoredGraphLookup:
        """The graph searched for this job: the curated graph, or the raw graph when it has no query lists."""
        if self._chosen is None:
            tracker = RunTracker(f"workspace={self.workspace_id}")
            if self.curated.script_count:
                self._chosen = self.curated
            else:
                self._chosen = self.raw
                tracker.warn(
                    STEP_BML_LOOKUP,
                    "no query lists in the curated graph (XML not confirmed yet, or confirmed before this "
                    "feature); searching the raw graph instead",
                    error_code=CURATED_FALLBACK_CODE, workspace_id=self.workspace_id,
                    triggering_error=FALLBACK_TRIGGER, recovery_selected=FALLBACK_RECOVERY, fallback_target=RAW,
                    exit_condition=RESULT_DEGRADED, result=RESULT_DEGRADED)
            tracker.info(STEP_BML_LOOKUP, f"step 2 searches the {self._chosen.source}",
                         workspace_id=self.workspace_id, source_graph=self._chosen.source)
        return self._chosen

    @property
    def script_count(self) -> int:
        """Graph nodes that hold queries, in the graph this job searches."""
        return self.chosen.script_count

    @property
    def tables(self) -> list[str]:
        """Every table any stored query reads, in the graph this job searches."""
        return self.chosen.tables

    def lookup(self, table: str) -> BmlLookup:
        """Find nodes whose queries read ``table``; the result names the graph that answered."""
        return self.chosen.lookup(table)
