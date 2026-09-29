"""CPQ XML ingestion pipeline — direct XML to raw graph, then Resolve/Relate to a curated graph.

Selected per-request via env vars (see ``aryx.cpq_ingestion.config``):
``ARYX_INGEST_FILE_TYPE=xml`` and ``ARYX_INGEST_PIPELINE=cpq_ingestion``.

Backend-agnostic: the raw graph and the curated graph each resolve to
FalkorDB locally or Oracle Graph on ``dev_oci`` via the existing
``Settings.effective_graph_backend()`` switch — nothing in this package
hardcodes a backend. See ``README.md`` alongside this file for the
architecture and the scope boundary (what is, and is not, implemented
relative to the Raw Graph -> Resolve/Relate -> Curated Graph proposal).
"""
from __future__ import annotations

from aryx.cpq_ingestion.pipeline import project_raw_graph_and_flatten
from aryx.cpq_ingestion.routing import cpq_ingestion_pipeline_active

__all__ = ["cpq_ingestion_pipeline_active", "project_raw_graph_and_flatten"]
