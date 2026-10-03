"""Bridge from a raw graph projection into resolve/relate (Connector seam).

Resolve/relate's actual input contract is a ``Connector`` yielding
``RawRecord``s (see ``connectors/base.py``) -- not CSV rows. ``RecordsConnector``
already proves this: the document-mentions flow replays already-extracted
records through the exact same ``run_pipeline`` used for CSV/DB sources
(``doc_discovery.py``'s mentions loop). ``RawGraphConnector`` is the same
pattern, one level earlier: it replays a raw graph projection's nodes,
grouped by XML tag, as one ``RawRecord`` per node.

Only the connector lives here. Match-key inference, containment-edge
translation into ``Relationship`` rows, and the orchestration that calls
``run_pipeline`` per tag are separate, later pieces (see
``cpq_ingestion/README.md``'s scope-boundary section) -- deliberately not
built yet, so each piece can be tested in isolation before they're wired
together.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterator

from aryx.connectors.base import Connector
from aryx.cpq_ingestion.raw_graph.models import RawGraphProjection, RawNode
from aryx.models import RawRecord, SourceRef

from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)

#: `RawRecord.source.system` for every record produced by this adapter --
#: lets provenance/debugging tell a raw-graph-sourced entity apart from one
#: that came from a CSV row or a REST API record.
SOURCE_SYSTEM = "cpq_ingestion_raw_graph"


def group_nodes_by_tag(projection: RawGraphProjection) -> dict[str, list[RawNode]]:
    """Group a projection's nodes by XML tag.

    Each tag becomes one candidate ``ontology_type`` and one resolve/relate
    run (mirroring how ``_xml_to_csvs`` already treats a tag as an entity
    type today) -- callers run one ``RawGraphConnector`` per tag returned
    here, not one connector for the whole projection.
    """
    by_tag: dict[str, list[RawNode]] = defaultdict(list)
    for node in projection.nodes:
        by_tag[node.tag].append(node)
    return dict(by_tag)


def parse_record_id(record_id: str) -> tuple[str, int]:
    """Reverse ``RawGraphConnector``'s ``"{source_key}:{node.id}"`` encoding.

    ``rsplit`` (not ``split``) because ``source_key`` -- a filename stem --
    is not guaranteed colon-free; ``node.id`` (always the last segment, and
    always an int) is not.
    """
    source_key, node_id = record_id.rsplit(":", 1)
    return source_key, int(node_id)


class RawGraphConnector(Connector):
    """Replays one XML tag's raw graph nodes into the pipeline as RawRecords.

    ``record_id`` is namespaced with ``source_key`` (not just ``node.id``)
    because a ``RawNode.id`` is only unique within the one projection it was
    built from -- two files in the same job would otherwise produce
    colliding record ids for, say, both files' node 0. This mirrors why
    ``naming.py``'s ``raw_ws_graph``/``raw_workspace_id`` fold ``source_key``
    into the raw graph's own storage scope for the same reason.
    """

    def __init__(self, nodes: list[RawNode], *, tag: str, source_key: str) -> None:
        self._nodes = nodes
        self._tag = tag
        self._source_key = source_key

    def extract(self) -> Iterator[RawRecord]:
        for node in self._nodes:
            yield RawRecord(
                source=SourceRef(
                    system=SOURCE_SYSTEM,
                    dataset=self._tag,
                    record_id=f"{self._source_key}:{node.id}",
                ),
                payload=dict(node.properties),
            )
        logger.info(
            "raw graph nodes extracted tag=%s source_key=%s records=%d",
            self._tag, self._source_key, len(self._nodes),
        )
        raven_log("DEBUG", "P4", "ingest.raw_graph.extract nodes replayed as records",
                  context={"tag": self._tag, "source_key": self._source_key, "records": len(self._nodes),
                           "zero_records": len(self._nodes) == 0})
