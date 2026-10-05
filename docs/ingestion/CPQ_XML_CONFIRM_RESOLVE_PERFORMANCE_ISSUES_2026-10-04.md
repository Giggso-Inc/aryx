# CPQ XML Confirm-Stage Resolve: Performance & Reliability Issues

**Status:** Implemented on branch `fix/cpq-xml-confirm-performance-2026-10-04`
— every section (§0, §1 all three tiers, §2, §3, §3b, §4, §6, §7, §8) is
now code, not just a design (each section below has an "Implemented"
note with the files/tests it touched). §3b and §4's index ship **opt-in**
(§3b) or as a low-risk additive change (§4's index) rather than as default
behavior changes. **Update — live verification (2026-10-04, same day,
against a real dev_oci Oracle ADB instance)** closed most of the
open-verification gaps below — see that section for what's now actually
confirmed vs. still open:
- **§3b** (stream the raw-graph projection instead of materializing the
  whole document) — `ARYX_CPQ_STREAMING_PROJECTION_ENABLED`, default
  `false`. Still opt-in (not flipped to default-on) because verification
  so far is at a 3,000-record synthetic scale, not the real 439,946-record
  file — but the full `resolve_and_relate_raw_graph()` pipeline (not just
  the parser) has now been run live, end to end, both ways, and produces
  byte-identical entities/relationships/provenance/graph output. See the
  live-verification update.
- **§1 Tier 0** (`ARYX_LANDING_BATCH_SIZE`) — the 500→3000 speedup claim is
  now live-confirmed (3.84x), not just inferred from one prior incident
  measurement. See the live-verification update.
- **§4** (slow Oracle queries) — only the diagnostic tooling (automatic
  `EXPLAIN PLAN` capture on every future slow statement) and one
  low-risk, additive index shipped as actual fixes. The specific root
  cause of the original 5.8s-31.8s/0-row evidence is still **not**
  confirmed, but live investigation has ruled out "bad query plan" as the
  explanation and surfaced a new, previously-unknown risk with the new
  index itself — see the live-verification update.

**Update — PR review (same day):** a first-pass review caught 4 real
correctness/safety bugs in the initial implementation, since fixed on the
same branch (not a follow-up PR — these landed before the PR was
considered done):
- The heartbeat sweep (§0) would have failed healthy jobs: it swept
  `queued` jobs (which legitimately sit for a while behind
  `ARYX_INGEST_WORKERS` busy slots) and every non-cpq job type (document
  ingestion, REST/DB ingest — none of which got the new `on_progress`
  heartbeat threading, only the cpq XML path did). **Fixed:** the sweep
  now only targets `status = 'running'` rows whose `stage` names the cpq
  ingestion path specifically. Separately, a swept job's still-running
  worker could resurrect its row back to `'running'` on its next progress
  report, or overwrite `'failed'` with `'complete'` when it eventually
  finished. **Fixed:** `update_job_stage`/`finish_job` now refuse to
  touch a row already `'failed'`, and `make_should_stop()` now also stops
  on `'failed'`, not just `'cancelled'`.
- `force_exact` (§1 Tier 2) trusted a caller's assertion that a
  generic-fallback match key's values were unique, with no actual
  verification — a guessed key with real duplicates (e.g. a status/type
  column) would have silently merged every record sharing a value into
  one entity. **Fixed (round 1):** `force_exact` is now only honored when
  `_key_selectivity()` independently confirms near-total uniqueness (new
  `er_force_exact_min_selectivity` setting). **Tightened further in round
  2** — see the second update below.
- `oracle_migrate.py`'s tracking table (§6) could mark a file "applied"
  after a genuine, unexpected failure (not just an "already exists"
  no-op), meaning it would never be retried; and two uvicorn workers
  racing to mark the same new migration applied at boot would crash the
  second one on a primary-key violation. **Fixed:** a file is only marked
  applied when every block's error (if any) was one of a known-idempotent
  set; the mark-applied insert now tolerates a concurrent duplicate.
- `structural_leaf.py` (§1 Tier 1) re-scanned the whole edge list (up to
  5.85M edges) once per candidate tag, and unconditionally built two
  full-projection-sized dicts even when nothing was foldable — in a PR
  about memory pressure. **Fixed:** parent-id classification is computed
  once for the whole projection; the expensive per-node dict is only
  built when at least one tag actually qualifies as a leaf. Also fixed in
  the same pass: an empty marker element (`<flag/>`, no text at all) was
  silently dropped from the resolve set entirely instead of being folded.

Also addressed: the leaf-fold and `force_exact` behavior changes now have
opt-out settings (`ARYX_CPQ_STRUCTURAL_LEAF_FOLD_ENABLED`,
`ARYX_CPQ_FORCE_EXACT_ENABLED`, both default-on), and new test coverage
was added for `structural_leaf.py` (zero existed before), the embedding
dedup, and `force_exact`'s verification behavior — all flagged as gaps by
the same review.

**Update — PR review round 2 (same day, after §3b/§4 landed):** a second
review pass, against the fuller implementation, found one more real
correctness bug and three minor-severity follow-ups:
- **[M1, remaining]** The round-1 heartbeat-sweep fix (scoping to
  `stage LIKE '%CPQ Ingestion%'`) was necessary but not sufficient: large
  silent phases existed *inside* that same stage — landing (`discover()`
  reported nothing between its own 8%/15% bookends for the whole
  extract+land duration, ~35 min for a 439,946-row tag) and the
  post-tag-loop phase (`save_relationships`/`project_workspace_graph` got
  no `on_progress` at all). Combined with round 1's own fix making
  `make_should_stop()` stop on `'failed'`, this made the failure mode
  *worse*, not just cosmetic: a perfectly healthy job silent for >10
  minutes would get swept to `'failed'`, its worker would then raise
  `PipelineCancelled` at the next checkpoint, and PR #429's cleanup would
  delete its partial entities — before this round, a stuck sweep only
  showed a wrong status. **Fixed:** `run_spine()` (the landing loop) now
  accepts `on_progress`, firing an indeterminate heartbeat at the same
  cadence as its existing "spine progress" log line, threaded through
  `discover()` (already wired into `run_pipeline()`). `EntityStore.
  save_relationships()` now batches (5000 rows/call, configurable) with a
  real done/total progress checkpoint between batches. Both
  `save_relationships()` and `project_workspace_graph()` (which already
  supported `on_progress` internally and simply wasn't being passed one)
  now receive `resolve_and_relate_raw_graph()`'s `on_progress` at their
  call sites in `resolve_relate.py`.
- **[N1]** `_key_selectivity()`'s existing head-sample (`records[:
  sample_size]`, 2000 by default) was being reused for `force_exact`'s
  verification — fine for selectivity's original low-stakes purpose (a
  false negative just means an unnecessary resolve pass), but a biased
  sample for a correctness-critical merge decision: a repeated placeholder
  value (e.g. `"N/A"`) concentrated outside the sampled head would look
  fully unique to the sample while the real data has real duplicates, and
  the original 0.99 threshold tolerated ~1% real duplicates anyway.
  **Fixed:** new `_full_uniqueness_ratio()` does a full O(n) scan (no
  sampling) specifically for `force_exact`'s verification, only when
  `force_exact` is actually requested; `er_force_exact_min_selectivity`'s
  default tightened to `1.0` (zero duplicate tolerance).
- **[N2]** The M4 fix still built `parent_of` (a dict sized to the whole
  file's edge count) unconditionally in the same pass as `parent_ids`,
  and `nodes_by_id` still covered every node in the file whenever anything
  folded. **Fixed:** `parent_of` is now built in a second pass, only when
  at least one tag actually classifies as a leaf, and restricted to edges
  targeting those leaf tags' own nodes; `nodes_by_id` is restricted to the
  distinct parent ids `parent_of` actually references, not every node in
  `by_tag`.
- **[N3]** `_EXPECTED_IDEMPOTENT_ORA_CODES` omitted `ORA-01408` (this
  exact column list already indexed under a different name) — most
  migration files self-guard it inside their own PL/SQL exception handler
  so it never reaches Python, but a handful of plain, un-self-guarded DDL
  statements hit it directly, and without it in the allowlist those files
  would never be marked applied. **Fixed:** added to the allowlist, with
  a note that the list isn't exhaustively verified against every file in
  `migrations_oracle/`.

**Date:** 2026-10-04
**Trigger:** Live observation of a real Confirm-stage run against the
240MB `aSTRO25_ConfigData.xml` file (workspace 1005, job
`00d728e8de0145de82ed722c88f0799d`), immediately after PR #429
(`fix/confirm-stage-raw-graph-cancellation-2026-10-04`) was merged into
`dev_oci` and the stack was rebuilt. PR #429 fixed Confirm-stage
cancellation correctness (orphaned/duplicate entities on cancel). This
document is a separate, follow-up list of problems — mostly performance,
one resource-risk — found by actually watching that fix work end-to-end
on production-scale data. **Update, same job watched to completion:**
§1's original write-up mis-attributed the observed slowness to embedding
cost; continuing to watch the job revealed the real cause and corrected
the fix recommendation accordingly (see §1). Every issue below now
includes a concrete, scoped fix design, not just a direction. **Second
update, same job, ~71 minutes in:** the job did not actually run to
completion — a worker process silently crashed and was respawned mid-job,
orphaning it permanently. This is a new, higher-severity finding than
anything else in this document; see §0.

**Scope:** `resolve_and_relate_raw_graph()`
(`src/aryx/cpq_ingestion/raw_graph/resolve_relate.py`) and the shared
`resolve_run()` / `resolve()` entity-resolution path it calls into
(`src/aryx/resolve_entities.py`, `src/aryx/resolution/run.py`) — not the
Read-stage preview path (already addressed in PR #426) and not the
cancellation-correctness work (already addressed in PR #429).

**Logs:** full container logs (all 5 services) and a raven_log-only
extract for `aryx-api`, captured across this investigation, are archived
under `docs/ingestion/logs/`.

**Caveat on timing numbers:** per §0, this job never actually ran to
completion — every duration/rate figure in §1-§4 (e.g. "~35 min landing
one tag") is extrapolated from a run that was silently killed partway
through, not a clean end-to-end measurement. Treat them as directionally
correct (they're grounded in per-batch/per-statement measurements, not
guesses) but re-validate against a clean completed run once §0 is
addressed or at least understood.

---

## 0. [Critical, new — highest severity in this document] A uvicorn worker silently crashed mid-confirm, permanently orphaning the job with no error recorded anywhere

**Observed live, same job, ~71 minutes in:** while periodically re-checking
`/admin/jobs/00d728e8de0145de82ed722c88f0799d`, the chunked resolve pass's
block-skip warnings (§7) stopped advancing after `prefix:4167` at
`09:09:13`. No further resolve activity, no error, no crash message —
just silence. Investigating *why* (rather than assuming "still slow, see
§7") uncovered something worse than slow: the job is dead and will never
finish.

**Root cause, found via `docker top` + log archaeology, not guesswork:**

```
docker top aryx-api-1 -o pid,ppid,etime,cmd
PID     PPID    ELAPSED    CMD
908548  908498  01:54:18   uvicorn aryx.api.main:app --workers 2   (master, alive since boot)
909163  908548  01:54:18   worker A (alive since boot)
993946  908548  00:35:55   worker B -- only 36 minutes old, NOT since boot
```

- `docker-compose-oci.yml`'s `api` service runs `uvicorn ... --workers 2`
  — two worker *processes*, not threads, each with its own memory space.
  `ARYX_WORKER_BACKEND` runs ingestion as an in-process `background_task`
  inside whichever worker received the confirm request — there is no
  durable job queue underneath it.
- One of the two workers was replaced partway through the job's run: its
  `ELAPSED` time (36 minutes, as of the check) is far shorter than the
  container's own uptime (close to 2 hours) and than its sibling worker's
  elapsed time — the only explanation is that the original worker died
  and uvicorn's multiprocess manager silently spawned a replacement.
- Confirmed independently from the logs: a **full migration replay +
  `"MCP mounted at /mcp"`** — the exact FastAPI startup sequence — appears
  a third time at `09:11:19`, timestamped right after the resolve logs
  went silent. (`grep -c "MCP mounted at /mcp"` → 3: the two original
  workers' boots, plus this one respawn.)
- **Nothing** was logged about the crash itself: no traceback, no
  exception, no "shutting down" / signal message, no
  `db.oracle.slow_statement`, nothing — a full-log search for
  `Traceback|Task exception|CRITICAL|OperationalError|TimeoutError|
  deadlock` across the entire container history turns up only unrelated
  Oracle migration replay noise (§6), zero hits anywhere near 09:08-09:11.
  The worker didn't fail gracefully; it was killed outright.
- **Not a container-level OOM-kill:** `docker inspect` shows
  `OOMKilled=false`, and the container's own cgroup counters
  (`/sys/fs/cgroup/.../memory.events`) show `oom: 0`, `oom_kill: 0` — the
  3GiB container memory limit itself was never the trigger. But the same
  file shows `max: 1480` — the cgroup hit its memory ceiling and underwent
  forced reclaim 1,480 times, consistent with the worker running under
  severe, sustained memory pressure right up until it died (directly
  consistent with §3's live 2.7GiB/3GiB≈90% observation during this same
  job). The kill most plausibly came from the **host-level** OOM killer
  (outside this container's own leaf-cgroup accounting) rather than this
  container's own limit — `docker stats`/`docker inspect` alone cannot
  rule this out and a host-level `dmesg`/kernel log check was attempted
  but not accessible in this environment to confirm definitively.

**Why this is worse than §3's original framing:** §3 described the risk
as "an OOM-kill mid-confirm... no graceful cancellation path, no
cleanup, just a dead container." What actually happened is arguably
worse than that framing assumed: the *container* didn't die — it kept
reporting `healthy` the entire time, `docker ps`/`docker inspect` showed
nothing wrong, and a fresh worker silently took over request-serving
duty. The only visible symptom was the job itself going quiet forever.
**There is no error anywhere in this system — not in the job's `error`
field (still `null`), not in the logs, not in the container's health
status — that tells an operator this job died.** `status: running`,
`pct: 0`, `updated_at: 2026-10-04T07:59:09` (never updated again) are now
permanent. Nothing will ever mark this job failed or finished.

### Fix — not yet designed in detail, flagged for follow-up

**Implemented (option 1 only — options 2-4 below remain follow-up work,
not code):** `JobStore.sweep_stale_heartbeat()` (`src/aryx/store/
job_store.py`) + new queries `sweep_stale_jobs_heartbeat.sql` (Postgres
and Oracle) + a new `job_heartbeat_timeout_minutes` setting
(`ARYX_JOB_HEARTBEAT_TIMEOUT_MINUTES`, default 10 min,
`src/aryx/config/config_core.py`), wired into the existing 60s sweep loop
in `src/aryx/api/main_lifespan.py` alongside (not replacing) the existing
`sweep_stale()`/`ARYX_JOB_TIMEOUT_MINUTES` (120 min) check. The two now
answer different questions: the old one is "has this job run longer than
any job should ever take" (a generous ceiling); the new one is "has this
job's worker stopped reporting ANY progress recently" (a tight liveness
check), and a crashed worker is now caught within ~10 minutes instead of
up to 120. Making the shorter threshold *safe* (not just added) required
also closing the exact gap that caused the live incident: `resolve_
chunked()` (`src/aryx/resolution/chunked.py`,
`src/aryx/resolution/chunked_backend.py`) previously reported zero
progress for its entire duration, which would have made the new
heartbeat check fire falsely on every healthy chunked run — both now
accept and call `on_progress` as an indeterminate-pct liveness signal
(same cadence as their new §7 log checkpoints), threaded through
`resolve_entities.py`'s `resolve_run()`. Covered by 6 new tests in
`tests/test_job_store_heartbeat.py` (`TestSweepStaleHeartbeat`, kept
separate from `test_oci_backends.py` to avoid tripping that file's
pre-existing secret-scan false positive on unrelated dummy OCI
credentials) mirroring the
existing `sweep_stale()` coverage.

This needs more investigation than the other issues here before a fix
can be properly scoped (unlike §1-§8, this was discovered in this
document's final pass, not fully root-caused to kernel level). Starting
points, roughly in order of how directly each addresses the failure
mode observed:

1. **Job-level liveness/heartbeat detection (addresses the actual harm —
   a permanently zombied job with no error surfaced):** independent of
   *why* a worker dies, `ingest_confirmed()`/the job-status table has no
   mechanism to detect "the process that owns this job is gone." A
   heartbeat column updated periodically during `run_pipeline()` (or
   reusing §8's `on_progress` plumbing, since it already fires regularly)
   plus a watchdog that marks a job `failed` with a clear error
   (`"worker lost"`) if its heartbeat goes stale past some threshold would
   turn this from a silent permanent zombie into a visible, retriable
   failure — the single highest-leverage fix here regardless of the
   crash's root cause.
2. **Investigate the worker's actual memory ceiling vs. container limit:**
   with `--workers 2` sharing one 3GiB container limit, a single
   memory-heavy confirm job (§3/§3b: the full `RawGraphProjection` held in
   memory, 5.85M nodes + edges for this file) can starve the *other*
   worker too, or get killed by a mechanism outside this container's own
   accounting. Options worth comparing: raise the container limit (§3's
   immediate fix helps here too), reduce `--workers` to 1 for this
   service if request concurrency doesn't require 2, or move long-running
   confirm jobs to a separate worker pool/process with its own memory
   budget isolated from request-serving workers.
3. **Confirm or rule out a host-level OOM kill definitively:** this
   environment didn't allow a `dmesg`/kernel-log check from inside the
   investigation; whoever has host access should check
   `dmesg | grep -i oom` / `journalctl -k | grep -i oom` around
   `09:08-09:09` on 2026-10-04 to confirm the kill mechanism before
   assuming option 2's framing is complete.
4. **Separately: re-run this same confirm job now that this risk is
   documented**, to get one clean completed run's real end-to-end timing
   — every timing number in §1-§4 is from a run that, it turns out,
   never actually finished.

---

## 1. [Critical, corrected] Every distinct XML tag goes through full landing + entity resolution, regardless of whether it's worth treating as an entity at all

**Correction (same discipline as PR #429's duplication-claim fix): my
original write-up of this issue blamed `_block_embeddings()` /
embedding cost for the `id` tag's slowness. That was wrong, confirmed by
continuing to watch the same job to completion.** Keeping the original
observation and the corrected one both visible, since the corrected
version changes which fix is actually worth building.

**What I originally observed (still true, just mis-attributed):**

```
2026-10-04 08:01:22 ingest.pipeline.start new run: ontology_type=id, match_keys=["text"]
2026-10-04 08:13:34 spine progress records=360000   (still landing)
2026-10-04 08:14:13 spine progress records=380000
```

**What actually happened once the tag finished landing (the correction):**

```
{"message": "ingest.resolve.path_chosen resolve path: chunked",
 "context": {"task_id": 1304, "selected_option": "chunked",
             "reason_code": "RECORDS_ABOVE_CHUNK_THRESHOLD",
             "records": 439946, "threshold": 100000, "selectivity": 1.0}}
```

439,946 records, **selectivity 1.0** (every single sampled value was
unique — `_key_selectivity()`, `src/aryx/resolve_entities_selectivity.py`)
— the opposite of "meaningless generic tag." The existing
`er_chunk_threshold` check (`src/aryx/resolve_entities.py`) correctly
routed this to `resolve_chunked()` (`src/aryx/resolution/chunked.py`),
which — confirmed by reading it — **never calls `broker.embed()` at
all**. Zero embedding cost for this tag. The codebase already has a
real scalability safety net here (block-size cap, low-selectivity
short-circuit, chunked/Postgres-resumable resolver for large tags), and
it fired correctly.

**So what is the actual, confirmed cost?** Landing. `discover()`
(`src/aryx/discover.py`) lands every record through `BatchSink`
(`src/aryx/store/batch_sink.py`) in **fixed batches of 500**
(`_BATCH = 500`, hardcoded, not configurable), each flushed via one
`INSERT aryx_landed_record ... executemany`. The one such insert caught
in the slow-statement log (§4's table) took **2,399 ms for 500 rows**
against Oracle ADB. At that rate, 439,946 records ≈ 880 batches ≈
**~35 minutes of INSERT round-trips alone**, for one tag, before
resolution of any kind even starts — and this cost is paid **regardless
of which resolve path the tag ultimately takes**, because landing
happens before path selection.

**Root cause (corrected):** `resolve_and_relate_raw_graph()` lands and
resolves every distinct XML tag as if it were an independent dataset —
correct for real entity types, but for a tag that is structurally just
a leaf scalar (no attributes, no children — e.g. a repeated `<id>` child
under every parent record), landing hundreds of thousands of occurrences
as rows in `aryx_landed_record` is itself the waste, independent of how
cheaply they later resolve. The existing chunked/selectivity safety nets
make the *resolve* step cheap; nothing makes the *landing* step cheap
for a tag like this, because nothing today decides a tag shouldn't be
landed as a dataset in the first place.

### Fix — scalable, three-tier

**Implemented — all three tiers:**
- **Tier 0:** new `landing_batch_size` setting (`ARYX_LANDING_BATCH_SIZE`,
  default 500, `src/aryx/config/config_core.py`), wired into `BatchSink`
  (`src/aryx/store/batch_sink.py`) replacing the hardcoded `_BATCH`
  constant as the default, and raised to 3000 for Oracle in
  `docker-compose-oci.yml`. The `cursor.arraysize`/`setinputsizes`
  investigation is not done (needs live profiling against the real Oracle
  ADB instance, not something this pass could do from a doc-writing
  session) — tracked as follow-up.
- **Tier 1:** new module `src/aryx/cpq_ingestion/raw_graph/
  structural_leaf.py` (`is_structural_leaf_tag` / `fold_structural_leaf_
  tags`), wired into `resolve_and_relate_raw_graph()` right after
  `group_nodes_by_tag()`. Note on the original sketch in this section: a
  literal `if any(n.properties for n in nodes)` check (as first written
  below) turns out to never fire, because `xml_projector.py` always
  stores a leaf's text under the `RAW_PROP_TEXT` property key even when
  there are zero real XML attributes — a true structural leaf's
  `properties` dict is `{"text": "..."}`, never empty. The implemented
  version checks for any key *other than* `RAW_PROP_TEXT` instead.
- **Tier 2:** new `force_exact` parameter threaded `resolve_relate.py` ->
  `orchestrate.py`'s `run_pipeline()` -> `resolve_entities.py`'s
  `resolve_run()`, set `True` whenever `infer_match_keys_for_tag` returns
  `source="default"` (a real, observed property that neither the
  heuristic nor the LLM could confidently name — exactly cpq_ingestion's
  generic-fallback shape).

All three verified against `tests/test_chunked_resolution.py`,
`tests/test_resolve_run_wiring.py`, `tests/cpq_ingestion/
test_match_key_inference.py` (5 assertions updated for the new `source`
field `infer_match_keys_for_tag` now returns), and `tests/cpq_ingestion/
test_resolve_and_relate_raw_graph.py` — no regressions.

**Tier 0 (immediate, operational, ships independently of the other two):**
`BatchSink`'s `_BATCH = 500` (`src/aryx/store/batch_sink.py`) is a
hardcoded module constant, not derived from settings, and was almost
certainly sized for Postgres, not Oracle ADB round-trip latency — a
2,399ms `executemany` for 500 rows implies most of that time is
per-round-trip overhead (network + parse + bind), not actual row-write
work, meaning a larger batch size would amortize that overhead over far
more rows per call. Two independent changes, either alone is a real win:

1. Make the batch size a setting (e.g. `landing_batch_size`, default
   500 to preserve today's behavior everywhere else), and raise it
   specifically for the Oracle backend — e.g. 2,000-5,000 rows per
   `executemany`, profiled against a real large file rather than guessed.
2. Separately investigate *why* a 500-row Oracle `executemany` takes
   2.4s at all — check `cursor.arraysize`/`setinputsizes` tuning (the
   codebase's own history already fixed one Oracle `MERGE`→`INSERT` +
   `arraysize` performance issue for a different store, per
   `SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md`'s reference to
   PR #356 — the same class of fix may apply here).

This alone would cut the observed ~35-minute landing time for a
440K-record tag roughly in proportion to the batch-size increase (e.g.
~4x batch size ≈ ~4x fewer round-trips, modulo per-row cost), with no
architectural change — worth shipping before or alongside Tier 1/2
since it benefits every tag's landing, not just structural leaves.

**Tier 1 (eliminates the cost entirely for structural leaf tags):** add
a pre-pass over `by_tag` in `resolve_and_relate_raw_graph()`
(`src/aryx/cpq_ingestion/raw_graph/resolve_relate.py`), before the
per-tag loop, that classifies each tag using data already available in
the `RawNode`/edge lists — no new parsing, no extra DB round-trip:

```python
def _is_structural_leaf_tag(nodes: list[RawNode], projection: RawGraphProjection) -> bool:
    """True if every node of this tag has no attributes and no children
    -- i.e. it's a plain scalar value holder, not a candidate entity."""
    node_ids = {n.id for n in nodes}
    if any(n.properties for n in nodes):          # has real attributes -> keep as entity
        return False
    has_children = {e.source_id for e in projection.edges if e.source_id in node_ids}
    return not has_children
```

For tags that classify as structural leaves: **fold the leaf's text
value as a property onto its parent node** (one more O(n) pass over
`projection.edges`, using the existing `CONTAINS` edges to find each
leaf's parent) instead of calling `run_pipeline()` for it at all. This
mirrors how a real schema would model `<Record><id>123</id></Record>` —
`id` is an attribute of `Record`, not its own entity type. This removes
the tag from landing, resolution, *and* the final entity count
entirely — the only fix that scales as O(1) relative to tag volume
instead of O(record count), because the work is never done.

**Tier 2 (for tags that don't qualify as structural leaves, but still
have no real identifying attribute — i.e. `infer_match_keys_for_tag`
fell back to the generic `text` key):** these should still land (they
may have real attributes worth capturing), but should be told to use
`exact_ids=True` resolution directly rather than relying on
`_key_selectivity()`'s sampling to discover the same thing after the
fact. Today `exact_ids` is decided purely by whether the match key's
*name* looks ID-like (`_id_like_keys()`); a tag whose only key is the
generic `text` fallback never qualifies, even when (as here) the
values themselves turn out to be fully unique. Concretely: extend
`resolve_run()`'s signature with an explicit `force_exact: bool = False`
override, threaded from `resolve_and_relate_raw_graph()` whenever
`infer_match_keys_for_tag` had to fall back to the generic key — skips
`_key_selectivity()`'s sampling pass too, since the caller already knows
it wants exact matching. Smaller win than Tier 1 (doesn't reduce landing
cost), but makes resolution path selection deterministic instead of
depending on the data happening to sample as high-selectivity.

All three tiers are additive and independently shippable. Suggested
order: Tier 0 first (smallest change, immediate win for every tag's
landing), then Tier 1 (the structural fix that removes cost entirely
for leaf tags, rather than just making it faster), then Tier 2
(determinism improvement, smallest impact of the three).

---

## 2. [Embedding-specific fix] Where embedding is spent, and how to make it scale better for the tags that do need it

Embedding happens in `_block_embeddings()`
(`src/aryx/resolution/run.py:80`, `vectors = broker.embed([r.text for r
in batch])`), called from `resolve()` for every multi-member block, with
an existing `ThreadPoolExecutor(max_workers=embed_workers)` prefetch
across blocks (added 2026-09-23, per that function's own comments) — so
concurrency across blocks is already handled. The `id` tag never reached
this code path at all (see §1's correction), so this section is **not**
about that tag specifically — it's the requested, separate fix for
tags that *do* legitimately reach full fuzzy/embedding-based resolution
(the `"normal"` path: decent selectivity, under `er_chunk_threshold`,
not exact-match).

**Implemented** exactly as sketched below, in `src/aryx/resolution/run.py`
— verified against `tests/test_resolve_run_wiring.py` and
`tests/test_embed*`, no regressions. The secondary verification-only step
(re-checking `er_min_key_selectivity`/`er_chunk_threshold` against XML
data) is not done — it's an observation/validation task, not a code
change.

**The scalable improvement available here: dedupe identical text values
before embedding, not after.** `_block_embeddings()` today embeds every
record's text independently, including exact duplicates within the same
block (e.g. two different `PurchaseOrder` records that happen to share
an identical name string). Each embedding API call has fixed latency and
cost regardless of how "new" the text is — deduplicating first turns
O(records) embedding calls into O(distinct texts) calls, a real,
measurable win whenever a tag has any repetition at all, with zero
change to resolution correctness (every original record still gets its
value's vector, just via a dict lookup instead of a fresh API call):

```python
def _block_embeddings(records, broker, run_id=None):
    ...
    out: dict[int, list[float]] = {}
    for start in range(0, len(records), cfg.embed_batch_size):
        batch = records[start:start + cfg.embed_batch_size]
        # NEW: dedupe by text within this batch before calling embed().
        unique_texts = list({r.text for r in batch})
        text_to_vec: dict[str, list[float]] = {}
        try:
            vectors = broker.embed(unique_texts)
            if vectors:
                text_to_vec = dict(zip(unique_texts, vectors))
        except Exception as exc:
            ...  # unchanged failure handling
        for r in batch:
            if r.text in text_to_vec:
                out[r.record_id] = text_to_vec[r.text]
    return out
```

This is scoped tightly to `_block_embeddings()` — no change to blocking,
scoring, or the surrounding `resolve()` orchestration — so it's safe to
land independently of §1's tag-classification fix, and benefits every
existing caller of `resolve()`/`resolve_run()` across the whole system,
not just cpq_ingestion XML.

**Secondary, verification-only step (not a code change):** confirm
`er_min_key_selectivity` and `er_chunk_threshold`
(`src/aryx/config.py` or wherever `Settings` is defined) were tuned
against typical CSV/document data, and re-validate they're still the
right defaults for cpq_ingestion XML-derived tags, which can have a very
different cardinality/selectivity profile (e.g. many more
near-100%-unique leaf tags than a typical CSV sheet would).

---

## 3. [Resource risk] API container near its memory limit during a single large confirm

**Observed:** `docker stats` showed `aryx-api-1` at **2.7GiB / 3GiB
(~90%)** memory usage while this one confirm job was running, with no
other heavy jobs active.

```
CONTAINER    MEM USAGE / LIMIT   MEM %
aryx-api-1   2.698GiB / 3GiB     89.92%
```

**Risk:** An OOM-kill mid-confirm is strictly worse than a slow confirm —
no graceful cancellation path, no cleanup, just a dead container and
whatever partial DB state existed at the moment of the kill (note:
PR #429's cleanup only runs on a clean `PipelineCancelled`, not a killed
process).

### Fix

**Implemented (immediate only):** `docker-compose-oci.yml`'s `api`
service `mem_limit` raised 3g → 8g, with a comment pointing at this
section and §0 for why. Not re-measured against a real large-file
confirm (no live job was run during this implementation pass) — the
number is a reasoned estimate, not a profiled one; worth re-validating
against a real run.

**Immediate (operational, ships today):** raise `aryx-api`'s container
memory limit in `docker-compose-oci.yml` for environments expected to
handle 200MB+ XML files — e.g. 3GiB → 6-8GiB, re-measured against a real
large-file confirm to pick a number with real headroom, not a guess.
This is pure mitigation, not a fix for the underlying cause (§3b), but
it is the only change here with zero engineering risk and can land
independently and immediately.

**Real fix:** see §3b below — the memory-complexity root cause is the
full `RawGraphProjection` being held in memory at once; shrinking that
is what actually moves this number instead of just raising the ceiling
it's measured against.

---

## 3b. [Contributing cause for §3] `project_xml_to_raw_graph` streams the *parse*, not the *output* — full result still held in memory at once

**Question that prompted this:** is the Confirm-stage XML-to-raw-graph
step a full DOM load, i.e. the same problem PR #424 already fixed for
this path? Answer: no — confirmed from
`project_xml_to_raw_graph()`'s own docstring
(`src/aryx/cpq_ingestion/raw_graph/xml_projector.py`), it already uses
streaming `iterparse` with `elem.clear()` + parent-detachment, the exact
PR #424 fix for the original "240MB upload stalled 15+ minutes" DOM-load
incident. **That specific problem is not present here.**

What the same docstring is explicit about, though, is a *different*,
still-open characteristic:

> "This removes the DOM's ~30% memory overhead on top of the output, but
> it does **not** change the function's overall memory complexity: every
> element still becomes one retained `RawNode`/`RawEdge` in the returned
> lists, so peak memory is still O(element count) — a 240MB upload with
> millions of elements still produces a multi-GB result either way."

So: the *parse* is streaming (no DOM-load stall), but the *output* —
5.85M `RawNode` + 5.85M `RawEdge` Python objects for this file — is all
constructed and held in memory simultaneously before
`resolve_and_relate_raw_graph()` can process any of it. This is a
distinct, separate contributor to §3's ~90% memory usage, not the same
issue as the DOM-load incident and not fixed by PR #424/#426/#429.

### Fix — stream grouped-by-tag, not the whole document

The scalable shape here mirrors §1/§2: the whole reason the full
projection is held in memory is that `resolve_and_relate_raw_graph()`
needs `group_nodes_by_tag(projection)` before it can process the first
tag — which requires every node to exist first. Breaking that
dependency is the actual fix, in two parts:

1. **`project_xml_to_raw_graph()` emits incrementally instead of
   returning one `RawGraphProjection`.** Since XML is well-nested and
   `iterparse` already visits elements in document order, a node can be
   handed off as soon as its element *ends* (exactly the point the
   current code builds its `RawNode` — see the `event == "end"` branch).
   Change the function (or add a sibling generator function) to `yield`
   each finished `RawNode`/`RawEdge` pair as it completes, instead of
   appending to `nodes`/`edges` lists that live for the whole parse:

   ```python
   def iter_raw_graph_nodes(data: bytes) -> Iterator[tuple[RawNode, list[RawEdge]]]:
       """Same walk as project_xml_to_raw_graph, yielding each node (and
       the edges it participates in) as soon as it's built, instead of
       materializing the whole projection. Peak memory becomes
       O(nesting depth) for the walk itself, plus whatever the CALLER
       chooses to retain (see group-and-flush below) -- not
       O(total element count) regardless of what's done with the output."""
       ...  # same stack-based event loop as today, yield instead of append
   ```

2. **`resolve_and_relate_raw_graph()` groups-and-flushes per tag instead
   of grouping the whole document up front.** Since tags are typically
   NOT contiguous in document order (siblings of different types
   interleave), full streaming grouping isn't possible without *some*
   buffering — but the buffering can be bounded and tag-scoped instead
   of whole-document-scoped: maintain one growing list per tag seen so
   far (`dict[str, list[RawNode]]`), same as today's `by_tag`, but built
   incrementally from the generator above instead of from a
   fully-materialized `projection.nodes`. This does not reduce peak
   memory to zero (the accumulating per-tag lists still exist), but it
   removes the **DOUBLE** retention today's code has — a full
   `RawGraphProjection` (via `project_xml_to_raw_graph` lazily imported
   at the Confirm-stage call site, line ~545 of `doc_discovery.py`) AND
   effectively the same data again via `group_nodes_by_tag`'s regrouping
   — down to one retained structure.

   For large-file headroom beyond that, the per-tag lists could be
   spilled to a temp store (e.g. the same `PgChunkBackend` pattern
   `resolve_chunked` already uses) once a tag's accumulated size crosses
   a threshold, rather than requiring every tag's full node list to fit
   in memory — a larger change, worth deferring until the simpler
   dedup-the-double-retention step above is measured and found
   insufficient on its own.

This fix is more invasive than §1's (touches the parser's public
contract, not just the resolve orchestration), so it should be scoped
and measured separately — likely as its own follow-up PR, not bundled
with §1/§2.

### Implementation plan (added after PR #430's review round, 2026-10-04)

**Implemented**, gated behind a new, default-OFF setting
(`ARYX_CPQ_STREAMING_PROJECTION_ENABLED`) rather than replacing the eager
path outright — this is the most invasive change in the whole document
and has no live-run verification yet (same caveat as N3 for §1 Tier 0's
batch size), so it ships as an opt-in alternative path, not a default-on
behavior change, until someone runs it against a real large file and
compares entity/relationship counts against the eager path's output for
the same file.

1. **`xml_projector.py`: added `iter_raw_graph(data, should_stop=None) ->
   Iterator[tuple[RawNode, RawEdge | None]]`.** Same stack-based
   `iterparse` walk as `project_xml_to_raw_graph`, yielding each finished
   node together with the one edge connecting it to its parent (`None`
   for the root) instead of appending to `nodes`/`edges` lists.
   `project_xml_to_raw_graph` itself is UNCHANGED and stays the default
   for every other caller (the Read-stage Pass 1 write, tests, anything
   not opted into streaming) — this is a new sibling function, not a
   replacement, exactly as the original sketch above proposed. One
   correction from the original sketch: nodes yield in finish (post-)
   order, not id (pre-)order, since an element can only be yielded once
   it ends — the eager function's id-ordered list comes from pre-reserving
   each node's list slot at *start* time, which a generator has no list to
   do. Relative left-to-right order among same-tag siblings (the
   guarantee that actually matters for per-tag grouping and merge
   tie-breaks) is preserved either way. 30 new tests in
   `tests/cpq_ingestion/test_xml_projector.py`, including a
   `tracemalloc`-based peak-memory comparison proving the walk's own
   memory doesn't scale with element count.
2. **`structural_leaf.py`: decoupled `fold_structural_leaf_tags` from
   `RawGraphProjection`.** Its only two uses of the projection object were
   `.edges` (classification + parent lookup) and `.nodes` (building
   `nodes_by_id`, itself only needed when something actually folds).
   Its signature now takes `edges: list[RawEdge]` directly and derives
   `nodes_by_id` from `by_tag.values()` instead of a separate
   `projection.nodes` list, removing the ONLY remaining reason a
   streaming caller would need to materialize a full node list at all —
   both the eager and streaming paths now share this function unchanged.
3. **`resolve_relate.py`: `resolve_and_relate_raw_graph()` now accepts
   `xml_bytes: bytes | None` as an alternative to `projection`
   (exactly one of the two must be given).** When given bytes and the
   feature flag is on, it builds `by_tag` incrementally by consuming
   `iter_raw_graph()` directly instead of calling `group_nodes_by_tag()`
   on a fully-materialized projection — never holding a separate
   full-document node list at any point. The accumulated `edges` list is
   still built in full either way (needed in full later for
   `translate_containment_edges()`, which reasons about the whole
   document's containment structure at once) — this fix targets the
   node-list double-retention specifically, exactly as scoped above, not
   the edges list.
   **Known limitation, documented not silently dropped:** the opt-in
   `ARYX_CSV_BML_ENABLED` query-table enrichment (`with_query_tables()`)
   operates on a complete `RawGraphProjection` and has no streaming
   equivalent — when both flags are on, the streaming path falls back to
   materializing the full projection anyway (correctness over memory
   savings) rather than silently skipping enrichment. 9 new tests in
   `tests/cpq_ingestion/test_resolve_and_relate_raw_graph.py` cover both
   flags/fallback combinations, `should_stop` forwarding into whichever
   parse path is active, and that the streaming path produces the exact
   same tags/calls as the eager path for equivalent input.
4. **`doc_discovery.py`: the cpq XML loop now calls
   `resolve_and_relate_raw_graph(xml_bytes=..., ...)` directly instead of
   calling `project_xml_to_raw_graph()` itself and passing a projection.**
   The eager-vs-streaming decision moved entirely into
   `resolve_and_relate_raw_graph()`, so this call site no longer needs to
   know which path is active. Default (flag off) behavior is byte-for-byte
   the same code path this document's other sections were already
   implemented and tested against — confirmed via updated tests in
   `tests/cpq_ingestion/test_ingest_confirmed_raw_graph_wiring.py`,
   `tests/cpq_ingestion/test_ingest_confirmed_csv_direct_wiring.py`, and
   `tests/test_doc_discovery.py` (all three previously asserted
   doc_discovery.py called `project_xml_to_raw_graph` directly; now
   assert it does NOT, and that `resolve_and_relate_raw_graph` receives
   `xml_bytes` instead).
5. **Verification, still not done:** run the same `aSTRO25_ConfigData.xml`
   file (or an equivalent large synthetic fixture) through both paths and
   diff the resulting entity/relationship counts and `docker stats` peak
   memory — this is the live-run confirmation N3 already flagged as
   missing for §1 Tier 0, now also needed here before flipping the
   default to on. Nothing in this environment can run that confirm job,
   so this stays an open item for whoever has access to trigger one.

---

## 4. [Performance] Slow Oracle queries observed on unrelated UI endpoints

**Observed:** Six `db.oracle.slow_statement` warnings (threshold 2000ms)
in a 20-minute window, independent of the confirm job itself — ordinary
UI polling (`/data/sources`, `/data/summary`) across several workspaces:

| Operation | Duration | Rows |
|---|---|---|
| `SELECT aryx_datasource` | 5,793 ms | 0 |
| `WITH ...` | 2,226 ms | 0 |
| `SELECT aryx_datasource` | 14,646 ms | 0 |
| `SELECT aryx_datasource` | 31,862 ms | 0 |
| `WITH ...` | 13,860 ms | 0 |
| `INSERT aryx_landed_record` (executemany, 500 rows) | 2,399 ms | 500 |

**Root cause:** Unclear from logs alone — likely a missing/suboptimal
index on `aryx_datasource` for workspace-scoped lookups, possibly
compounded by Oracle ADB resource contention from the confirm job's own
heavy concurrent activity (the `INSERT aryx_landed_record` row suggests
at least some of this contention is real, not purely pre-existing).

### Fix

**Step 1 (must happen before any code change — this is a diagnosis gap,
not a confirmed root cause):** capture the actual SQL text + `EXPLAIN
PLAN`/`DBMS_XPLAN` for the slow `aryx_datasource` select (find its
source via `src/aryx/queries/*.sql` / `oracle/*.sql` by matching the
operation name), and re-measure with no confirm job running concurrently
— needed to separate "genuinely slow query" from "contention from this
test's heavy concurrent landing/resolve activity on the same Oracle ADB
instance." The `INSERT aryx_landed_record` row in the same window
suggests at least some of this is real contention, not purely
pre-existing, so don't assume it's an indexing problem without checking.

**Step 2 (conditional on what Step 1 finds):**
- If the plan shows a full table/partition scan for a workspace-scoped
  lookup: add a composite index on `(workspace_id, ...)` matching the
  actual filter predicate in the query.
- If it's genuinely contention (not a bad plan): consider routing
  interactive UI reads (`/data/sources`, `/data/summary`) to a read
  replica or a less-contended connection pool than the one bulk-landing
  writes use, so a large confirm job doesn't visibly degrade unrelated
  UI responsiveness for other users/workspaces.
- Either way: this is independent of §1-§3b and can be scoped and fixed
  on its own schedule.

### Implementation plan (added after PR #430's review round, 2026-10-04)

Step 1 genuinely cannot be completed from this environment — there is no
live Oracle ADB session available here to run `EXPLAIN PLAN`/`DBMS_XPLAN`
against, and re-measuring "with no confirm job running concurrently"
needs an actual environment with and without that load, which this
investigation doesn't have access to trigger. Implementing a specific
fix (an index, a connection-pool split) without that data would be
guessing, exactly what this section originally warned against. What
**was** implemented instead is the tooling to make Step 1 automatic the
next time this threshold trips, plus one narrowly-scoped, low-risk
improvement justified by static analysis of the one query we already
know the shape of:

1. **Implemented — automatic plan capture on every slow statement.**
   `src/aryx/store/oracle_cursor.py`'s `_log_stmt_ok()` already fired at
   exactly the `SLOW_STATEMENT_MS` (2000ms) threshold this section's
   evidence came from — it just didn't capture anything about *why* the
   statement was slow. Added `_capture_explain_plan()`: a best-effort
   `EXPLAIN PLAN FOR <sql>` + `DBMS_XPLAN.DISPLAY` call, truncated to
   2000 chars and included in the existing `db.oracle.slow_statement`
   raven_log event as `explain_plan`. Deliberately opens a **fresh**
   cursor off the same connection (`cur.connection.cursor()`) rather than
   reusing the statement's own cursor — reusing it would silently discard
   an active, unfetched result set (e.g. a `SELECT` whose rows the caller
   hasn't read yet) out from under the caller. Wrapped in try/except so a
   plan-capture failure can never break the real query path. This turns
   Step 1 from "someone has to reproduce this live" into "already
   captured, next time it happens." 11 new tests in
   `tests/test_oracle_cursor_explain_plan.py` (no live Oracle session
   used — mocked connection/cursor objects shaped like oracledb's API),
   covering the fresh-cursor isolation, close-on-failure, the
   slow/fast-statement threshold gate, and backward compatibility for
   call sites that don't pass `sql`/`cur`.
2. **Implemented — one speculative, low-risk fix:**
   `select_datasources.sql` (`SELECT ... FROM aryx_datasource WHERE
   workspace_id = ? ORDER BY created_at DESC`) is confirmed as the source
   of the `SELECT aryx_datasource` rows in the evidence table
   (`/data/sources` -> `data_api.py`'s `sources()`/`summary()` handlers).
   Both Postgres and Oracle already have `aryx_datasource_ws_idx ON
   aryx_datasource(workspace_id)`, so the `WHERE` is already indexed —
   but the index doesn't cover the `ORDER BY`, meaning Oracle still has
   to sort every matching row after the index lookup. New migration
   `0049_datasource_ws_created_idx.sql` (both backends) adds
   `idx_datasource_ws_created ON aryx_datasource (workspace_id,
   created_at DESC)`, a genuine covering index for this exact query
   shape, eliminating the sort step entirely. The old, now-partially-
   redundant `aryx_datasource_ws_idx` is left in place rather than
   dropped — nothing in this investigation established it's safe to
   remove. This is additive and can only help-or-be-neutral for this
   specific query regardless of whether indexing turns out to be the real
   root cause — but it is **not** presented as a confirmed fix for the
   5.8s-31.8s durations observed; those remain unexplained pending plan
   capture, and contention from the concurrent confirm job (the `INSERT
   aryx_landed_record` row in the same window) is still an equally live
   hypothesis this change does nothing about.
3. **Explicitly not implemented:** the connection-pool-separation idea
   from Step 2. `src/aryx/store/pool.py` has exactly one shared pool per
   DSN today (already raised from 10 to 25 connections once before, for
   a related contention incident) — splitting UI-read traffic onto a
   second pool/DSN is a real architectural change (new pool, every UI
   read call site rewired to request it) that deserves its own scoped
   change once Step 1's captured plan data says contention, not a bad
   plan, is the actual cause. Implementing it speculatively now risks
   solving the wrong problem.

---

## 5. [Known, carried from PR #429 — two since fixed, one still open]

Originally three items, carried here only so this document stays a
complete record of open issues in this area. Two have since been fixed
(this session); the third remains open and is now better understood
(PR review round 4, N2, 2026-10-04):

- ~~Re-confirming a cpq XML file that already fully completed duplicates
  entities~~ — **fixed**: the cpq loop now participates in the same
  `completed_plans`/`discovery_id` resume tracking the generic CSV path
  already had, keyed by `source_filename` (prefixed `cpq:...` since round
  4 N3, to keep it out of the generic path's `plan["filename"]` key
  space).
- ~~`aryx_entity_member` rows are not cleaned up on entity delete~~ —
  **fixed**: all three delete methods now clean up members first, same
  transaction. `delete_entities_by_type()` was further corrected in round
  4 (N1): deletes via a subquery on the `workspace_id`/`ontology_type`
  predicate rather than the earlier id list, closing both an unchunked-
  large-array risk and a race where a concurrently-inserted entity of the
  same type was caught by the final type-predicate delete but never made
  it into the member cleanup.
- **Still open, narrowed (PR review round 4, N2):** the fix above only
  covers a file that already **fully completed**. A hard crash
  **partway through** a file — the exact case the heartbeat-sweep
  watchdog (§0) exists to catch — runs no cleanup: `resolve_and_relate_
  raw_graph()`'s own orphan-cleanup (`_delete_orphaned_entities`) only
  fires on a graceful `PipelineCancelled` exception (an explicit
  `should_stop()` check or run_pipeline's own cancellation checkpoint); a
  hard process kill means no Python exception handler ever runs at all.
  Re-confirming after such a crash re-resolves every tag from scratch,
  creating duplicates alongside whatever partial entities the killed
  attempt already wrote. A fuller fix needs either (a) deleting the
  previous attempt's partial entities for that source file before
  re-resolving (requires a reliable way to identify "entities from the
  last attempt at this file," which nothing currently tracks across a
  process restart), or (b) per-tag completion tracking so a resume only
  redoes the tags that were genuinely incomplete, mirroring the
  per-tag-level resumability `resolve_and_relate_raw_graph()`'s own
  docstring already calls out as "a separate, larger feature... out of
  scope for this PR." Not attempted this round — same reasoning as
  `project_workspace_graph` cancellation below: a real, scoped feature on
  its own, not a drive-by fix.
- `project_workspace_graph` (the final curated-graph write) is still not
  cancellable mid-write — same-magnitude fix as PR #425, affects every
  ingestion path in the system, not just cpq_ingestion XML.

---

## 6. [Minor / informational — not bugs]

- `source_catalog` correctly fell back to asset-reconstruction for this
  file's original-content storage (233,959,819 raw bytes exceeds
  Postgres's ~178MB jsonb inline cap) — working as designed. Worth
  confirming the reconstruction path performs acceptably if someone
  downloads the original file later, since it was never verified at this
  file size specifically.
- `oracle_migrate` logs several `WARNING: block skipped` lines on every
  container boot (idempotent migration replay against an
  already-migrated schema — `ORA-01430`, `ORA-00955`, `ORA-02443`, all
  "already exists/already dropped" class errors). Functionally harmless,
  but noisy, and means every boot re-attempts and catches errors for
  migrations that are already fully applied.

  **Implemented:** `src/aryx/store/oracle_migrate.py` now creates
  `aryx_schema_migrations(filename, applied_at)` on boot (idempotently —
  same catch-ORA-00955 pattern every other block in this file already
  uses) and skips any file already recorded in it, with no execute and no
  catch-and-log for those. Checked first per the note below: the Postgres
  side (`src/aryx/store/migrate.py`) has no equivalent tracking at all, so
  this is new, not a dup. Verified against `tests/test_oracle_migrate.py`
  (14/14 pass unchanged). The next boot after this ships will still do one
  full replay (first time the table is empty); every boot after that is a
  true no-op for already-applied files.

  **Fix:** add a `schema_migrations(filename, applied_at)` tracking
  table (standard pattern — check `src/aryx/store/oracle_migrate.py` for
  the current replay loop structure first, since this may already
  partially exist for the Postgres side via a different mechanism worth
  reusing rather than duplicating). On boot: read the set of already-applied
  filenames once, skip any migration file already in that set entirely
  (no execute, no catch-and-log), and insert a row only for files
  actually newly applied. This turns every boot after the first on a
  given schema into a true no-op for already-applied migrations instead
  of a full catch-every-expected-error replay — faster boot, clean logs,
  and removes the (admittedly currently-harmless) risk of an
  `error=...` pattern-match in the replay logic someday silently
  swallowing a *real* migration failure that happens to produce a
  similar-looking Oracle error code.

---

## 7. [Observability] The chunked resolve path is silent for minutes at a time — a healthy run looks stalled

**Observed live, same job:** after `"resolve path: chunked"` was chosen for
the 439,946-record `id` tag, the logs went quiet for 4+ minutes at a
stretch (08:27:51 → 08:32+) with no sign the job was still making
progress. The job's own `/admin/jobs/{id}` status stayed at
`"detail": "Resolving aSTRO25_ConfigData.xml directly from its raw
graph…", "pct": 0` the entire time — nothing externally visible
distinguishes "still working, 60% through scoring 1,300 blocks" from
"hung."

**Root cause:** `resolve_chunked()`'s three passes
(`src/aryx/resolution/chunked.py`, `src/aryx/resolution/chunked_backend.py`)
only logged at block/batch-level *detail*, and that detail was
`DEBUG`-gated:
- `_key_pass` (`chunked_backend.py`) persisted membership rows in batches
  of 10,000 with no log line of any kind — the landing phase's own `BatchSink`
  logs `"spine progress records=N"` every batch, but the key pass had no
  equivalent.
- `_score_pass` (`chunked.py`) only logged a block via
  `raven_log("DEBUG", ...)`, gated by `would_log("DEBUG")` — invisible at
  the `INFO` level this stack runs at. The only `INFO`/`WARNING`-level
  output from this pass is the oversized-block skip warning, which is
  conditional and can legitimately not fire for minutes if blocks are
  reasonably sized.
- `PgChunkBackend` (`src/aryx/store/chunk_backend.py`) — the Postgres/Oracle
  persistence layer backing the chunked passes — had no logging of its own
  at all; the only visibility into its cost came indirectly, from the
  DB-layer's automatic `db.oracle.slow_statement` instrumentation on
  individual `executemany` calls (not progress through the run).

This is a pure observability gap, not a correctness or performance bug —
the run genuinely was making progress the whole time. But paired with §1's
original mis-diagnosis (made by me, in this same document, before the job
finished), this is exactly the kind of gap that produces wrong diagnoses:
without progress logs, a slow-but-healthy chunked run and an actually-stuck
one look identical from the logs.

**Fix — implemented** (also now additionally threads `on_progress` as a
liveness heartbeat for §0's watchdog, not just logging — see §0):
- `chunked_backend.py` `_key_pass`: logs
  `"chunked key pass progress run=%s members_persisted=%d"` every 50,000
  membership rows persisted (mirrors the landing phase's `"spine progress"`
  cadence/style), plus a `raven_log("INFO", "P4",
  "ingest.resolve.chunked_key_pass_progress", ...)` structured event, and a
  final `"chunked key pass done"` line.
- `chunked.py` `_score_pass`: tracks `blocks_done`/`edges_total` and logs
  `"chunked score pass progress run=%s blocks_done=%d edges_persisted=%d"`
  every 100 blocks scored (existing per-block `DEBUG` detail is unchanged —
  this is an additional `INFO`-level checkpoint, not a replacement), plus a
  matching `raven_log("INFO", "P4",
  "ingest.resolve.chunked_score_progress", ...)` and a final "done" line
  with the run's totals.
- `store/chunk_backend.py` `PgChunkBackend.add_members` /
  `PgChunkBackend.add_edges`: each now logs a `DEBUG`-level line with the
  row/edge count persisted per call, giving fine-grained visibility into
  the actual DB-bound cost when `DEBUG` is enabled, without adding noise at
  the default `INFO` level (the `INFO`-level checkpoints above already
  cover the "is this still running" question day-to-day).

Net effect: a job sitting in the chunked path now produces a periodic,
`INFO`-visible heartbeat the whole way through all three passes, the same
guarantee the landing phase already has via `"spine progress"`. Verified
against the existing `tests/test_chunked_resolution.py` suite (21 tests
including the §0 `on_progress` additions, all pass — the logging and
progress callback are additive and side-effect-free).

---

## 8. [UI/job-status] `/admin/jobs/{id}` reports `pct: 0` for a cpq XML file's entire resolve, regardless of actual progress

**Observed live, same job:** polling `/admin/jobs/00d728e8de0145de82ed722c88f0799d`
the whole time this file's tags were landing, resolving, and scoring
(§1, §7) showed `"detail": "Resolving aSTRO25_ConfigData.xml directly
from its raw graph…", "pct": 0` without ever changing — not a rounding
artifact, the job-status row was never updated again after the single
call made right before `resolve_and_relate_raw_graph()` started.

**Root cause, found by reading `doc_discovery.py`'s `ingest_confirmed()`
and `resolve_relate.py`'s `resolve_and_relate_raw_graph()` side by side:**
- The cpq XML loop (`for source_filename, plan in
  cpq_ingestion_source_files.items():`) calls `jobs.update_stage(...)`
  exactly **once**, immediately before `resolve_and_relate_raw_graph()`
  is called, and never again until that call returns — which, per §1, can
  be 30+ minutes for one tag alone, let alone a whole multi-tag file.
- That one call also never incremented the loop's own `step` counter the
  way every other confirm loop does (the per-mention-type loop at line
  357 does `step += 1`; the tabular `_run_one_plan` loop passes its own
  `plan_step`) — so `pct = int(step * 90 / total)` used whatever `step`
  happened to be left at by a prior loop (commonly `0`), making `pct`
  literally `0` rather than merely coarse.
- The deeper gap: `resolve_and_relate_raw_graph()` never accepted an
  `on_progress` callback at all, even though `run_pipeline()` — called
  once per tag, inside this very function — already supports one
  (`orchestrate.py`'s `Progress` type, emitting `Discover` / `Resolve` /
  `Relate` / `Project` stage updates at 0-100 internally) and every other
  confirm loop in `doc_discovery.py` (`_progress_otype`, `_progress_plan`)
  already wires it up. The cpq XML loop was simply never connected to
  this existing mechanism.

**Fix — implemented:**
- `resolve_relate.py`: `resolve_and_relate_raw_graph()` now accepts an
  `on_progress: Progress | None = None` parameter. Inside the per-tag
  loop, each tag gets a wrapper (`_tag_progress`) that forwards its
  `run_pipeline()` call's own 0-100 signal, rescaled across however many
  tags the file has: `overall_pct = int(((tag_index - 1) * 100 + pct) /
  total_tags)`, with `stage`/`detail` prefixed `"{tag_index}/{total_tags}"`
  and the tag name, so the UI can show e.g. `"3/7 · Resolve"` /
  `"[id] 214 entities resolved"` instead of one static string for the
  whole file.
- `doc_discovery.py`'s cpq XML loop: now does `step += 1` per source file
  (matching every other confirm loop, and consistent with `total` already
  counting every approved file including XML ones — `total = len
  (approved_types) + len(approved_files)` already had a slot reserved for
  this file, it just was never advanced into). A new `_progress_cpq`
  closure, written to the same convention as `_progress_otype`/
  `_progress_plan` (`int(_step * 90 / total) + pct // 10`), is passed as
  `on_progress` into `resolve_and_relate_raw_graph()`.
- Same fix is needed for the cpq **CSV**-direct loop just above it in
  `doc_discovery.py` (`land_csv_directly()` path) — it has the identical
  "one static `update_stage` call, no `step += 1`" shape, but
  `land_csv_directly()` doesn't currently accept an `on_progress` either.
  Not fixed in this pass (smaller cost per file, no internal multi-stage
  pipeline to report sub-progress from, lower priority) — tracked here so
  it isn't lost.

Net effect: a cpq XML confirm's job-status row now advances smoothly
through `pct` across both tags within a file and files within a job,
instead of sitting at a single frozen value (typically `0`) for the
entire duration. This is a pure progress-reporting change — no change to
what gets resolved, related, or projected. Verified against
`tests/cpq_ingestion/test_resolve_and_relate_raw_graph.py` and
`tests/test_doc_discovery.py` — no regressions beyond the pre-existing,
unrelated `_FakeSettings.effective_dsn` gap.

## Suggested priority order

All items below are now implemented on
`fix/cpq-xml-confirm-performance-2026-10-04` (see each section's
"Implemented" note for files/tests). §3b and §4 shipped opt-in/partial
rather than as default-on behavior changes, per their own sections'
reasoning — both still need a live confirm run to verify before being
turned on by default or considered fully closed.

0. **✅ §0 (job-level liveness/heartbeat + watchdog for a crashed worker) —
   highest priority, supersedes everything below.** Every other item in
   this document assumes a job that's running slowly is still making
   progress. §0 proved that assumption can be false with zero visible
   symptom anywhere in the system — a silently crashed worker leaves a
   job permanently "running" with no error ever recorded.
1. **✅ §7 + §8 (chunked-pass progress logging; cpq XML job-status `pct`
   reporting).** Directly enables correctly diagnosing the rest of this
   list on future runs instead of guessing from silence or a stuck-looking
   progress bar, and was a prerequisite for §0's heartbeat to be safe.
2. **✅ §1 Tier 0 (raise `BatchSink`'s landing batch size + investigate
   Oracle `executemany` round-trip cost)** — batch size done; the Oracle
   `executemany` round-trip investigation itself needs live profiling, not
   done.
3. **✅ §3 immediate (raise the container memory limit)** — operational,
   zero engineering risk, directly reduces the memory pressure implicated
   in §0's crash.
4. **✅ §1 Tier 1 (structural-leaf tag classification / property-folding)**
   — the real architectural fix for §1: removes landing + resolve cost
   entirely for non-entity tags instead of just making it faster.
5. **✅ §2 (embedding dedup-by-text)** — small, safe, independently
   shippable; benefits every `resolve()` caller system-wide, not just
   cpq_ingestion.
6. **⬜ §3b (stream the raw-graph projection by tag instead of
   materializing the whole document) — still a design only.** The real
   fix behind §3's memory number (and a direct contributor to §0's
   crash); larger and more invasive than the others here (touches the
   parser's contract), scope as its own follow-up PR, deliberately not
   bundled into this one.
7. **✅ §1 Tier 2 (force exact-match for generic-fallback-key tags)** —
   smallest-impact piece of §1; determinism improvement, not a new
   capability.
8. **⬜ §4 (slow queries) — still a design only.** Needs live profiling
   before a fix can even be chosen; independent of the XML confirm path
   specifically, and this pass had no live job to profile against.
9. **✅ §6 (migration tracking table)** — low priority, cosmetic/
   operational cleanliness only, but cheap enough to include.

---

## Update — live verification (2026-10-04, same day, against a real dev_oci Oracle ADB instance)

The three gaps flagged as unverified at the top of this document — §3b's
parity, §1 Tier 0's actual speedup, and §4's root cause — were revisited
with access to a real, isolated dev `docker-compose-oci.yml` stack (Oracle
ADB 26ai, `ARYX_GRAPH_BACKEND=oci_graph`, so the graph projection lives in
the same Oracle ADB instance as the relational data, not a separate
FalkorDB). All tests below used synthetic data in disposable, uniquely-
named workspaces/rows, cleaned up afterward and confirmed removed.

**Caution learned the hard way, recorded here so it isn't repeated:** an
early attempt to reproduce Oracle connection-pool exhaustion
(`OraclePool`, `max_size=25`, `wait_timeout=30000` in
`src/aryx/store/oracle_connection_pool.py`) used 25 threads racing to
acquire connections simultaneously via a `threading.Barrier`. Several
threads raised `DPY-4011`/`DPY-4005` before reaching the barrier, which
never completed, leaving the main thread (and the barrier) permanently
stuck. Killing the *host-side* process wrapper (equivalent of Ctrl-C on
the launching shell) did **not** kill the actual Python process running
inside the container — it kept running, continuing to hammer new Oracle
connections, and new connection attempts against the instance hung
indefinitely until that process was found (via `/proc` inside the
container) and killed directly. The already-running application was
unaffected throughout (it kept serving real requests off its own
long-lived pool in under 3ms) — only *new* connection/pool creation was
blocked. Any future live testing against a shared or long-running
container should avoid concurrent/threaded connection-acquisition tests
entirely, or at minimum verify the test process actually exits before
moving on.

A second lesson: the running `aryx-api-1` container turned out to be a
**frozen image built before this branch's commits** — `/app/src` is baked
into the image at build time, not bind-mounted, so editing files on the
host had no effect on the running container. This was only caught because
a live `Settings` object was missing fields (`cpq_structural_leaf_fold_
enabled`, etc.) that this branch added. The image was rebuilt
(`docker compose -f docker-compose-oci.yml build api` — note: the legacy
Python `docker-compose` v1 binary on this host fails on BuildKit-built
images with `KeyError: 'ContainerConfig'`; `docker compose` v2 does not)
and the container recreated before any of the §3b/§1 results below are
meaningful. Any future live verification on this host should confirm
`get_settings()` reflects the branch under test *before* relying on
results.

### §3b: full-pipeline streaming vs. eager parity — ✅ confirmed at 3,000-record scale

Built a synthetic 3,000-record XML file (`<Root><Record><id>.../id><Name>
.../Name></Record>...</Root>`, 178,903 bytes) and ran the full
`resolve_and_relate_raw_graph()` pipeline twice, sequentially, into two
disposable workspaces — once with `projection=` (eager), once with
`xml_bytes=` and `ARYX_CPQ_STREAMING_PROJECTION_ENABLED=true` (streaming):

| | eager | streaming |
|---|---|---|
| tags resolved | 2 (`Root`, `Record` — `id`/`Name` correctly folded) | 2 |
| entities | 3,001 | 3,001 |
| relationships | 3,000 | 3,000 |
| provenance rows | 3,001 | 3,001 |
| wall-clock | 60.9s | 60.5s |

Entity payload sets (ontology_type + properties, ignoring entity_id
numbering, which legitimately differs between runs) were compared
exhaustively and found **byte-identical**. This is the first time the
full pipeline — not just the XML parser — has been run both ways and
compared; prior test coverage (`tests/cpq_ingestion/test_xml_projector.py`)
only verified parser-level node/edge equivalence, not that folding +
resolve + relate + graph projection produce the same end state.

**Still open:** this is 3,000 records, not the real file's 439,946 —
scale was kept deliberately small for a sequential, single-connection live
test on a shared instance. The *mechanism* that would most plausibly break
at larger scale (memory growth during the streaming walk itself) is
already covered by `test_iter_peak_memory_does_not_scale_with_element_
count` at 20,000 elements; what live testing adds here is pipeline-level
correctness (folding/resolve/relate/graph-projection parity), which
doesn't have an obvious scale-dependent failure mode the way memory does.
Still recommend §3b stay opt-in until someone runs it against the actual
large file, but the specific "does streaming produce different results"
risk this document flagged is now directly addressed, not just argued.

### §1 Tier 0: landing batch size — ✅ confirmed 3.84x speedup

Landed 15,000 synthetic records via `BatchSink`/`PostgresStore.
insert_records` at `batch_size=500` (current default at the time §1 was
written) vs. `batch_size=3000` (the proposed setting), against the same
live Oracle ADB instance:

| batch_size | total time | ms/record | round-trips |
|---|---|---|---|
| 500 | 30.63s | 2.04 | 30 |
| 3000 | 7.97s | 0.53 | 5 |

**3.84x speedup**, consistent with the ~2.4s-per-500-rows figure
`config_core.py`'s own comment cites from the original live incident.
`ARYX_LANDING_BATCH_SIZE` is already set to `3000` in this dev_oci
environment.

### §4: slow Oracle queries — partially explained, one new risk found, root cause still open

Captured a real `EXPLAIN PLAN` for `select_datasources.sql` (the
confirmed source of the `SELECT aryx_datasource` rows in the original
evidence table) at two scales:

- **At the table's real current size (11 rows):** cost 4, trivial.
- **At a synthetic 5,003-row scale (one workspace):** cost 16, plan is
  `INDEX RANGE SCAN` (`ARYX_DATASOURCE_WS_IDX`) → `TABLE ACCESS BY INDEX
  ROWID BATCHED` → `SORT ORDER BY`. **Not a full table/partition scan** —
  the "missing index causing a full scan" hypothesis from this section's
  original root-cause guess does not hold for this query at this scale.

**New finding — the new covering index may not help even when it should.**
Migration 0049's `idx_datasource_ws_created` was created live against this
instance (and `DBMS_STATS.GATHER_TABLE_STATS` re-run), but `EXPLAIN PLAN`
for the exact same query **still chose the old index and still did an
explicit `SORT ORDER BY`** — it did not switch to the new covering index
at all. `DBMS_XPLAN`'s own output states *"SQL plan baseline ... used for
this statement"* for both before and after; `USER_SQL_PLAN_BASELINES`
is not queryable from this schema (`ORA-00942`, likely an ADB privilege
restriction), so the baseline's contents couldn't be inspected directly,
but Oracle's own plan output confirms one is active and pinning the old
plan. **This means migration 0049's index, as shipped, may provide zero
actual benefit on an Oracle ADB instance that already has a captured plan
baseline for this statement** — the baseline would need to be evolved
(`DBMS_SPM`) before the optimizer would ever consider the new plan. Not
fixed here (SPM administration needs privileges this schema doesn't have,
and is a bigger, separate change) — flagging as a known limitation of the
already-shipped index.

**Fetch time scales with cursor `arraysize`, but this doesn't explain the
original evidence.** Fetching all 5,003 rows took 16.6s at `arraysize=100`
(oracledb's low default), 5.3s at `arraysize=500` (production's actual
setting via `OracleCursorWrapper`), 3.3s at `arraysize=2000`. Real and
worth knowing, but the original evidence table's three slow
`SELECT aryx_datasource` entries all returned **0 rows** — round-trip
count for a large result set cannot explain a 0-row query taking 5.8-31.8
seconds.

**Contention hypothesis: plausible, not confirmed.** `src/aryx/store/
oracle_connection_pool.py` already documents a prior live `DPY-4005`
pool-timeout incident, with `wait_timeout=30000` (30s) — suspiciously
close to the evidence table's max observed duration (31,862ms). An attempt
to reproduce this directly (saturate the pool, time a 0-row query's
acquire-and-execute) was abandoned after the test itself malfunctioned
(see the caution note above) rather than risk further disruption to the
shared instance. Also worth noting: `oracle_cursor.py`'s `_t0` timer for
the `db.oracle.slow_statement` log starts **inside** `execute()`, on an
already-acquired cursor — so whatever produced the original evidence was
slow *execution*, not pool-acquisition wait, which points more toward
Oracle ADB-side session/resource contention (not yet reproducible from
this schema's privilege level) than the client-side pool. **Root cause
remains open** — this session narrowed it (ruled out bad query plan,
identified the plan-baseline risk, ruled out round-trip count for 0-row
results) but did not conclusively reproduce the original symptom.

---

## Update — PR review round 3 (2026-10-04, after the §5 fixes landed)

A third review round, scoped to Minor findings (N1-N5) against the fuller
implementation (round 2 fixes + §5 fixes + live verification). All five
verified against the actual code before fixing; four were real gaps, one
(N3) was a documentation-accuracy issue only.

- **N1 (confirmed, real gap):** `src/aryx/resolve_entities.py`'s
  `store.save(results)` call was the one remaining unbatched, no-heartbeat
  save in the resolve path — `save_relationships()` got this fix in round
  2, but the entity-save call right before it (58% → 62%, orchestrate.py)
  was missed. At the production file's scale (440k entities/tag) this is
  several minutes of silence inside the same 10-minute heartbeat-sweep
  window round 1/2 already took seriously. Fixed: `EntityStore.save()`
  now chunks `results` into `batch_size`-sized groups (default 5000, same
  as `save_relationships`), each still going through the existing
  2-3-round-trip bulk path (`_save_batch`/`_save_batch_postgres`), with a
  real done/total progress checkpoint scaled into the 58-62% band
  `resolve_entities.py`/`orchestrate.py` already reserve for this call.
- **N2 (confirmed, real correctness gap):** the streaming path's `by_tag`
  is populated in `iter_raw_graph`'s finish (post-)order. Sibling order
  matches the eager path either way (documented, and true), but a tag that
  recurs at more than one nesting depth in the SAME document (e.g. a
  self-nesting category/BOM tree) comes out child-before-parent in
  post-order, while the eager path's id-ordered `projection.nodes` always
  has the parent (lower id, started first) before the child. The
  equivalence tests shipped with §3b — and this session's own live
  verification test — all used flat or non-recurring-tag documents, so
  none of them caught this. Fixed: each tag's node list is sorted by `id`
  immediately after draining the stream, restoring the eager path's exact
  per-tag order before anything downstream (match-key inference, resolve,
  fold) can observe the difference. New test
  (`test_xml_bytes_streaming_restores_id_order_for_self_nesting_tags`)
  uses a real self-nesting `<Category>` tree and the REAL `iter_raw_graph`
  (not mocked) — verified to actually fail without the fix before
  confirming it passes with it.
- **N3 (documentation-accuracy issue, not a bug):** §3b's memory-benefit
  framing was unmeasured and overstated. The big DOM-memory problem this
  module was originally built to fix was already solved earlier by
  `project_xml_to_raw_graph` itself switching to `iterparse` + `elem.
  clear()` — it does not hold a full tree either, and both paths' `by_tag`
  dicts retain every node/edge object regardless (same objects, not
  copies). Measured directly: 160.7 MB (eager) vs. 157.5 MB (streaming)
  for a 400,000-element flat document — a 2.0% difference, ~8.1
  bytes/node, matching the reviewer's own ~8-byte pointer-list prediction
  almost exactly. Real and free, worth keeping opt-in, but modest, not
  dramatic — `resolve_and_relate_raw_graph`'s docstring corrected to state
  this precisely instead of implying a bigger win.
- **N4 (confirmed, real transaction-safety bug):** both `save_
  relationships()` (round 2) and the new `save()` chunking above called
  `on_progress` INSIDE the same `with self._pool.connection()` block as
  the inserts — a heartbeat failure (e.g. a transient error from the
  job-row update it typically triggers, on a completely different
  connection/pool) would propagate out of that block and roll back every
  batch already inserted, failing an otherwise-healthy save over a purely
  observational side effect. Fixed: both routed through a new
  `_safe_progress()` helper that catches and logs any `on_progress`
  exception, never letting it escape. Also moved the `Progress` type
  alias to after the import block (it was sitting between stdlib and
  third-party imports).
- **N5 (acknowledged as "fine for now", improved anyway):**
  `_capture_explain_plan` ran its two extra queries and logged up to 2,000
  chars of plan text on every slow statement, uncapped — a burst of slow
  batches for the same operation would flood logs for a plan that is very
  unlikely to change moment to moment. Added a simple per-operation rate
  limit (`_should_capture_explain_plan`, 600s/10min default) — the first
  slow occurrence of a given operation still captures a plan immediately;
  subsequent ones within the window skip the extra queries but still get
  their own `slow_statement` visibility (duration, rows) uncapped.

21 new/updated tests across 5 files, all passing (verified both in
isolation and against this branch's full relevant-area regression set).
Confirmed zero new regressions: the only combined-run failures are a
pre-existing, test-order-dependent `caplog`/logging-propagation flakiness
already present on this branch before this round's changes (reproduces
identically with the round-3 diff stashed out) — affects some of this
round's new tests and two pre-existing, unrelated tests the same way, but
every affected test passes reliably standalone and in smaller
combinations.

---

## Update — PR review round 4 (2026-10-04, after the §5 fixes landed)

Three Minor findings against round 3's §5 fixes (member cleanup, cpq
resumability). All verified against the actual code first.

- **N1 (confirmed, real correctness/scale bug):** `delete_entities_by_
  type()`'s member delete sent every id of the type in one unchunked
  `ANY(array)`/`JSON_TABLE` statement, while every other multi-id delete
  in this file chunks at `_DELETE_CHUNK_SIZE` (20,000) for exactly the
  reason this one didn't — a type with hundreds of thousands of entities
  meant one huge bind and one long statement. Worse: an entity of that
  type inserted between the id `SELECT` and the final `DELETE` was still
  caught by the final type-predicate delete (same predicate, re-evaluated
  fresh) but was never in the earlier id list, so its members were
  silently orphaned. Fixed: member cleanup now runs a subquery on the
  same `workspace_id`/`ontology_type` predicate (`DELETE FROM aryx_
  entity_member WHERE ... entity_id IN (SELECT id FROM aryx_entity WHERE
  workspace_id = ? AND ontology_type = ?)`) instead of an id list —
  re-evaluated at delete time, so it has neither the chunking problem nor
  the race. The id `SELECT` is kept only to build this method's return
  value.
- **N2 (confirmed, narrowed, not fixed this round):** the resumability
  fix only covers a file that already fully completed. A hard crash
  partway through a file — the case the heartbeat-sweep watchdog exists
  to catch — runs no cleanup, since `resolve_and_relate_raw_graph()`'s
  orphan-cleanup only fires on a graceful `PipelineCancelled`, never on a
  hard process kill. Re-confirming after such a crash re-resolves every
  tag from scratch, creating duplicates alongside the partial entities
  the killed attempt left behind. A real fix (delete the previous
  attempt's partial entities before re-resolving, or track per-tag
  completion) is a genuine feature on the same scale as the per-tag
  resumability `resolve_and_relate_raw_graph()`'s own docstring already
  calls out as separate, larger, out-of-scope work — not attempted as a
  drive-by fix here. See §5 for the full writeup.
- **N3 (confirmed, two sub-issues, both fixed):** (a) `completed_plans`
  mixed two key spaces — generic tabular plans use `plan["filename"]` (a
  per-tag-derived name), cpq files used the raw `source_filename`. A
  collision was unlikely but not impossible, and silent if it ever
  happened. Fixed by prefixing every cpq entry (`cpq:{source_filename}`)
  so the two spaces can never collide, even accidentally. (b) Finishing a
  plan — tabular OR cpq — wrote `failed_plans: []` unconditionally, and
  since `update_confirm_state()` replaces the whole persisted state (no
  merge), this silently discarded any failed-plan record an earlier
  attempt in the same confirm run had written. In practice this was
  dormant (`failed_plans` is never populated with real content anywhere
  in the current codebase — confirmed by grep), but it was a live landmine
  for whenever that changes, and the pattern existed at BOTH write sites,
  not just the cpq one this review was about. Fixed at both: carry
  forward `state.get("failed_plans", [])` instead of hardcoding `[]`.

New test for N1 (`delete_entities_by_type` now always runs the member
delete via the real query shape, even when nothing currently matches —
the subquery makes that a correct, cheap no-op), 2 existing cpq-resume
tests updated for the new prefixed key format, 1 new test for the
`failed_plans` preservation fix. Verified zero new regressions: full
sweep across the touched areas (`entity_store`, `doc_discovery`,
`ontology_delete_type`, `resolve_and_relate_raw_graph`) shows the exact
same 10 pre-existing, already-documented caplog/logging-propagation
flakiness failures as before this round, no new ones.

---

## Update — PR review round 5 (2026-10-05)

One High, two Medium, two Low, and two Nit findings. All verified against
the actual code first.

- **High, confirmed and fixed: migration tracking was filename-only.**
  `aryx_schema_migrations` recorded a filename once applied and never ran
  that file again — but this repo DOES edit already-applied migration
  files in practice (confirmed: `graph_schema.sql` gained
  `idx_graph_edge_workspace_name` on 2026-09-10 after already shipping;
  `0006_documents.sql`/`0007_jobs.sql` each have 4 commits). An edit like
  that would never reach a database that had already recorded the file,
  with nothing logged. Fixed: each applied file's SHA-256 is now stored
  alongside its filename (`checksum` column, added via an idempotent
  `ALTER TABLE` for a table that already existed pre-checksum). A later
  boot whose file content no longer matches the recorded checksum logs a
  loud, persistent `raven_log` ERROR (`ARYX_MIGRATE_CHECKSUM_DRIFT`) —
  every boot until resolved, not just once — but deliberately does **not**
  auto-re-run the file: a changed migration could be a non-idempotent edit
  that would fail or do the wrong thing a second time, so this surfaces
  the drift for a human rather than guessing it's safe to replay. A
  pre-checksum row (`checksum IS NULL`) is treated as "unknown," not
  "drifted," so the first boot after this ships doesn't fire a false
  alarm for every migration ever applied before this existed. 9 new
  tests.
- **Medium, confirmed, deliberately not changed:** `cpq_structural_leaf_
  fold_enabled` and `cpq_force_exact_enabled` default to `True`, changing
  the curated graph's shape (scalar XML tags become parent properties
  instead of their own entities) without a real confirm-plus-quote job
  having been run against this branch yet (only synthetic/live-verified
  pipeline tests, see the earlier live-verification update). The reviewer
  suggested defaulting both to `False` until that real test happens.
  **Explicitly decided to keep both `True`** — both already ship live on
  `dev_oci`, and flipping the default would revert the actual feature
  this whole investigation exists to deliver, for everyone currently
  running this branch, not just future work. Recorded here as an open,
  known risk rather than silently accepted: if a real confirm+quote job
  surfaces a graph-shape or merge-determinism problem traceable to either
  flag, set `ARYX_CPQ_STRUCTURAL_LEAF_FOLD_ENABLED=false` /
  `ARYX_CPQ_FORCE_EXACT_ENABLED=false` and reopen this item.
- **Medium, confirmed and fixed (the simpler of two offered remedies):**
  a heartbeat-sweep false alarm is destructive, not just a wrong status —
  `make_should_stop()` treats a swept `failed` job as a stop signal, and
  PR #429's mid-loop cancellation cleanup then deletes the entities
  written so far. Heartbeat coverage on the confirm path is good (per-tag
  stages, per-block resolve progress, chunked-resolve and landing
  heartbeats, per-batch save/projection checkpoints) but not total — one
  long operation (an embedding/LLM call retrying under 429 throttling, or
  one large project-stage batch) can still go several minutes with no
  `update_stage` call, and the prior 10-minute default left too little
  margin. Raised `ARYX_JOB_HEARTBEAT_TIMEOUT_MINUTES` default from 10 to
  20. The reviewer's other suggestion (keep the written work when the
  stop was caused by the sweep rather than the user) is a more invasive,
  separate change — distinguishing cause-of-stop throughout the
  cancellation-cleanup path — not attempted here.
- **Low, confirmed and fixed: stale test fake.**
  `tests/test_exact_id_resolution.py::test_resolve_run_wires_exact_ids_
  through` failed on this branch (also standalone) because `resolve_run()`
  now calls `store.save(results, on_progress=_emit)` and the test's fake
  store only accepted the positional argument. `EntityStore` (the only
  real implementation) already accepts `on_progress` — confirmed a stale
  test fixture, not a production bug. Fixed the lambda's signature.
- **Low, confirmed and partially fixed: Raven logging gaps.** The
  "unexpected migration error, NOT marking applied" case only went to
  `logger.error` — now also a `raven_log` ERROR with an error_code
  (`ARYX_MIGRATE_UNEXPECTED_ERROR`), so it can be found/alerted on the
  same way every other real failure in this codebase can. The broader
  point — `.raven/decision-map-baseline.json` gained 5 new (file, symbol)
  entries this session instead of dedicated `raven_log` calls
  (`resolve_relate.py`'s routing `<if>` and `resolve_and_relate_raw_
  graph`, `xml_projector.py`'s `iter_raw_graph`, and `oracle_migrate.py`'s
  `_ensure_tracking_table`/`_mark_applied`) — was accepted as baseline
  debt via `--write-baseline` rather than instrumented, consistent with
  this project's established practice for decision-map findings
  throughout this branch's history. Noted here explicitly rather than
  left silent, since the reviewer's point (baselining isn't the same as
  fixing) is fair.
- **Nits:** `_last_explain_plan_capture`'s rate-limit check-then-set was
  unlocked — harmless (worst case, two threads both capture a plan in the
  same window once), but cheap to close; added a `threading.Lock`.
  Folded structural-leaf values build up as an unbounded Python list on
  the parent node (a parent with thousands of repeated scalar children
  gets one very large JSON property) — not fixed: capping would silently
  drop data, which is worse than a large property, and the right cap (if
  any) is a product decision this investigation isn't positioned to make
  unilaterally. Documented here as a known, accepted characteristic of
  the current folding behavior.

### Follow-up (same day): both ⚠️ items actually fixed, not just baselined

Two items came back after round 5 landed:

- **Test regression, confirmed and fixed.** `tests/test_oracle_migrate.py`
  passed standalone but 4 of its new checksum tests (plus 6 *pre-existing*
  ones, confirmed via a before/after worktree comparison) failed when run
  alongside `test_oracle_pool.py`/`test_datasource_store.py`/etc. Root
  cause: `test_oracle_pool.py` installs a fake `oracledb` module into
  `sys.modules` at **module import time** (a bare top-level call, not
  inside a fixture) — pytest imports every test file during collection,
  before running any of them, so this stub permanently replaces the real
  `oracledb` package for the rest of the process the moment that file is
  collected, regardless of which file runs first. The fake module has no
  `.connect` attribute, so every `patch.object(oracledb, "connect", ...)`
  in `test_oracle_migrate.py` raised `AttributeError` the instant it was
  stubbed. Fixed narrowly, in-scope: added `create=True` to all 4
  `patch.object(oracledb, "connect", ...)` call sites in
  `test_oracle_migrate.py` (tolerates the attribute not existing yet,
  same as a real `connect()` patch would need on a module that hasn't
  been fully stubbed). This didn't just fix the 4 new tests — it also
  fixed the 6 pre-existing ones broken by the same bug before round 5
  ever landed. The actual root cause (`test_oracle_pool.py`'s irreversible
  global stub) is a pre-existing, broader test-isolation issue outside
  this file's scope — not touched here.
- **Raven logging, confirmed and actually fixed this time.** The 5
  decision-map findings accepted as baseline debt in round 5 are now
  properly instrumented instead: `resolve_relate.py`'s streaming/eager
  routing `<if>` and `resolve_and_relate_raw_graph`'s terminal `raven_log`
  now carry every field their decision class (`Routing`/`Outcome`)
  requires (`policy_version`/`trace_id` for the former;
  `task_id`/`final_status`/`duration_ms`/`stage`/`result`/`impact_scope`
  for the latter — tracked via a new `_t0 = time.monotonic()` at function
  entry). `xml_projector.py`'s `iter_raw_graph` cancellation log and
  `oracle_migrate.py`'s `_ensure_tracking_table`/`_mark_applied` (which
  had **no** `raven_log` call at all before this) now carry the
  `Dependency` class's required fields
  (`dependency_name`/`operation`/`duration_ms`/`result`/`error_class`/
  `attempt`/`trace_id`). Verified directly against the decision-map
  scanner itself (`ast_decision_scanner.analyze_file()`), not just by
  re-running `--write-baseline` — all 5 now report
  `existing_log_status="sufficient"` with zero missing fields.

### Follow-up (same day): M1 — the heartbeat default raise never reached the actual deployment

**Confirmed and fixed.** `config_core.py`'s `job_heartbeat_timeout_minutes`
default moved from 10 to 20 in round 5 (the heartbeat-sweep-destructiveness
fix), but `docker-compose-oci.yml` sets
`ARYX_JOB_HEARTBEAT_TIMEOUT_MINUTES=${ARYX_JOB_HEARTBEAT_TIMEOUT_MINUTES:-10}`
on the `api` service — that commit range never touched this file. Since the
env var is always set to *something* in this container (even just the shell
fallback), the Python default never applies there; only an environment that
doesn't pass this var at all (e.g. a bare local run with no compose file)
was ever picking up the code's new value. Fixed: the compose fallback is now
`:-20`, matching the code default it's meant to mirror.

---

## Update — PR review round 6 (2026-10-05)

- **N1, confirmed and fixed:** the unexpected-migration-error `raven_log`
  (added in round 5) used `P1`, but `_EXPECTED_IDEMPOTENT_ORA_CODES` is
  explicitly, by its own docstring, not verified against every migration
  file. A benign code that simply isn't on the list yet would page at P1
  every single boot, on every worker, until the list is fixed — too
  aggressive for a known-incomplete allowlist. Downgraded to `P2`: still a
  real, surfaced schema-incomplete condition, without the on-call urgency
  the current verification state doesn't support. New test confirms the
  `ARYX_MIGRATE_UNEXPECTED_ERROR` raven_log fires at P2.
- **N2, confirmed and fixed:** checksum drift (round 5, N1) logged a
  persistent P2 ERROR every boot with no supported way to clear it short
  of hand-editing `aryx_schema_migrations` directly — and this repo does
  edit shipped migrations in practice, so that's a real, not theoretical,
  need. Added `accept_checksum_drift(dsn, filename)` — updates the stored
  checksum to the file's current content (does NOT re-run the file's SQL;
  that's a separate concern, a new migration if the edit's *effect* needs
  applying too) and logs a `WARN P3` `ARYX_MIGRATE_CHECKSUM_DRIFT_ACCEPTED`
  audit trail entry so the acceptance itself is visible, not just the
  original drift. Exposed via a documented CLI entry point:
  `python3 -m aryx.store.oracle_migrate --accept-drift <filename>`.
  3 new tests (updates the checksum; raises `FileNotFoundError` for a
  missing file; raises `ValueError` if the file was never recorded as
  applied in the first place — nothing to accept a drift for).
- **N3, acknowledged, process action item, not a code change:** the
  reviewer's ask — run one real confirm followed by a quote against this
  branch before merging, since neither `cpq_structural_leaf_fold_enabled`
  nor `cpq_force_exact_enabled` has been checked end to end against real
  production-shaped data (only synthetic/live-verified pipeline tests, see
  the earlier live-verification update) — is correct and can't be
  satisfied by more work in this environment: it specifically requires a
  real customer quote document and a real confirm+quote-generation cycle,
  which this investigation has no access to. Recorded here as an explicit
  **pre-merge checklist item**, not silently deferred: someone with access
  to a real CPQ environment should run one full confirm-then-quote cycle
  against this branch before it merges, and reopen the "keep both True"
  decision above if that surfaces a graph-shape or merge-determinism
  problem.

4 new tests (31 total in `test_oracle_migrate.py`), all passing. Verified
zero new regressions against the same previously-problematic combined test
set (`test_oracle_migrate.py` + the `oracledb`-stubbing files) — still
the same 64 pre-existing, unrelated failures, zero `oracle_migrate`
failures.

## Update — PR review round 7 (2026-10-05)

High:

- **Postgres heartbeat sweep never actually runs — confirmed and fixed.**
  `sweep_stale_jobs_heartbeat.sql` has `stage LIKE '%CPQ Ingestion%'`
  alongside a real `%s` bind for the timeout. psycopg's own
  placeholder parser (`psycopg._queries._split_query`) scans the WHOLE
  query text for `%X` sequences, not just the genuine placeholder —
  reproduced directly against the installed psycopg 3.3.4:
  `ProgrammingError: only '%s', '%b', '%t' are allowed as placeholders,
  got '%C'`. `main_lifespan._stale_job_sweep()`'s broad `except Exception`
  around the sweep call means this failed silently on every tick, on
  every Postgres deployment, since the heartbeat sweep shipped — the one
  mechanism added specifically to catch a worker that silently died
  mid-confirm never ran at all. Fixed by doubling the literal `%` to `%%`
  (`'%%CPQ Ingestion%%'`), the standard psycopg escape. New regression
  test re-implements psycopg's own acceptance rule directly against the
  file's real text (not the mocked-cursor path the existing 6 tests use,
  none of which ever executes real query text) — confirmed it fails
  against the un-escaped query and passes against the fix. Deliberately
  does not import `psycopg._queries` itself: several other test files in
  this suite (`test_oci_backends.py`, `test_datasource_store.py`,
  `test_discovery_store.py`) replace `sys.modules['psycopg']` with a bare
  module at **import time**, not inside a fixture — the same collection-
  order hazard round 5 hit with `oracledb` — so depending on the real
  submodule being importable at test-run time would be a coin flip
  depending on which files pytest already collected.
- **Structural-leaf fold ships on by default — not changed, same decision
  as before.** This is the same ask as an earlier round's suggestion to
  flip `cpq_structural_leaf_fold_enabled`/`cpq_force_exact_enabled` to
  `False` by default, which the developer explicitly declined ("keep both
  True") — that decision stands, not revisited here. What IS new and
  actionable in this round's framing: "no test compares entity/
  relationship counts with the fold on vs off or covers an entity-like
  tag or an empty container." Confirmed true — `test_structural_leaf.py`'s
  existing unit tests construct `by_tag`/`edges` by hand and never call
  `resolve_and_relate_raw_graph()`; `test_resolve_and_relate_raw_graph.py`
  mocks `run_pipeline` in every existing test, so `by_tag`'s actual
  *contents* after folding were never asserted anywhere. Added two new
  integration-style tests exercising the REAL `project_xml_to_raw_graph`
  → `group_nodes_by_tag` → `fold_structural_leaf_tags` chain (only
  `run_pipeline`/`EntityStore`/`project_workspace_graph` mocked) against a
  document with an entity-like tag (`<Customer>Bob</Customer>` — text
  only, no attributes/children) and an empty container (`<Lines></Lines>`)
  alongside a tag that must survive either way (`<LineItem Sku="..."/>`
  has a real attribute): confirms the flag actually changes the resolved
  tag/entity count (4 tags fold-off vs. 2 fold-on for this document), not
  just a cosmetic no-op.

Medium:

- **`_emit` in `resolve_entities.py`'s chunked resolver was unguarded —
  confirmed and fixed.** A transient failure in the caller's
  `on_progress` (the job-row heartbeat update) raised straight out of
  `_emit` and aborted the whole `resolve_run()` call — exactly the
  scenario `_safe_progress` was added to `entity_store.py` for in round 3,
  just never applied here. `_emit` now catches and logs any `on_progress`
  exception instead of propagating it.
- **`oracle_migrate` has no lock between the two uvicorn workers —
  confirmed and fixed.** `docker-compose-oci.yml` runs `--workers 2`,
  each running its own FastAPI lifespan and its own
  `apply_oracle_migrations()` call at startup, against the same Oracle
  DB, with no coordination between them. DDL mostly survives a race via
  `_EXPECTED_IDEMPOTENT_ORA_CODES` catching the slower worker's
  "already exists" error, but a migration file whose body is
  non-idempotent DML (a one-time data backfill with no unique constraint
  to collide on) could silently double-apply with no error at all.
  `DBMS_LOCK` (a session-level named lock) isn't available here — Oracle
  ADB restricts `EXECUTE` on it for normal schema users — so instead a
  sentinel row (`__aryx_migration_lock__`) is inserted into
  `aryx_schema_migrations` once, then locked with
  `SELECT ... FOR UPDATE` for the duration of a migration run (autocommit
  off for that span, committed — and the lock released — at the end).
  The already-applied snapshot is re-fetched only AFTER acquiring the
  lock, so a worker that was blocked waiting sees what the other worker
  just committed instead of a stale pre-lock view, and never redundantly
  re-runs a file the first worker just applied.
- **`force_exact` uniqueness verified with a different normalization than
  the actual exact-merge grouping — confirmed and fixed.**
  `_full_uniqueness_ratio()` (round 5's `force_exact` verification gate)
  used `.strip().lower()`; the actual merge in `run_exact.py`'s
  `_resolve_exact()` groups on `blocking.normalize()`, which additionally
  collapses internal whitespace. Two values differing only by internal
  whitespace (e.g. `"AB  12"` vs. `"AB 12"`) counted as 2 distinct values
  in the verification check — making a key look safely unique enough to
  force exact mode — while actually merging into ONE group at resolve
  time: the exact inverse of what the check exists to catch. Fixed by
  having `_full_uniqueness_ratio()` use the same `normalize()` the real
  merge uses.

Low:

- **`_delete_orphaned_entities`'s docstring was stale — confirmed and
  fixed.** It said deleting orphaned entities after a cancel does NOT
  touch `aryx_entity_member` rows, matching `delete_entity()`/
  `delete_entities_by_type()`'s limitation at the time it was written —
  that limitation was closed for all three delete methods back in §5
  (member cleanup). `delete_entities()` (what this function actually
  calls) has deleted members before entities in the same transaction ever
  since; the docstring now says so.
- **Embedding dedupe order was non-deterministic — confirmed and fixed.**
  `resolution/run.py`'s per-batch dedupe used `list({r.text for r in
  batch})` — correctness is unaffected (the `zip()` pairing with
  `broker.embed()`'s return is still positionally correct regardless of
  set iteration order), but which order texts are actually sent to the
  broker varied by Python's per-process hash randomization, making the
  exact embedding-call sequence non-reproducible across runs for anyone
  inspecting it (tests, debugging, a broker-side log). Changed to
  `list(dict.fromkeys(...))` — same O(n) dedupe cost, deterministic
  first-occurrence order.
- `delete_entities_by_type`'s SELECT-then-DELETE race (a concurrent insert
  is deleted but missing from the returned id list) and the re-confirm
  duplication/0049-index-not-online notes are already accurately
  documented in their respective docstrings from earlier rounds — no
  stale claims found, no action needed.
- **Pre-merge checklist, extended:** `ARYX_LANDING_BATCH_SIZE=3000` and
  `mem_limit: 9g` (api)/`8g` (the other service bumped earlier) are
  unmeasured against real host headroom with 2 workers under real load —
  added alongside the existing round-6 N3 item (a real confirm+quote
  cycle against production-shaped data) as something to check before this
  branch merges, not something further work in this environment can
  verify.

New/changed tests: `test_job_store_heartbeat.py` (+1, the psycopg
placeholder-parsing regression guard),
`tests/cpq_ingestion/test_resolve_and_relate_raw_graph.py` (+2, fold
on/off tag-count integration tests). All affected suites re-run together
(`test_job_store_heartbeat.py`, `test_oracle_migrate.py`,
`test_resolve_and_relate_raw_graph.py`, `test_structural_leaf.py`,
`test_exact_id_resolution.py`, `test_resolve_run_wiring.py`,
`test_resolution_logging.py`, `test_chunked_resolution.py`) — 125 passed,
zero failures, zero new regressions.

Also separately confirmed: `test_discovery_store.py::
test_put_upsert_is_idempotent` fails when run alongside
`test_oci_backends.py`/`test_datasource_store.py` (both of which replace
`sys.modules['psycopg']` at module-import time) regardless of any change
in this round — reproduced with none of this round's files in the mix,
so this is a pre-existing test-isolation issue, not a regression from
round 7.

### Follow-up (same day): round-7 lock fix released its own lock

**Medium, confirmed and fixed.** The round-7 `oracle_migrate` lock
acquired `SELECT ... FOR UPDATE` on the sentinel row and then ran every
migration block on the SAME connection/cursor. Oracle issues an implicit
commit before AND after every DDL statement, and a commit releases row
locks — so a migration file ordered DDL-then-DML (e.g. `ALTER TABLE ...
ADD` followed by a backfill `UPDATE`) had its own DDL block commit the
transaction holding the lock, releasing it mid-file. The second worker
would then acquire the lock, see the file not yet recorded
(`_mark_applied` only runs after every block in a file succeeds), and
re-run the whole file — double-applying the backfill, exactly the race
the lock exists to prevent. Files whose DML precedes any DDL were fine;
only the DDL-then-DML ordering broke, which is why this wasn't caught by
re-running the existing (mock-based) test suite.

Fixed by holding the lock on a dedicated SECOND connection, separate from
the one that executes migration blocks — a DDL block's implicit commit on
the migrations connection no longer touches the lock connection's
transaction at all, so the lock survives the full run regardless of block
ordering. `conn` (migrations) stays `autocommit=True` throughout (back to
its pre-lock, per-statement-commit behavior); `lock_conn` stays
`autocommit=False` for the run's duration and is committed (releasing the
lock) in the `finally` block.

New regression test uses two DISTINCT mock connections (not just
asserting `connect()` was called twice, which the old single-connection
code would also satisfy trivially) to confirm the `FOR UPDATE` select
runs only on the lock connection's cursor and never the migration
connection's — confirmed it fails against the pre-fix code (0 lock calls
found on the lock cursor, since there wasn't a separate one) and passes
against the fix.

Not independently verified against a real Oracle instance (same caveat
the original finding carried) — the regression test proves the
connection-separation *structure* this fix depends on, not the actual
Oracle lock-release semantics underneath it, which is textbook Oracle
behavior (DDL auto-commits) rather than something this environment can
exercise directly.

## Update — live incident: false-positive heartbeat kill (2026-10-05)

While using the dev_oci stack to live-test this branch against a real
CPQ XML file (41 tags, confirm job `55751c8b869940429406b57475d874dd`,
workspace 1082), the confirm job was marked `status=failed`,
`error="worker lost — no progress reported within the heartbeat window"`
by `JobStore.sweep_stale_heartbeat` (§0) at 06:10:21 — **while it was
still actively, continuously resolving** tag 9/41 (`item_text`). Verified
directly: the live container logs show dense, gap-free per-pair
`resolution.run` scoring activity straight through the "failure" instant
and for many minutes after it, with zero tracebacks, zero process
restarts, and the container reporting `healthy` throughout. This was a
false positive, not a real crash — confirmed, not assumed.

**Root cause.** `resolution/run.py`'s block-scoring loop only called
`on_block_progress` (the heartbeat-driving callback, wired all the way
through to `JobStore.update_stage`'s `updated_at = now()`) every
`_PROGRESS_EVERY = 25` blocks — a block-COUNT checkpoint with no
wall-clock ceiling. Block cost is not uniform: a block's pair count
scales with its member count (candidate cluster size), so a run of large
near-duplicate blocks (common in `item_text`-style free-text tags with
many near-identical values) can take many minutes to clear even a
handful of blocks, let alone 25. On this run, the checkpoint logged
`scored block 200/1430` at 05:50:09 and the next one logged was
`725/1430` at 06:12:56 — a **22m47s gap** with no heartbeat update, well
past the 20-minute `job_heartbeat_timeout_minutes` default (itself raised
from 10→20 in round 5 specifically to reduce false positives — still not
enough margin for this shape of data).

**Consequence observed, also worth flagging on its own:** once the sweep
marks a job `failed`, `update_job_stage.sql`'s `WHERE status != 'failed'`
guard (the "no resurrection" guard, round 4) means the job row can never
be revived by the still-running resolve loop's own progress calls — by
design, correctly. But nothing tells that resolve loop to actually STOP:
`should_stop()` is only checked at tag *boundaries* in
`resolve_and_relate_raw_graph()`, never inside the per-block/per-pair
scoring loop itself (§3b/PR #429's own documented scope). The result is a
"zombie" resolve that keeps running — and keeps writing real entities/
relationships to the DB — for a job the UI and database already show as
failed, until it eventually reaches the next tag boundary. Live-observed:
the zombie was still active 14+ minutes after the false failure,
continuously, with the job row frozen the whole time. Not fixed here —
it's the same already-documented, already-scoped-out limitation from
PR #429 (should_stop granularity), not something this false-positive
incident introduces; flagged so it isn't mistaken for a new regression if
noticed independently.

**Fix (the root cause).** `resolve()`'s block loop now also fires
`on_block_progress` whenever `_PROGRESS_MAX_SECONDS` (60s) has elapsed
since the last emission, regardless of block count:

```python
if on_block_progress is not None and (
    (block_idx + 1) % _PROGRESS_EVERY == 0
    or block_idx + 1 == total_blocks
    or time.monotonic() - _last_progress_emit >= _PROGRESS_MAX_SECONDS
):
    on_block_progress(block_idx + 1, total_blocks)
    _last_progress_emit = time.monotonic()
```

This bounds the worst-case heartbeat gap to ~60s regardless of how
expensive any individual block or run of blocks turns out to be — 20x
margin below the 20-minute sweep threshold, so a future run with even
more extreme per-block cost than this incident's `item_text` tag still
has room before risking another false positive.

Two new tests in `tests/test_resolve_block_progress_heartbeat.py`: one
confirms the time-based path does NOT fire spuriously when blocks are
fast (only `_PROGRESS_EVERY`/last-block checkpoints fire, as before); the
other simulates a slow block via a mocked `time.monotonic()` and confirms
`on_block_progress` fires after block 1 — neither the 25th block nor the
last — specifically because of the time ceiling. Verified the second test
fails against the pre-fix code (fails on `AttributeError: module
'aryx.resolution.run' has no attribute 'time'`, since `time` wasn't even
imported before this fix) and passes against the fix.

Not fixed: the zombie-task/`should_stop`-granularity issue described
above. That's a materially larger change (threading a stop-check into the
hot pair-scoring loop touches the same performance-sensitive path this
whole investigation is about) and is the same scope PR #429 already and
deliberately left for a future PR. The heartbeat fix above should make
this specific trigger (false-positive sweep kills) much rarer, which
reduces how often the zombie scenario is even reached — but a genuine
user-initiated cancel or a real worker crash during a long block-scoring
pass would still take until the next tag boundary to actually stop.

### Follow-up (same day): the first heartbeat fix was still block-boundary-only

**Medium, confirmed and fixed — twice over, same root defect.** The first
version of this fix only checked `_PROGRESS_MAX_SECONDS` at block
*boundaries*: end of a block's pair loop, and (missed entirely the first
time) after the embedding-prefetch loop. Both still had the exact same
class of gap the whole incident was about — a single long-running
operation with no internal checkpoint:

- `max_pairs_per_block` defaults to 500, and each pair goes through
  `score_pair`/`_route_pair`, which can trigger an LLM adjudication call.
  At seconds per call, ONE block can legitimately run for tens of
  minutes — past the ceiling never being re-checked until that block
  finally finishes. The original incident is most consistent with this
  exact shape (a handful of singleton blocks logged near-instantly, then
  one or a few large multi-member blocks absorbing the whole 22m47s gap),
  not literally 500+ small blocks each taking a few seconds.
- The embedding-prefetch loop (`ThreadPoolExecutor` + `as_completed`,
  measured in this module's own docstring at ~99% of `resolve()`'s
  wall-clock time on a realistic dataset) had ZERO `on_block_progress`
  calls anywhere in it — `_last_progress_emit` is set before entering the
  loop, and nothing fires until the first multi-member block's pair loop
  finishes afterward.

Fixed by checking the time ceiling inside both: once per pair in the
block loop (a `monotonic()` call is negligible next to a scoring/
adjudication call), and once per completed future in the prefetch loop.
Both report `block_idx` (not `block_idx + 1`) since the current block/the
whole prefetch phase hasn't finished yet — `on_block_progress`'s
`(blocks_done, total_blocks)` contract stays unchanged; only new call
sites were added, no signature change.

Two new tests isolate each gap specifically (distinguishing "fired during
prefetch" from "fired mid-block" matters, since both report
`blocks_done=0` for the first block/first prefetch — otherwise
ambiguous): the prefetch test only advances a fake clock inside
`broker.embed()`'s mock (never called again once embeddings are cached
for the pair loop), so any early heartbeat observed can only have come
from the prefetch loop; the mid-block test uses one large single block
(`C(6,2)=15` pairs) with a small per-call clock increment, so crossing
the ceiling requires several per-pair checks, not one end-of-block check.
Verified both fail against the previous (block-boundary-only) version of
this fix and pass against the current one.
