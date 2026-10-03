# CPQ Raw-Graph XML Ingestion: Spark Parallelization Plan

**Status:** Planning only — no code changed by this document.
**Date:** 2026-10-03
**Trigger:** Live incident — a 240MB XML upload through the `cpq_ingestion`
raw-graph path stalled 15+ minutes (fixed at the memory level by
`fix/xml-raw-graph-projection-scalability-2026-10-03`, PR #424 — streaming
`iterparse` instead of a full DOM parse). This plan covers the next step:
introducing real parallel execution via Spark, per explicit direction —
not a "should we" evaluation, a "how" plan.

**Scope:** The `cpq_ingestion` raw-graph XML projection path specifically
(`project_raw_graph_and_flatten` → `project_and_write_raw_graph` →
`project_xml_to_raw_graph` / `write_raw_graph`). This is a **different**
subsystem from the one covered by
[`SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md`](./SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md),
which analyzed the *confirm* pipeline (Resolve/Relate/graph-projection in
`orchestrate.py`) and shipped a ~48% end-to-end win there (PR #356,
already merged into `dev_oci`) **without** Spark, via `ThreadPoolExecutor`
tuning and two correctness fixes (Oracle `MERGE`→`INSERT`, cursor
`arraysize`). That work does not touch this plan's code paths at all —
this is genuinely unexplored territory, not a rehash.

---

## 1. What's being parallelized, concretely

Today, for one XML file, `project_xml_to_raw_graph()` walks the document
single-threaded, building two flat Python lists (`nodes`, `edges`) via
`iterparse`. There are two independent axes of parallelism available,
and they have very different cost/complexity profiles:

| Axis | What it parallelizes | Needs Spark? | Cross-item shared state? |
|---|---|---|---|
| **A. Across files** in one multi-file upload | Each file's `project_raw_graph_and_flatten()` call | No — in-process `ThreadPoolExecutor` suffices | None — confirmed: each file gets its own raw-graph scope (`get_raw_graph_store`'s `source_key=stem` naming) |
| **B. Within one file** | Splitting one huge XML's element tree across workers | This is the real target for Spark | Yes — node-id collisions and one shared root node (see §3) |

**Axis A is currently NOT parallelized at all** — `doc_discovery.py`'s
tabular-file loop is a plain sequential `for`, unlike the confirm
pipeline's non-last-plan loop which already uses `ingest_workers`. This
is a free, zero-infra win sitting next to the Spark work and is called
out in §6 as an optional low-cost first step, but it is **not** a
substitute for axis B, which is what actually bounds a single huge file.
This plan's main body is axis B.

---

## 2. Why Spark (not just a bigger ThreadPoolExecutor) for axis B

Per the prior analysis's own framework: Spark earns its keep when (a) a
single process's thread pool hits a real ceiling (CPU/memory/connection
limits on one container), or (b) the work should run as an independently
-scaled stage decoupled from the interactive upload-request path. Both
apply here in a way they didn't for the confirm-pipeline's LLM-judging
stages:

- **(a) is a real ceiling, not a theoretical one, for this specific
  workload.** Unlike the confirm pipeline's LLM-call-per-item stages
  (I/O-bound, where `ThreadPoolExecutor` genuinely helps despite the
  GIL), element-by-element XML projection is **CPU-bound pure Python**
  (confirmed by this session's benchmarking: raw per-element
  `RawNode`/`RawEdge` construction dominates the cost, not I/O or the
  parser). The GIL means threading gives **zero** speedup for this
  workload inside one process — `multiprocessing` (real parallel
  processes) or a distributed engine (Spark) are the only ways to get
  actual parallel CPU throughput here, not a bigger `ThreadPoolExecutor`.
- **(b) matches the product goal stated here** — running large-file
  ingestion as a scalable, cluster-backed stage rather than inside one
  FastAPI container's background-task thread.

## 3. The structural property that makes this tractable

`project_xml_to_raw_graph`'s own walk produces exactly one edge type —
`CONTAINS`, parent element → child element — and the only node with no
parent is the document root. This means:

- **Every top-level child of the root is the root of a fully
  self-contained subtree** — no edges ever cross from one top-level
  sibling's subtree into another's. The *only* inter-partition edge in
  the entire document is each top-level sibling's own edge back to the
  single shared root.
- This is the best possible shape for data-parallel splitting: partition
  by top-level sibling, process each partition's subtree completely
  independently, and the merge step is trivial (offset ids, re-attach
  each partition's top-level node to one shared root id, concatenate).
  No cross-partition graph traversal, no multi-pass reconciliation, no
  distributed join needed.

This property should be **verified**, not assumed, against the project's
own real XML shapes before committing to the design below (see §8) — it
holds for any well-formed XML with one root element (true by the XML
spec itself), so the only real risk is a document that is *not* flat at
the top level (e.g. one root with a single giant child containing
everything) — see §7 Risk 1.

---

## 4. Target architecture

```
                         ┌─────────────────────────────────┐
                         │  POST /admin/docs/read            │
                         │  (existing FastAPI route)         │
                         └───────────────┬───────────────────┘
                                         │ file > ARYX_XML_SPARK_THRESHOLD_MB
                                         ▼
                         ┌─────────────────────────────────┐
                         │  Partition stage (driver-side,    │
                         │  cheap): iterparse the root's      │
                         │  direct children only — record     │
                         │  each child's byte-offset span,    │
                         │  do NOT fully parse yet             │
                         └───────────────┬───────────────────┘
                                         │ N partitions (byte ranges)
                                         ▼
                    ┌────────────────────────────────────────────┐
                    │  Spark job: sc.parallelize(partitions)       │
                    │    .mapPartitions(project_subtree)           │
                    │  -- project_subtree() is THIS SESSION'S       │
                    │     already-fixed, already-tested streaming  │
                    │     project_xml_to_raw_graph() logic, run     │
                    │     unmodified against one partition's bytes │
                    └───────────────┬────────────────────────────┘
                                         │ N × RawGraphProjection
                                         │ (LOCAL ids, 0-based per partition)
                                         ▼
                         ┌─────────────────────────────────┐
                         │  Merge stage: offset each           │
                         │  partition's node ids by a per-      │
                         │  partition constant, re-point each   │
                         │  partition's single top-level node   │
                         │  at one shared root id                │
                         └───────────────┬───────────────────┘
                                         │ one combined RawGraphProjection
                                         ▼
                         ┌─────────────────────────────────┐
                         │  write_raw_graph() — UNCHANGED,    │
                         │  already batched, already has the  │
                         │  fast full_rebuild=True INSERT       │
                         │  path (PR #356)                     │
                         └─────────────────────────────────┘
```

**Key design decision: reuse `project_xml_to_raw_graph` unmodified as the
per-partition worker function.** It's already pure (no I/O, no DB, no
global state — confirmed by its own module docstring and this session's
streaming rewrite), already tested at scale (this session's new
100K-element test), and already does exactly the right unit of work —
project one XML subtree into nodes/edges. Spark's `mapPartitions` just
needs to call it once per partition with that partition's byte range.
**No projector logic needs to change for Spark** — only a partitioning
step before it and a merge step after it are new.

---

## 5. Concrete work items

### 5.1 Partition-boundary finder (new, driver-side)

A new function, e.g. `find_top_level_element_spans(data: bytes) ->
list[tuple[int, int]]`, that uses `iterparse(events=("start",))` at
**depth 1 only** (root's direct children) to record each child's
start/end byte offsets in the original buffer, without building any
node/edge objects. This has to be at least a partial parse (XML has no
fixed-width records to seek through), but it's far cheaper than full
projection since it does no `RawNode`/`RawEdge` construction and can
stop tracking a subtree's internal structure the instant it knows where
that subtree ends (needs end-event byte position, which `expat`/`etree`
expose via `elem.tail` positioning — needs a small spike to confirm the
cleanest way to get exact byte offsets from `iterparse`, since the
stdlib doesn't expose raw parser byte position directly on every event;
most likely approach: a custom `expat`-level `CurrentByteIndex` callback,
which the `xml.parsers.expat` module exposes directly on the underlying
parser, bypassing `ElementTree`'s wrapper for this one measurement).

### 5.2 Per-partition worker (reuse, not new)

`project_xml_to_raw_graph(data[start:end])` — called as-is, once per
partition, inside Spark's `mapPartitions`. Each partition's slice must
be independently well-formed XML (the child element plus enough
ancestor-reconstruction to parse standalone — i.e. wrap each slice in a
synthetic single-element wrapper matching the root's tag/namespace
declarations, since a bare child-element byte range isn't valid XML on
its own without the root's namespace context). This wrapping step is new,
small, and testable in isolation.

### 5.3 Merge stage (new)

Given `N` partition results, each a `RawGraphProjection` with local ids
starting at 1:
1. Create exactly one root `RawNode` (tag/attrib from the original
   root element, captured once by the partition-boundary finder).
2. For partition `i`, offset every node id by `i * OFFSET_SIZE` (a
   constant comfortably larger than any single partition's expected max
   element count — e.g. 10,000,000; validate against real data in §8).
3. Re-point partition `i`'s single top-level node's edge (which in the
   per-partition run has `parent_id=None` / no edge, since it looked
   like a self-contained root to the isolated projector) to the shared
   root id from step 1.
4. Concatenate all offset node/edge lists plus the one root node.

### 5.4 API-route integration

`doc_discovery.py`'s XML branch (`cpq_ingestion_pipeline_active(n)` →
`project_raw_graph_and_flatten`) gains a size check: below
`ARYX_XML_SPARK_THRESHOLD_MB` (new setting, suggested default ~20-50MB —
validate in §8), call the existing in-process path unchanged. Above it,
submit a Spark job instead (see §5.5) and return a job handle, not a
result — this changes `_read_job`'s contract from "blocks until done" to
"poll a Spark job," which needs its own status-mapping work (see §5.6).

### 5.5 Spark job submission

Requires choosing a concrete execution target — not decided by this
plan, needs an infra decision alongside it:
- **OCI Data Flow / AIDP** (what the prior analysis scoped): submit via
  AIDP's REST API, a Spark application packaged with this repo's
  `project_xml_to_raw_graph` + the new partition/merge code as its
  payload, reading the uploaded XML from Object Storage (the file would
  need to land in OCI Object Storage first — today's upload path holds
  it in-memory/local only).
- **A self-hosted Spark cluster** (e.g. standalone mode in the existing
  Docker Compose stack, or Kubernetes): lower cold-start latency than a
  managed on-demand cluster, but is new infrastructure to run and
  operate, not a managed service.
- This plan assumes **OCI Data Flow**, matching the prior analysis's own
  infra section and this stack's existing OCI-native posture
  (`ARYX_OCI_*` settings already throughout `config_oci.py`) — flag this
  explicitly for confirmation before building against it.

### 5.6 Job-status integration

The existing `aryx_job` row / polling UI (`useJobPoller.ts`,
`GET /admin/jobs/{job_id}`) expects a `status`/`stage`/`pct` row updated
by `jobs.update_stage()`/`jobs.finish()` from inside the worker. A Spark
job running on a remote cluster can't call back into this API process's
`JobStore` directly in the same way — needs either:
- A lightweight polling bridge: the FastAPI process polls the AIDP job's
  own status API on an interval and translates it into `jobs.
  update_stage()` calls, or
- The Spark driver calls back to a small internal webhook endpoint on
  this API (`POST /admin/jobs/{job_id}/spark-progress`) with progress
  updates, requiring outbound network access from the Spark cluster to
  this API — a new network path to secure (shared API key, like the
  existing `ARYX_INTERNAL_API_KEY` pattern used for the shay-backend
  bridge).

---

## 6. Optional, much cheaper complementary win (axis A, not Spark)

Independent of all of the above: parallelizing **across files** in a
multi-file upload (§1, axis A) is a same-pattern-as-everywhere-else
`ThreadPoolExecutor` change to `doc_discovery.py`'s tabular-file loop,
with **zero** new infrastructure, since each file's raw graph is already
independently scoped. This doesn't help a single huge file (the actual
incident), but it's a nearly-free win for the common multi-file-XML-
upload case and uses no new infra. Flagged here as a candidate to ship
independently and sooner, not a substitute for the Spark work above.

---

## 7. Risks

1. **The flat-top-level assumption (§3) needs verifying against real
   data.** A document with one root containing one giant child (instead
   of many flat siblings) wouldn't partition usefully at depth 1 — would
   need recursive partitioning (split at depth 2 if depth 1 yields too
   few/unbalanced partitions), adding real complexity to §5.1.
2. **Partition imbalance.** If one top-level sibling is vastly larger
   than the others (e.g. one `<Catalog>` with 95% of all elements, next
   to a handful of small siblings), Spark parallelism doesn't help much —
   that one partition still runs single-threaded on one executor. Needs
   a size-aware partitioning strategy (e.g. further split any partition
   above a size threshold), not naive 1-partition-per-sibling.
3. **Byte-offset wrapping correctness (§5.2).** Slicing raw bytes and
   re-wrapping them as standalone XML is fiddly — namespace prefixes
   declared on the root but used by a deeply-nested descendant, CDATA
   sections or entities spanning a slice boundary, etc. Needs real
   fuzzing/characterization testing against varied real XML shapes
   before trusting it, not just the flat synthetic shape used in this
   session's benchmarks.
4. **New infra dependency and ops cost** — cluster idle-timeout billing
   risk (per the prior analysis's own warning), job-submission latency
   (likely seconds-to-tens-of-seconds of Spark app cold-start, which is
   pure overhead for files near the size threshold — reinforces needing
   a real threshold, not "always use Spark for XML").
5. **Job-status bridging (§5.6) is a new, not-yet-designed integration
   surface** — needs its own security review (webhook auth) and failure-
   mode handling (what happens to the `aryx_job` row if the Spark job
   dies without ever calling back, or AIDP's own status API is
   unreachable).

---

## 8. Suggested validation before/alongside building (not gating the plan, informing it)

Per explicit direction this plan does not wait on these, but they should
happen early in implementation, not be skipped entirely:
- Confirm the flat-top-level-siblings shape (§3, §7.1) against a handful
  of real production-shaped XML files, not just synthetic test data.
- Pick `ARYX_XML_SPARK_THRESHOLD_MB` and the per-partition `OFFSET_SIZE`
  constant based on real element-count/size ratios from production data,
  not guessed round numbers.
- Confirm OCI Data Flow / AIDP availability and quota in this org's
  tenancy before building against it as the execution target (§5.5) —
  an infra/procurement dependency, not something resolved by code.

---

## 9. Phased implementation order

1. **Phase 1 — Partition/merge logic, validated locally without Spark.**
   Build §5.1-§5.3 (partition finder, byte-slice wrapping, merge) and
   prove correctness via `multiprocessing.Pool` (real separate processes,
   same parallelism model Spark uses, zero cluster infra needed) against
   both the existing small sample XMLs and new large synthetic/real
   fixtures. This de-risks the hardest, most novel part (byte-slice
   wrapping + id-merge correctness) before any cluster work starts, and
   ships a real, measurable, Spark-shaped speedup without needing
   infrastructure first (`multiprocessing.Pool` on an 8-16 core box 
   already uses genuine parallel processes, unlike ThreadPoolExecutor).
2. **Phase 2 — AIDP integration.** Swap `multiprocessing.Pool` for
   `sc.parallelize(...).mapPartitions(...)` against a real OCI Data Flow
   cluster, using the exact same partition/worker/merge functions from
   Phase 1 unchanged (the whole point of designing it as plain functions
   first). Build the file-to-Object-Storage handoff and job-submission
   wiring.
3. **Phase 3 — Job-status bridge (§5.6) and route integration (§5.4).**
   Wire the size-threshold routing decision and whichever status-bridging
   approach is chosen into the real upload endpoint, behind a feature
   flag so it can be rolled out gradually and compared against the
   existing path.
4. **Phase 4 (optional) — Apply the same pattern to axis A (§6)** and/or
   revisit whether any of the confirm-pipeline stages from the prior
   analysis would now benefit from the same Spark infra, now that it
   exists, re-running that analysis's own "measure before assuming"
   discipline rather than assuming the earlier "not worth it" verdict
   still holds once a cluster is already available.

---

## 10. Phase 1 result — rejected, 2026-10-03

Phase 1 was built (partition via `ElementTree.tostring()` re-serialization
of top-level siblings instead of the byte-offset slicing in §5.1 — avoids
manual namespace reconstruction) and benchmarked via `multiprocessing.Pool`
against a 29MB / 600K-element synthetic document on an 8-core machine:

| Mode | Time | Speedup vs. sequential |
|---|---|---|
| Sequential (`project_xml_to_raw_graph`) | 5.66s | — |
| Parallel, 1 worker | 28.64s | 0.20x |
| Parallel, 2 workers | 30.92s | 0.18x |
| Parallel, 4 workers | 25.38s | 0.22x |
| Parallel, 8 workers | 29.46s | 0.19x |

**Parallel was ~5x slower than sequential at every worker count tested,
including 1 worker.** The flat result across worker counts rules out
"needs more cores to amortize the overhead" — the cost is fixed per call,
not a function of contention between workers. Two causes, both structural:

1. `_split_top_level_elements` runs a full second streaming parse over the
   whole document before any partition work starts.
2. Each worker process returns a `RawGraphProjection` holding hundreds of
   thousands of `RawNode`/`RawEdge` dataclass instances, which
   `multiprocessing.Pool` must pickle out of the child process and
   unpickle in the parent. For ~1.2M small objects that IPC cost alone
   dwarfs the 5.66s of actual projection work being parallelized.

This is the same class of problem the GIL-vs-I/O reasoning in §2 predicted
could happen on the serialization side, just worse in practice than
anticipated — not "overhead eats into the win" but net negative across the
board. A real Spark migration (Phase 2) would hit the identical wall unless
partition results cross the process/cluster boundary as a columnar/binary
format (Arrow, Parquet) rather than pickled Python dataclasses — a
materially different and more expensive design than anything validated
here.

**Decision: do not pursue Spark/AIDP (Phase 2+) for this path.** The
prototype (`parallel_projector.py` + its tests) was removed rather than
shipped — it validated the premise and the premise didn't hold. The
streaming fix in `xml_projector.py` (PR #424) already addressed the actual
production incident (the 240MB stall and its peak-memory growth); this
plan's remaining phases are not worth building without a different
serialization strategy to re-test first, and no one has asked for that
investment.
