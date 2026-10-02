"""Where step 2's XML graph comes from: any XML, projected on demand.

``projection_from_xml`` uses the same projector the XML ingestion uses
(``aryx.cpq_ingestion``: one node per element, nesting as ``CONTAINS`` edges), so the
graph is identical to the one ingestion builds and nothing about the XML's
vendor, tags or layout is assumed. A caller that already holds a projection
(e.g. the XML ingestion path) can skip parsing entirely and pass it to
``BmlIndex.from_projection``.

Why not read the *stored* raw graph back? The store clips every property to ~200
characters (a script's ``text`` is saved as 201 characters), so query text cannot
be recovered from it; reading it would silently miss most queries.
"""
from __future__ import annotations

from pathlib import Path

from aryx.cpq_ingestion.raw_graph.models import RawGraphProjection
from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph
from aryx.csv_bml_ingestion.errors import XmlSourceError


def projection_from_xml(source: str | Path | bytes) -> RawGraphProjection:
    """Project any XML (path or bytes) into the raw graph."""
    try:
        data = source if isinstance(source, bytes) else Path(source).read_bytes()
    except OSError as exc:
        raise XmlSourceError(f"could not read XML file {source}: {exc}") from exc
    try:
        return project_xml_to_raw_graph(data)
    except Exception as exc:  # noqa: BLE001 -- defusedxml/ET raise a variety of parse errors
        raise XmlSourceError(f"could not parse XML into a graph: {exc}") from exc
