"""The one switch that turns the upload integration on: ``ARYX_CSV_BML_ENABLED``.

Off by default, so existing XML/CSV ingestion behaves exactly as before until it is
set. When on:

* XML ingestion also records, on each graph node that holds SQL queries, which
  tables those queries read (``bml_graph``), and
* an uploaded CSV is ingested into a table named after the file — but only if a
  query for that table exists in the XML knowledge graph already stored
  (``upload_hook``).
"""
from __future__ import annotations

import os

ENABLE_ENV = "ARYX_CSV_BML_ENABLED"
_TRUE = {"1", "true", "yes", "on"}


def csv_bml_enabled() -> bool:
    """True when ``ARYX_CSV_BML_ENABLED`` is set to a truthy value (read at call time)."""
    return os.environ.get(ENABLE_ENV, "").strip().lower() in _TRUE
