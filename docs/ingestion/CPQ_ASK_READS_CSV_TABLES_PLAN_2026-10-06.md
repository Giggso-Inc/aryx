# Ask / CPQ engine reads the CSV pipeline's workspace tables

## Problem

The CSV pipeline loads each CSV into `ws<workspace id>_<file stem>` (for example
`ws242_newcountryregmapping`), because that is what the XML scripts query. The CPQ engine's Data Table loaders read
only `aryx_entity`, the place the older ingest path put CSV rows. So the data was loaded but Ask never saw it:

```
_load_all_tables ... ws=242 constraint=0 sequence=0 hierarchy=0 series_mapping=0 region_rule=0
```

Ask then asked the user for values the table could answer (`Region -- Please provide a value.` after the country).

## Design

One seam, the Oracle CPQ reader (`cpq/rdb/rdb_oracle.py`), plus a small new module (`cpq/rdb/rdb_workspace_tables.py`).

| Reader call | Change |
|---|---|
| `fetch_entities_by_exact_type`, `fetch_entities_by_type` | when there are no entity rows, answer from the workspace table of that name |
| `fetch_workspace_table_groups` (new) | rows of every workspace table whose columns satisfy the caller's shape test |
| Data Table scans (`_scan_all_tables`, `_cached_shape_scan`, attr-var-mapping scan) | add the workspace tables to what the entity scan found |

Rules:

* **Which tables:** only the tables the pipeline owns for this workspace: owner tag `csv_bml_ingestion:ws=<id>` in the
  table comment AND the exact `ws<id>_` name (workspace 7 never reads `ws70_...`).
* **No double counting:** a table is skipped when entity rows of the same logical name exist.
* **Row shape:** like an entity row. NULL cells are not keys; column names are re-cased to the engine's spelling
  (`ruletype` -> `ruleType`, `udcc` -> `UDCC`). `CPQModel` and `cpqModel` differ only in case and belong to different
  shapes, so a table is read with the spelling the caller's shape test accepts. Rows also answer `get`/`[]`/`in`
  case-insensitively.
* **Only what is asked for:** a table is read only when its columns fit the requested shape, so large tables nobody asks
  for are never loaded. Ids are synthetic and negative.
* **No switch per table:** there will be many Data Tables, so none needs an environment flag. A table is used when the
  pipeline has created it for the workspace and its columns fit a shape the engine asks for; a workspace without such
  tables is unaffected. Oracle only (the Postgres reader returns none); any failure returns nothing, so the engine
  behaves as before. Per-table cap `ARYX_CPQ_WS_TABLE_MAX_ROWS` (default 1,000,000).
* **Country -> region:** the engine's own `cpq_country_region_table_enabled` (plan F5) now defaults to on, so the
  ingested `newCountryRegion` table is consulted before the built-in country list; with no such table the list is the
  fallback exactly as before. It stays an off-switch (`ARYX_CPQ_COUNTRY_REGION_TABLE_ENABLED=false`), not something to
  turn on.

## Menu options behind `Children` wrappers

A graph built from the raw XML keeps `attribute -> Children wrapper -> menu item`. The engine collected options only
from direct menu-item neighbours, so in such a workspace **no attribute had any option** (0 of 429 in the test
workspace) and every question was a free-text prompt (for example `Region -- Please provide a value.`), which also
stopped `derive_region` (it needs `attr.options`). `cpq/children_wrappers.py` widens a neighbour map by one hop through
the wrappers a node CONTAINS (`direction == "out"`, never its parent's wrapper). It is used by the attribute menu
collection (`product_config_menu_base.py`) and the product-option fetch (`product_option_fetch.py`). A graph without
wrappers is returned unchanged.

## Not changed

XML ingestion, the CSV pipeline, the entity read path, and the Postgres reader.

## Known limits

* The flag-free table read costs one cached listing query (~30 s TTL) per workspace.
* The engine's Data Table caches live up to 300 s; a CSV loaded just before a question may take that long to show.
* The vocabulary of re-cased names (`CANONICAL_COLUMNS`) holds the spellings the shape detectors use. A new detector
  needs its columns added there; a test fails if one is missing.
* The reader does not change what the Ask engine does with the rows. If Ask still asks for something, check the
  `region_rule=` counts in the log first.

## Tests

`tests/test_cpq_menu_through_children_wrappers.py`: wrapper detection, own-wrapper only (not the parent's), unchanged
without wrappers, failure tolerance, chunking, both call sites. `tests/test_cpq_rdb_workspace_tables.py`: spelling, detector coverage, listing isolation (ws7 vs ws70), NULL cells,
shape filter, skip when entities exist, row cap, no tables, failure tolerance, and the loader end to end.
