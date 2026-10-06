"""XML-ingest side of the knowledge graph: record which tables each script's queries read.

Why this exists: the graph store clips every *string* property to ~200 characters
(``aryx.graph.oracle_graph_store_helpers._GRAPH_ATTR_STR_MAX``, an ORA-03106 guard
for large script bodies), so a script's text cannot be searched once it is stored.
Lists are not clipped. So while the full text is still in hand — during XML
ingestion — each node holding SQL queries gets three short list properties:

* ``bml_tables``       lowercase table names its queries read (the lookup key);
* ``bml_queries``      the query texts (capped), parallel to
* ``bml_query_tables`` comma-joined lowercase tables for each query.

CSV ingestion later finds scripts by searching the stored graph for
``bml_tables`` — no XML needed, nothing about tag or call names assumed.
"""
from __future__ import annotations

import logging

from aryx.cpq_ingestion.raw_graph.models import RawGraphProjection, RawNode
from aryx.csv_bml_ingestion.bml_index import iter_query_nodes

logger = logging.getLogger(__name__)

TABLES_KEY = "bml_tables"
QUERIES_KEY = "bml_queries"
QUERY_TABLES_KEY = "bml_query_tables"
SCRIPT_PROPS_KEY = "bml_script_props"   # set by the leaf fold: tag name(s) the query lists were folded under
MAX_QUERIES_PER_NODE = 8
MAX_SQL_CHARS = 2000


def enrich_projection(projection: RawGraphProjection) -> RawGraphProjection:
    """Return ``projection`` with query-table lists added to every node that holds queries.

    Nodes without queries are returned untouched; the input is not modified.
    """
    extra: dict[int, dict[str, list[str]]] = {}
    for node, _prop, queries in iter_query_nodes(projection):
        cur = extra.setdefault(node.id, {TABLES_KEY: [], QUERIES_KEY: [], QUERY_TABLES_KEY: []})
        for q in queries:
            tables = sorted({t.lower() for t in q.tables})
            if not tables:
                continue
            for t in tables:
                if t not in cur[TABLES_KEY]:
                    cur[TABLES_KEY].append(t)
            if len(cur[QUERIES_KEY]) < MAX_QUERIES_PER_NODE:
                cur[QUERIES_KEY].append(q.sql[:MAX_SQL_CHARS])
                cur[QUERY_TABLES_KEY].append(",".join(tables))
    extra = {nid: props for nid, props in extra.items() if props[TABLES_KEY]}
    nodes = [RawNode(id=n.id, tag=n.tag, properties={**n.properties, **extra[n.id]}) if n.id in extra else n
             for n in projection.nodes]
    logger.info("csv_bml_ingestion: enriched %d of %d graph nodes with query tables", len(extra), len(nodes))
    return RawGraphProjection(nodes=nodes, edges=projection.edges)
