# CPQ Rule-Catalog JSON Export & Rule-Execution Trace — TDD Plan

Test-first implementation plan for two new CPQ engine capabilities:

1. **Rule Catalog JSON Export** — a per-catalog JSON dump of every hiding/recommendation/constraint
   rule, grouped by product family → product line → model where resolvable.
2. **Rule Execution Trace** — a per-**configuration-session** (not per ask-turn), execution-ordered
   log of every rule that actually fired across the whole session, from first rule-fire until the
   session's confirm signal, sealed into one file per session.

Both live under `src/aryx/cpq/`. No schema/migration changes required — both are read-side
features built on data and mechanisms that already exist (`load_hiding_rules()`,
`load_recommendation_and_constraint_rules()`, the `BmPrdFamily`/`BmCatalog` entity tree, and
`logging_context.py`'s `run_id` contextvar).

**Key correction from the original plan (validated with Andie):** `run_id` is not minted per
ask-turn/HTTP request — it is minted once per `CpqSession` (`state.py:244`, `CpqSession.run_id`)
and threaded through every turn of that configuration. `CpqSession.status` already models the
exact lifecycle needed: `"configuring"` → `"awaiting_approval"` → `"approved"` (Step 8, BOM
payload generated). **`status == "approved"` IS the confirm signal.** This means the trace file's
session-scoping requires no new identifier or lifecycle plumbing — only a new writer and one hook
at the existing status transition.

This document is self-contained: a future session with no prior conversation history should be
able to implement directly from it.

---

## 1. Scope Recap

| Feature | New file | Reads from | Writes |
|---|---|---|---|
| Rule export | `src/aryx/cpq/rule_export.py` | `rdb.fetch_rules()`, `rdb.fetch_value_rules()`, `BmPrdFamily`/`BmCatalog` entities | one JSON per `(workspace_id, catalog_prefix)` |
| Rule trace | `src/aryx/cpq/rule_trace.py` | hooked into `evaluate_rules_loop()`'s existing passes + `CpqSession.status` transitions | one sealed file per configuration session, keyed `{catalog_prefix}_{session_start_ts}.jsonl` |

Confirmed design decisions (from prior planning round):
- Export granularity is **per catalog**, not per ingested CSV — rules aren't tracked at CSV
  granularity today (`rdb.py` keys purely on `workspace_id + rule_type + catalog_prefix`).
- Product/family/line/model classification uses the **existing** `BmPrdFamily`/`BmCatalog` tree
  (walked the same way `model_variable_candidates()` already does), matched against rule condition
  values with **exact, casing-normalized** string matching — no fuzzy matching.
- Rules that don't cleanly resolve to a tree node (no product condition at all, or a
  script-conditioned rule whose literal comparisons can't be resolved) go into an explicit
  `unscoped_or_unresolved` bucket. Never silently guessed, never silently dropped.
- **Trace file lifecycle**: opens on the first rule-fire of a `CpqSession` that has no open trace
  file yet; appends every fired rule from every subsequent ask-turn under that same `run_id`, in
  exact chronological execution order; seals when `CpqSession.status` transitions to `"approved"`.
  The next rule-fire under a different/new `run_id` opens a fresh file — never appends across
  sessions.
- **Orphan sessions** (never reach `"approved"` — abandoned configuration) time out after
  **24 hours** from the file's first write: a sweep seals the file as `status: "orphaned_timeout"`
  rather than leaving it open indefinitely.

---

## 2. Test Pyramid

```
Tier 0  Fixtures & golden corpus         (no test logic yet — data only)
Tier 1  Unit tests                       (pure functions, no DB, <1s each)
Tier 2  Golden-corpus regression tests   (real catalog fixtures vs. frozen JSON)
Tier 3  Integration tests                (full evaluate_rules_loop(), trace ordering)
Tier 4  Regression anchors               (pinned counts — loud failure on silent drift)
```

Build top-to-bottom in this order. Do not write Tier 2+ assertions before Tier 0 fixtures exist
and have been hand-reviewed — a wrong golden file makes every later test lie.

---

## 3. Tier 0 — Fixtures & Golden Corpus

### 3.1 Source data
Reuse real, already-ingested catalog fixtures rather than inventing synthetic rule data — the
same underlying BM-exported data already used elsewhere in the test suite (the two catalogs
referenced throughout this session: the APX Next config catalog and the SL3500e catalog). Real
data exercises real shapes: casing inconsistencies, multi-family trees, script-backed rules.

Directory layout:

```
tests/cpq/fixtures/
    apx_next/
        bm_config_rule.csv
        bm_config_rule_input.csv
        bm_config_rule_action.csv
        bm_config_attr.csv
        bm_prd_family.csv
        bm_catalog.csv
        ...
    sl3500e/
        (same shape)

tests/cpq/golden/
    apx_next.rule_export.json      # frozen expected export
    sl3500e.rule_export.json
    apx_next.rule_trace.jsonl      # frozen expected trace for one fixed multi-turn session scenario
    sl3500e.rule_trace.jsonl
```

Each `*.rule_trace.jsonl` golden file represents **one full configuration session** (multiple
ask-turns, one `run_id`, ending in an `"approved"` status transition) — not a single turn.

### 3.2 Golden file generation rule
- Golden JSON files are **hand-reviewed before being trusted**, not auto-generated and blindly
  committed.
- Regeneration requires an explicit flag/script (e.g. `pytest tests/cpq/test_rule_export.py
  --update-golden`), never a silent overwrite on a normal test run.
- Every regeneration diff must be reviewed in the PR — a rule silently disappearing from the
  golden file is exactly the failure mode this corpus exists to catch.

### 3.3 Fixture manifest (what each fixture must contain, so it's a meaningful corpus and not just "some rows")
- At least one rule with a `condition_value` that **exactly matches** a `BmCatalog` node name.
- At least one rule with a `condition_value` that has a **casing mismatch** against the tree
  (mirrors the real `"MHz"` vs `"MHZ"` bug class found in a prior PR review) — must land in
  `unscoped_or_unresolved`, proving the matcher doesn't silently normalize past real divergence.
- At least one rule with **no product condition at all** (conditions on an unrelated attribute).
- At least one **script-backed** rule (`condition_script`/BML) whose literal comparison cannot be
  statically resolved to a tree node.
- At least one product line with **2+ child models**, to prove line-level rules propagate to all
  children rather than only the line node itself.
- At least one **cyclic or malformed `parent_id`** row (a node that is its own ancestor, or points
  to a non-existent parent) to exercise the tree-builder's fallback path without infinite-looping.

---

## 4. Tier 1 — Unit Tests

`tests/cpq/test_rule_export.py`

- `test_build_product_tree_simple_hierarchy` — 3-level family→line→model tree builds correctly;
  leaf detection matches `single_model_variable_name()`'s existing "never another's parent_id"
  definition.
- `test_build_product_tree_handles_cycle_without_hanging` — cyclic `parent_id` input returns a
  tree with the cyclic branch excluded/flagged, and returns in bounded time (assert via a test
  timeout, not just "didn't crash").
- `test_build_product_tree_handles_dangling_parent_id` — a `parent_id` pointing to nothing:
  treated as a root, not silently dropped.
- `test_classify_rule_scope_exact_match` — condition value exactly equals a model node name →
  resolves to that model (and its ancestor family/line).
- `test_classify_rule_scope_casing_mismatch_is_unresolved` — `"700/800 MHz"` vs. tree's
  `"700/800 MHZ"` → lands in `unscoped_or_unresolved`, does NOT fuzzy-match.
- `test_classify_rule_scope_no_condition_is_unscoped` — rule with no product-relevant condition →
  `unscoped_or_unresolved`, not silently attached to every model.
- `test_classify_rule_scope_script_backed_is_unresolved` — `condition_script`-only rule → always
  `unscoped_or_unresolved` (no BML evaluation attempted at export time — export is static, not a
  simulation).
- `test_classify_rule_scope_line_level_condition_covers_all_child_models` — a condition value
  matching a *line* node is tagged at the line level, with all child models listed as covered, not
  duplicated per-model in the output.

`tests/cpq/test_rule_trace.py`

- `test_rule_trace_records_single_fired_rule` — one rule fires in one pass → exactly one trace
  entry, correct `pass_num`, `rule_type`, `rule_id`, `outcome`.
- `test_rule_trace_skips_rules_that_did_not_fire` — a rule whose condition is false in this turn
  produces no trace entry (trace is "what fired", not "what was evaluated").
- `test_rule_trace_tags_current_run_id` — entry's `run_id` matches `get_run_id()` at call time.
- `test_rule_trace_records_bml_tier_for_script_backed_rule` — script-backed rule's entry includes
  which BML tier resolved it (Tier 1 / Tier 1.5 / Tier 2).
- `test_rule_trace_opens_file_on_first_fire` — no file exists for a `run_id` yet → first fired
  rule creates `{catalog_prefix}_{session_start_ts}.jsonl`.
- `test_rule_trace_appends_across_multiple_turns_same_run_id` — simulate 3 separate ask-turns
  under the same `run_id` (session), each firing rules → all entries land in the **same** file, in
  chronological order across turns, not one file per turn.
- `test_rule_trace_seals_file_on_status_approved` — `CpqSession.status` flips to `"approved"` →
  file is closed/sealed (no further writes accepted for that `run_id`, even if called again).
- `test_rule_trace_new_session_opens_new_file` — after sealing, a fresh `CpqSession`/`run_id` for
  the same catalog opens a **new**, distinctly-named file, not appending to the sealed one.
- `test_rule_trace_orphan_session_times_out_after_24h` — a file opened >24h ago with no
  `"approved"` transition gets swept and sealed as `orphaned_timeout` by the timeout sweep.
- `test_rule_trace_orphan_sweep_does_not_touch_active_sessions` — a file opened <24h ago is left
  untouched by the same sweep.

---

## 5. Tier 2 — Golden-Corpus Regression Tests

`tests/cpq/test_rule_export_golden.py`, parametrized over every fixture directory under
`tests/cpq/fixtures/`:

- `test_export_rules_json_matches_golden[apx_next]`
- `test_export_rules_json_matches_golden[sl3500e]`

Each: load the fixture rows into the test DB (or in-memory equivalent used elsewhere in this
suite), call `export_rules_json(workspace_id, catalog_prefix)`, deep-compare against the frozen
golden JSON.

**Mandatory anti-drop assertion**, run in the same test:

```python
total_loaded = len(hiding_rules) + len(recommendation_rules) + len(constraint_rules)
total_exported = sum(len(v) for v in flatten_export_buckets(export_result))
assert total_loaded == total_exported, "a rule was silently dropped from the export"
```

This is the single most important assertion in the whole plan — classification can be imperfect
(rules can legitimately land in `unscoped_or_unresolved`), but **every loaded rule must appear
somewhere** in the output.

---

## 6. Tier 3 — Integration Tests

`tests/cpq/test_rule_trace_integration.py`

- `test_trace_order_matches_apply_order` — run a real ask-turn fixture through
  `evaluate_rules_loop()` with 2+ fixed-point passes (a hiding rule's effect must trigger a
  recommendation rule, which must trigger a constraint rule, forcing multiple passes). Assert the
  captured `RuleTrace` sequence exactly matches call order: all of pass 1's hiding→recommendation→
  constraint entries appear before any of pass 2's.
- `test_trace_spans_full_session_across_multiple_ask_turns` — drive a `CpqSession` through 3+
  separate ask-turn calls (same `run_id` throughout, status `"configuring"` the whole time), each
  firing different rules; assert one continuous file accumulates entries from all 3 turns in true
  chronological order, not reset between turns.
- `test_trace_seals_exactly_at_approval_turn` — the ask-turn call that flips `status` to
  `"approved"` is the last one whose rule-fires are recorded; a rule that fires in that same turn
  before the status flip is still captured; nothing is recorded after sealing.
- `test_trace_isolated_across_concurrent_sessions` — simulate two full `CpqSession`s (different
  `run_id`s, potentially the same catalog) with interleaved turns; assert each session's file
  contains only its own entries — no cross-contamination, even when both are open simultaneously.
- `test_trace_matches_golden_jsonl[apx_next]` / `[sl3500e]` — same golden-corpus discipline as
  Tier 2, applied to a fixed, deterministic **multi-turn session** scenario per fixture, from first
  fire through the `"approved"` transition.
- `test_trace_orphan_sweep_seals_abandoned_session_integration` — a `CpqSession` fixture frozen at
  `"configuring"` with a trace file timestamped >24h old gets sealed as `orphaned_timeout` by the
  sweep job, verified end-to-end (writer + sweep, not just the sweep's unit logic).

---

## 7. Tier 4 — Regression Anchors

- `test_apx_next_export_rule_count_is_pinned` — asserts total exported rule count for the
  `apx_next` fixture equals a hardcoded number (e.g. `assert total == 47`). Any change to
  ingestion, rule loading, or classification that silently changes what gets exported fails this
  test loudly, forcing a deliberate golden-file update rather than an invisible behavior change.
- Same pattern for `sl3500e`.

---

## 8. Out of Scope / Explicit Non-Goals

- No fuzzy/heuristic string matching for family/line/model classification (exact-normalized only,
  per confirmed design decision) — do not add Levenshtein/embedding matching later without a new
  design discussion.
- Export does not evaluate `condition_script` rules against sample data to guess their scope —
  static classification only.
- No Oracle/OCI backend variant required for either feature in this pass (mirrors the existing
  Postgres-only scope of the `discoveries.py` durability fix).
- No mid-session file rotation/size cap — a session's trace file grows unbounded until sealed;
  revisit only if a real pathologically-long configuration is observed.
- The 24h orphan-timeout sweep is a simple age check on file-open-time vs. `CpqSession.status`, not
  a full session-expiry system — it only governs trace-file sealing, not `CpqSession` itself.

---

## 9. Definition of Done

- [ ] Tier 0 fixtures + golden files committed and hand-reviewed in their own PR/commit, before any
      assertion logic is written against them.
- [ ] All Tier 1 unit tests pass with no DB dependency.
- [ ] All Tier 2 golden-corpus tests pass, including the mandatory anti-drop assertion.
- [ ] All Tier 3 integration tests pass, proving trace order, session isolation, seal-on-approve,
      and the 24h orphan-timeout sweep.
- [ ] Tier 4 pinned-count tests in place as a tripwire for future silent drift.
- [ ] `rule_export.py` and `rule_trace.py` contain no new query logic — both are read/instrument-only
      layers on top of `rdb.py`/`engine.py`'s existing rule loading and execution.
