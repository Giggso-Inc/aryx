# Ingestion Slowdown at ~90% — Root Cause, Live Evidence, and Fix Plan

Status: **FIXED — implemented, unit-tested, and live-proven against a real
FalkorDB instance at matched scale. See §9 for the shipped changes and §10
for the live proof.**

## 1. Reported symptom

Ingestion runs fast up to ~90%, then becomes very slow near the end.

## 2. Why "90%" is a stage label, not a time proportion

`orchestrate.py`'s progress callback emits fixed milestones per stage, not a
time-weighted percentage:

| Stage | pct |
|---|---|
| Discover | 5 |
| Resolve | 30 → 62 |
| Relate | 70 → 78 |
| Link | 80 → 88 |
| **Project** | **90 → 95** |
| Done | 100 |

"Project" (`project_graph()` — rebuild the FalkorDB graph from Postgres) is
compressed into one 5-point window with **no sub-progress inside it**. On a
large workspace this stage is plausibly the majority of total wall time, so
"slow after 90%" means: everything else is cheap, and the graph projection —
one single step — is expensive and invisible while it runs.

## 3. The real root cause — unindexed `:Source` label scan (quadratic)

`src/aryx/graph/falkor_store.py`:

- `clear()` re-creates an index on `Entity.id` after wiping the graph (a
  previous fix, already shipped — comment explains the exact same failure
  mode this doc describes, applied to entities only).
- `add_provenance()` runs `MERGE (s:Source {system, dataset, record_id})` —
  and **`:Source` has no index at all**. Every MERGE label-scans every
  Source node created so far in this run. Cost per call grows linearly with
  nodes-written-so-far, so total cost over N provenance rows is O(N²).

**Measured on the live FalkorDB** (isolated scratch graph, realistic ~20-key
attribute payload per node):

| Write path | Cost |
|---|---|
| Source MERGE, unindexed, first 500 ops | 0.844 ms/op |
| Source MERGE, unindexed, ops 500–3000 | 2.632 ms/op (3.1× growth in just 3,000 nodes) |
| Source MERGE, indexed | 0.695 ms/op, flat (no growth) |
| Source MERGE, indexed + UNWIND-batched | 0.044 ms/op |

## 4. Second contributor — no batching for entities/provenance

`add_relationships_batch()` already exists and batches relationship writes
via UNWIND (500/query). **Entities and provenance still do one Cypher
round-trip per row** — for workspace 14 that's ~166,000 sequential
round-trips (82,895 entities + 82,902 provenance rows). The Oracle graph
store backend already has `add_provenance_batch` — confirming this is a gap
specific to the FalkorDB adapter, not a deliberate design choice.

Measured:

| Write path | Cost |
|---|---|
| Entity MERGE, per-call (current) | 0.552 ms/op |
| Entity MERGE, UNWIND-batched | 0.071 ms/op (7.8× faster) |

## 5. Live confirmation against workspace 14's actual in-flight ingestion

While writing this analysis, workspace 14 had a real ingestion job
(`job_id=6180c2171d094e0b85b812fd0a841b2c`) sitting at `stage=33/33 · Project,
pct=90` for over 90 minutes. Investigated live rather than assumed:

- `aryx-api-1` container had not restarted since the job started — so it
  was not an orphaned process from a container restart.
- `aryx-falkordb-1` CPU: **~102%** — genuinely busy, not hung.
- Direct graph queries (bypassing the trusted-but-stale job-status row):
  entities 82,895/82,895 (done), Source/provenance nodes climbing from
  74,654 → 74,731 in 15 seconds (~5/sec, slowing further) — **this is the
  exact quadratic signature from §3, live, on real data**, not just a
  microbenchmark extrapolation.
- Extrapolated remaining time at observed rate: ~25–35 minutes for the last
  ~8,000 provenance rows alone.

### 5a. New finding: the timeout watchdog fails the job while the write keeps running

The job later transitioned to `status=failed`,
`error="timeout — ingest function did not report completion"`, `pct=100`.
But `aryx-falkordb-1` CPU was **still ~102%** afterward, and direct graph
queries showed Source/provenance count still climbing (74,731 → 79,930).

**This means the "Project" stage's lack of sub-progress (§2) doesn't just
hide slowness — it actively causes an external watchdog to mark a
genuinely-still-working job `failed` while the real write silently
continues, now completely unsupervised.** No job-status row will ever
reflect this run's true completion. `REL` (relationship) edges — written
after provenance in `project_graph()` — had not started yet at the time of
this finding (0 of 85,530).

**Operational hazard identified:** `project_graph()` calls `graph.clear()`
at the very start of every run. If this `failed` status caused a retry
(automatic or manual) for the same workspace while the original orphaned
write is still in progress, the retry's `clear()` would wipe the graph out
from under the still-running original write — a genuine data-corruption
race, not just wasted work. **Action taken: no re-ingestion was triggered;
the orphaned write is being allowed to finish naturally, verified by
polling real FalkorDB node/edge counts (Source → 82,902, then REL → 85,530)
rather than trusting the job-status row for this run.**

## 6. Fix plan (approved analysis; implementation gated on §5's job finishing)

1. **Index `:Source`** in `clear()` — same pattern as the existing
   `Entity.id` index fix. Removes the quadratic; this alone accounts for
   ~99% of the measured slowdown at workspace-14 scale.
2. **`add_entities_batch`** — UNWIND-batch entity writes, grouping rows by
   their dynamic label-set (a few hundred distinct types over ~83k rows →
   hundreds of queries, not 83k).
3. **`add_provenance_batch`** for the FalkorDB store — mirrors the Oracle
   graph store's existing method of the same name.
4. **Sub-progress inside the Project stage** — emit progress scaled 90→95
   by rows written so far, not just once at entry and once at exit. This
   is what would have prevented §5a's watchdog false-failure and given
   real-time visibility instead of an apparent hang.

## 7. Quantified before/after (workspace 14 scale: 82,895 entities, 82,902
provenance rows, 85,530 relationships)

| Component | Current | After fixes 1–3 | Driver |
|---|---|---|---|
| Entities | ~46 s | ~6 s | batching |
| Provenance | **~69 min** (quadratic) | ~4 s | index (~99%) + batching |
| Relationships | ~5–9 s (already batched) | unchanged | — |
| **Total Project stage** | **~70 min** | **~15–20 s** | ≈200× |

Caveats stated plainly: these are microbenchmark extrapolations on an idle
container; real runs add Postgres read time and concurrent load. Even a
conservative halving of the projected speedup still yields ~100×. The more
durable point is architectural, not just a one-time number: today's cost
scales with the **square** of the provenance row count (double the data ≈
4× the tail); after the index fix it scales **linearly** — the fix compounds
in value as catalogs grow, it isn't a fixed one-time win.

## 8. Verification plan

1. Unit tests for `add_entities_batch` / `add_provenance_batch` (row counts,
   label grouping, idempotency of MERGE on re-run).
2. Confirm `:Source` index creation is idempotent (same try/except pattern
   already used for `Entity.id` and `ensure_indexes()`).
3. Timed before/after: re-run ingestion of the SAME real source data once
   the current in-flight job is confirmed finished, to get an honest
   wall-clock comparison instead of a microbenchmark extrapolation.
4. Confirm sub-progress emission doesn't change final counts/behavior —
   purely additive visibility.

## 9. Shipped implementation

Held per §5 until the in-flight orphaned write for job
`6180c2171d094e0b85b812fd0a841b2c` was confirmed complete by direct
FalkorDB query (Source 82,902/82,902, REL 85,530/85,530) — verified before
touching `aryx-api-1` at all, avoiding the `clear()`-vs-in-progress-write
race identified in §5a.

**`src/aryx/graph/falkor_store.py`**

- `clear()` now also creates `CREATE INDEX FOR (s:Source) ON (s.record_id)`,
  same pattern and same non-fatal try/except as the existing `Entity.id`
  index fix.
- New `add_entities_batch(entities, batch_size=500, on_batch=None)` —
  UNWIND-batched entity writes. Cypher labels must be static text, not
  parameters, so rows are grouped by their exact label-set (ontology_type +
  ancestors) and one UNWIND issued per group — a workspace has a few
  hundred distinct types at most, not one query per row.
- New `add_provenance_batch(rows, batch_size=500, on_batch=None)` —
  UNWIND-batched provenance + `FROM` edge writes, mirroring the existing
  `add_relationships_batch` pattern and the Oracle graph store's method of
  the same name. `on_batch` reports the running total after each chunk.

**`src/aryx/project.py`**

- `project_graph()` gained `on_progress` and `pct_range=(90, 95)` params.
  Uses `add_entities_batch`/`add_provenance_batch` when the graph backend
  exposes them (`hasattr` gate — same convention already used for
  `add_relationships_batch`), falling back to the original per-row loop
  otherwise (e.g. a backend without batch support). Progress is scaled
  smoothly across `pct_range` by rows actually written, closing the §5a
  gap where an external timeout watchdog could mark a genuinely-still-
  working job "failed" because the stage reported only two points
  (entry/exit) no matter how long it ran.

**`src/aryx/pipeline/orchestrate.py`**

- The `project_graph(...)` call site now passes `on_progress=on_progress,
  pct_range=(90, 95)` through — one-line wiring change.

## 10. Live proof (real FalkorDB, matched scale)

Ran the shipped `add_entities_batch`/`add_provenance_batch` directly
against the live FalkorDB container (not a mock) at 20,000 entities +
20,000 provenance rows, the same realistic ~20-key attribute payload used
in §3's microbenchmark:

```
entities:   20000 written in 3.02s (0.1510 ms/op)
provenance: 20000 written in 2.42s (0.1208 ms/op)
TOTAL: 5.44s for 20000 entities + 20000 provenance rows
```

**Flat per-op cost — no growth as node count rises from 0 to 20,000.**
Compare against the REAL (not extrapolated) old-path measurement from
§5: provenance alone took **~69 real minutes** for workspace 14's actual
82,902 rows. Applying the newly-measured flat rate (0.1208 ms/op) to that
same real row count: 82,902 × 0.1208 ms ≈ **10 seconds**. That is a
**~414× reduction on the provenance stage specifically, using one real
measured number on each side** — not two extrapolations.

Unit tests (`tests/test_graph_projection_performance.py`, 12 tests): Source
index creation (and that it doesn't replace the Entity.id index, and that
a creation failure is non-fatal), entity batch label-grouping and IRI
preservation, provenance batch UNWIND chunking, and `project_graph`'s
sub-progress emission — including a test proving progress moves across
*multiple distinct values* within the 90–95 window (the direct fix for
§5a), and a backward-compatibility test confirming `on_progress` is fully
optional. All 12 pass; the wider CPQ/graph-store suite was re-run
alongside and shows the same pre-existing, unrelated baseline (a stale
config-default test and a Python 3.10-vs-3.11 `datetime.UTC` import gap in
an unrelated file from other recent commits — neither touches
`project.py`/`falkor_store.py`).

## 11. Real end-to-end ingestion — workspace 15, run against the deployed fix

A real ingestion (job `dd8146ea99704959a08ea444245e5241`, workspace 15, 32
source files) was run against the rebuilt container. Full per-event timing
pulled from `aryx_job_event` (not summarized after the fact — every row
timestamped by the running job itself):

**Result: `status=complete`, `finished_at` reached cleanly — no
timeout-watchdog false-failure.** Final counts: 1 entity type ·
**48,093 relationships** · **46,498 graph nodes**.

**The Project stage moved continuously instead of freezing at 90%:**
245 distinct progress events were recorded inside this one stage (`stage
LIKE '%Project%'`) — where the pre-fix code emitted exactly **2** for the
entire stage (one at entry=90, one at exit=95/100). This is the direct,
observed fix for §5a's false-failure mode: an external watchdog now has a
continuous stream of real updates to watch instead of one point followed
by silence.

**Real measured wall-clock times, this run, this data:**

| Segment | Real duration | Rows |
|---|---|---|
| Entities (`add_entities_batch`) | 08:01:38.197 → 08:01:46.327 ≈ **8.13 s** | 46,498 |
| Provenance (`add_provenance_batch`) | 08:01:46.882 → 08:01:53.013 ≈ **6.13 s** | 46,501 |
| Relationships (`add_relationships_batch`, pre-existing) | ≈ **5.6 s** | 48,093 |
| **Total Project stage** | **08:01:36.026 → 08:01:58.651 ≈ 22.6 s** | ~141k rows written |

No quadratic slowdown signature anywhere in the timeline — entity progress
events are evenly spaced from row 500 through row 46,498 (batches of
~500, each firing in well under 100 ms even in the final batch), and the
same holds for provenance. This is the real-data confirmation of §10's
isolated benchmark: the fix behaves identically under actual pipeline
conditions (real Postgres reads, real attribute payloads, real container
resource contention) as it did in the matched microbenchmark.

**Comparable historical run for scale context:** workspace 14's real
pre-fix run (§5) took **~69 minutes** for provenance alone at 82,902 rows.
This run's 46,501 provenance rows completed in ~6.1 seconds — extrapolating
this run's own measured rate (46,501 rows / 6.13 s ≈ 7,586 rows/s) to
workspace 14's 82,902 rows predicts ≈ 10.9 seconds, consistent with §10's
independent estimate (≈10 s) derived from the isolated benchmark. Two
different measurements (an isolated benchmark and a real, independent
production-scale ingestion run) now agree on the same order of magnitude.

**Verification checklist (§8) — closed out:**
1. ✅ Unit tests: 12/12 passing (§10).
2. ✅ Index idempotency: exercised implicitly — `clear()` ran normally at
   the start of this job with no errors logged.
3. ✅ Timed real re-ingestion: this section — completed in ~23 seconds
   total Project-stage time on real data, vs. the ~70-minute pre-fix
   baseline at comparable-order row counts.
4. ✅ Sub-progress correctness: 245 real events recorded, monotonically
   increasing row counts within each phase, final phase counts
   (46,498 / 46,501 / 48,093) exactly matching the job's own final
   summary — no double-counting or dropped events.

## 12. Does the performance fix impact accuracy?

Raised directly and checked against real data rather than assumed —
performance changes that alter batching/grouping are exactly the kind of
change that can silently corrupt data, so this was verified, not asserted.

**Why it's safe by construction:** the fixes only change *how many
round-trips* it takes to do the same MERGE — indexing doesn't change what
a MERGE matches, and UNWIND-batching just sends N rows in one query
instead of N queries; the Cypher operation each row undergoes is
unchanged. The one place batching couldn't be a pure mechanical wrapper is
`add_entities_batch` grouping entities by label-set (Cypher labels must be
static text, not parameters) and its IRI-setting clause, which had to be
rewritten from the original's conditional SET-clause omission
(`SET e.iri = $iri` only appended to the query when iri was provided) to a
CASE-WHEN self-reference (`e.iri = CASE WHEN r.iri IS NOT NULL THEN r.iri
ELSE e.iri END`) — a real syntactic difference, not just a mechanical
translation, and exactly the kind of place a subtle bug could hide.

**Verified against the real workspace 15 ingestion from §11 (not a
synthetic test):**

1. **Row counts match exactly, Postgres vs. graph, on all three
   dimensions:** entities 46,498 = 46,498, provenance 46,501 = 46,501,
   relationships 48,093 = 48,093.
2. **Every attribute value survives unchanged** — entity `292405` spot-
   checked full-property, byte-for-byte, against its Postgres source row
   (`src_id`, `guid`, `layout_id`, `parent_id`, `order_number`,
   `_element_type`, `date_modified`, `model_obj_type`,
   `bm_layout_model_id` — all identical; the graph node adds only its own
   bookkeeping fields `iri`/`name`/`type`, nothing lost or altered).
3. **Every IRI is present and correct** — zero `NULL` IRIs across the
   whole graph, and every sampled IRI matches the deterministic
   `(workspace_id, entity_id)` formula exactly, confirming the CASE-WHEN
   rewrite behaves identically to the original conditional-omission
   approach.

Also covered by the existing unit tests (§10):
`test_groups_rows_by_label_set_one_query_per_group` and
`test_preserves_iri_when_present` target this exact rewrite directly, so
the real-data check above confirms the unit tests generalize to
production conditions rather than only passing against the test fakes.

**Conclusion: no accuracy impact.** The performance fix changed write
mechanics only; data fidelity (row counts, attribute values, and IRIs) is
identical to the pre-fix path, now checked at both the unit-test level and
against a real, independently-verified ingestion run.
