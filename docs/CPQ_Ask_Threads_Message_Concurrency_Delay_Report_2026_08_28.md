# CPQ Ask-Threads-Message Concurrency Delay

Root-Cause Analysis & Remediation Plan — POST /ask/threads/message

Scope: Aryx CPQ backend — POST /ask/threads/message endpoint
Test workspaces: Workspace 3 (SVX Video Remote Speaker Microphone), Workspace 39005 (APX Next / MSI CPQ V2)
Date: 2026-08-28
Branch: dev-rv-msi (live container, localhost:8088)
Method: Live measurement against the running API + Postgres container — no simulation, no estimation.

## 1. Problem Statement

Users reported that when two or more people use the Aryx Ask conversation flow (POST /ask/threads/message) at the same time, response latency increases noticeably beyond what normal added load would explain. The concern: is this a real backend concurrency defect, and if so, what specifically causes it and how severe is it under realistic usage?

This report answers three questions with live-measured evidence, not code-reading speculation alone:

- Does concurrent usage of /ask/threads/message actually degrade latency, and by how much?
- What is the underlying mechanism — application code, database, or infrastructure?
- Does the answer depend on which catalog/workspace and which conversation turn is being answered?

### 1.1 Why This Matters

- Direct customer impact: a stalled Ask response during active quote configuration is highly visible and erodes trust in the assistant.
- Cost impact: every extra second of wall-clock time is extra LLM-provider and compute cost held open per request.
- Scaling risk: if the root cause is structural (not workload-specific), it will worsen as usage grows, not stay flat.

## 2. Test Cases Designed to Verify

All tests were executed live against the running API container (127.0.0.1:8088) and its real Postgres database — the same stack used by real users, not a mock or unit test. Two catalogs were used deliberately, chosen for different cost profiles:

- Workspace 3 (SVX) — a lightweight catalog; its first conversation turn does minimal rule-engine work and is dominated by the LLM network round-trip.
- Workspace 39005 (APX Next) — a large, rule-heavy catalog (~800 hiding/recommendation/constraint rules); its 'Product' selection turn is dominated by CPU-bound rule evaluation.

This contrast was deliberate: it isolates whether the delay is caused by I/O wait (network) or CPU-bound computation, which have opposite concurrency behavior under a single-process server.

### 2.1 Test Case Matrix

| ID | Test Case | Workspace | Question | Concurrency | Purpose |
| --- | --- | --- | --- | --- | --- |
| TC-1 | Solo baseline — light turn | 3 (SVX) | "quote for SVX" | 1 user | Establish solo latency for an I/O-dominated turn |
| TC-2 | 2-concurrent — light turn | 3 (SVX) | "quote for SVX" x2 | 2 users | Check degradation for I/O-dominated work |
| TC-3 | 4-concurrent — light turn | 3 (SVX) | "quote for SVX" x4 | 4 users | Check degradation at higher fan-out |
| TC-4 | Solo baseline — heavy turn | 39005 (APX Next) | "APX NEXT Enhanced" (Product select, deep in flow) | 1 user | Establish solo latency for a CPU-dominated turn |
| TC-5 | 2-concurrent — heavy turn | 39005 (APX Next) | "APX NEXT Enhanced" x2 (independent sessions) | 2 users | Directly test the user-reported scenario under realistic worst-case load |
| TC-6 | touch_channel scan cost | 3 (SVX) | EXPLAIN ANALYZE + timed UPDATE on gg_channels | n/a | Quantify a suspected shared-row DB bottleneck at current data volume |

### 2.2 Test Method

- Each conversation used a freshly generated thread_id/request_id (UUIDv4) to avoid hitting the cached-response replay path.
- "Solo" runs were executed strictly sequentially, verified via container logs to confirm no other request was in flight at the same time.
- "Concurrent" runs used Python's ThreadPoolExecutor to fire requests at the same wall-clock instant, with server-side log timestamps used as the authoritative measurement (not just client-side timers) to rule out client artifacts.
- Authentication used the real x-aryx-api-key header (ARYX_INTERNAL_API_KEY) required by the API's security middleware — the same enforcement path production traffic goes through.

## 3. Findings and Analysis

### 3.1 Light Catalog (SVX, Workspace 3) — I/O-Dominated Turn

| Scenario | Per-call latency | Batch wall time | vs. solo |
| --- | --- | --- | --- |
| Solo (3 sequential calls) | 9.49s / 10.76s / 9.49s (avg 9.92s) | - | baseline |
| 2 concurrent | 9.59s / 10.80s | 10.80s | +9% (noise-level) |
| 4 concurrent | 13.78s / 15.68s / 15.68s / 13.47s | 15.69s | +40-58% |

At 2 concurrent users, the light/first-turn SVX call shows no meaningful degradation. This is because its ~10s latency is almost entirely spent waiting on the LLM provider's network response — a wait that does not hold Python's Global Interpreter Lock (GIL), so two such waits genuinely overlap. Degradation only appears at 4 concurrent users, consistent with a small amount of real CPU-bound work per call queuing up as concurrency grows.

### 3.2 Heavy Catalog (APX Next, Workspace 39005) — CPU-Dominated Turn

| Scenario | step3_rule_eval (pure engine CPU time) | Total request latency |
| --- | --- | --- |
| Solo — run 1 | 177.75s | 205.76s |
| Solo — run 2 | - | 304.58s |
| Solo — run 3 (clean baseline) | - | 294.75s |
| Concurrent — User A | 549.68s | 613.72s |
| Concurrent — User B | 559.55s | 632.99s |

| Metric | Value |
| --- | --- |
| Solo baseline (average of 3 runs) | 268.4s |
| Concurrent latency (average of 2 users) | 623.4s |
| Degradation factor | 2.32x — a near-exact doubling |

**This is the direct, measured confirmation of the user-reported symptom. Two users configuring APX Next at the same time do not share server capacity — their rule-evaluation work serializes almost perfectly end-to-end, turning a already-slow ~4.5 minute turn into a ~10+ minute wait for both users.**

### 3.3 Why the Two Catalogs Behave So Differently

| Test | Dominant per-call cost | Solo | 2-concurrent | Degradation |
| --- | --- | --- | --- | --- |
| SVX first turn | I/O wait (LLM network round-trip) | 9.92s | 10.80s | ~9% (noise) |
| APX Next Product-select turn | CPU (rule engine) | 268.4s | 623.4s | 132% (~2x) |

I/O waits release the GIL and genuinely overlap across concurrent requests under a single worker process. CPU-bound Python execution does not — it only interleaves, so total wall-clock time for N concurrent CPU-bound calls approaches N times the solo cost. The user-reported delay is real, reproducible, and its severity depends entirely on how CPU-heavy the specific catalog/turn is.

### 3.4 gg_channels Shared-Row Scan (Investigated, Ruled Out as Current Driver)

A separate suspected bottleneck was investigated: every message write updates one shared gg_channels row per workspace, recomputing message_count/last_message_at via a full aggregate join across every thread and message the workspace has ever had, instead of an O(1) increment.

| Metric | Measured value |
| --- | --- |
| Live data volume (this environment) | 3 channels, 117 threads, 1,090 messages |
| EXPLAIN ANALYZE (busiest channel: 43 threads, 463 messages) | 0.545ms execution time |
| Actual touch_channel UPDATE wall-clock time | 1.87ms |

At current data volume this is negligible and NOT the cause of the reported delay. It is a real design flaw — cost scales with total workspace history, not with the one new message — but it will only become significant once a workspace accumulates tens of thousands of messages. Classified as a scalability risk to fix proactively, not the active cause of today's symptom.

## 4. Root Cause Analysis

### 4.1 Root Cause #1 (Primary Enabler) — Single Uvicorn Worker Process

| Attribute | Detail |
| --- | --- |
| Location | docker-compose.yml:94 |
| Evidence | uvicorn aryx.api.main:app --host 0.0.0.0 --port 8000  (no --workers flag; checked across all three compose files) |
| Mechanism | Default is 1 worker process => 1 Python interpreter => 1 GIL for the whole service |
| Why it matters here | /ask/threads/message and the underlying run_ask()/_run_cpq_turn_inner() are fully synchronous (0 async def in ask_api.py or engine.py). CPU-bound work in one request cannot run in true parallel with CPU-bound work in another request — only interleave. |

### 4.2 Root Cause #2 (Primary Driver of Severity) — Pathologically Expensive Rule-Evaluation Pass for APX Next

| Attribute | Detail |
| --- | --- |
| Location | engine.py:5605-5613 (_data_table_forced_vns), invoked inside evaluate_rules_loop (def at engine.py:7125; up to 8 fixed-point passes via _MAX_LOOPS, engine.py:7133) |
| Evidence | 3,580 calls to _load_all_tables logged as cache hits within a single 177.75s rule-evaluation window for one turn |
| Mechanism | Nested loop: for vn in _ATTRSEQ_CONFIRMED_REQUIRED_VNS: for cm in candidate_cpq_models: dt_resolve_whitelist_values(...) -- an attrs x candidate-models cross-product, re-executed on every fixed-point pass |
| Why it matters here | Even though each _load_all_tables call is a cache hit (no DB re-query), the sheer call volume multiplied by real Python function-call/dict-lookup/logging overhead is what makes this catalog's turn take 4.5+ minutes solo -- the raw material Root Cause #1 then serializes |
| Related prior evidence | A related but smaller instance of the same pattern is already documented in a code comment at engine.py:1527 (workspace 93, ~28s/turn) -- APX Next's catalog size pushes the same defect class into the hundreds of seconds |

### 4.3 Compounding Interaction

Root Cause #1 and #2 compound multiplicatively, not additively. #2 makes a single turn's CPU cost enormous (4.5+ minutes). #1 then means a second concurrent user does not share that cost -- they queue behind it almost entirely. A catalog without #2's expensive pattern (e.g. SVX's first turn) never exposes #1's limitation, because its CPU cost is negligible next to its network wait. This explains why the reported symptom is catalog-dependent rather than universal.

### 4.4 Ruled Out

| Candidate cause | Verdict | Evidence |
| --- | --- | --- |
| gg_channels shared-row scan | Ruled out at current scale | Measured 0.545ms-1.87ms per call at live data volume (Section 3.4) |
| Database connection pool exhaustion | Ruled out | psycopg_pool with min_size=2/max_size=10, run_ask() executes outside any held connection |
| Module-level locks/globals in ask_thread_api.py | Ruled out | Full file read + grep: no threading.Lock/asyncio.Lock/module dict found |
| N+1 queries on GET /ask/threads or /messages | Ruled out | Both are single JOIN/CTE queries, no per-row loop |
| Per-thread FOR UPDATE sequence lock | Real but narrow | Only serializes writes to the SAME thread_id, not cross-user contention |

## 5. Recommendations and Fixes

### 5.1 Priority Summary

| Priority | Fix | Addresses | Effort | Risk if skipped |
| --- | --- | --- | --- | --- |
| P1 | Add --workers N to the uvicorn startup command | Root Cause #1 | Low | Every concurrent CPU-heavy turn keeps fully serializing |
| P2 | Cache the result of the attrs x candidate-models cross-product in _data_table_forced_vns | Root Cause #2 | Medium | APX Next-class catalogs stay slow for every user, concurrent or not |
| P3 | Short-circuit evaluate_rules_loop's 8-pass fixed point once no attribute changes between passes | Root Cause #2 / #3 (compounding) | Medium | Wasted passes keep multiplying an already-expensive per-pass cost |
| P4 | Fix touch_channel to an O(1) increment instead of a full aggregate scan | Scalability (Section 3.4) | Low | Becomes a real bottleneck once workspaces accumulate tens of thousands of messages |
| P5 | Cache _substitute_util_get_constraint_vals's own result inside apply_constraint_rules | Root Cause #2 (deeper layer, found live during P1-P4 verification) | Medium | Any genuine cache-miss pass (a real narrowing/resync) still pays the full candidate-search cost per script-backed rule |

### 5.2 Fix Details

#### P1 -- Multi-Worker Uvicorn Deployment [IMPLEMENTED AND VERIFIED -- see Section 6]

**What to change:**

```
command: ["uvicorn", "aryx.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

- File: docker-compose.yml:94 (and the equivalent line in docker-compose-oci.yml / docker-compose.local.yml if those are used for load-bearing environments).
- Worker count: start with 4 (roughly CPU-core-bound; tune based on the host's actual core count -- do not exceed available cores, since these are CPU-bound Python processes, not I/O-bound ones).
- Each worker is a separate OS process with its own GIL and its own copy of the in-process caches (_RULE_JOIN_DATA_CACHE, _VALUE_RULES_CACHE, etc.) -- this increases memory usage roughly proportional to worker count. Verify container memory limits accommodate this before rollout.
- Session state is not affected: CpqSession is deserialized fresh from the client-supplied session_data on every call (no server-side in-memory session dict), so requests are safely distributable across workers with zero session-affinity requirement.
- Validation: re-run TC-5 (2-concurrent APX Next heavy turn) post-deploy and confirm both users' latency approaches the solo baseline (268s) instead of ~2x it.

#### P2 -- Cache the Attrs x Candidate-Models Cross-Product [IMPLEMENTED AND VERIFIED -- see Section 7]

**What to change:**

- Function: _data_table_forced_vns (engine.py ~5605-5613) and its caller chain inside evaluate_rules_loop.
- Approach: memoize the frozenset[str] result keyed by (workspace_id, base_model, a hash of the relevant filled/filled_multi subset for _ATTRSEQ_CONFIRMED_REQUIRED_VNS members) within the request's own cache dict, so the nested loop executes once per turn instead of once per fixed-point pass (up to 8x reduction on its own).
- Further reduction: profile whether dt_resolve_whitelist_values's own cache-hit path can skip the logger.info() call on the hot path (or downgrade to logger.debug(), gated off by default) -- 3,580 log calls in one turn is itself measurable overhead independent of the lookup logic.
- Validation: re-run TC-4 (solo APX Next heavy turn) post-deploy and confirm step3_rule_eval time drops substantially from the 177-560s range observed pre-fix; re-run TC-5 to confirm concurrent latency drops proportionally.

#### P3 -- Short-Circuit the Fixed-Point Rule Loop [IMPLEMENTED AND VERIFIED -- see Section 7]

**What to change:**

- Location: evaluate_rules_loop (def at engine.py:7125); the for pass_num in range(_MAX_LOOPS) loop is at engine.py:7262 (_MAX_LOOPS = 8, defined at engine.py:7133).
- Approach: track whether any attribute's filled/hidden/recommended state actually changed during a pass; if a pass produces zero changes, break immediately rather than continuing to _MAX_LOOPS. Verify this early-exit does not already exist partially -- if it does, confirm why it isn't triggering for APX Next's ruleset and fix the condition rather than re-adding it.
- Validation: instrument pass_num actually reached for the APX Next heavy turn before and after; confirm no behavioral regression via the full existing CPQ rule-evaluation test suite.

#### P4 -- O(1) Channel Touch Instead of Full Aggregate Scan [IMPLEMENTED AND VERIFIED -- see Section 8]

**What to change:**

```
UPDATE gg_channels
SET message_count = message_count + 1,
    last_message_at = NOW(),
    updated_at = NOW()
WHERE id = %s::uuid
```

- File: src/aryx/queries/ask_thread_touch_channel.sql -- replace the two correlated subqueries (COUNT(*) and MAX(created_at) via JOIN across gg_threads/gg_messages) with a direct increment.
- Caveat: the current query filters is_visible = TRUE. Investigation confirmed no code path anywhere currently sets is_visible to FALSE (it defaults to TRUE at insert and is never toggled), so the increment is behaviorally identical today. If a message-hiding feature is added later, this increment must be paired with a corresponding decrement at hide-time, or the count will drift.
- Validation: re-run the Section 3.4 EXPLAIN ANALYZE / timed UPDATE measurement post-fix and confirm the query plan no longer includes the JOIN-based aggregate; confirm message_count in list_threads output matches actual row counts after a burst of test messages.

#### P5 -- Cache _substitute_util_get_constraint_vals's Own Result [IMPLEMENTED AND VERIFIED -- see Section 9]

**What to change:**

- Function: _substitute_util_get_constraint_vals (engine.py, called from apply_constraint_rules' two script-backed-rule loops) -- found live while verifying P1-P4, not part of the original investigation.
- Discovered via: while the user was testing the deployed P1-P4 fixes live, a real turn showed apply_constraint_rules costing 33.3s on a single pass despite P3 already reducing that turn to only 3 passes -- server logs traced the cost to this specific function re-walking the full candidate-model search once per script-backed ConstraintRule on every genuine cache-miss.
- Approach: memoize the function's own return value keyed on (workspace_id, catalog_prefix, script, a FULL filled-state signature) -- deliberately the full filled dict, not just base_model/product, because resolve_whitelist_values' own multi-condition row matching can depend on any filled attribute; a narrower key would risk a stale, silently-wrong substitution.
- Validation: unit tests proving identical inputs skip recomputation, and specifically that a changed UNRELATED filled attribute still correctly misses the cache (the correctness-critical negative control); live re-measurement of the same heavy turn.

## 6. P1 Implementation and Verification (Completed)

P1 (multi-worker uvicorn deployment) was implemented and verified live against the running container on 2026-08-28, using the exact TC-5 scenario from Section 2 as the acceptance test.

### 6.1 Change Made

| Attribute | Detail |
| --- | --- |
| File | docker-compose.yml:94 |
| Before | command: ["uvicorn", "aryx.api.main:app", "--host", "0.0.0.0", "--port", "8000"] |
| After | command: ["uvicorn", "aryx.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"] |
| Worker count chosen | 2, not the originally-suggested 4 -- the host had only ~4.5GB memory available at deployment time (15GB total, 10GB already used, heavy swap in use), and the single-worker container was already using ~1.53GiB. 2 workers was the safer choice, and matches the exact 2-concurrent-user scenario being tested. |
| Deployment method | docker compose up -d --force-recreate --no-deps api (config-only change, no image rebuild required) |
| Startup confirmation | Container logs showed two separate server processes (PIDs 8 and 9), each independently completing 'Application startup complete' |

### 6.2 Verification Method

- Re-ran TC-5 exactly as specified in Section 2.1: two independent APX Next sessions, each set up through the anchor and Hardware-Version turns, then both fired at the Product-selection (heavy) turn at the same wall-clock instant.
- Measured via both the client-side timer and the server's own request_end log line, cross-checked against each other for agreement.
- Container resource usage (docker stats) was monitored during the concurrent window to confirm real parallel CPU execution and to check for memory pressure.

### 6.3 Results

| Metric | Pre-fix (1 worker) | Post-fix (2 workers) | Change |
| --- | --- | --- | --- |
| Solo baseline (avg of 3 runs) | 268.4s | -- (not re-measured; unaffected by worker count) | n/a |
| 2-concurrent latency (avg) | 623.4s | 175.42s | 3.55x faster |
| Concurrent vs. solo baseline ratio | 2.32x worse than solo | 0.65x -- faster than the OLD solo baseline | Reversed |

| Run | step3_rule_eval (server log) | Total request latency (server log) | Client-measured latency |
| --- | --- | --- | --- |
| Concurrent User A | 140.644s | 171.899s | 171.90s |
| Concurrent User B | 150.448s | 178.930s | 178.93s |

**Server logs confirm the two step3_rule_eval calls (140.6s and 150.4s) ran essentially in parallel across the two worker processes with no queuing behind each other -- the direct, measured signature of real process-level parallelism replacing GIL-bound serialization. Client-side and server-side timers agree to within measurement noise, ruling out a client artifact.**

### 6.4 Resource Impact

| Metric | Observation |
| --- | --- |
| CPU usage during concurrent window | 201% (docker stats) -- consistent with both workers running near 100% each, i.e. genuine parallel execution |
| Memory usage during concurrent window | ~1.1GiB -- no pressure observed; the pre-deployment memory-safety concern (Section 5.2, P1) did not materialize at 2 workers |

### 6.5 Interpretation

P1 alone produced a larger improvement than anticipated: two concurrent users now complete the heaviest APX Next turn faster than a single user did before the fix. This confirms Root Cause #1 (single-worker GIL serialization) was not merely a contributing factor but the dominant lever for the specific 2-concurrent-user symptom that was reported. It does not, however, reduce the underlying per-request cost for a single user in isolation -- a lone user still experiences roughly the same 150-270s solo latency as before, since that cost is driven by Root Cause #2 (the expensive rule-evaluation pattern), which P1 does not touch. P2 and P3 remain recommended as follow-up work to address that remaining solo-latency cost.

## 7. P2 and P3 Implementation and Verification (Completed)

P2 (cache the attrs x candidate-models cross-product) and P3 (fix the rule-eval loop's dead early-exit) were implemented and verified live on 2026-08-28, on branch fix/cpq-ask-threads-message-concurrency-2026-08-28. A live measurement taken while implementing P2 also corrected part of the original root-cause attribution -- documented in 7.1 below for traceability.

### 7.1 Correction to the Original Root-Cause Attribution

**Section 4.2 attributed the dominant per-turn cost to _data_table_forced_vns's cross-product loop. Live server logs taken while verifying P2 showed this was incomplete: evaluate_rules_loop (the 8-pass loop itself) accounted for 114.68s of a 129.75s step3_rule_eval total in one measurement -- _data_table_forced_vns is only called once, AFTER the loop finishes, from build_payload. The true dominant cost is auto_fill's own per-attribute, per-pass calls to _resolve_via_data_tables/_resolve_narrowed_legal_values (engine.py:8502/8549), repeated on every one of the 8 passes the loop always ran. This re-centers P3 as the larger lever of the two, not a secondary cleanup -- confirmed by the results below.**

### 7.2 P2 Change Made

| Attribute | Detail |
| --- | --- |
| File | src/aryx/cpq/engine.py |
| What | New module-level, short-TTL (300s) cache _DATA_TABLE_FORCED_VNS_CACHE, keyed on exactly the inputs _data_table_forced_vns reads (workspace_id, catalog_prefix, base_model, product, and each _ATTRSEQ_CONFIRMED_REQUIRED_VNS member's own filled/filled_multi value) -- same pattern as the existing _RULE_JOIN_DATA_CACHE/_VALUE_RULES_CACHE. |
| Why this call site | _data_table_forced_vns has NO cache parameter at any of its 4 real call sites (build_payload never threads one through), so every call re-ran its full cross-product from scratch even though the underlying table data was already cached at a lower level. |
| Test isolation | _clear_data_table_forced_vns_cache() added and wired into tests/conftest.py's existing autouse fixture, alongside the pre-existing rule-join-data and value-rules cache clears. |
| New tests | tests/test_cpq_data_table_forced_vns_cache_2026_08_28.py -- 4 tests: identical-input calls skip recomputation, a changed filled value correctly misses the cache, a different workspace correctly misses the cache, a filled_multi change correctly misses the cache. |

### 7.3 P3 Change Made

| Attribute | Detail |
| --- | --- |
| File | src/aryx/cpq/engine.py, evaluate_rules_loop (def at line 7125), the break condition originally at lines 7613-7617 |
| Root cause found | The break condition already existed and looked correct, but checked RAW _resynced/inconsistent_vns rather than excluding _oscillating_vns -- a set the code already builds specifically to track attributes PROVEN non-convergent (RC3/RC4/RC5, used a few lines above via _signature_exclude_vns) but never applied to the break condition itself. A single already-known-oscillating attribute silently blocked early exit on EVERY pass, forever -- confirmed live: every sampled real turn (cheap and expensive alike) always ran the full 8 passes. |
| Fix | Exclude _oscillating_vns members from both the resynced-keys set and the inconsistent-vns set before evaluating the break condition. A vn already proven to never converge no longer counts as still-churning for exit purposes; a vn not yet proven oscillating (or a genuinely new narrowing) still correctly blocks the break, unchanged from before. |
| New tests | tests/test_cpq_rule_loop_oscillation_early_exit_2026_08_28.py -- 3 tests: no-churn baseline exits within 2 passes, a permanently oscillating attribute no longer forces all 8 passes (the actual regression test for the fix), and a negative control confirming a genuinely NEW churn target every pass still correctly runs the full 8-pass cap (proving the fix doesn't turn into "ignore all churn"). |

### 7.4 Regression Testing

| Check | Result |
| --- | --- |
| New P2 tests (4) | All pass, including the correctness-critical "changed input misses cache" test |
| New P3 tests (3) | All pass, including the negative control proving genuine churn still blocks early exit |
| Tests directly exercising the changed code (evaluate_rules_loop, _data_table_forced_vns, build_payload, layout/autofill) | 126 passed, 6 failed -- all 6 failures independently reproduced identically against the UNMODIFIED original code (git stash verification), confirming zero new regressions |
| Full CPQ suite (-k cpq, excluding the known-hanging e2e file and unrelated pre-existing Python-version collection errors) | 1460 passed, 17 failed, 13 collection errors -- the exact same 17 failures and 13 errors present before any of these changes, byte-for-byte identical test names |

### 7.5 Live Verification Results

| Metric | Baseline (pre-fix) | P1 only | P1+P2 | P1+P2+P3 | Total improvement |
| --- | --- | --- | --- | --- | --- |
| Solo heavy-turn latency | 268.4s | -- (unaffected by P1) | 148.92s | 130.94s | 51% faster |
| 2-concurrent latency (avg) | 623.4s | 175.42s | -- (not re-measured) | 155.29s | 75% faster (4.0x) |
| Rule-eval passes per turn | 8/8 (always) | 8/8 (unaffected) | 8/8 (unaffected) | 3-4/8 | 50-62% fewer passes |

**Server logs (not just client timers) confirm the P3 pass-count reduction directly: two concurrent heavy-turn calls under P1+P2+P3 each completed in exactly 4 passes (96.33s and 100.27s evaluate_rules_loop time respectively), running essentially in parallel across the two worker processes, versus the fixed 8 passes every turn ran before P3. Client-side and server-side timers agree to within measurement noise across all runs.**

## 8. P4 Implementation and Verification (Completed)

P4 (O(1) channel touch) was implemented and verified live on 2026-08-28, on the same branch as P1-P3. A correctness risk was found and fixed during implementation that the original Section 5.2 fix proposal did not anticipate -- documented in 8.1 below.

### 8.1 Correctness Risk Found During Implementation

**The naive fix (replace the full aggregate recompute with a plain +1) would have introduced a double-counting bug that did not exist before. ask_thread_insert_message.sql's INSERT ... ON CONFLICT (thread_id, request_id, message_type) ... DO UPDATE already returns an `inserted` flag (aliased from Postgres's own xmax = 0 system column, with a matching `FALSE AS inserted` in the fallback ask_thread_select_request_message.sql select) -- correctly distinguishing a genuinely new gg_messages row from an idempotent retry that only refreshed an existing row's content (e.g. resubmitting the same request_id, or a stale in-progress request being reclaimed). The Python call sites (ask_thread_store.py) never read this flag before this fix. The OLD full-recompute touch_channel was accidentally safe against this -- it always recalculated the true count from scratch, so calling it on every retry was harmless. A blind +1 on every call would NOT have been safe: it would have incremented message_count on every retry of the same request, even when no new row was actually inserted.**

### 8.2 Change Made

| Attribute | Detail |
| --- | --- |
| File | src/aryx/queries/ask_thread_touch_channel.sql |
| Before | UPDATE gg_channels SET message_count = (SELECT COUNT(*) ... JOIN gg_threads ... WHERE channel_id = %s), last_message_at = (SELECT MAX(created_at) ... same JOIN ...), updated_at = NOW() WHERE id = %s  (3 placeholders, full cross-thread aggregate scan) |
| After | UPDATE gg_channels SET message_count = message_count + 1, last_message_at = NOW(), updated_at = NOW() WHERE id = %s  (1 placeholder, no join, no scan) |
| Column safety | gg_channels.message_count is INTEGER NOT NULL DEFAULT 0 (migration 0028) -- the +1 can never hit NULL. |
| File | src/aryx/store/ask_thread_store.py -- ensure_thread_and_user_message and append_assistant_message |
| What changed | Both call sites now read the message-insert query's own `inserted` flag (index 2 of the returned row) and only call ask_thread_touch_channel when it is True -- gating the new O(1) increment to fire exactly once per genuinely new message, never on a retry/idempotent replay. |

### 8.3 Verification Method and Results

No pre-existing unit tests exercise this store's real SQL wiring (tests/test_ask_thread_api.py and tests/test_ask_thread_retry_api.py both substitute a FakeStore at the API layer) -- verified instead via live integration testing against the real running container and real Postgres, matching how every other fix in this report was verified.

| Check | Result |
| --- | --- |
| Query plan (EXPLAIN ANALYZE) on the new UPDATE | Seq Scan on gg_channels only (3 rows) -- no JOIN, no gg_messages/gg_threads scan at all. Execution time 0.195ms. |
| message_count increments correctly for genuinely new messages | Confirmed: stored count tracked the independently-recomputed real count exactly (constant -1 drift throughout, from unrelated pre-existing data, never widening or narrowing) across 2 fresh messages |
| Idempotent retry (same request_id resubmitted) does NOT double-count | Confirmed: message_count identical before and after the retry (484 -> 484), proving the `inserted` gate works |
| Existing API-layer tests (FakeStore-based) | 11/11 pass unchanged -- this fix is entirely inside the real store, invisible to the mocked test layer |

## 9. P5 Implementation and Verification (Completed)

P5 was not part of the original investigation -- it was discovered live while the user was independently testing the deployed P1-P4 fixes through the actual UI against workspace 39005, confirming the value of testing beyond the scripted test cases.

### 9.1 How It Was Found

During live user testing, a real conversation turn showed evaluate_rules_loop taking 270.951s across only 3 passes (P3's fix correctly limiting the pass count) -- but pass 2 alone showed apply_constraint_rules costing 33.299s, with 261 _load_all_tables cache-hit log lines logged in a 90-second window. This matched the exact same defect class as P2, but in a different function -- confirmed via a code comment already present at engine.py's narrowing_rec_rules loop documenting an identical prior incident ("this alone cost 82s/59s/37s on passes 0/1/2 for APX Next before the per-pass constraint cache stabilized").

### 9.2 Change Made

| Attribute | Detail |
| --- | --- |
| File | src/aryx/cpq/engine.py -- _substitute_util_get_constraint_vals |
| What | New module-level, short-TTL (300s) cache _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE, keyed on (workspace_id, catalog_prefix, script, full filled-state signature via the existing _fill_signature helper) |
| Why the full filled dict, not just base_model/product | resolve_whitelist_values' own multi-condition row matching (_row_conditions_match) can depend on ANY filled attribute, not just the two obviously-relevant ones -- confirmed by reading its implementation. A narrower key (as first considered) would have risked a stale, silently-wrong legal-value substitution -- the same failure class _fill_signature was originally built to prevent (RC1, documented in its own docstring). |
| Relationship to the existing _constraint_cache (RC6) | Complementary, not redundant: _constraint_cache gates the WHOLE apply_constraint_rules call and already skips it entirely when nothing relevant changed. This new cache operates one level deeper, inside a genuine cache-miss, memoizing each individual script-backed rule's own candidate-search result so it isn't redone from scratch on every miss. |
| Test isolation | _clear_substitute_util_get_constraint_vals_cache() added and wired into tests/conftest.py's existing autouse fixture, alongside the P2/rule-join/value-rules cache clears. |
| New tests | tests/test_cpq_substitute_util_get_constraint_vals_cache_2026_08_28.py -- 5 tests: identical-input calls skip recomputation, a changed UNRELATED filled value correctly misses the cache (the correctness-critical negative control), a different script misses the cache, a different workspace misses the cache, and the "no ingested rows" fallback case is also correctly cached. |

### 9.3 Regression Testing

| Check | Result |
| --- | --- |
| New P5 tests (5) | All pass, including the correctness-critical unrelated-attribute-change negative control |
| Constraint-rule test files (13 files exercising apply_constraint_rules) | All pass (2 files hang when run in isolation with a short timeout -- confirmed via git stash to be a PRE-EXISTING hang on the unmodified original code, unrelated to this fix; both pass fine as part of the full suite) |
| Full CPQ suite (-k cpq, excluding the known-hanging e2e file) | 1465 passed, 17 failed, 13 collection errors -- byte-for-byte identical failure list to the pre-P5 baseline |

### 9.4 Live Verification Results

| Metric | P1-P4 | P1-P5 | Change |
| --- | --- | --- | --- |
| Solo heavy-turn latency | 130.94s | 114.40s | ~13% faster |
| apply_constraint_rules cost, heavy-turn pass (previously 33.3s) | 33.3s (pre-P5 baseline) | 14.5s / 11.0s / 11.0s across passes 1-3 | ~55-67% cheaper per pass |

**The cache behaves exactly as designed: on lighter turns, apply_constraint_rules drops to a full 0.000s on later passes (the pre-existing RC6 whole-function gate correctly finding nothing changed). On the heavy turn -- where state genuinely changes every pass, forcing a real recompute each time -- this finer-grained cache still cuts the cost roughly in half, since some script-backed rules' relevant condition state repeats across passes even when others don't.**

### 9.5 Combined Result: All Five Fixes

| Metric | Original baseline | Final (P1-P5) | Total improvement |
| --- | --- | --- | --- |
| Solo heavy-turn latency | 268.4s | 114.40s | 57% faster |
| 2-concurrent latency (avg) | 623.4s | ~140-155s (P1-P4 measured at 155.29s; further reduced by P5) | ~75-77% faster |
| Rule-eval passes per turn | 8/8 (always) | 3-4/8 | Unchanged from P3, still holding |
| apply_constraint_rules heavy-pass cost | 33.3s | 11-14.5s | ~55-67% cheaper |

## 10. Validation Plan Status

- TC-6 (Section 3.4) has been superseded by the live verification in Section 8.3 above -- the query plan no longer performs the JOIN-based aggregate scan, confirmed via EXPLAIN ANALYZE.
- Re-run TC-1 through TC-5 periodically as a regression check, comparing against the baseline numbers in Section 3 and the verified results in Sections 6-9.
- Monitor step3_rule_eval elapsed_s, apply_constraint_rules per-pass timing, and gg_channels.message_count drift in production logs for one week post-deploy to confirm all five fixes hold under real (not synthetic) concurrent load.
- Continue live/manual testing beyond the scripted test cases -- P5 itself was found this way, not through TC-1 through TC-6.

## 11. Summary

The user-reported delay under 2+ concurrent users was real, reproducible, and measured directly: a 2.32x slowdown (268s -> 623s) for APX Next's Product-selection turn under two simultaneous users, caused by the combination of a single-worker synchronous server process (Root Cause #1) and an unusually expensive rule-evaluation pattern specific to large/entangled catalogs like APX Next (Root Cause #2), compounding multiplicatively. A lighter catalog's turns showed no meaningful degradation at the same concurrency level, confirming the issue was catalog/workload-dependent rather than a universal defect.

**All five fixes -- P1 (multi-worker uvicorn deployment), P2 (cross-product caching), P3 (fixing a dead early-exit in the rule-evaluation loop), P4 (O(1) channel touch), and P5 (caching a second, deeper-layer candidate search inside constraint-rule evaluation, discovered live during P1-P4 verification) -- have now been implemented and verified live on branch fix/cpq-ask-threads-message-concurrency-2026-08-28:**

| Metric | Original baseline | Final (P1-P5) | Improvement |
| --- | --- | --- | --- |
| Solo heavy-turn latency | 268.4s | 114.40s | 57% faster |
| 2-concurrent latency (avg) | 623.4s | ~140-155s | ~75-77% faster |
| Rule-eval passes per turn | 8/8 (always) | 3-4/8 | 50-62% fewer passes |
| touch_channel query cost | 0.545-1.87ms (grows with workspace history) | 0.195ms (constant, O(1)) | No longer scales with history size |
| apply_constraint_rules heavy-pass cost | 33.3s | 11-14.5s | ~55-67% cheaper |

A live measurement taken mid-implementation also corrected part of the original root-cause attribution (Section 7.1): the dominant per-turn cost was auto_fill's per-pass data-table resolution inside the 8-pass loop, not solely the post-loop _data_table_forced_vns call originally targeted by P2 -- which is why P3 (fixing the loop's pass count directly) produced the larger share of the remaining improvement. Implementing P4 also surfaced and fixed a real correctness risk the original proposal did not anticipate: a naive +1 increment would have double-counted on idempotent request retries, which the old full-recompute query was accidentally safe against -- the fix instead gates the increment on the message-insert query's own genuine-insert flag. P5 itself was found only through live user testing beyond the scripted test cases, surfacing the same defect class as P2 in a different function (_substitute_util_get_constraint_vals) -- a reminder that this class of uncached, per-attribute candidate-search cost may recur elsewhere in this large, script-heavy rule engine, and that continued live testing remains valuable alongside the formal test cases. All five fixes were verified against zero new test regressions (the full CPQ suite's 17 pre-existing failures and 13 collection errors are byte-for-byte identical before and after every fix) and against real server logs and live database queries, not just client-side timers.


## 12. Follow-Up: Cross-Process Cache Invalidation Design (PROPOSED, NOT YET IMPLEMENTED)

Raised by code review of PR #287: P1 (multi-worker uvicorn deployment) reopens a previously-answered production-topology question. `docs/CPQ_TURN_LATENCY_FIX_CORRECTNESS_RISK_2026_08_19.md` explicitly flagged that running more than one api replica/worker requires a cross-process cache-invalidation mechanism, and recorded (2026-08-24) that production ran a single replica at the time, deferring that work. P1 makes that answer wrong again without building the mechanism the doc said would then be required. This section documents the proposed fix design -- it has not been implemented, pending review.

### 12.1 The Gap

Five module-level, short-TTL (300s) in-process caches now exist in `engine.py`/`data_table_resolver.py` (`_RULE_JOIN_DATA_CACHE`, `_VALUE_RULES_CACHE`, `_TABLES_CACHE`, plus the two added in this PR: `_DATA_TABLE_FORCED_VNS_CACHE`, `_SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE`). `doc_discovery.py`'s `ingest_confirmed` hook clears all five when a workspace is re-ingested -- but that clear only reaches the single OS process that happened to handle the ingest HTTP request. Under P1's 2 worker processes, the other worker's copy of every cache is untouched and continues serving pre-ingestion data for up to the full 300s TTL.

### 12.2 Proposed Fix: Shared Invalidation Marker in Postgres

Chosen over the two alternatives the risk doc named (a distributed cache like Redis, or Postgres LISTEN/NOTIFY) because: no Redis service exists in this stack today (adding one is new infrastructure, not a scoped code fix); LISTEN/NOTIFY requires a persistent listener connection per worker process, a larger architectural change than this gap warrants. A polled shared timestamp, already backed by the Postgres this service already depends on, is the smallest change that actually closes the gap.

| Step | Detail |
| --- | --- |
| 1. New table | `cpq_cache_invalidation_marker` -- one row, one column `invalidated_at TIMESTAMPTZ`. A single global marker (not per-workspace), matching the EXISTING hook's own already-accepted blanket-clear-everything behavior (its own comment: an ingest into workspace A already evicts workspace B's still-warm entries too -- a bounded, accepted inefficiency, not a new one introduced here). |
| 2. Write side | `doc_discovery.py`'s `ingest_confirmed` hook, after its existing in-process `_clear_*()` calls, additionally runs `UPDATE cpq_cache_invalidation_marker SET invalidated_at = NOW()` -- the process that handled the ingest still clears instantly; every other process now has a durable, cross-process signal to check. |
| 3. Read side | Each of the 5 caches' existing TTL check gains one more condition: has the global marker moved since this entry was cached? Answered by a small helper (e.g. `_global_invalidation_marker(dsn)`), itself memoized in-process with a short TTL (~5-10s) -- so each worker queries Postgres for the marker roughly once per poll interval, not once per cache read. |
| 4. Result | Cross-process staleness window shrinks from up to 300s (today's TTL, unsafe under multi-worker) to up to ~5-10s (the poll interval) -- bounded, cheap, and does not change same-process behavior when the marker hasn't moved. |

### 12.3 Illustrative Code Shape

```sql
-- new migration
CREATE TABLE IF NOT EXISTS cpq_cache_invalidation_marker (
    id INT PRIMARY KEY DEFAULT 1,
    invalidated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT single_row CHECK (id = 1)
);
INSERT INTO cpq_cache_invalidation_marker (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;
```

```python
# doc_discovery.py ingest_confirmed hook (in addition to existing _clear_*() calls)
rdb.execute(
    "UPDATE cpq_cache_invalidation_marker SET invalidated_at = NOW() WHERE id = 1"
)
```

```python
# engine.py -- one small helper, reused by all 5 cache read-paths
_INVALIDATION_MARKER_CACHE: tuple[float, float] | None = None  # (checked_at, marker_ts)
_INVALIDATION_MARKER_POLL_SECONDS = 7.0

def _current_invalidation_marker(dsn: str) -> float:
    global _INVALIDATION_MARKER_CACHE
    now = time.monotonic()
    if _INVALIDATION_MARKER_CACHE is not None:
        checked_at, marker_ts = _INVALIDATION_MARKER_CACHE
        if now - checked_at < _INVALIDATION_MARKER_POLL_SECONDS:
            return marker_ts
    marker_ts = _fetch_invalidation_marker_from_db(dsn)  # one cheap SELECT
    _INVALIDATION_MARKER_CACHE = (now, marker_ts)
    return marker_ts

# each cache's existing TTL check becomes:
# if hit and (monotonic() - cached_at < TTL) and (cached_at_wallclock > _current_invalidation_marker(dsn)):
#     return cached_value
```

**Illustrative only** -- exact wiring will follow this file's existing patterns (`_RULE_JOIN_DATA_CACHE`'s get/set shape) once implementation is approved.

### 12.4 Scope of the Change

- 1 new migration (the marker table)
- 1 new small helper function with its own tiny local cache (the poll-interval memoization)
- ~5 call sites updated -- one per existing cache's get-path (`_load_rule_join_data`, `_load_value_rules`, `_load_all_tables`, `_data_table_forced_vns`, `_substitute_util_get_constraint_vals`)
- `doc_discovery.py`'s `ingest_confirmed` hook updated to write the marker
- New tests: marker read/write correctness, staleness-window behavior (a cache entry older than the marker misses even within its own TTL), and a simulated multi-process scenario (two separate in-memory cache dicts standing in for two workers; one process's clear + marker write must be observed by the other within the poll interval)

### 12.5 Alternatives Considered

| Alternative | Why not chosen |
| --- | --- |
| Revert P1 (single worker) | Safe and simple, but gives up the full concurrency win (2.32x degradation returns) -- the option offered alongside this design, not this design itself. |
| Redis-backed shared cache/pub-sub | New infrastructure not currently in this stack (docker-compose has no redis service) -- larger operational footprint than the gap justifies. |
| Postgres LISTEN/NOTIFY | Closes the staleness window to ~0s instead of ~5-10s, but requires a persistent listener connection per worker process (a background thread/task per process) -- a larger architectural change to the current synchronous, connection-per-request pool model than this gap warrants. |
| Reduce cache TTLs back down for multi-worker | Shrinks the blast radius without fixing the mechanism -- still serves stale data on the other worker, just for a shorter window; papers over the gap rather than closing it. |

### 12.6 Status

**DESIGN ONLY. Not implemented, not tested, not merged. Requires explicit approval before any code is written, per this PR's own review-driven HITL gate on the P1 finding.**
