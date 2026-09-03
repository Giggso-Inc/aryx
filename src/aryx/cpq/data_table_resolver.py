"""Resolves constraint/sibling-manifest data from real Oracle CPQ Data Table
exports, not the master-string attributes that are always empty in a static
Rules/Attributes ("Download Configuration") export -- see docs/CPQ_CARRIER_
WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md §11-§12 for how `whitelist`
and `attrSequence` were identified and cross-validated against a real Oracle
CPQ admin trace page and a live Pipeline Viewer capture.

Reads from Aryx's real ingested entity store (aryx_entity via
aryx.cpq.rdb.get_cpq_rdb()), NOT from any bundled/hardcoded CSV file --
whichever Data Table CSVs a user uploads through the normal ingestion UI
(same CsvConnector path as any other tabular upload) are what this module
sees. There is no fixed file list, no per-product data file, and nothing
here needs updating when a new catalog's own Data Table CSV is ingested.

Rows are classified by TABLE SHAPE (see `cpq.data_table_shapes` for the
four shapes and how a new one gets added).

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), this module
is a thin re-export hub over 8 focused sibling modules -- the actual
resolver logic lives in `cpq.data_table_cache`, `cpq.data_table_shapes`,
`cpq.data_table_loader`, `cpq.data_table_whitelist`,
`cpq.data_table_governance`, `cpq.data_table_product`,
`cpq.data_table_variant`, and `cpq.data_table_consistency`. Every name
below is re-exported so
`engine.py`'s existing `dt_*`-aliased top-level imports, `doc_discovery.py`'s
deferred `_clear_tables_cache` import, and the test suite's direct
`data_table_resolver.<name>` attribute access all keep working unchanged.
Import from the specific sibling module directly in new code -- this file
exists for backward compatibility, not as the place to add new logic.
"""
from __future__ import annotations

from aryx.cpq.data_table_consistency import (
    discover_cpq_models_for_base_model,
    find_inconsistent_filled_pairs,
    find_inconsistent_filled_pairs_detailed,
)
from aryx.cpq.data_table_governance import (
    attr_ever_governed_for_cpq_model,
    attribute_applies,
    governed_attr_names_for_base_model,
    governed_required_attr_names_for_base_model,
)
from aryx.cpq.data_table_loader import (
    _clear_tables_cache,
    _load_all_tables,
    _TABLES_CACHE_TTL_SECONDS,
)
from aryx.cpq.data_table_product import (
    resolve_product_cpq_model_family,
    resolve_product_cpq_models_from_rows,
    resolve_region_allow_value,
)
from aryx.cpq.data_table_stale_models import _is_stale_cpq_model
from aryx.cpq.data_table_variant import resolve_invalid_product_variant
from aryx.cpq.data_table_whitelist import _row_conditions_match, resolve_whitelist_values

__all__ = [
    "attr_ever_governed_for_cpq_model",
    "attribute_applies",
    "discover_cpq_models_for_base_model",
    "find_inconsistent_filled_pairs",
    "find_inconsistent_filled_pairs_detailed",
    "governed_attr_names_for_base_model",
    "governed_required_attr_names_for_base_model",
    "resolve_invalid_product_variant",
    "resolve_product_cpq_model_family",
    "resolve_product_cpq_models_from_rows",
    "resolve_region_allow_value",
    "resolve_whitelist_values",
]
