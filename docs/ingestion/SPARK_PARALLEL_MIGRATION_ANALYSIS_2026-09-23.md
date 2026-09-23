# Ingestion Pipeline: Parallel/Spark Migration Analysis

**Status:** Phase 1 ✅ done, Phase 2 ✅ done (§8) — worker count raised, a
hidden progress-reporting bottleneck found and fixed, and candidate
batching implemented, all live-verified against the real LLM. Branch
`perf/ingest-parallel-2026-09-23` (holds all phases), pushed, not yet PR'd.
Phases 3–4 not started.

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

**What:** The record-matching stage (`resolution/run.py`) — currently a plain
sequential loop over "blocks" (groups of similar records), no concurrency.

**Work, in order:**
1. **Investigate first** — confirm whether each block can really be processed
   independently, or whether one block's result can affect another's (this
   was flagged as unverified in §5/§6, not confirmed either way).
2. Only if step 1 confirms independence: parallelize by block, same
   `ThreadPoolExecutor` pattern as Phases 1–2.

**Risk:** Medium — unlike Phases 1–2, we don't yet know this one is safe to
parallelize. Skipping the investigation step and parallelizing blindly could
silently change matching results.

**Expected win:** Unknown until measured — this stage's share of total time
wasn't isolated in §3's timing breakdown (it's folded into the "21s" for
Discover+Resolve+Seed on the last plan, so it's small for this particular
job, but could matter more on other datasets).

**Effort:** Medium — the investigation itself is the main cost; the actual
code change (if safe) is small.

---

### Phase 4 — Step 10: Graph projection (biggest cost, hardest fix)

**What:** The graph-write stage — 35% of total time (45m39s), the single
largest cost measured. Currently does `clear()` then rebuilds the entire
workspace graph from scratch, every time.

**Work, in order:**
1. **Investigate the write path** (`project_full.py`) to design an
   incremental/partitioned write model — e.g. writing only what changed,
   instead of clearing and rebuilding everything.
2. Redesign the write logic to that model.
3. Only after step 2, add parallelism (more threads, or Spark) — there's
   nothing to parallelize until the write path itself has independent pieces
   to hand out.

**Risk:** High. This is a real architecture change to how the graph store
gets written, not a config tweak — get it wrong and the graph could end up
incomplete or inconsistent.

**Expected win:** Biggest of all four phases (45m39s today) — but also the
only one that requires a redesign before any parallelization is even
possible, per §6.

**Effort:** High — this is its own project, not a quick fix. Recommend
scoping it as a separate follow-up investigation once Phases 1–3 are done.

---

**Summary:** Phase 1 and Phase 2's first step are safe, cheap, and should
happen first — Phase 2 especially, since it's the biggest quick win
available. Phase 3 needs an investigation before any code changes. Phase 4 is
the biggest total win but the most work, and shouldn't be started until its
own write-path investigation is done.
