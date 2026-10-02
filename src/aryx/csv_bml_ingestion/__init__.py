"""CSV -> RDBMS ingestion driven by queries found in an XML knowledge graph.

Steps (see README.md): extract table name from the CSV filename -> find the query for that
table in the XML graph -> apply schema / index SQL (LLM-authored at run time when absent) ->
ingest the CSV rows, with Raven logging throughout. Public surface: ``ingest_csv``,
``BmlIndex``, ``IngestResult``.

Exports are loaded lazily so that importing a light submodule (e.g. ``config``, which the
upload path reads on every request) does not import the whole pipeline.
"""
from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "BmlIndex": "aryx.csv_bml_ingestion.bml_index",
    "IngestResult": "aryx.csv_bml_ingestion.options",
    "ingest_csv": "aryx.csv_bml_ingestion.pipeline",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str):  # noqa: ANN202 -- PEP 562 lazy export
    if name in _EXPORTS:
        return getattr(import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
