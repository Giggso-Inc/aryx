# Document Ingestion — Full-Trace Logging & Resolution Wiring

**Status:** Approved, in implementation
**Audience:** Engineering, ingestion/resolution owners
**Prepared for:** Observability into `/admin/docs/read` and `/admin/docs/confirm`
**Date:** 2026-07-08

## 1. Executive Summary

Aryx's document ingestion flow — `POST /admin/docs/read` (discovery) and `POST /admin/docs/confirm` (ingestion) — routes through a deep call chain ending in the entity-resolution funnel (block → score → route → golden-record merge). An audit of every step in both flows found the pipeline stages below `ingest_confirmed()` (discover/land, relate, FK-link, project) are already well logged, but three areas are not, and two of them are more than a logging gap:

1. The discovery/read side (`read_files`, `_infer_type`, `_consolidate_csv_names`, most of `_xml_to_csvs`, two of `_detect_fk_links`'s three passes) is almost entirely unlogged, as is the HTTP handler layer outside failure paths.
2. The resolution funnel has no per-pair/per-band logging — auto-merge and reject decisions are completely silent; only adjudicate has a score-less debug line.
3. Two things an operator would expect resolution logs to show don't run in production at all: the human-review queue (`review` is always `None`, so `[0.75, 0.90)`-band pairs are silently dropped, never reaching `aryx_adjudication`) and attribute-conflict persistence (`conflicts` is always set to `None` on the production code path, so `aryx_attribute_conflict` never gets written despite a warning firing).

This plan adds full-trace, correlatable logging across both flows and activates the two dead-but-already-built code paths (review queue, survivorship-based conflict persistence) rather than just logging around the gap.

## 2. Problem Statement

### What's missing today

- No way to trace one document's ingestion end-to-end by a single correlation id — `discovery_id` (`did`) never reaches `read_files()` or anything it calls; `run_id` never reaches the resolution funnel at all.
- No visibility into *why* two records did or didn't merge — which band a pair landed in, what its score was, whether it was auto-merged, sent to an LLM, queued for a human, or rejected.
- The human-review queue and attribute-conflict tracking — both already fully built (`StoreReviewSink`, `SurvivorshipPolicy`, existing `aryx_adjudication`/`aryx_attribute_conflict` tables, an existing workspace-level survivorship config API) — are wired to nothing. No amount of logging would reveal activity in these paths because they never run.

### Why this matters

- Operators debugging "why didn't these two records merge" have no trace to follow today.
- The adjudication queue UI/API (`api/adjudication_api.py`) already exists and is presumably exposed, but has nothing to show — it's a built feature with a disconnected write side.
- Attribute conflicts are silently discarded even though the system already computes and logs a warning about them.

## 3. Recommendation

Two-part change, landing together since both touch the same functions:

**Part A — Resolution funnel:** thread `run_id` through the funnel (`resolve_run → resolve → block → _block_embeddings → score_pair → _route_pair`) so every log line is correlatable to one run; add explicit per-pair, per-band logging including a previously-nonexistent reject branch; wire up the existing-but-unused `StoreReviewSink` and a `SurvivorshipPolicy` (default `most_complete`) so the review queue and conflict persistence actually activate.

**Part B — HTTP + discovery layer:** purely additive logging across `doc_discover_api.py` and the unlogged parts of `doc_discovery.py`, threading `discovery_id`/`job_id` down into every function that currently can't be correlated to a request.

## 4. Technical Direction

### Part A — Resolution funnel

**Signature changes** (all additive, trailing, optional or matching-default — verified against every call site in `src/` and `tests/`, zero breaking changes):

| Function | File | Change |
|---|---|---|
| `resolve_run()` | `src/aryx/resolve_entities.py:16` | + `workspace_id: int = 1` |
| `resolve()` | `src/aryx/resolution/run.py:111` | + `run_id: int \| None = None` |
| `block()` / `MultiKeyBlocker.block()` | `src/aryx/resolution/classical.py:23`, `blocking.py:83` | + `run_id: int \| None = None`, forwarded |
| `_block_embeddings()` | `src/aryx/resolution/run.py:31` | + `run_id: int \| None = None` |
| `score_pair()` | `src/aryx/resolution/classical.py:47` | + `run_id: int \| None = None` |
| `_route_pair()` | `src/aryx/resolution/run.py:56` | + `run_id`; return type `None` → `str` (band decision label) |

`run_id` (one per discover-run) is threaded as the fine-grained correlation key inside the funnel. `job_id` (one confirm-job, potentially spanning several runs) is deliberately *not* threaded past `resolve_run()`'s own existing completion log — it's a coarser id not needed on every per-pair line.

**Logging additions:** block-count summary after `block()` returns (currently absent); per-pair logging in `_route_pair()` covering all four bands — `auto_merge` (INFO), `adjudicate` (INFO, with LLM verdict), `review` (INFO when queued, INFO `dropped_no_sink` when no sink, WARNING + `review_dropped` if the queue write itself fails), and a newly-explicit `reject` branch (DEBUG, since it's the natural high-volume case and the four-band threshold structure is itself the right volume filter); a final run-level summary with counts for each band; embedding-call logging in `_ollama_embed()` matching the existing `_oci_embed()` debug style; a WARNING (replacing a silent `pass`) when an embedding batch fails.

**Review-queue wiring:** `StoreReviewSink` (`src/aryx/resolution/review_queue.py:31-44`) and `AdjudicationStore` already exist and already target the existing `aryx_adjudication` table (`migrations/0020_adjudication.sql`) — no new store or migration needed. Instantiated inside `resolve_run()` (not `orchestrate.py`, not lazily inside `resolve()`) so `resolve()` stays DB-free and unit-testable, and so `tests/test_scalability_fixes.py::TestOrchestratePairs` (which patches `resolve_run` wholesale) remains fully insulated. Wrapped in try/except with `review=None` fallback — a DB hiccup degrades gracefully rather than failing the run.

**Survivorship-policy wiring:** also built inside `resolve_run()`, reusing the **already-live** `aryx_workspace.survivorship` JSONB column and its `GET`/`PUT` API (`api/workspace_api.py:98-115`) — no new API surface. Default strategy is `most_complete` (not the dataclass's own `first_non_empty` default), chosen because `first_non_empty` is explicitly documented as input-order-dependent (non-deterministic, since landed-record read order isn't guaranteed), while `most_complete` is deterministic and already validated by an existing test (`test_golden_record_order_independent`). Workspaces with no configured policy get `most_complete`; workspaces that have configured one via the existing API get their own.

This is an explicit, accepted behavior change, not a side effect to hide: passing a non-`None` policy switches the golden-record merge from confidence-weighted voting to policy-based picking, which can change which attribute value wins on a conflict for *newly created* entities going forward (already-materialized entities are untouched).

### Part B — HTTP + discovery layer

Purely additive logging, no behavior change. Threads `discovery_id`/`job_id` as optional trailing params into `read_files()`, `_infer_type()`, `_consolidate_csv_names()`, `_xml_to_csvs()`, `_detect_fk_links()`, `_detect_fk_links_workspace()`, and `RecordsConnector` — all currently unable to log anything correlatable. Adds logging to every currently-silent branch: upload-size rejection, job creation, the 404-expired-discovery path, all three of `_xml_to_csvs`'s silent fallback-to-raw-XML branches, both of `_detect_fk_links`'s unlogged passes (an unconditional summary is added so a zero-links result is distinguishable from "never ran"), the zero-matching-mentions skip in `ingest_confirmed()`, and the `OntologyStore` lookup failure. `_xml_to_csvs`/`_detect_fk_links` are also called from a separate `/admin/ingest/file` endpoint — new params are optional so that endpoint is unaffected.

## 5. Scope Definition

### In scope
- `src/aryx/resolve_entities.py`, `src/aryx/resolution/run.py`, `classical.py`, `blocking.py`, `review_queue.py`, `survivorship.py`, `src/aryx/broker/__init__.py`
- `src/aryx/api/doc_discover_api.py`, `src/aryx/pipeline/doc_discovery.py`, `src/aryx/discoveries.py`, `src/aryx/connectors/records_source.py`
- New/extended tests in `tests/test_adjudication.py`, `test_blocking.py`, `test_resolution_funnel.py`, `test_survivorship.py`, `test_doc_discovery.py`

### Out of scope
- Any change to the pipeline stages below resolution that are already well logged (discover/land, relate, FK-link, project)
- Adding a `job_id` parameter to `run_pipeline()` itself — left as a `TODO` comment at its two call sites for a later pass, since nothing in this plan requires it
- New config flags to gate the review-queue/conflict-persistence activation — accepted as always-on per explicit decision (existing `ARYX_ER_REVIEW` threshold is the correct lever if queue volume needs tuning)
- Schema/migration changes — both `aryx_adjudication` and `aryx_attribute_conflict` already exist with the columns needed

## 6. Risks and Mitigations

### Risk: Review-queue/conflict-table row growth on repeated ingestion
Neither table has a uniqueness constraint; re-ingesting the same source data creates a fresh `run_id` and a fresh batch of rows each time.
**Mitigation:** This mirrors an already-existing re-ingestion-duplicates-entities behavior in the pipeline, not a new failure mode. Worth a release-note mention for workspaces with scheduled re-syncs; not a blocker.

### Risk: Review-band volume floods the adjudication queue
For noisy/near-duplicate-heavy datasets, the `[0.75, 0.90)` band could be a meaningful fraction of scored pairs.
**Mitigation:** The existing `ARYX_ER_REVIEW` threshold is the right lever to narrow the band if a specific workspace needs it — no new flag introduced.

### Risk: Attribute-value output changes for entities with conflicting attributes
Switching from confidence-weighted merge to `most_complete` can change which value survives.
**Mitigation:** Accepted and explicit — this is the direct, intended consequence of activating conflict persistence, verified to only affect entities that actually have conflicting attribute values (identical output otherwise).

### Risk: New DB connections per resolution run
`AdjudicationStore`/`make_workspace_store` open new connections inside `resolve_run()`.
**Mitigation:** Both wrapped in try/except with safe fallback; `make_workspace_store`'s connection is short-lived and closed immediately; confirm's parallel file-plan execution caps concurrency at `settings.ingest_workers` (default 3) — not a resource risk in practice.

## 7. Acceptance Criteria

- A single `discovery_id` and, separately, a single `run_id`, can be `grep`'d across the log stream to see every step of that document's read and resolve, in order.
- Every one of the four resolution bands produces a log line at the decision point, including reject (at DEBUG).
- A pair scoring in the review band produces a real row in `aryx_adjudication`; an entity with conflicting attribute values produces a real row in `aryx_attribute_conflict` — both verified by direct query, not just by log inspection.
- No existing test in the affected files fails; new tests cover the return-value change, the review-sink failure fallback, and the survivorship default.

## 8. Technical Notes for Engineering Handoff

- Resolution funnel entry point: `src/aryx/resolve_entities.py:16` (`resolve_run`) → `src/aryx/resolution/run.py:111` (`resolve`) → `run.py:56` (`_route_pair`, the core per-pair decision point).
- Already-built, currently-unused infrastructure being activated: `src/aryx/resolution/review_queue.py:31` (`StoreReviewSink`), `src/aryx/resolution/survivorship.py:32` (`SurvivorshipPolicy`), `src/aryx/workspaces.py` (`make_workspace_store`/`get_survivorship`).
- HTTP/discovery entry points: `src/aryx/api/doc_discover_api.py:81` (`/read`), `:106` (`/confirm`) → `src/aryx/pipeline/doc_discovery.py:466` (`read_files`), `:809` (`ingest_confirmed`).
- Logging convention already established in this codebase and followed throughout: `%`-style lazy formatting (never f-strings), correlation id (`did=%s`/`job=%s`/`run_id=%s`) as the first field wherever available, `step/total` fractional notation for loop progress. Central config: `src/aryx/logging_setup.py` (plain-text, not structured/JSON).

## 9. Final Summary

This is an extension of existing, already-well-established patterns in the codebase (the `%`-style job/run-scoped logging already used in `ingest_confirmed()`, the already-built review/survivorship infrastructure) rather than new architecture. The bulk of the work is mechanical logging additions; the two behavior-activating pieces (review queue, conflict persistence) are deliberately scoped to reuse existing tables, stores, and APIs so no migration or new API surface is introduced.
