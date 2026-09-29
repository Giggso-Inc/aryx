"""Named constants for the cpq_ingestion pipeline — no magic strings scattered across modules."""
from __future__ import annotations

#: Value of ARYX_INGEST_FILE_TYPE that activates this pipeline for XML uploads.
FILE_TYPE_XML = "xml"

#: Value of ARYX_INGEST_PIPELINE that activates this pipeline (case-insensitive).
PIPELINE_CPQ_INGESTION = "cpq_ingestion"

#: Relationship name written for every structural (parent-element -> child-element) edge in the raw graph.
RAW_EDGE_CONTAINS = "CONTAINS"

#: Node property key holding a leaf element's text content, when it has no children.
RAW_PROP_TEXT = "text"
