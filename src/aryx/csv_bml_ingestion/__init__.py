"""CSV -> RDBMS ingestion driven by BML queries found in a CPQ XML graph.

Steps (see README.md): extract table name from the CSV filename -> find the
BML query for that table in the XML graph -> apply the LLM-authored schema /
index SQL (``sql/<table>/``) -> ingest the CSV rows, with Raven logging
throughout. Public surface: ``ingest_csv`` and ``BmlIndex``.
"""
from __future__ import annotations

from aryx.csv_bml_ingestion.bml_index import BmlIndex
from aryx.csv_bml_ingestion.options import IngestResult
from aryx.csv_bml_ingestion.pipeline import ingest_csv

__all__ = ["BmlIndex", "IngestResult", "ingest_csv"]
