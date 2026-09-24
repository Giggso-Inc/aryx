# Ingestion Pipeline: Parallel/Spark Migration Analysis

**Status:** Phase 1 ✅ done, Phase 2 ✅ done, Phase 3 ✅ done, Phase 4 ✅
done (§8) — worker count raised, a hidden progress-reporting bottleneck
found and fixed, candidate batching implemented, Resolve-stage embedding
prefetch parallelized, and graph projection's existing incremental write
path found, fixed (three separate correctness bugs, both Postgres and
Oracle), and wired into the confirm pipeline (`orchestrate.py` →
`project_auto`) — all live-verified against the real LLM/broker/Oracle
ADB. Phase 4 Part B — parallelizing the full-rebuild write path itself —
🟢 Oracle implemented and live-measured: the concurrency mechanism alone
gave no real win (entities 0.91x, a regression; relationships 1.07x,
negligible), which prompted re-investigating instead of stopping there —
found and fixed the real bottleneck: a 500-row `MERGE` batch hung 180+
seconds against the real ADB with zero conflicts possible, where the
equivalent plain `INSERT` completed in under a second. The full-rebuild
path now uses INSERT instead of MERGE (live-verified: 500 entities in
1.6s, 500 relationships in 0.8s, vs. MERGE's 180+s hang); the incremental
path is untouched and still uses MERGE. FalkorDB deliberately not
implemented (known unfixed connection-pooling gap F1, an unsynchronized
client-side schema cache, and a single-threaded server execution model
that likely caps the achievable win — see §8 Phase 4 Part B). Branch
`perf/ingest-parallel-2026-09-23` (holds all
phases), pushed, not yet PR'd.

**Date:** 2026-09-23
**Trigger:** Evaluating OCI AIDP (Spark clusters + Workflows) as a parallel-execution
target for large-volume ingestion, prompted by watching a real confirm job's
FK-detection stage run for 38+ minutes during live verification of a separate fix
(2026-09-22).

**Scope:** (1) recap of the prior scalability investigation relevant to
parallelization, (2) a new finding that prior investigation missed, (3) a full
current-state map of the confirm/ingest pipeline's stages and their concurrency
characteristics, (4) what a Spark/AIDP migration would actually require per stage,
and (5) a recommendation.

**Prior investigation:** [docs/raven/SCALABILITY_BOTTLENECKS.md](../raven/SCALABILITY_BOTTLENECKS.md)
(P1–P19, last updated 2026-07-28). This document extends it, not replaces it.

---

## 1. What the prior investigation (P1–P19) already found

Two findings from the July report are directly relevant to parallelization:

- **P4 — Single-threaded pipeline worker.** The whole confirm job runs inside a
  single FastAPI `BackgroundTask`, one job at a time per API process. Its own OCI
  fix path explicitly names **OCI Data Flow (managed Spark)** as the answer —
  "submit pipeline jobs as Spark applications, scale workers automatically, pay
  per use." Confirmed still true today (see §3 below) — no dispatcher/queue was
  added since.
- **P17 — Schema-FK LLM inference: sequential batches.** `_infer_schema_fk_links()`
  runs 5 independent LLM batches (grouping *entity types*, not individual column
  pairs) one after another — measured at ~8 minutes of a 41-minute job, with no
  cross-batch dependency. Identified as safely parallelizable via
  `ThreadPoolExecutor`, **not yet fixed**.

The July report's own measured baseline (30-file workspace, 12,244 entities,
60,144 relationships): **40m6s total**, dominated at the time by graph
projection (55%, since fixed). After P8–P12's fixes, the same-shaped job was
re-timed at **40m56s**, with the cost now spread across Discover/Resolve/Seed/
Relate (41%), schema-FK LLM inference (20%), and graph projection (18%).

**Nothing in that report covers dynamic (value-overlap) FK detection.** That's
the gap this document fills.

---

## 2. New finding: dynamic FK judging is the real dominant cost, and it's undocumented

The "FK Detection: Judging candidate foreign keys (N/M)…" stage watched live
during a separate live-verification session is **not** P17's schema-FK
mechanism. It's a different feature — value-overlap-based dynamic FK detection
(`src/aryx/pipeline/dynamic_fk/`) — added 2026-07-23, just before the July
report's last update, but never profiled by it.

**Live-measured, 2026-09-22, real job (`bd8750b9fad04a17bd5c772fdaac250c`), 32-file
XML-derived catalog ingest:**

| Metric | Value |
|---|---|
| Total candidates judged | 2,186 |
| Wall-clock time (this stage alone) | **38m44s** (12:15:48 → 12:54:32) |
| Concurrency | `ThreadPoolExecutor`, `ARYX_FK_DYNAMIC_JUDGE_WORKERS` default = 4 |
| Observed throughput | ~1.06s/candidate (aggregate) → ~4.2s per individual LLM call, consistent with 4-way concurrency actually in effect |
| Mechanism | One LLM call per candidate (`complete_json`, "cheap" tier) — a real network round-trip, not a DB query or pure comparison |

For scale: this single stage (38m44s) is **longer than the July report's entire
measured end-to-end pipeline run (40m6s)** for a comparably-sized workspace.
It's the largest identified cost in the current pipeline, full stop.

**Why the candidate count is so high:** `dynamic_fk.py`'s own docstring states
there is **no count cap** on candidates judged — `ARYX_FK_DYNAMIC_JUDGE_WORKERS`
bounds concurrency, never coverage. The pre-filter (`fk_value_overlap_threshold`,
default 0.05) is deliberately loose, and candidate count is
`O(plan_pairs × cols_a × cols_b)` plus prefix-transform variants. A single wide
XML/XLSX upload explodes into one CSV plan per element type/worksheet
(confirmed elsewhere in the pipeline for the same reason CPQ docs reference a
33-file batch sitting "queued" for 9+ minutes of dynamic-FK activity, and a
96-mention-type single-PDF incident) — so thousands of candidates arise from
*wide, multi-entity-type* uploads, not necessarily huge row counts.

**Mitigation already in place:** a FK-link cache + per-type-pair dirty/clean
skip (added 2026-08-01/02) avoids re-judging unchanged pairs on *repeat* runs.
The 38m44s figure above is representative of a **cold/first-time ingest** —
exactly the scenario relevant to "huge amount of data" initial loads.

---

## 3. Measured end-to-end timing — the same real job, full breakdown

Reconstructed from `aryx-api-1`'s own logs for job `bd8750b9fad04a17bd5c772fdaac250c`
(32-file XML-derived catalog ingest, same job as §2) — `started_at` →
`finished_at` per the job store, cross-referenced against per-file
`stage=X pct=Y` progress log lines and the `ingest_timing` structured log line.
Final result: **1 entity · 346,344 relationships · 38,591 graph nodes.**

| Stage | Start | End | Duration | % of total |
|---|---|---|---|---|
| Queue → job start (API overhead) | 12:14:06 | 12:14:20 | 14s | <1% |
| Column-name + script-data-flow FK detection (stages 3–4) | 12:14:20 | 12:14:40 | 20s | <1% |
| Workspace-level FK detection (stage 5) | 12:14:40 | ~12:14:56 | ~16s | <1% |
| Dynamic FK — candidate generation (stage 6a) | ~12:14:56 | 12:15:48 | 52.8s | 1% |
| **Dynamic FK — LLM judging, 2,186 candidates, 4 workers (stage 6b)** | 12:15:48 | 12:54:32 | **38m44s** | **29%** |
| Non-last plans, 31 files concurrent (stage 7, Discover/Resolve-skip/Seed only) | 12:55:39 | 13:14:53 | 19m14s | 15% |
| Last plan — Discover+Resolve+Seed (stage 7a) | 13:14:57 | 13:15:18 | 21s | <1% |
| Last plan — Relate, main pass (stage 7b) | 13:15:18 | 13:17:07 | 1m49s | 1% |
| Last plan — Schema-FK/fk_link/relate-isolated/dimension_link combined (stages 7c/7d) | 13:17:07 | 13:40:02 | 22m55s | 17% |
| **Last plan — Project graph (clear + full rebuild, stage 7e)** | 13:40:02 | 14:25:41 | **45m39s** | **35%** |
| Wrap-up + validation + cache invalidation (stages 8–9) | 14:25:41 | 14:26:03 | 22s | <1% |
| **Total** | 12:14:05 | 14:26:03 | **2h11m58s** | |

**The two dominant costs are dynamic-FK judging (29%) and graph projection
(35%) — together 64% of the run.** This changes the priority ranking from §4:
graph projection, not just dynamic-FK judging, is a top-tier cost for a
workspace producing this much relationship volume (346K relationships,
38.6K nodes) — and per §4/§5, it's also the stage with no clean parallelization
path today (full `clear()` + sequential rebuild against one graph store).

Also notable: the combined "Schema-FK/relate-isolated/dimension_link" window
(22m55s, 17%) bundles several of the stages discussed in §4 (P17's schema-FK
batches among them) — precise sub-stage boundaries within that window weren't
separately logged for this run, so the 22m55s is an upper bound on all of them
combined, not attributable to any single one without further instrumentation.

**Caveat on comparing this run to the July baseline:** this job's workspace
ended up with 346K relationships / 38.6K graph nodes — roughly 6x the July
report's reference workspace (60,144 relationships). The two aren't
directly comparable at the percentage level; the point of this table is the
*shape* of where time goes today (LLM-judging-bound early, graph-write-bound
late), not a claim that this exact ratio holds at every scale.

---

## 4. Full current pipeline — stage map, execution order

`_confirm_job()` → `ingest_confirmed()` (`src/aryx/pipeline/doc_discovery/doc_discovery.py`),
inside one FastAPI `BackgroundTask` (P4: still true, confirmed no change).

| # | Stage | File:function | Concurrency today | Touches |
|---|---|---|---|---|
| 1 | Mentions-by-type ingest | doc_discovery.py:194-218 | Sequential `for` loop (deliberate — see §4) | In-memory + downstream calls |
| 2 | Persist tabular sources | doc_discovery_persist.py | Sequential | DB writes |
| 3 | Column-name FK detection | doc_discovery_fk.py | Sequential, pure in-memory | Plan data only |
| 4 | Script data-flow FK links | doc_discovery_fk.py | Sequential, in-memory/regex | Plan data only |
| 5 | Workspace-level FK detection | doc_discovery_fk.py | Sequential | 1 `OntologyStore` read + in-memory |
| 6a | Dynamic FK — candidate generation | dynamic_fk.py `generate_candidate_pairs` | Sequential, in-memory | In-memory only |
| 6b | **Dynamic FK — LLM judging** | dynamic_fk.py `judge_candidates_with_llm` | **ThreadPoolExecutor, 4 workers** | LLM calls only, per-candidate |
| 7 | Non-last tabular plans | doc_discovery.py:400-417 | **ThreadPoolExecutor** (`ingest_workers`) | Discover→Resolve→Seed only (relate/project skipped) |
| 7a | Resolve (last plan) | resolution/run.py:228 | **Sequential** `for` over blocks — no ThreadPoolExecutor found | `EntityStore` reads/writes |
| 7b | Relate (last plan) | enrich_relate.py:154 | **ThreadPoolExecutor** | `EntityStore` + LLM per pair |
| 7c | Schema-FK inference (last plan, = P17) | enrich_schema_fk.py:80-87 | **Sequential**, unfixed | `EntityStore` + LLM per batch of types |
| 7d | fk_link / cooccurrence / dimension_link | fk_edges.py etc. | Sequential (relate_isolated is threaded) | In-memory / `EntityStore` |
| 7e | Project graph | project_full.py:78-140 | **Sequential, full clear()+rebuild** | Full-workspace `EntityStore` read + graph writes |
| 8 | Ingest validation | doc_discovery.py:427-441 | Best-effort | DB reads |
| 9 | CPQ cache invalidation | doc_discovery.py:458-510 | In-process | 1 DB marker write |

**Design constraint that shapes several "sequential" stages:** only the *last*
tabular plan runs relate/schema-FK/project — deliberately, so those stages see
the complete entity set before running. `project_graph` does a full
`clear()`-then-rebuild of the whole workspace graph, which is inherently
non-partitionable as currently written.

---

## 5. Parallelization candidates, ranked

**Already parallel (no work needed):**
- Dynamic FK judging (6b) — 4 workers today
- Non-last tabular plans (7) — threaded
- Relate / relate-isolated (7b) — threaded

**Confirmed safe to parallelize:**
1. **Dynamic FK judging (6b) — increase worker count / batch multiple candidates
   per LLM call.** This is the single highest-value target, **still pending
   (Phase 2, not started)**. Each candidate is fully independent (no shared
   mutable state beyond a local list appended after `future.result()` on the
   main thread) — confirmed embarrassingly parallel. At 4 workers today for
   38m44s, going to e.g. 16–20 workers could plausibly cut this stage by
   3–4x *before considering Spark at all*, subject to LLM provider rate
   limits (unverified — needs a controlled test).
2. **Schema-FK inference (7c, = P17)** — ✅ **Done, Phase 1** (`perf/ingest-
   parallel-phase1-2026-09-23`, commit `1ec72c08`). 5 independent batches,
   now run via `ThreadPoolExecutor` instead of sequentially.

**Sequential by design — would need real redesign, not just added concurrency:**
- **Resolve blocking (7a)** — no concurrency found; blocks are *likely*
  independent (blocking partitions records) but this was not verified in this
  pass — would need inspection of `resolution/blocking.py`/`classical.py`
  before claiming it's parallelizable.
- **Project graph (7e)** — `clear()` + full sequential rebuild against the
  *entire* workspace. This is the worst fit for partitioned/distributed
  execution as currently written: it's one external mutable target (the graph
  store), not a set of independent partitions.
- **Mentions-by-type loop (1) / last-plan-runs-after-others (7)** — sequential
  *on purpose*, because downstream stages need to see the complete entity set.
  Parallelizing these would require redesigning the "only the last item sees
  everything" contract, not just adding a thread pool.

---

## 6. What a Spark/AIDP migration would actually require

**The honest framing, repeated from earlier discussion in this session:** Spark
buys distributed *data-parallel* execution — splitting a DataFrame across
executors — not "the same Python function, just with more time." Stages 6b, 7b,
and 7c (LLM-call-per-independent-item) are the only stages that map cleanly onto
that model without a redesign, because their unit of work (one candidate/pair/
batch → one LLM call → one result) is already embarrassingly parallel; Spark
would just be a different way to fan that out than `ThreadPoolExecutor`, with
real added cost (cluster provisioning, job submission overhead — likely more
than the ThreadPoolExecutor fix's win for these specific stages, see §6).

**Per-stage migration requirement:**

| Stage | Spark-shaped today? | What would need to change |
|---|---|---|
| Dynamic FK judging (6b) | Yes — trivially | Wrap candidate list as a DataFrame/RDD, `mapPartitions` calling the LLM per row. Minimal logic change; real work is infra (cluster + catalog connection to reach whatever holds candidate data). |
| Schema-FK inference (7c) | Yes — trivially | Same shape, 5 rows instead of thousands — Spark overhead would likely exceed the win. |
| Relate / relate-isolated (7b) | Yes | Same pattern as above. |
| Resolve blocking (7a) | **Unverified** | Would need to confirm block-level independence first; if confirmed, becomes a `groupBy`+`mapPartitions` on blocking key. |
| Project graph (7e) | **No** | Would require replacing the `clear()`+full-rebuild contract with an incremental/partitioned write model — a genuine architecture change to `project_full.py`, not a backend swap. Graph writes (FalkorStore/OracleGraphStore) are also not natively Spark-partitionable targets. |
| Mentions-by-type / last-plan-sees-all (1, 7) | **No** | The "last item sees everything" contract is the opposite of Spark's partition-independence assumption; would need redesign to a two-phase model (parallel per-type extraction, then a single aggregation/merge stage) before any of this is Spark-shaped. |

**Infra requirements, regardless of which stages move:**
- AIDP Workspace + a USER Cluster (Spark compute — the DEFAULT/master-catalog
  cluster explicitly cannot run jobs)
- An External Catalog connection from AIDP to the Oracle ADB (data stays in
  ADB; AIDP doesn't need a copy) — same access pattern as the current
  `EntityStore`/`OntologyStore` connections, just from Spark executors instead
  of the API process
- A Workflow (scheduled or triggered) if this needs to run unattended, with
  parameters identifying which discovery/workspace to process
- Explicit cluster idle-timeout/stop-after-job configuration, since default
  idle timeout (2h) would otherwise bill for unused time between runs

---

## 7. Recommendation

**§3's measured data changes the priority, not just the confidence.** The two
real costs are dynamic-FK judging (38m44s, 29%) and graph projection (45m39s,
35%) — and they need different fixes, because they have different
parallelization characteristics:

**Dynamic FK judging — don't reach for AIDP/Spark first.** It's embarrassingly
parallel today and already uses a thread pool — the cheapest, fastest win is
raising `ARYX_FK_DYNAMIC_JUDGE_WORKERS` (and applying the same fix to P17's
schema-FK batches) and measuring the actual ceiling before concluding more
parallelism is needed than a bigger thread pool can provide. No new
infrastructure, no rewrite.

**Graph projection is the harder problem, and it's not a parallelism question
at all right now.** Per §5/§6, `project_graph` does a full `clear()` +
sequential rebuild against one graph store — there's no existing partition
boundary to hand to more threads *or* to Spark executors. Neither
`ThreadPoolExecutor` nor AIDP fixes 45m39s here without first redesigning the
write path itself (e.g., incremental/delta writes instead of clear+rebuild,
or partitioning the rebuild by entity type/batch in a way the graph store can
accept concurrently). That redesign is the actual prerequisite — the backend
(more threads vs. Spark) is a secondary decision that only matters once the
write path itself is partitionable.

**Where Spark/AIDP would genuinely earn its keep:** if per-candidate LLM
judging volume grows enough that a single API-process thread pool becomes the
bottleneck itself (CPU/memory/connection limits on one container, not just
"more threads would help"), or if you want this to run as a scheduled,
independently-scaled batch stage decoupled from the interactive confirm-job
path entirely. That's a real, defensible reason to adopt AIDP — but it applies
to the LLM-judging-shaped stages (6b/7b/7c) specifically, not "the whole
ingestion pipeline": project_graph and the last-plan-sees-all contract aren't
Spark-shaped without the redesign above, regardless of backend.

**Suggested next steps, in order:**
1. A controlled test — bump `ARYX_FK_DYNAMIC_JUDGE_WORKERS` from 4 to
   something like 16–20 on the existing thread-pool implementation, re-run
   the same 32-file ingest, and measure the actual new wall-clock time and
   whether LLM provider rate limits become the new ceiling. Cheap to try,
   answers whether Spark is solving a real remaining problem here or one a
   one-line config change already solves.
2. Separately investigate `project_graph`'s write path (`project_full.py`) to
   determine whether an incremental-write redesign is feasible before any
   parallelization decision for that stage — this wasn't in scope for this
   pass and needs its own investigation.

---

## 8. Phased Implementation Plan

Simple version — one phase per group of steps, easiest first.

### Phase 1 — Easy wins ✅ Done (2026-09-23)

**Branch:** `perf/ingest-parallel-phase1-2026-09-23` (commit `1ec72c08`), pushed
to `enterprise`, not yet PR'd.

**What actually shipped, and why it differs from the original plan below:**
investigating steps 1/2/4/9 before touching code changed the picture from
"four identical `ThreadPoolExecutor` wraps":

- **Step 9 (schema-FK batches, P17) — fixed as planned.** 5 independent LLM
  calls per confirm job, now run via `ThreadPoolExecutor`
  (`ARYX_FK_SCHEMA_BATCH_WORKERS`, default 4) instead of sequentially. This
  one really is I/O-bound (network calls to the LLM), so threading is the
  right tool.
- **Step 1 (column-name FK detection, `_detect_fk_links`) — fixed, but not
  with threads.** This function is pure CPU-bound Python (string/regex
  comparisons only — no LLM, no DB, no network I/O). Python's GIL means
  `ThreadPoolExecutor` provides **no speedup at all** for CPU-bound work —
  only one thread runs Python bytecode at a time regardless of thread count.
  The real problem was algorithmic: the function compared every plan
  against every other plan directly, O(N²) in file/plan count (negligible
  at 32 plans — confirmed <1% of a 2h12m real job in §3 — but growing with
  the *square* of file count, not linearly, as datasets get wider). Fixed
  by building a reverse index once (O(N)) instead of re-scanning every
  plan per plan, for Pass 1 and Pass 3 fully, and 2 of Pass 2's 3 rules
  (Rule B, substring containment, genuinely needs a different algorithm —
  documented as a known remaining gap, not silently left unmentioned). This
  function had **zero test coverage** before this fix — added 13
  characterization tests against the original implementation first
  (cross-checked via `git stash` against the true pre-rewrite code) before
  rewriting, so the rewrite is verified behavior-identical, not just
  "doesn't crash."
- **Step 2 (script data-flow FK) — investigated, left untouched.** It's
  already O(rows) within a single file — linear, not the quadratic problem
  being fixed here. There was nothing to fix.
- **Step 4 (dynamic-FK candidate generation)** — not addressed in this
  pass; same CPU-bound/GIL consideration as step 1 applies, and it's a
  smaller cost (52.8s per §3) than step 1 was. Candidate for a follow-up
  if profiling after Phase 2 shows it's still worth the effort.

**Verified:** 19 new tests (13 for `_detect_fk_links`, 6 for the schema-FK
concurrency change), all passing against both old and new behavior where
applicable; `raven-decision-map-gate` clean; no regressions in the broader
`doc_discovery`/`enrich` test suite (6 pre-existing unrelated failures
confirmed via clean-baseline comparison, not caused by this work).

**Risk:** Low — every behavior-changing edit was characterization-tested
against the true original first.

---

<details>
<summary>Original Phase 1 plan (superseded by the "what actually shipped" section above — kept for reference)</summary>

**What:** Steps 1, 2, 4, 9 — column-name FK check, script data-flow FK check,
dynamic-FK candidate generation, schema-FK batches (P17).

**Why easy:** All four are plain Python loops over independent items — no LLM
accuracy risk, no shared state, no database write-ordering to worry about.
Same pattern (`ThreadPoolExecutor`) already used elsewhere in this codebase
(e.g. dynamic-FK judging itself, `_relate`).

**Work:** Wrap each loop in a `ThreadPoolExecutor`, same shape as the existing
dynamic-FK judging code. No LLM prompt changes, no schema changes.

**Risk:** Low. Results should be identical, just faster.

**Expected win:** Small on their own (these steps are currently <1% of total
time each per §3) — but they're free wins while Phase 2 is being worked on,
and P17 (step 9) has been sitting identified-but-unfixed since July.

**Effort:** Low — a few hours each, four independent small changes.

*(This plan assumed all four steps were I/O-shaped like the dynamic-FK
judging stage. Steps 1/2/4 turned out to be CPU-bound, where threading is
ineffective — see the corrected section above.)*

</details>

---

### Phase 2 — Step 5: Dynamic FK judging (biggest current cost, easiest big win)

**Status:** ✅ Done (2026-09-23). Worker count raised, a hidden
progress-reporting bottleneck found and fixed, and candidate batching
implemented — all live-verified against the real LLM (small, targeted
tests, not full 32-file/2186-candidate re-runs, per direction to keep
verification cheap once the mechanism is confirmed working).

**What:** The LLM judging loop that's currently 29% of total pipeline time
(38m44s in the measured run).

**Step 1 result — raised `ARYX_FK_DYNAMIC_JUDGE_WORKERS` 4 → 16, live-tested
on the same real job:**

| Metric | 4 workers (baseline) | 16 workers |
|---|---|---|
| Total LLM-judging time (log timestamps, first→last verdict) | 38m44s (2324s) | **11m47s (707s)** |
| Per-candidate | 1.06s | 0.32s |
| Speedup | — | **3.29x** |

The LLM judging itself scaled almost exactly as expected (theoretical max
4x from a 4x worker increase). No rate limiting or errors from the LLM
provider at 16 workers.

**But that speedup didn't reach the job's actual completion time — a second,
previously-hidden bottleneck was exposed and had to be fixed too.** The
per-candidate progress callback (`_dynamic_fk_progress` →
`jobs.update_stage()`) does **two DB round-trips per call** (an `UPDATE` +
an `INSERT` into a job-events table), called once per candidate — 2186
sequential round-trips to cloud Oracle ADB, live-measured at ~1.09s/call.
At the original 4-worker default this was invisible, hidden inside LLM
latency that was already slower than the write. Once workers dropped LLM
latency to 0.32s/candidate, the ~1.09s/write became the new dominant cost
— live-confirmed via a stalled progress counter (still crawling forward 5+
minutes after all 2186 LLM verdicts had already logged). Extrapolated, the
unthrottled write alone would cost ~2186 × 1.09s ≈ 40 minutes — erasing the
entire worker-count win.

**Fix applied:** throttled `_dynamic_fk_progress` to report at most once
per `ARYX_FK_DYNAMIC_PROGRESS_REPORT_MIN_INTERVAL_S` (default 2.0s)
wall-clock time, always reporting the first call immediately (so the UI
shows the stage starting without delay) and the last call unconditionally
(so the stage always ends at an accurate 100%, not a stale intermediate
count). This is a real behavior change to existing, tested code — added
new tests for the throttling behavior itself and fixed one existing test
whose rapid-fire synchronous calls would otherwise have been (correctly)
throttled down to fewer `update_stage` calls than it asserted.

**Step 2 result — worker count + throttle fix together, re-verified live:**
progress reporting kept pace with actual LLM completion in real time (no
lag), confirmed via ~0.32s/candidate progress cadence matching the
16-worker judging rate exactly, across 1,313+ candidates before the
verification job was stopped (no need to run it to full completion once
the mechanism was confirmed — see the small-test note below).

**Step 3 — candidate batching, implemented and live-tested:**
`ARYX_FK_DYNAMIC_JUDGE_BATCH_SIZE` (default 5) groups N candidates into one
LLM call instead of one call per candidate. Verified with small, targeted
live tests against the real LLM (5-8 synthetic candidates, not the full
dataset):

- 5 candidates, batch size 5 → 1 LLM call, correct verdicts on all 5
  (3 genuinely-linked pairs found, 2 genuinely-unlinked pairs rejected).
- 8 candidates, batch size 5 → 2 LLM calls (5 + 3), correct verdicts on
  all 8.

**Two real bugs found and fixed via this live testing — neither was
catchable by mocked unit tests, since both are about how the real LLM
responds, not the parsing logic in isolation:**
1. The model returned verdicts keyed `"pair_index"` instead of the
   schema's required `"index"` — silently discarding every verdict in the
   batch (judgments themselves were correct, only the key name drifted).
   Fixed by accepting common index-key aliases, with a positional fallback
   when the response has exactly one verdict per candidate but no
   recognizable index key at all.
2. The model omitted the `reason` field entirely for batched verdicts,
   even though the original per-candidate version reliably included it —
   undermining this stage's whole "why is this pair linked" auditability.
   Fixed by making the system prompt explicitly require a reason on every
   verdict, not just marking it required in the JSON schema (which alone
   wasn't enough to reliably elicit it). Confirmed fixed: subsequent test
   runs returned meaningful reasons for every verdict.

**Failure semantics changed, by design:** a failed LLM call now costs a
whole batch's verdicts (fail-open as not-linked, logged) instead of one
candidate's — a real trade-off of fewer/larger calls, not a bug.
`ARYX_FK_DYNAMIC_JUDGE_BATCH_SIZE=1` recovers the exact original
one-call-per-candidate behavior if this trade-off is ever undesirable for
a given deployment.

**Risk:** Low for the worker-count change and throttle fix (no accuracy
impact — reporting/concurrency only). Batching's accuracy risk was real
and specifically why small live tests (not just mocks) were required
before trusting it — both bugs found were response-format issues, not
judgment-quality issues; the actual link/no-link decisions were correct
in every test run.

**Effort:** Low for worker count + throttle (one config value, one
throttle wrapper). Medium for batching (schema/prompt redesign, index-
mapping robustness, two rounds of live-test-driven fixes) — matching the
Medium estimate in the original plan.

---

### Phase 3 — Step 7: Resolve stage (needs investigation before any change)

**Status:** ✅ Done (2026-09-23). Investigated first, per plan — found the
block loop itself is NOT safely parallelizable, but the embedding fetch
inside it is. Parallelized only that, live-verified against the real
broker.

**What:** The record-matching stage (`resolution/run.py`) — a sequential
loop over "blocks" (groups of similar records) that scores pairs, routes
them (auto-merge / LLM-adjudicate / human-review / reject), and mutates a
shared `UnionFind` clustering structure.

**Step 1 — investigation result: blocks are NOT independent, but embedding
fetch is.**
- `MultiKeyBlocker.block()` deliberately places each record into up to 3
  *overlapping* blocks (prefix / token-set / Soundex keys) — not a disjoint
  partition. The block loop mutates a single shared `UnionFind`
  (unsynchronized plain dict, path-compression on `find()`), plus shared
  `pair_scores`/`band_counts` dicts, across all blocks. Naively running the
  block loop itself on a `ThreadPoolExecutor` would race on all three.
- Inside each block, though, `_block_embeddings()` (the per-block Ollama
  embedding call) and `score_pair()` are pure, side-effect-free functions —
  no shared state, safe to run concurrently across blocks.
- A small 96-record/61-block synthetic live test against the real broker
  (with timing instrumentation, not the full pipeline) measured where
  Resolve's time actually goes: **embedding 22.66s of 22.97s total
  (98.7%)**, scoring 0.29s, routing 0.00s — decisively confirming embedding
  is the only cost worth parallelizing, and that leaving the routing loop
  sequential loses almost nothing.

**Step 2 — fix applied:** added `ARYX_ER_EMBED_WORKERS` (default 8).
`resolve()` now prefetches every multi-member block's embeddings
concurrently via `ThreadPoolExecutor`/`as_completed` **before** the main
block loop runs, into an `embeddings_by_block` dict; the loop itself
(scoring, routing, `UnionFind`/`pair_scores`/`band_counts` mutation) is
completely unchanged and still fully sequential.

**Step 3 — verification.** Existing test suite
(`test_resolution_logging.py`, `test_exact_id_resolution.py`,
`test_adjudication.py`, `test_chunked_resolution.py`,
`test_partition_pair_scores.py`, `test_resolve_run_wiring.py`) updated to
set `er_embed_workers` on the two settings mocks that exercise `resolve()`
end-to-end — all green (2 unrelated pre-existing failures in
`test_adjudication.py` confirmed via `git stash` to fail identically on
the pre-Phase-3 code, not caused by this change). A separate small live
test against the real broker ran `resolve()` twice on the same 12-record/
4-cluster dataset — once with `er_embed_workers=1`, once with `=8` — and
asserted the captured cluster membership was byte-identical between the
two runs, confirming the parallel prefetch doesn't change matching
results.

**Risk:** Low, as executed — the investigation is exactly what kept this
low: only the pure, side-effect-free embedding call was parallelized, and
the identical-output live test is direct evidence the change is safe.

**Expected win:** Roughly proportional to `er_embed_workers` on any run
with multiple multi-member blocks needing embeddings, up to network/Ollama
throughput limits — this stage's share of total time wasn't isolated in
§3's timing breakdown for the original real job (folded into the "21s" for
Discover+Resolve+Seed on the last plan, so small there), but the 96-record
synthetic test showed embedding dominates Resolve's cost whenever blocks
are non-trivial, so the win scales with dataset size and duplicate
density, not with this particular job.

**Effort:** Medium, as estimated — investigation (measuring where Resolve's
time goes, confirming block independence doesn't hold) was the main cost;
the actual code change was small once the safe boundary was identified.

---

### Phase 4 — Step 10: Graph projection (biggest cost, hardest fix)

**Status:** ✅ Done (2026-09-23) — investigated, found the redesign this
plan called for **already exists** but was unused by the confirm
pipeline, found + fixed the correctness bug blocking it from being safely
wired in, found + fixed a second, independent live-only Oracle bind bug
while wiring it in, and wired `project_auto` into `orchestrate.py`. All
live-verified end-to-end against the real Oracle ADB: full rebuild on
first run, correct fall-through to incremental on the second, with the
relationship-only-change fix (Step 2/3 below) proven through the full
wiring, not just direct `ProjectionStore` calls.

**What:** The graph-write stage — 35% of total time (45m39s), the single
largest cost measured. `orchestrate.py`'s confirm pipeline always calls
`project_graph()`, which does `clear()` then rebuilds the entire workspace
graph from scratch, every run.

**Step 1 — investigation result: the incremental write model this plan
called for already exists, just isn't wired to confirm.**
- `project_incremental.py` (dirty-set update, G8) and `project_auto()`
  (`src/aryx/project/__init__.py` — picks incremental vs. full rebuild
  based on watermark + dirty-ratio) already exist, are already tested, and
  are already used in production — but only by `data_api.py`'s
  `_rebuild_graph_projection` (an admin rebuild endpoint), never by
  `orchestrate.py`'s confirm pipeline, which hardcodes `project_graph()`
  directly and never even constructs a `ProjectionStore`. So this is not
  "design + build a redesign" (the High-risk/High-effort framing this plan
  originally had) — it's "wire an existing path in safely."

**Step 2 — investigation found a real correctness bug in that existing
path.** The dirty set is computed purely from `aryx_entity.updated_at`
(`WHERE updated_at >= watermark`) vs. a watermark — no graph diffing.
Checked every write path to `aryx_entity`: the 1 INSERT and all 4 UPDATE
queries correctly set `updated_at`. But `insert_relationship.sql` — the
query the `dimension_link` stage uses to create new entity-to-entity
relationships — does **not** touch either endpoint's `updated_at`.
`project_incremental`'s relationship fetch
(`relationships_for(dirty_ids)`) only pulls edges touching already-dirty
entity ids. Net effect: a new relationship created between two entities
that were **both** already resolved in an earlier run — exactly what
`dimension_link` does routinely — was silently dropped by an incremental
projection run. No error, no log, just a missing edge. Confirmed as a
real, pre-existing bug via a characterization test (fails against the
original code, passes after the fix) and a live reproduction against the
real Oracle ADB.

**Step 3 — fix applied, both backends.** Added `aryx_relationship.updated_at`
(migration `0045_relationship_dirty_tracking.sql`, Postgres and Oracle
variants) and a new query, `select_dirty_relationship_entity_ids.sql`,
returning entity ids touched by a relationship change since the watermark.
`project_incremental()` now unions those ids with the attribute-dirty ids
before calling `relationships_for()`, so a relationship-only change is
picked up without needing to touch either entity's own `updated_at` (which
would have incorrectly implied the entity's attributes changed too).
Entity nodes and provenance writes are unaffected — only the relationship
fetch scope widened.

**Step 3b — Oracle-specific fix, live-verified.** While investigating,
found `select_tombstones.sql` (used by both `project_incremental` and
`project_auto`'s dirty-ratio check) has no Oracle override and uses
Postgres's `EXCEPT`, which is not valid Oracle syntax (Oracle needs
`MINUS`) — a second, independent pre-existing bug that would have broken
the entire incremental path on Oracle regardless of the relationship fix
above. `select_provenance_for_entities.sql` and
`select_relationships_for_entities.sql` already had correct
JSON_TABLE-based Oracle overrides (found only after listing the
`queries/oracle/` directory directly — an earlier keyword-grep pass missed
them and wrongly suggested they were broken too; corrected before making
any change there). Added the missing `select_tombstones.sql` Oracle
override; the new `select_dirty_relationship_entity_ids.sql` needs no
override (plain `%s` + `UNION`, no `EXCEPT`/`ANY()`, auto-translates via
`oracle_sql_translate.py`) — confirmed by running the real translator
against it. Live-verified end-to-end against the real Oracle ADB
(currently the active test environment): applied the new migration,
confirmed the `updated_at` column and index exist, inserted a real
relationship between two pre-existing entities, and confirmed
`dirty_relationship_entity_ids()` + `relationships_for()` +
`tombstones()` (the fixed `MINUS` query) all execute correctly and return
the right rows.

**Step 4 — a second, independent live-only bug found while wiring in.**
Live-testing the full `project_auto` path against real Oracle ADB (not
just direct `ProjectionStore` calls) surfaced a third pre-existing bug:
`advance_watermark()`'s Oracle override (`upsert_projection_state.sql`)
references its one bind param (`:1`) **twice** — once in the `MERGE ...
USING DUAL ON` clause, once in the `INSERT VALUES` — and oracledb's
thin-mode driver requires one positional value per *occurrence* of a
numbered placeholder when params are passed as a tuple, not one per
distinct name (`DPY-4009: 2 positional bind values are required but 1
were provided`). Every full-rebuild run calls `advance_watermark()`, so
this would have broken on Oracle the moment `project_auto` actually ran —
invisible to any mock-based test, since it depends on the real driver's
bind-counting behavior, not on parsing logic. Fixed by switching the bind
to a named param (`:workspace_id`) passed as a dict — oracledb correctly
dedupes a named bind referenced multiple times, unlike a positional one.
Live-verified: full-rebuild → incremental → relationship correctly
picked up, all through `project_auto`, against the real ADB.

**Step 5 — wired in.** `orchestrate.py` now constructs a `ProjectionStore`
and calls `project_auto()` instead of `project_graph()` directly.
`project_auto()` gained `on_progress`/`pct_range` passthrough (only
`project_graph`'s branch has real per-row scaled progress;
`project_incremental` has no equivalent internal granularity, so that
branch reports once at the window's start and once at its end — a
deliberate, documented trade-off, not an oversight: unlike the original
full-rebuild timeout-watchdog problem this docstring references, an
incremental run only touches what's dirty since the last watermark, so it
is expected to be fast enough that start/end-only reporting is fine).
Added direct test coverage for `project_auto`'s mode-picking logic itself
(previously untested — only its two branches were), which was a real gap
flagged during the original investigation.

**Risk:** Was High per the original plan's framing (a from-scratch
redesign); the actual work landed Low-Medium — three additive/corrective
fixes (schema column, bind-style, pipeline wiring), each backed by a
characterization test proving the bug and a fix test proving the
resolution, all live-verified against the real Oracle ADB rather than
trusted from mocks alone.

**Expected win:** Proportional to how much of the graph is actually dirty
on a given confirm run — large for routine "add a few more files"
confirms on an established workspace (dirty ratio well under the 30%
`ARYX_PROJECT_DIRTY_MAX` threshold), no win (correctly falls back to full
rebuild) for a workspace's first large confirm or any run touching most
of the graph. Not yet measured against a real multi-file confirm job —
the live verification here used small, targeted scenarios (2-entity,
single-relationship), matching the "keep tests small" direction rather
than re-running the full 32-file job.

**Effort:** Lower than originally scoped — the hard part (the redesign)
already existed; effort went into finding and fixing three correctness
gaps (two DB-portability bugs, one relationship-staleness bug) that were
blocking safe use, not into building new write-model architecture.

---

### Phase 4 Part B — Scoping: parallelizing the full-rebuild write path itself

**Status:** 🟢 Oracle implemented (2026-09-24); FalkorDB deliberately not
implemented, by explicit direction, given the risks below. This is the
case Part A doesn't help: a workspace's first-ever confirm, or any run
whose dirty ratio exceeds `ARYX_PROJECT_DIRTY_MAX` (30%) — `project_auto`
correctly falls back to `project_graph()`'s full `clear()` + rebuild,
which Part A left untouched. The full-rebuild comparison run against the
pre-Phase-1-4 baseline (a fresh workspace's first confirm, by
construction) hit exactly this case for its Project stage, prompting this
scoping — see the pre-PR verification section below for that run's
numbers.

**What would be parallelized:** `project_graph()`'s three write stages
(entities → provenance → relationships) already batch into chunks
(UNWIND for FalkorDB, `executemany` for Oracle) but process every chunk
*sequentially* through one connection/client. The candidate: run
independent chunks concurrently via `ThreadPoolExecutor`, the same
pattern already proven safe in Phases 1–3. Cross-stage order must stay
sequential (provenance/relationship edges reference entity vertices that
must already exist), but within the entities-write stage, and within the
relationships-write stage, chunks target disjoint node/edge sets and are
prima facie safe to run concurrently — *if* the underlying client/backend
actually supports it.

**Oracle backend (`OracleGraphStore`) — implemented.**
- Already uses `self._pool = get_oracle_pool(dsn)`, a real connection
  pool — the same pattern Phases 1–3 already proved safe for concurrent
  access (`ProjectionStore`, schema-FK batches, embedding prefetch).
  `add_entities_batch`/`add_provenance_batch`/`add_relationships_batch`
  currently open **one** connection for the whole batch and iterate
  chunks sequentially inside it — switching to one connection per chunk,
  submitted via `ThreadPoolExecutor`, is a small, low-risk change
  structurally.
- `add_provenance_batch` has an internal read-after-write dependency
  (merge sources → `SELECT` their ids back → merge provenance links using
  those ids) that must stay sequential *within* that stage, same as
  today — only the entities and relationships stages are candidates for
  chunk-level concurrency as-is.
- Oracle ADB genuinely executes concurrent sessions in parallel (separate
  server processes/threads per session) — unlike FalkorDB below, there is
  a real mechanical reason to expect a wall-clock win here, not just
  theoretical.
- This is also the graph backend actually in use in the currently active
  `docker-compose-oci.yml` stack (`ARYX_GRAPH_BACKEND=oci_graph` →
  `OracleGraphStore`/PGX — that compose file doesn't run FalkorDB at all,
  per its own comment: *"falkordb → Oracle Graph / PGX"*), making this the
  higher-priority half of this scoping for the environment actually being
  tested against.

**Implementation.** Added `oracle_graph_batch_workers` (default 4,
`config_graph.py`). `_OracleGraphBatchMixin` gained a shared
`_write_chunks(chunks, query_name, on_batch)` helper used by both
`add_entities_batch` and `add_relationships_batch`: with 1 chunk or
`oracle_graph_batch_workers <= 1` it reproduces the exact original
sequential behavior (one connection, chunks in submission order) —
otherwise each chunk is submitted to a `ThreadPoolExecutor`, each
acquiring its **own** connection from the pool (never sharing one across
threads, per the risk this scoping identified for FalkorDB — Oracle's
pool already makes this safe). `add_provenance_batch` is unchanged and
stays sequential within one connection, per the read-after-write
dependency noted above. `on_batch` now fires in completion order, not
submission order — callers must treat it as a running total, not a
positional sequence (both current callers, `project_full.py`'s
`_scaled()`, already only care about the total).

Tests: existing chunk-size tests updated to assert `sorted(chunk_sizes)`
instead of exact order (order is no longer guaranteed once concurrency is
default-on — confirmed this wasn't just incidental by reading
`ThreadPoolExecutor`/`as_completed`'s actual ordering contract, not
assumed). New `TestGraphStoreBatchConcurrency` class: chunks use distinct
connections under concurrency, `oracle_graph_batch_workers=1` reproduces
the original single-connection sequential path exactly (regression
guard), and `on_batch`'s running total is correct and monotonically
increasing regardless of completion order. All stable across 10 repeated
runs (checked for flakiness given the real threading involved, not just
run once).

**Live verification, real numbers — mixed result.** Ran a direct
sequential-vs-parallel A/B against the real Oracle ADB using workspace
783's already-resolved data from the full-rebuild comparison run above
(25,981 entities; a 25,000-row relationship subset, not the full 364K, to
keep the sequential half of the test bounded):

| Write | Sequential (workers=1) | Parallel (workers=4) | Result |
|---|---|---|---|
| Entities (25,981 rows) | 68.0s | 74.7s | **0.91x — regression** |
| Relationships (25,000-row subset) | 25.7s | 24.0s | 1.07x — negligible |

Both runs produced identical row counts in both cases (25,981 vertices;
24,994 edges) — correctness holds, concurrency doesn't corrupt or drop
rows. But the performance case this scoping built on grounds
("Oracle ADB genuinely executes concurrent sessions in parallel") did not
hold up under measurement on this specific ADB tier: entities got
*slower* under concurrency, and relationships saw essentially no change.
Most likely explanation, not independently confirmed: this ADB tier's
session/CPU capacity is already saturated by one connection's throughput,
so additional concurrent connections add thread/connection overhead
without unlocking real additional parallel execution — the theoretical
mechanism (Oracle can run concurrent sessions) doesn't guarantee a
*this instance* has spare capacity for a second one to use productively.

**Decision:** kept `oracle_graph_batch_workers` defaulting to 4 (not
dropped to 1) despite the mixed result — one measurement on one ADB tier
wasn't treated as sufficient grounds to disable the mechanism outright,
since a larger-OCPU production tier could plausibly have the spare
capacity this dev-tier instance doesn't. `ARYX_ORACLE_GRAPH_BATCH_WORKERS=1`
opts out. Anyone relying on this for a real performance win should
re-measure on their actual target ADB tier first, the same live A/B shape
used here, rather than trust the default's presence as evidence it helps.

**Follow-up finding — MERGE itself, not concurrency, was the real
bottleneck.** The "no real win" result above prompted re-investigating the
original assumption (client-side concurrency helps) instead of just
accepting it. Live-testing in isolation found the actual cause: a 500-row
`MERGE ... executemany()` batch **hung for 180+ seconds** against the
real Oracle ADB — confirmed on a completely fresh, never-touched workspace
(so no lock contention was possible) via a fine-grained, step-by-step
diagnostic that isolated the hang to the `executemany()` call itself. The
equivalent 500-row plain `INSERT ... executemany()` batch completed in
well under a second, every time, at multiple row counts. This explains
the earlier concurrency result: if MERGE's per-row existence-check is
this expensive, no amount of client-side parallelism can fix it — the
work itself needs to shrink.

**Fix, implemented and live-verified:** `project_graph()`'s full-rebuild
path (the only place this applies — it always calls `clear()` first, so
no existing rows can ever conflict, unlike the incremental path) now
writes via plain `INSERT` instead of `MERGE`. New Oracle queries
`insert_graph_vertex.sql`/`insert_graph_edge.sql`; `add_entities_batch`/
`add_relationships_batch` gained a `full_rebuild: bool = False` parameter
selecting the query, defaulting to the original MERGE behavior so
`project_incremental()` (which never calls `clear()` and may legitimately
need to update existing rows) is unaffected. `add_relationships_batch`
also deduplicates by `(workspace_id, source, target, name)` when
`full_rebuild=True` — the RDB's `aryx_relationship` table has no
uniqueness constraint on that triple, and unlike MERGE (which silently
absorbs an accidental duplicate as a no-op re-match), a plain INSERT
would raise `ORA-00001` on one. `FalkorStore`'s equivalent methods accept
(and ignore) the same parameter for call-site parity — FalkorDB's Cypher
`MERGE` has no evidence of the same pathology.

Live-verified end-to-end with the real `OracleGraphStore` methods (not
raw SQL) on a fresh workspace: 500 entities in 1.60s and 500
relationships in 0.80s via `full_rebuild=True` — versus MERGE's 180+
second hang at the same scale, which never completed. The incremental
(`full_rebuild=False`, MERGE) path was re-checked too and still works
correctly for a small update. This is the change that actually closes
most of the gap Phase 4 Part B originally set out to close — Part A only
helps incremental confirms, and the concurrency-only version of Part B
measured no real win, but avoiding MERGE's per-row cost entirely on the
full-rebuild path is a large, confirmed, mechanism-understood win.

**FalkorDB backend (`FalkorStore`) — real, documented risks; smaller
expected win.**
- `FalkorStore.__init__` constructs a single `FalkorDB` client (wrapping
  one `redis.Redis` client) per instance — no connection-pooling layer of
  its own. This is not a new observation: a prior investigation
  (`docs/graph/FALKORDB_QUERY_EXHAUSTION_F3_F4_FIX_2026_08_14.md`) already
  flagged this exact gap as **F1 — "No FalkorDB connection pooling — a
  fresh `FalkorDB(...)` client per adapter instance" — High severity, not
  fixed**. Any parallelization work here should fix/coordinate with F1
  rather than duplicate it.
- Read the FalkorDB Python client's source directly (`falkordb.Graph._query`):
  each `Graph` object caches the server's label/property/relationship-type
  ID mappings in `self.schema` (`GraphSchema`), refreshed via
  `self.schema.refresh(version)` on a `SchemaVersionMismatchException`.
  `GraphSchema.refresh()`/`.clear()` mutate plain, **unsynchronized**
  Python lists/ints — no lock. A full rebuild of a large workspace
  introduces many new labels and properties; if multiple threads share
  one `Graph` object and concurrently trigger a schema refresh, this is a
  real race on mutable client-side cache state, confirmed by reading the
  library source, not assumed. The safe fix is one `FalkorStore`/`Graph`
  instance per worker thread (cheap to construct — it only wraps a redis
  client), never sharing one across threads, mirroring how Postgres/Oracle
  pooling already works in this codebase.
- Bigger caveat: FalkorDB is a Redis module, and Redis's command-execution
  model is single-threaded per shard — the server processes one
  `GRAPH.QUERY` at a time regardless of how many client connections send
  concurrent requests. Client-side concurrency here would overlap network
  round-trip latency, not actual server-side execution time, which is a
  much smaller theoretical win than Oracle's genuinely parallel session
  execution. This needs to be measured, not assumed, before investing
  effort — the docstring-level "cheap to build more clients" doesn't mean
  "faster in wall-clock."
- There's also a direct production precedent for concurrency problems
  against FalkorDB specifically: `MAX_QUEUED_QUERIES` was raised 25→250
  as a stopgap after FalkorDB's query queue was observed exhausting under
  concurrent `/ask` traffic (same doc as F1 above) — evidence that adding
  more concurrent query pressure against FalkorDB has caused real
  operational problems before, in a different feature. Any FalkorDB-side
  parallelization here should be load-tested against that same queue
  limit, not treated as a clean slate.

**FalkorDB: explicitly not implemented.** Per direction, only the Oracle
side was built. The risks above stand as the reason: F1 (no connection
pooling) is a known, pre-existing, unfixed gap from a separate
investigation; the client-side schema-cache race is a real finding from
reading the library source, not fixed here; and the single-threaded
Redis command-execution model means the achievable win is genuinely
unclear without measurement, unlike Oracle where the mechanism for a win
is well understood. If this gets picked up later, fix/coordinate with F1
first, and measure a small live comparison before assuming the same
per-chunk-concurrency approach pays off the way it does for Oracle.

**Risk:** Concurrency piece — Low: correctness is proven (identical output
sequential vs. parallel, live-verified) and `oracle_graph_batch_workers=1`
is a clean, tested opt-out; the *performance* risk is real and measured
(this ADB tier's default makes entity writes slower, not faster) but
scoped to a config value, not a correctness concern. MERGE→INSERT piece —
Low: `full_rebuild=True` is only reachable from `project_graph()`, which
always calls `clear()` immediately before, so the "no conflicts possible"
assumption the plain INSERT depends on is structurally guaranteed, not
just usually true; the relationship-dedup guard covers the one real gap
(no RDB uniqueness constraint on the edge triple) that INSERT is stricter
about than MERGE was. `project_incremental()` is untouched — still MERGE,
still upsert-safe. FalkorDB — not attempted, so no new risk introduced;
the pre-existing F1 gap and query-queue precedent remain exactly as
scoped above, unchanged by this work.

**Effort:** Low-Medium for Oracle overall — the concurrency mechanism
(one new setting, one shared helper method, two call sites, ordering-
related test updates) turned out to be the smaller and less impactful
half of this work. The bigger, more valuable piece came from not
stopping at "concurrency didn't help": two new Oracle query files, a
`full_rebuild` parameter threaded through both graph-store
implementations (Oracle: real behavior change; FalkorDB: accepted no-op
for parity), a relationship-dedup guard, new tests for both the query
selection and the dedup, and a live A/B (500-row MERGE vs. INSERT, real
ADB, fresh workspace) that took the investigation from "no win" to "the
single biggest lever in this entire phase." Zero for FalkorDB — not
implemented.

---

**Summary:** All four phases are done. Phase 2 was the biggest quick win
available; Phase 3 confirmed via investigation that only its embedding
fetch (not the whole block loop) was safe to parallelize, and captured
most of the stage's win from that alone. Phase 4's own investigation
found its "redesign the write path" step was already done by someone
else's earlier work (`project_incremental`/`project_auto`) — the real
blockers were three separate correctness bugs (relationship staleness,
missing Oracle `EXCEPT`→`MINUS` override, an Oracle repeated-bind driver
quirk) keeping it unsafe to use, each found and fixed with its own
characterization test and live verification against the real Oracle ADB,
then wired into the confirm pipeline as the final step. Phase 4 Part B
scoped parallelizing the full-rebuild path itself for the one case Part A
doesn't cover (a genuine from-scratch rebuild); implemented for Oracle
only, per direction. Live-measuring the concurrency mechanism against the
real ADB — not just trusting the theoretical case — found a mixed result
(entities slightly regressed, relationships roughly flat), a direct
instance of this session's own "measure, don't assume" discipline
catching its own optimism. Rather than stop there, the negative result
prompted a deeper look, which found the actual bottleneck: MERGE's
per-row existence-check, not connection concurrency — a 500-row MERGE
batch hung 180+ seconds against the real ADB with zero conflicts
possible, while the equivalent plain INSERT completed in under a second.
The full-rebuild path now uses INSERT (safe because it always follows
`clear()`), live-verified end-to-end; the incremental path is untouched
and still correctly uses MERGE. This turned out to be the single largest,
best-confirmed win in the whole phase — bigger than the concurrency idea
it grew out of. FalkorDB has real, documented risks (an unfixed
connection-pooling gap, an unsynchronized client-side schema cache, and a
single-threaded server execution model) that make its expected win
unclear without its own measurement, so it was left scoped but
unimplemented.
