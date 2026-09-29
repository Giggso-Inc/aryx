# cpq_ingestion

Direct XML → raw knowledge graph → (existing) Resolve/Relate → curated graph,
for CPQ XML uploads, backend-agnostic across FalkorDB (local) and Oracle
Graph (dev_oci).

## Why this exists

Local testing (`docs/` — see the two reference documents this package was
built from: *Raw Graph → Resolve/Relate → Curated Graph* and *Raw Knowledge
Graph — Live Local Test*) validated a "Scenario A" direct XML→graph
projection against FalkorDB and confirmed the existing production
`_xml_to_csvs()` silently drops elements nested under a plural wrapper tag
with a single child type (e.g. `<Contacts><Contact/></Contacts>`) — the
wrapper satisfies neither its entity-detection rule nor its container rule,
so `_walk()` never descends into it. The gap was confirmed to propagate all
the way through Resolve/Relate into the final curated graph.

This package makes the raw-graph projection (which does not have that gap —
it has no entity-detection heuristic at all) a real, env-gated capability of
the ingestion API, on both FalkorDB and Oracle Graph.

## Activation

Both env vars must be set (either alone leaves the existing XML→CSV path
unchanged):

| Env var | Example | Meaning |
|---|---|---|
| `ARYX_INGEST_FILE_TYPE` | `xml` | File extension this run treats as CPQ input |
| `ARYX_INGEST_PIPELINE` | `cpq_ingestion` | Which pipeline handles matching files |
| `ARYX_CPQ_RAW_GRAPH_ENABLED` | `true` (default) | Set `false` to skip the raw-graph write |
| `ARYX_CPQ_RAW_WORKSPACE_OFFSET` | `1000000000` (default) | Oracle Graph only — see below |

See `config.py` for the full field docstrings.

## Backend selection

Nothing in this package hardcodes FalkorDB or Oracle Graph. Both the raw
graph (`raw_graph/store.py`) and the curated graph
(`aryx.pipeline.orchestrate.run_pipeline`'s existing Project stage) resolve
the backend the same way: `Settings.effective_graph_backend()` — FalkorDB
locally, Oracle Graph when `ARYX_GRAPH_BACKEND=oci_graph` or `ARYX_OCI_MODE=true`.

## Raw graph storage scope

`aryx_graph_vertex`/`aryx_graph_edge` (the Oracle Graph tables) key rows by a
plain `workspace_id` column with no raw/curated discriminator and no FK to
`aryx_workspace`. Writing the raw graph into the *same* `workspace_id` as the
curated graph would mean the curated graph's `clear()`-then-rebuild wipes the
raw graph on every ingest. To keep both inspectable side by side, the raw
graph is written to a **derived** scope instead:

- FalkorDB: a distinct graph name, `aryx_raw_ws_<id>` (`naming.raw_ws_graph`).
- Oracle Graph: a distinct `workspace_id`, `<id> + ARYX_CPQ_RAW_WORKSPACE_OFFSET`
  (`naming.raw_workspace_id`).

## Module layout

```
cpq_ingestion/
  config.py         — ARYX_-prefixed settings (own BaseSettings, see below)
  constants.py       — named constants (file type / pipeline name / edge name)
  routing.py         — cpq_ingestion_pipeline_active(filename) activation check
  pipeline.py        — project_raw_graph_and_flatten(): the integration point
  naming.py          — raw graph storage-scope derivation
  raw_graph/
    models.py         — RawNode / RawEdge / RawGraphProjection / RawGraphWriteResult
    xml_projector.py  — pure XML -> (nodes, edges) walk, no I/O
    store.py           — backend dispatch + clear()/write batch calls
```

`config.py` is a standalone `BaseSettings` rather than a mixin merged into
the shared `aryx.config.Settings` — deliberately, to keep this addition
self-contained and independently reviewable on a fast-moving branch. It
reads the same `.env` file and the same `ARYX_` prefix, so no other file
needs to change for these settings to take effect.

## Integration point

`aryx.api.file_ingest.file_ingest_run` calls
`project_raw_graph_and_flatten(data, stem, ...)` instead of
`_xml_to_csvs(data, stem)` directly when `cpq_ingestion_pipeline_active(name)`
is true; otherwise the call falls through to the existing
`_xml_to_csvs(data, orig_stem)`, byte-for-byte unchanged. Both return the
same `[(csv_bytes, csv_filename), ...]` shape, so every downstream step
(auto-FK detection, per-type `run_pipeline` calls, catalog recording) is
identical either way.

## Scope boundary — what this does NOT implement

The reference "Raw Graph → Resolve/Relate → Curated Graph" proposal also
describes rewiring Resolve and Relate to read directly from the raw graph
(new adapters replacing `store.landed_records()` and the CSV-header read in
`_detect_fk_links`) instead of from CSV/`aryx_landed_record` rows. That
rewire:

- was explicitly noted as *not yet built* even in the reference testing
  this package is based on ("no such code exists yet, so a small Pass-1
  script was written and run for this test" — Scenario A was never chained
  into Resolve/Relate, only compared against them),
- touches `resolve_entities.py`, `resolution/run.py`'s caller, and
  `doc_discovery_fk.py`'s `_detect_fk_links` internals — a materially larger
  and riskier change than this ticket's tested scope, and
- is not needed to get a real, correct raw graph + curated graph on Oracle
  ADB: the existing CSV → Resolve → Relate → Project path already works
  end-to-end on Oracle Graph via `effective_graph_backend()` (see
  `orchestrate.py`'s Project stage) — this package's raw graph sits
  alongside it as an additional, unfiltered provenance/audit layer, exactly
  as validated in local testing.

If/when that deeper rewire is wanted, `raw_graph/store.py`'s
`get_raw_graph_store()` already returns a store that can answer "nodes of
type X with their property keys" queries — the natural extension point for
a future `ResolveInputAdapter`/`RelateInputAdapter` is a new module here,
built against that same store, without touching this package's existing
files.

## Testing

- `tests/cpq_ingestion/test_xml_projector.py` — pure unit tests against the
  exact two sample XML variants used in local testing, asserting the exact
  node/edge counts confirmed live (14/13 wrapped, 12/11 unwrapped).
- `tests/cpq_ingestion/test_routing.py` — env-var activation matrix.
- `tests/cpq_ingestion/test_raw_graph_store.py` — backend dispatch and the
  FalkorDB/Oracle write calls, mocked (no live Oracle ADB in this
  environment; follows the existing `tests/test_oracle_pool.py` stubbing
  pattern for `OracleGraphStore`).
- `tests/cpq_ingestion/test_pipeline_integration.py` — a real, live
  integration test against the local Docker FalkorDB (no mocks), run
  opt-in via `ARYX_RUN_LOCAL_INTEGRATION_TESTS=1` since it requires the
  docker-compose stack to be up.
