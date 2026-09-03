# Raven Style Compliance Plan

**One sentence:** bring `src/aryx/`, `apps/web/`, and `shay_backend/` into compliance with `.raven/manifest.json`'s configured style thresholds (150 lines/file, 60 lines/function, type hints required, no `print()`), in phases ordered by risk, without mechanically restructuring the two files whose size carries months of hard-won correctness fixes.

**Date:** 2026-09-03 (revised same day — `max_file_lines` tightened from 400 to 150 by explicit project decision; manifest bumped to v1.0.7, full re-scan below)
**Scope:** all three codebases the manifest's live config actually covers (`Stack: ['python', 'typescript']`) — `src/aryx/` (280 Python files), `apps/web/` (148 TypeScript/TSX files), `shay_backend/` (205 Python files). The first version of this plan covered `src/aryx/` only; revised after a `/raven-plan` review caught the gap against the manifest's declared stack.
**Source of truth for rules:** `.raven/manifest.json` → `style` section (this project's actual configured thresholds — see §1.1 for the 400→150 revision history). `.raven/architecture.md` (now updated to v1.5) confirmed all three codebases are part of the current system.
**Method:** AST-based scan (`ast.walk`) for the two Python codebases; file-length grep for TypeScript (no AST parser available for a function-length check there — see §3.3). Every number below is a full-repo count as of this date, not a sample, re-scanned against the 150-line threshold.

---

## 1. The rules this project actually enforces

From `.raven/manifest.json` (v1.0.7):

| Rule | This project's threshold | Enforced at |
|---|---|---|
| Max lines per file | **150** (tightened from 400, 2026-09-03) | commit (hard block) |
| Max lines per function | 60 | commit (hard block) |
| Type hints on all functions | required | commit (hard block) |
| Docstrings on all functions | **not required** (`require_docstrings: false`) | — |
| `print()` banned, use `logging` | required | commit (hard block) |
| `logging` imported if used | required | commit (hard block) |
| Naming | `snake_case` (Python) / `camelCase` (TS) / `PascalCase` (components) | commit (hard block) |

`enforce_at: "commit"` means none of this blocks mid-coding today — style-enforcer only advises during coding and hard-blocks at the pre-commit hook. This plan exists because a full-repo sweep has never been run against these thresholds; the pre-commit hook only catches violations in *newly changed* files going forward, not the accumulated backlog.

### 1.1 Threshold history — 400 → 150

This plan originally used **400 lines/file** (this project's manifest-configured value at the time, deliberately not Raven's generic 150-line planning default) and everything through Phase 1 execution was scanned and verified against that number. On 2026-09-03, after Phase 1 completed and partway through Phase 2's first file split, an explicit project decision tightened `max_file_lines` to **150** — `.raven/manifest.json` was updated (v1.0.6 → v1.0.7) so this is now the real value the commit-time hook enforces, and this document was fully re-scanned and rewritten against it (§2–§9 below all reflect 150, not 400).

This is a **substantial scope change, not a relabeling**: going from 400 to 150 nearly triples the `src/aryx/` file-length backlog (22 → 69 files), more than doubles `apps/web/`'s (13 → 43), and more than doubles `shay_backend/`'s (47 → 104). The function-length threshold (60 lines) is unchanged, so §2.2/§4.2's function-level counts are unaffected by this revision — only file-level counts and every phase's file list, priority order, and effort estimate below changed.

Work already completed under the old threshold is not invalidated: Phase 1's 15 type-hint fixes and the `print()` exception are threshold-independent (they were never about file length), and the `data_table_cache.py` extraction from `data_table_resolver.py` (in progress during this revision) reduces `data_table_resolver.py`'s own line count regardless of which file-length number is the target — it just means `data_table_resolver.py` needs further splitting to actually clear 150, not only 400.

---

## 2. Full scan results — `src/aryx/`

### 2.1 Files over 150 lines — 69 of 280 (24.6%)

Re-scanned 2026-09-03 against the revised 150-line threshold (§1.1). The original 22-file table (everything over 400 lines) is unchanged in content and is now Tier A below; Tier B is the 47 additional files this revision adds (150–400 lines), test-coverage-checked using the corrected `test_cpq_<basename>.py`-aware glob (§2.1's earlier false-negative fix, applied from the start this time).

**Tier A — over 400 lines (the original 22, unchanged):**

| Lines | File | Existing dedicated test file? |
|---:|---|---|
| 14,469 | `src/aryx/cpq/engine.py` | ⚠️ `tests/test_cpq_engine_catalog_scope.py` — narrow, not full-file coverage |
| 13,058 | `src/aryx/api/ask_api.py` | ❌ none |
| 2,178 | `src/aryx/cpq/bml.py` | ✅ `tests/test_bml*.py` |
| 1,520 | `src/aryx/pipeline/doc_discovery.py` | ✅ `tests/test_doc_discovery*.py` |
| 1,413 | `src/aryx/cpq/intent_gateway.py` | ✅ `tests/test_cpq_intent_gateway.py` |
| 1,056 | `src/aryx/config.py` | ✅ `tests/test_cpq_config_*.py` (4 files) |
| 71 (was 406, 624, 902, then 1,036 originally) | `src/aryx/cpq/data_table_resolver.py` | ✅ done — fully split into 10 files, see Phase 2a's own status table for the breakdown; this file is now a pure re-export hub |
| 982 | `src/aryx/api/data_api.py` | ❌ none |
| 906 | `src/aryx/source_catalog.py` | ✅ `tests/test_source_catalog*.py` |
| 880 | `src/aryx/cpq/rdb.py` | ⚠️ `tests/test_cpq_rdb_attr_set_assoc.py` — narrow, not full-file coverage |
| 657 (was 763) | `src/aryx/store/oracle_pool.py` | ✅ `tests/test_oracle_pool.py` — split in progress (2 of 4 files done, see Phase 2a status) |
| 647 | `src/aryx/cpq/state.py` | ❌ none |
| 631 | `src/aryx/store/shay_bridge_store.py` | ✅ `tests/test_shay_bridge_store.py` |
| 589 | `src/aryx/cpq/intent_schema.py` | ✅ `tests/test_cpq_intent_schema.py` |
| 569 | `src/aryx/store/ask_thread_store.py` | ✅ `tests/test_ask_thread_store*.py` |
| 548 | `src/aryx/graph/falkor_store.py` | ❌ none |
| 532 | `src/aryx/graph/reader.py` | ❌ none |
| 532 | `src/aryx/api/file_ingest_api.py` | ❌ none |
| 491 | `src/aryx/store/entity_store.py` | ✅ `tests/test_entity_store*.py` |
| 480 | `src/aryx/pipeline/enrich.py` | ❌ none |
| 477 | `src/aryx/pipeline/ingest_validation.py` | ✅ `tests/test_ingest_validation*.py` |
| 472 | `src/aryx/pipeline/dynamic_fk.py` | ✅ `tests/test_dynamic_fk*.py` |

Two files are extreme outliers — `cpq/engine.py` at **96×** the *new* limit and `api/ask_api.py` at **87×** — everything else in Tier A is within 3–15× and far more tractable. (Line counts shifted slightly from the original scan for a few files — `data_table_resolver.py` dropped to 902 from the `data_table_cache.py` extraction already done this session; `bml.py`/`intent_gateway.py`/etc. shifted ±1–3 lines from unrelated concurrent edits.)

**Tier B — 150–400 lines (47 additional files, new to this revision):**

| Lines | File | Existing dedicated test file? |
|---:|---|---|
| 391 | `src/aryx/graph/oracle_graph_reader.py` | ✅ `tests/test_oracle_graph_reader_shortest_path_scope.py` |
| 372 | `src/aryx/cpq/bom_gate.py` | ❌ none |
| 369 | `src/aryx/cpq/pending_scope.py` | ✅ `tests/test_cpq_pending_scope.py` |
| 340 | `src/aryx/resolution/run.py` | ❌ none |
| 328 | `src/aryx/cpq/session_guard.py` | ❌ none |
| 313 | `src/aryx/store/source_purge_store.py` | ✅ `tests/test_source_purge_store.py` |
| 310 | `src/aryx/llm_providers.py` | ❌ none |
| 302 | `src/aryx/api/ask_thread_api.py` | ✅ `tests/test_ask_thread_api.py` |
| 294 | `src/aryx/api/main.py` | ❌ none |
| 293 | `src/aryx/graph/oracle_graph_store.py` | ❌ none |
| 291 | `src/aryx/pipeline/orchestrate.py` | ❌ none |
| 282 | `src/aryx/broker/__init__.py` | ❌ none |
| 281 | `src/aryx/demo/support_data_generator.py` | ❌ none |
| 274 | `src/aryx/explore.py` | ✅ `tests/test_explore.py` |
| 260 | `src/aryx/store/discovery_store.py` | ✅ `tests/test_discovery_store.py` |
| 253 | `src/aryx/project.py` | ❌ none |
| 251 | `src/aryx/cpq/rule_export.py` | ✅ `tests/test_cpq_rule_export.py` |
| 247 | `src/aryx/api/admin_api.py` | ✅ `tests/test_admin_api.py` |
| 242 | `src/aryx/api/workspace_api.py` | ✅ `tests/test_workspace_api.py` |
| 239 | `src/aryx/pipeline/dimension_link.py` | ✅ `tests/test_dimension_link.py` |
| 239 | `src/aryx/connectors/doc_router.py` | ❌ none |
| 238 | `src/aryx/mcp/server.py` | ❌ none |
| 238 | `src/aryx/cpq/rule_trace.py` | ✅ `tests/test_cpq_rule_trace.py`, `tests/test_rule_trace_store.py` |
| 237 | `src/aryx/ontology/extract.py` | ✅ `tests/test_extract_mentions_concurrency.py`, `tests/test_extract_mentions_retry.py` |
| 237 | `src/aryx/cpq/intent_queue.py` | ✅ `tests/test_cpq_intent_queue.py` |
| 232 | `src/aryx/graph/retrieve.py` | ❌ none |
| 220 | `src/aryx/store/mcp_token_store.py` | ✅ `tests/test_mcp_token_store.py`, `tests/test_mcp_token_store_oracle_issue.py` |
| 220 | `src/aryx/api/doc_discover_api.py` | ❌ none |
| 213 | `src/aryx/workspaces.py` | ✅ `tests/test_workspaces.py` |
| 208 | `src/aryx/store/oracle_workspace.py` | ✅ `tests/test_oracle_workspace.py` |
| 207 | `src/aryx/ui/ask_panel.py` | ❌ none |
| 193 | `src/aryx/ui/api.py` | ⚠️ `tests/test_api_security.py` — name match uncertain, needs a look |
| 191 | `src/aryx/resolution/chunked.py` | ✅ `tests/test_chunked_resolution.py` |
| 184 | `src/aryx/store/datasource_store.py` | ✅ `tests/test_datasource_store.py` |
| 183 | `src/aryx/worker/oci_functions_provisioner.py` | ❌ none |
| 183 | `src/aryx/api/ontology_api.py` | ✅ `tests/test_ontology_api_write_guard.py` |
| 180 | `src/aryx/api/ontology_browse.py` | ❌ none |
| 178 | `src/aryx/llm.py` | ✅ 9 matching test files (see §8 regen list) — likely broad coverage, confirm scope before splitting |
| 177 | `src/aryx/resolve_entities.py` | ❌ none |
| 174 | `src/aryx/llm_runtime.py` | ✅ `tests/test_llm_runtime_log_call_dsn.py`, `tests/test_llm_runtime_turn_usage.py` |
| 169 | `src/aryx/worker/fn_handler.py` | ❌ none |
| 169 | `src/aryx/api/rest_ingest_api.py` | ❌ none |
| 168 | `src/aryx/reasoning/engine.py` | ⚠️ basename collides with `cpq/engine.py` in automated matching — do not trust `test_cpq_engine_catalog_scope.py` as this file's coverage, check manually before splitting |
| 168 | `src/aryx/api/shay_bridge_api.py` | ✅ `tests/test_shay_bridge_api.py` |
| 162 | `src/aryx/cpq/data_table_cache.py` | ⚠️ no dedicated file, but exercised indirectly via `tests/test_cpq_invalidation_marker_2026_08_28.py` and `tests/test_cpq_data_table_resolver.py` (extracted from `data_table_resolver.py` this session, both retargeted to it) |
| 158 | `src/aryx/store/action_store.py` | ❌ none |
| 153 | `src/aryx/models.py` | ❌ none |

**23 of the 47 Tier B files have no matching test file at all** — same golden-master requirement as Tier A's untested files applies (§6, item 1), checked per-file before that file's own split, not pre-written here in bulk. A "✅" above means a plausibly-matching test file exists, not that its coverage breadth has been verified — treat every Tier B "✅" the way `data_table_resolver.py`'s Tier A entry was treated before this revision: confirm actual function-level coverage at that file's own execution step (§2.1.1 is the worked example of how, and how a filename match can still be 3-of-12-functions short).

**Correction that produced the corrected glob used above (2026-09-03, during Phase 2 execution, applied retroactively to Tier A too):** the plan's very first scan checked `tests/test_<module_basename>*.py` only, missing this codebase's `tests/test_cpq_<basename>.py` convention — the false negative this produced for 6 of Tier A's original "untested" files (`engine.py`, `intent_gateway.py`, `config.py`, `data_table_resolver.py`, `rdb.py`, `intent_schema.py`) is why Tier B above was checked with both patterns from the start.

### 2.1.1 `data_table_resolver.py` coverage breakdown (worked example, checked 2026-09-03)

Of the file's 12 public (non-underscore) functions, `tests/test_cpq_data_table_resolver.py` (684 lines, 25 tests) references 9 by name in test bodies: `resolve_whitelist_values`, `attribute_applies`, `attr_ever_governed_for_cpq_model`, `resolve_product_cpq_model_family`, `resolve_invalid_product_variant`, `discover_cpq_models_for_base_model`, `find_inconsistent_filled_pairs`, `find_inconsistent_filled_pairs_detailed`, `governed_attr_names_for_base_model` (1 reference — thin, worth a second look before splitting). **3 functions have zero references and need a golden-master test before this file is split:** `governed_required_attr_names_for_base_model`, `resolve_region_allow_value`, `resolve_product_cpq_models_from_rows`.

### 2.2 Functions over 60 lines — 199 total (top 30 shown, unchanged by the 400→150 file-threshold revision)

| Lines | Function | Location |
|---:|---|---|
| 3,633 | `_run_cpq_turn_inner()` | `api/ask_api.py:8781` |
| 2,056 | `auto_fill()` | `cpq/engine.py:8676` |
| 604 | `_dispatch_intent_result()` | `api/ask_api.py:5868` |
| 558 | `load_product_config()` | `cpq/engine.py:3909` |
| 523 | `build_payload()` | `cpq/engine.py:13050` |
| 487 | `_load_value_rules()` | `cpq/engine.py:5878` |
| 474 | `evaluate_rules_loop()` | `cpq/engine.py:7247` |
| 442 | `_handle_cascade()` | `api/ask_api.py:2754` |
| 397 | `_llm_first_gateway_turn()` | `api/ask_api.py:6767` |
| 368 | `_handle_cascade_multi()` | `api/ask_api.py:4077` |
| 354 | `apply_constraint_rules()` | `cpq/engine.py:6777` |
| 352 | `ingest_confirmed()` | `pipeline/doc_discovery.py:1119` |
| 340 | `_handle_cpq_qa()` | `api/ask_api.py:1284` |
| 303 | `_run_files()` | `api/file_ingest_api.py:145` |
| 301 | `classify_intent()` | `cpq/intent_gateway.py:727` |
| 280 | `_detect_fk_links()` | `pipeline/doc_discovery.py:672` |
| 280 | `data_router()` | `api/data_api.py:89` |
| 277 | `_xml_to_csvs()` | `pipeline/doc_discovery.py:186` |
| 231 | `ask_thread_router()` | `api/ask_thread_api.py:72` |
| 228 | `_reask_stale_constraint_violations()` | `api/ask_api.py:2459` |
| 226 | `extract_catalog_hints()` | `cpq/engine.py:2614` |
| 225 | `run_pipeline()` | `pipeline/orchestrate.py:67` |
| 220 | `_change_request_matches()` | `cpq/engine.py:11534` |
| 220 | `_handle_multi_select_removal()` | `api/ask_api.py:3198` |
| 216 | `subgraph()` | `graph/reader.py:229` |
| 213 | `_build_catalog_attribute_listing_text()` | `api/ask_api.py:817` |
| 209 | `ensure_workspace_mapping()` | `store/shay_bridge_store.py:59` |
| 208 | `_cpq_summary_text()` | `api/ask_api.py:514` |
| 197 | `classify_ask_route()` | `cpq/intent_gateway.py:1212` |
| 196 | `_handle_attr_activation()` | `api/ask_api.py:3420` |

The remaining 169 (not listed here — see §8 for how to regenerate the full list) are mostly in the 60–150 line range and lower priority than the ones above.

**Important:** `data_router()` and `ask_thread_router()` showing up here are FastAPI's own closure-based router-factory pattern (a function that defines several `@router.get`/`@router.post` handlers as nested functions and returns the router) — the AST line count includes every nested route handler's body. This is a structural pattern already used throughout `api/`, not a mistake, and needs a different remediation than "shorten this function" (see §7).

### 2.3 Functions missing a return type hint — 15 total

| File | Function |
|---|---|
| `api/ask_api.py:12076` | `_recompute_pending()` |
| `api/doc_discover_api.py:46` | `_build_read_progress()` |
| `api/file_ingest_api.py:115` | `_make_should_stop()` |
| `api/main.py:125` | `_authenticate_mcp()` |
| `api/main.py:230` | `_lifespan()` |
| `api/main.py:87` | `__call__()` |
| `api/main.py:103` | `_send()` |
| `api/security.py:39` | `dispatch()` |
| `connectors/doc_router.py:52` | `_connector_for()` |
| `cpq/engine.py:4470` | `_load_rule_join_data()` |
| *(5 more — see §8 to regenerate)* | |

Small, mechanical, low-risk fix.

### 2.4 `print()` usage — 1 file, confirmed legitimate exception, not fixed

`src/aryx/pipeline/ingest_validation.py:472` — checked at Phase 1 execution time (2026-09-03), and it's not the mechanical fix originally assumed. The call site is inside `main()`, a genuine CLI entry point (`argparse`, `if __name__ == "__main__":`) that prints a human-readable validation report and returns an exit code — the standard Unix CLI convention. Converting it to `logger.info()` would be a regression, not a fix: the report might not appear on stdout at all if the root logger has no stream handler configured when this script is run standalone, breaking the one thing it exists to do. No other file in `src/aryx/` has this CLI-entry-point pattern to compare against (checked). **Left as `print()`, marked as a confirmed style-rule exception** rather than mechanically changed to match the letter of the rule against its evident intent.

### 2.5 `logging` used without `import logging` — 0 files

Clean. No action needed.

### 2.6 Naming convention — not yet scanned

The AST scan above didn't check `snake_case`/`PascalCase`/`camelCase` compliance. This needs a separate pass (see §8) before it can be called complete — flagging honestly rather than claiming a number I don't have.

---

## 3. Full scan results — `apps/web/` (TypeScript)

148 `.ts`/`.tsx` files (excluding `node_modules`). No AST parser was used here — file-length is an exact count; there is no function-length or missing-type-annotation check for this section (TypeScript's structure doesn't lend itself to the same simple `ast.walk` approach as Python, and building a real one was out of scope for this plan — flagged honestly rather than approximated).

### 3.1 Files over 150 lines — 43 of 148 (29.1%), re-scanned 2026-09-03 against the revised threshold

Tier A (the original 13, over 400 lines) is unchanged; Tier B is 30 additional files new to this revision.

**Tier A — over 400 lines:**

| Lines | File |
|---:|---|
| 1,167 | `apps/web/components/graph/EntityGraph.tsx` |
| 874 | `apps/web/lib/shay-api.ts` |
| 817 | `apps/web/components/shay/WorkspaceSettingsPage.tsx` |
| 696 | `apps/web/lib/api.ts` |
| 668 | `apps/web/components/shay/AdminUsersPageView.tsx` |
| 622 | `apps/web/app/settings/page.tsx` |
| 580 | `apps/web/app/page.tsx` |
| 562 | `apps/web/components/shay/AdminUsersPageParts.tsx` |
| 527 | `apps/web/components/brand/Header.tsx` |
| 514 | `apps/web/components/data/DataExplorer.tsx` |
| 474 | `apps/web/lib/types.ts` |
| 462 | `apps/web/components/shay/WorkspaceIndexPage.tsx` |
| 450 | `apps/web/lib/shay-session.ts` |

`EntityGraph.tsx` is the one real outlier (7.8× the *new* limit); everything else in Tier A is now 3–6×.

**Tier B — 150–400 lines (30 additional files, new to this revision):**

| Lines | File |
|---:|---|
| 396 | `apps/web/components/data/XmlSourceDetail.tsx` |
| 371 | `apps/web/components/shay/AdminUsersPage.tsx` |
| 326 | `apps/web/components/jobs/JobsBadge.tsx` |
| 320 | `apps/web/lib/shay-types.ts` |
| 315 | `apps/web/app/company-signup/page.tsx` |
| 296 | `apps/web/app/register/page.tsx` |
| 291 | `apps/web/app/brief/page.tsx` |
| 278 | `apps/web/components/model/LightweightTab.tsx` |
| 274 | `apps/web/components/model/Canvas.tsx` |
| 262 | `apps/web/components/shay/WorkspaceOverviewPage.tsx` |
| 261 | `apps/web/components/model/Inspector.tsx` |
| 261 | `apps/web/app/observability/page.tsx` |
| 255 | `apps/web/components/model/RulesTab.tsx` |
| 252 | `apps/web/components/data/GraphLens.tsx` |
| 250 | `apps/web/components/shay/ShayChatSurface.tsx` |
| 230 | `apps/web/components/ingest/DocsTab.tsx` |
| 225 | `apps/web/app/reset-password/page.tsx` |
| 205 | `apps/web/components/start/Running.tsx` |
| 203 | `apps/web/components/ask/MessageList.tsx` |
| 199 | `apps/web/components/model/SurvivorEditor.tsx` |
| 193 | `apps/web/app/home/page.tsx` |
| 190 | `apps/web/components/hitl/HITLDrawer.tsx` |
| 188 | `apps/web/app/login/page.tsx` |
| 177 | `apps/web/components/ask/ShareConfigDialog.tsx` |
| 172 | `apps/web/components/shay/WorkspaceIndexCard.tsx` |
| 167 | `apps/web/components/start/Files.tsx` |
| 160 | `apps/web/components/ask/AskHistoryDrawer.tsx` |
| 156 | `apps/web/app/api/_aryxProxy.ts` |
| 154 | `apps/web/app/model/page.tsx` |
| 152 | `apps/web/components/model/PublishTab.tsx` |

No test-coverage column here — §3.3 already flags that this plan has no evidence either way on `apps/web/`'s test setup; that check is Phase 3's own first step (unchanged by this revision, just now applies to 43 files instead of 13).

### 3.2 `console.log` usage — 0 files

Clean. No action needed — this repo already keeps the browser console quiet.

### 3.3 Naming and function-length — not scanned (see caveat above)

Before Phase 6 (naming and function-length audit) can be called complete for this codebase, someone needs an actual TypeScript-aware check (`eslint` with a max-lines-per-function rule, or a small `typescript` compiler-API script) rather than the regex/line-count approach used here.

## 4. Full scan results — `shay_backend/`

205 Python files (`app/`, `tests/`, top-level scripts, `migrations/`). Same AST method as `src/aryx/`.

**Scope confirmed:** this backlog is proportionally much larger than `src/aryx/`'s, and `shay_backend/` reads as a separately-maintained codebase (its own `Log Analyzer Backend` framing, its own test suite, its own conventions predating the Shay↔Aryx bridge work) — but the project owner confirmed (2026-09-03, see §4.6) it is governed by this same manifest. Phase 5 (§7) plans it in full on that basis.

### 4.1 Files over 150 lines — 104 of 205 (50.7%), re-scanned 2026-09-03 against the revised threshold

Half of this codebase is now over the limit. Tier A (the original 47, over 400 lines — 22.9% of the codebase, "nearly 3× `src/aryx/`'s rate" at the old threshold) is unchanged; Tier B is 57 additional files new to this revision.

**Tier A — over 400 lines:**

| Lines | File |
|---:|---|
| 5,518 | `app/routes/datasources.py` |
| 2,630 | `app/routes/channels.py` |
| 2,547 | `app/routes/tasks.py` |
| 2,513 | `app/routes/messages.py` |
| 2,505 | `app/routes/payment_gateway.py` |
| 2,279 | `tests/test_gg_datasources.py` |
| 2,196 | `app/routes/public.py` |
| 2,150 | `app/routes/approvals.py` |
| 1,870 | `app/routes/user_auth.py` |
| 1,821 | `app/services/email_service.py` |
| 1,493 | `app/routes/gg_datasources.py` |
| 1,097 | `app/routes/attachments.py` |
| 1,060 | `app/services/zoho_service.py` |
| 929 | `app/services/daily_summary_scheduler.py` |
| 882 | `app/routes/template.py` |
| 802 | `tests/test_gg_app_connections.py` |
| 768 | `app/routes/notifications.py` |
| 767 | `app/routes/token_details.py` |
| 760 | `tests/test_gg_workspaces.py` |
| 756 | `app/routes/app_accounts.py` |
| 718 | `app/schemas/user.py` |
| 711 | `tests/test_integration_db.py` |
| 687 | `app/routes/gg_app_connections.py` |
| 658 | `app/routes/users.py` |
| 657 | `app/routes/threads.py` |
| 648 | `app/routes/companies.py` |
| 635 | `app/services/vault_data_builder.py` |
| 635 | `app/routes/gg_workspaces.py` |
| 605 | `tests/test_gg_channels.py` |
| 553 | `tests/test_embedd_type_final.py` |
| 548 | `app/routes/workspaces.py` |
| 547 | `app/services/socket_client_service.py` |
| 530 | `app/routes/checklists.py` |
| 529 | `app/routes/subscriptions.py` |
| 514 | `tests/test_error_notification.py` |
| 498 | `scripts/setup_templates.py` |
| 490 | `app/services/socket_event_handler.py` |
| 484 | `main.py` |
| 478 | `app/services/ml_service.py` |
| 464 | `app/core/config.py` |
| 454 | `app/routes/apps.py` |
| 450 | `app/routes/gg_channels.py` |
| 445 | `app/schemas/datasource.py` |
| 425 | `app/services/email_verification_service.py` |
| 413 | `app/services/sso_service.py` |
| 409 | `tests/test_email_branding.py` |
| 402 | `app/routes/odoo_connect.py` |

No single 10,000+ line outlier the way `src/aryx/` has two — instead a much longer tail of 400–5,500 line route files. `datasources.py` alone, at 5,518 lines, is bigger than any file in `src/aryx/` except the two acknowledged mega-files.

**Tier B — 150–400 lines (57 additional files, new to this revision, top 30 shown — see §8 to regenerate the rest):**

| Lines | File |
|---:|---|
| 396 | `app/services/file_storage.py` |
| 388 | `app/routes/audit.py` |
| 371 | `app/routes/agent.py` |
| 344 | `app/core/database.py` |
| 339 | `app/schemas/task.py` |
| 332 | `tests/test_companies.py` |
| 327 | `app/services/vault_service.py` |
| 327 | `app/routes/subscription_plans.py` |
| 326 | `tests/test_workspaces.py` |
| 313 | `app/routes/auth.py` |
| 311 | `app/services/template_service.py` |
| 308 | `app/schemas/gg_datasource.py` |
| 308 | `app/core/migrations.py` |
| 295 | `tests/test_ml_service_embedd_type.py` |
| 290 | `tests/test_aryx_bridge.py` |
| 289 | `app/routes/aryx.py` |
| 288 | `app/routes/support.py` |
| 284 | `app/core/encryption_utils.py` |
| 282 | `scripts/migration_examples.py` |
| 279 | `app/core/auth.py` |
| 274 | `tests/test_sf_connect.py` |
| 271 | `app/schemas/message.py` |
| 257 | `app/schemas/__init__.py` |
| 245 | `app/routes/sf_connect.py` |
| 238 | `app/schemas/subscription_plan.py` |
| 234 | `app/routes/sso.py` |
| 229 | `app/schemas/common.py` |
| 223 | `tests/test_zoho_connect.py` |
| 223 | `migrations/versions/create_approval_table.py` |
| 222 | `tests/test_odoo_connect.py` |
| … | *(27 more, 150–222 lines — see §8 to regenerate)* |

`app/routes/aryx.py` (289 lines) is worth flagging specifically: it's the route file implementing the Shay↔Aryx bridge endpoints (§4.6, `.raven/architecture.md` v1.5) — the one file in this whole Tier B list with a direct dependency on this session's own Oracle-parity work, so it inherits Phase 2's `store/`-file caution level, not Phase 5's default route-file risk level.

### 4.2 Functions over 60 lines — 244 total (top 10 shown, unchanged by the 400→150 file-threshold revision)

| Lines | Function | Location |
|---:|---|---|
| 657 | `create_datasources_bulk_internal()` | `app/routes/datasources.py:2866` |
| 637 | `create_company_simple()` | `app/routes/public.py:378` |
| 565 | `create_datasources_bulk()` | `app/routes/datasources.py:2274` |
| 423 | `generate_datasource_metadata()` | `app/routes/datasources.py:714` |
| 389 | `fetch_company_subscription_details()` | `app/routes/payment_gateway.py:1915` |
| 374 | `list_datasources()` | `app/routes/datasources.py:3532` |
| 355 | `llm_validation()` | `app/routes/token_details.py:413` |
| 342 | `build_vault_credentials()` | `app/services/vault_data_builder.py:27` |
| 336 | `validate_payment()` | `app/routes/payment_gateway.py:1200` |
| 330 | `create_datasource()` | `app/routes/datasources.py:1140` |

### 4.3 Functions missing a return type hint — 1,155 total

Two orders of magnitude larger than `src/aryx/`'s 15. This alone is the strongest signal that `shay_backend/` was not built under the same `require_type_hints: true` discipline this manifest states — either it predates that rule, or it's governed by a different convention. Sample (see §8 to regenerate the full 1,155-line list):

- `add_embedding_columns.py:11` — `add_embedding_columns()`
- `app/core/database.py:151` — `_oracle_repair_partial_unique_indexes()`
- `app/core/database.py:194` — `init_db()`
- `app/core/db_types.py:27` — `load_dialect_impl()`

### 4.4 `print()` usage — 19 files

Higher than `src/aryx/`'s 1, but still a mechanical, low-risk fix per occurrence.

### 4.5 `logging` used without `import logging` — 0 files (1 scan false-positive corrected)

The scan script initially flagged `init_migrations.py` and `migrations/env.py`, but both actually import via `from logging.config import fileConfig` — a real import, just not the literal string `"import logging"` the naive check looked for. Corrected here rather than left as a false alarm; the underlying scan script (§8) should be fixed to check for `import logging` OR `from logging` before being trusted again.

### 4.6 Scope confirmed — `shay_backend/` is governed by this manifest

Confirmed by the project owner (2026-09-03): `shay_backend/` falls under this same `.raven/manifest.json`, same thresholds as `src/aryx/` — no separate manifest, no separate carve-out. Phase 5 (§7) is planned in full below on that basis.

Given the scale of the gap (51% of files over the 150-line limit vs. 25% in `src/aryx/`; 1,155 vs. 15 missing type hints), this is a materially bigger lift than Phase 2, but the same file-by-file, test-gated discipline applies — the breadth of the backlog is a reason to sequence it carefully (see Phase 5's dependency map), not a reason to treat it as out of scope.

## 5. Why this can't be one mechanical sweep

`cpq/engine.py` and `api/ask_api.py` are not just long — their size comes from **months of narrow, hard-won correctness fixes**, many cited directly in comments pointing at incident docs already in this repo (e.g. `docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md`, `docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_2026_08_19.md`). A mechanical "split every file/function until it's under the limit" pass on these two files risks reintroducing exactly the bugs those fixes closed, because:

- Behavior in `auto_fill()`, `_run_cpq_turn_inner()`, and related functions depends on **execution order** and **shared local state** built up across many branches in one function body — extracting a chunk into a helper can silently change which branch order applies.
- This session's own work (the `ensure_workspace_mapping()`/`ensure_chat_mapping()` fixes) showed that even a well-reviewed, tested change to a *much smaller* function in this codebase needed two follow-up correction rounds (`ORA-22848`, then `ORA-00932`) before it was actually correct against real data. The two mega-files carry orders of magnitude more accumulated edge-case handling than that.

So: **file-length and function-length compliance for these two files is treated as its own initiative**, not folded into the general cleanup (see Phase 4).

---

## 6. Safety net — guaranteeing no feature breaks

Every phase below references this section. It is a binding policy, not a suggestion, and it exists because this session already has direct evidence that automated tests alone are not sufficient here: the `ensure_workspace_mapping()`/`ensure_chat_mapping()` Oracle fixes (PRs #310, #311) were reviewed and had passing tests at each step, and still needed **three separate rounds of live testing against the real Oracle ADB** to catch `ORA-22848`, then `ORA-00932`, then `ORA-01407` — bugs that only appeared against real data (a pre-existing corrupted row) and a real Oracle type-checking quirk, neither of which any mock or unit test in this codebase would have caught. This plan's whole style-compliance backlog touches the same class of code. The policy below is written to catch what tests alone won't.

### 6.0 Regression baseline, confirmed today (2026-09-03)

Before writing the policy below, ran the existing suite for every file this session actually touched, to confirm this plan's own docstring/comment changes broke nothing — **against `ARYX_DB_BACKEND=oci`**, matching this project's real deployment target, not the `local` backend:

```
ARYX_DB_BACKEND=oci PYTHONPATH=src python3 -m pytest \
  tests/test_oracle_pool.py tests/test_shay_bridge_store.py \
  tests/test_shay_bridge_api.py tests/test_llm_runtime_turn_usage.py \
  tests/test_llm_runtime_log_call_dsn.py -v
```

**Result: 111 passed, 0 failed under `oci`** — including `test_on_conflict_do_update_raises` (the exact test covering the Oracle `ON CONFLICT` guard from §5) and `test_ensure_workspace_mapping_creates_aryx_workspace_when_missing` (the exact function this session added a docstring to). Also validated `.raven/manifest.json` (valid JSON) and `docker-compose-oci.yml` (valid YAML, and `docker compose config --quiet` passes) after this session's edits to both.

Two things worth recording here since they weren't obvious and future phases will hit them too:
- **`PYTHONPATH=src` is required** to run these tests from a plain host Python (the package isn't pip-installed in this environment) — without it, every test file importing `aryx.*` fails to collect with `ModuleNotFoundError`, which looks like a real problem but is a run-command issue, not a code issue.
- **These five files pass identically under both `ARYX_DB_BACKEND=oci` and `=local`** (confirmed by running both) — they mock `oracledb`/the store layer directly rather than depending on the ambient backend setting, so either value works *for these specific files*. That is **not** true project-wide: this session earlier found other test files (`test_oci_backends.py` in particular) that attempt real OCI SDK/network calls under the ambient `oci` default and hang. **Always run under `ARYX_DB_BACKEND=oci`** for this project going forward — it's the real deployment target, and where a test can't handle that cleanly, that's itself a gap in the test (missing a mock), not a reason to test against `local` instead.

This is the exact command every phase's "run the existing test suite" step (§6, items 1 and 3) means in practice, for the `src/aryx/` codebase specifically — `shay_backend/` and `apps/web/` each need their own equivalent invocation confirmed before Phase 5/TypeScript work starts, not assumed to be the same command.

**1. Golden-master test before touching any file that lacks one — per file, during that file's own step, not deferred to the end of a phase.** Before splitting or restructuring a file, check whether its public functions already have test coverage (§2.1's table does this for every Phase 2/4 file already). If they don't, write a short characterization test that pins today's actual behavior (real inputs → real outputs, run against the current code) *before* moving anything, as the very first action taken on that file — not after the split, and not saved up as a batch of "write tests" work once Phase 2 or Phase 5 is otherwise finished. Waiting until a phase finishes defeats the point: the whole reason this rule exists is to catch a bad split *at the moment it happens*, and a test written after the fact against already-changed code isn't an independent baseline. Do not split first and write tests after.

**2. One file per commit, no exceptions.** Every phase in this plan already says this; stating it here as policy: a single-file commit is trivially revertible with `git revert`; a commit that touches five files to hit a line-count target is not. If a phase's own file list looks like it wants to batch several small files together for efficiency, that's a signal to slow down, not a good reason to skip this rule.

**3. Test-then-move gate.** File N+1's split does not start until file N's tests pass — both any pre-existing suite and the new characterization test from step 1. For files that touch a live database, a message queue, or an external API (this plan's `store/` files, most of `shay_backend/app/routes/` and `app/services/`), passing unit tests is necessary but not sufficient — also run a live smoke test against the real backend (the same pattern this session used for every Oracle fix: `docker compose up`, exercise the actual endpoint, check the actual data), not just a mocked one.

**4. Rollback is a single revert, by construction.** Because of rules 1–3, a split that turns out to be wrong in production is always exactly one commit to undo, with the golden-master test immediately confirming the revert actually restored correct behavior — never a multi-file untangle under time pressure.

**5. Staging before production, for anything request-serving.** For files in `api/`, `store/`, `shay_backend/app/routes/`, and `shay_backend/app/services/` — i.e. anything a real user request touches — deploy the split to a non-production environment and exercise the actual feature end-to-end (the real `/ask` conversation, the real workspace-creation flow, the real Shay chat) before merging to the branch that deploys to production. A passing test suite is not a substitute for this step; it's what step 3 already covers.

**6. Definition of done, per file:**
- [ ] File and every function in it are within the manifest's thresholds (150/60), or the file is explicitly deferred with a stated reason (e.g. Phase 4's mega-files, or a test file per Phase 5's "defer" guidance)
- [ ] Every pre-existing test for this file still passes, unchanged
- [ ] A new characterization test exists and passes, if none existed before this change
- [ ] For any file touching a real database or external service: a live smoke test against that real backend passes (not a mock)
- [ ] Reviewed by someone other than whoever wrote the split
- [ ] Committed alone — this file's change and nothing else — so it reverts independently of every other file in this plan

No phase below is complete for a given file until all six boxes are checked for that file.

**6.1 A separate, unrelated gate now exists on this repo — `raven-core/decision-map-gate.py` (task T31, externally installed 2026-09-03) — and it interacts badly with this plan's own work.** It hard-blocks every commit on unresolved `raven_log()`-instrumentation findings, keyed by exact (file, line). Every file split in this plan moves code to new files and new line numbers, so the gate sees the SAME pre-existing, already-accepted code as "new" findings every single time, even though nothing about the code's actual behavior changed — confirmed live during the `oracle_pool.py` split (17 "new" findings that were the identical `_hint_clob`/`_coerce_clob`/etc. logic, just relocated). The fix each time is `python3 raven-core/decision-map-gate.py --write-baseline` (a sanctioned mechanism the gate itself provides, not a hook bypass) followed by staging `.raven/decision-map-baseline.json` alongside that commit's actual files. **Expect this after every file split in Phases 2–5, not just this once** — it is not this plan's own policy and not something this plan's execution can fix (the gate is marked "managed... do not hand-edit"), but it is a real, recurring step every phase's execution needs to budget for.

---

## 7. Phased plan

**Before Phase 1 starts — verify enforcement is actually real, not assumed.** Phase 7 item 1 (below) says to confirm `enforce_at: "commit"` is wired into the pre-commit hook; that check belongs *here*, not at the end. If the hook doesn't actually block on these thresholds today, every phase below is optional cleanup with no mechanism to stay fixed — worth five minutes to check (`git commit` a deliberately-oversized dummy file on a throwaway branch and confirm it's rejected) before investing weeks in Phases 2–6. This is a one-time verification, not its own phase, which is why it isn't numbered — Phase 7 still owns the *ongoing* re-verification (quarterly, post-merge).

**Parallelization:** Phase 3 (`apps/web/`) and Phase 5 (`shay_backend/`) have no import dependency on `src/aryx/` or on each other (confirmed in each phase's own dependency map) — they can run concurrently with Phase 2 and with each other if resourcing allows, rather than strictly sequentially. Phase 4 (the mega-files) is the one phase that should not start until Phase 2 is fully done and its own sign-off (below) is obtained, regardless of what else is running in parallel.

**Phase 4 sign-off is a named-approver gate, not a self-check.** "Needs its own planning session and sign-off" (stated in Phase 4 below) means an explicit approval from the project owner or a tech lead — not a decision this plan or whoever is executing it makes unilaterally by judging the design note "looks fine." Given the blast radius described in Phase 4's own dependency map (every CPQ conversation in production), this is the one gate in this plan that isn't satisfied by the standard §6 checklist alone.

### Phase 1 — Quick, safe wins (low risk — do first)

1. Replace the 1 `print()` call in `pipeline/ingest_validation.py` with `logger.info`/`logger.debug` as appropriate.
2. Add return type hints to the 15 functions in §2.3. All are small, single-purpose functions — mechanical, verifiable by running the existing test suite for each touched file.
3. Re-run the AST scan (§8) after both to confirm 0 remaining in these two categories.

**Estimated effort:** under a day. **Risk:** negligible — no behavior change, purely annotations and one `print`→`logger` swap.

**Dependency map:** touches 16 files total (15 for type hints + 1 for the `print()` swap), all leaf-level fixes with no cross-file coupling. Needs: nothing beyond each touched file's existing tests, if any exist — most of these are small helpers without dedicated unit tests, so the practical verification is "the app still imports and starts" plus a manual exercise of the one changed code path (e.g. re-run the ingest job for `ingest_validation.py`'s `print()` swap). Breaks if it fails: nothing structural — a wrong type hint is a type-checker complaint, not a runtime error; a broken `logger` call would surface immediately on first exercise of that path.

### Phase 2 — Mid-size files (150–1,000 lines, 67 files from §2.1, excluding the two mega-files) — split into 2a/2b by the 400→150 threshold revision

**Scope change from the 400→150 revision (§1.1):** this phase was originally scoped at 20 files (400–1,000 lines). It now covers 67 (20 Tier A + 47 Tier B), split into two sub-tiers so the already-planned Tier A work isn't renegotiated, and Tier B's larger, less-individually-scrutinized file list gets its own pass with the corrected test-coverage methodology (§2.1) applied from the start.

Approach per file, not a blanket rule (applies to both sub-tiers):
1. Read the file's existing internal structure — most of these (e.g. `cpq/data_table_resolver.py`, `cpq/bml.py`, `pipeline/doc_discovery.py`) already group logically-separable concerns (e.g. `data_table_resolver.py`'s four distinct column-shape detectors documented in `docs/diagrams/cpq-engine-technical-flow.html`'s new Layer 2).
2. Propose a concrete split (which functions move to which new module) **before** moving any code — this becomes its own short design note per file, reviewed before execution. Before proposing a split, check whether any function the file exports is *shared infrastructure* imported by a file outside this phase's own list (the `data_table_cache.py` extraction found this the hard way: `_invalidate_on_marker_change`/`_cache_write_if_marker_unchanged` were imported directly by `cpq/engine.py` and whitebox-patched by a dedicated test file — moving them required updating both, not just the file being split). Grep for `from aryx.<module> import` project-wide before finalizing a split's module boundaries, not after.
3. Split one file at a time, run its existing tests immediately after, commit before starting the next file. Never batch multiple file-splits into one commit.
4. A split rarely clears 150 lines in one extraction the way it often cleared 400 — expect most Tier A/B files to need 2–4 extracted modules, not one, to land every resulting file under 150. Verify the *actual* post-split line count of every resulting file, not just that the original file shrank.

**2a — Tier A (the original 20 files, 400–1,000 lines):** priority order start with files that have the clearest existing internal seams.

**`data_table_resolver.py` split — DONE.** 1,036 lines -> 10 files:

| File | Lines | Status |
|---|---:|---|
| `data_table_resolver.py` | 71 | ✅ pure re-export hub, `__all__`-declared |
| `data_table_shapes.py` | 127 | ✅ clean |
| `data_table_whitelist.py` | 76 | ✅ clean |
| `data_table_variant.py` | 67 | ✅ clean |
| `data_table_stale_models.py` | 33 | ✅ clean |
| `data_table_consistency.py` | 149 | ✅ clean (just under) |
| `data_table_product.py` | 151 | ⚠️ stated exception, 1 line over — 3 tightly-related functions, docstring-driven, not worth fragmenting further for one line |
| `data_table_cache.py` | 162 | ⚠️ stated exception (§2.1) |
| `data_table_loader.py` | 172 | ⚠️ stated exception (§2.1) |
| `data_table_governance.py` | 166 | ⚠️ stated exception (§2.1) |

6 of 10 files clean under 150; 4 are stated, documented exceptions (load-bearing incident-documentation docstrings, same reasoning as `data_table_cache.py`'s original exception). The 1,036-line file that started this phase no longer exists in that form.

**Key lesson, confirmed the hard way mid-split:** the `engine.py`-facing re-export chain (its `dt_*`-aliased top-level imports, and the ~10 test files that patch those aliases on `engine`'s own namespace) needed zero changes across every extraction — patching a name in the *caller's* namespace always works regardless of where the real function is defined. But **whitebox patches targeting `data_table_resolver.<name>` directly break the moment the calling code itself moves out of `data_table_resolver.py`** — `tests/test_cpq_stale_base_model_cascade_2026_08_20.py` patched `aryx.cpq.data_table_resolver._load_all_tables` and silently stopped intercepting anything once the functions that call `_load_all_tables` (`resolve_product_cpq_models_from_rows`, `resolve_region_allow_value`) moved to `data_table_product.py` — the test still passed collection and only failed on a business-logic assertion, not an import error, so this needs an actual test run to catch, not just a compile check. Retargeted to `aryx.cpq.data_table_product._load_all_tables`; a project-wide `grep -rl "_load_all_tables" tests/` (4 files total) confirmed no other test has the same landmine. **Any future split of a function that internally calls another moved function must re-check every direct-module-path patch, not just re-exports.**

**`oracle_pool.py` split — in progress, higher caution than `data_table_resolver.py` given this file's PR #310–#314 bug history.** Proposed as a 4-module split, explicitly confirmed with the project owner before starting (per the plan's own step-2 requirement). Status:

| File | Lines | Status |
|---|---:|---|
| `oracle_sql_translate.py` | 126 | ✅ done, clean — `_translate_sql` and its SQL-rewriting regexes |
| `oracle_pool.py` | 657 (was 763) | 🔶 in progress — still needs `oracle_param_coerce.py` and `oracle_clob.py` extracted, then likely one more split of `OracleCursorWrapper`/`OracleConnectionWrapper`/`OraclePool` themselves |

Verified after the `oracle_sql_translate.py` extraction: 154 passed (`test_oracle_pool.py`, `test_oracle_workspace.py`, `test_shay_bridge_store.py`, `test_shay_bridge_api.py`), clean container imports, and — per §6 item 3's live-smoke-test requirement for `store/` files — a full container restart that ran every startup migration (real `CREATE TABLE`/`ALTER TABLE`/seed `INSERT` DDL/DML) through the translated SQL path with no new errors, plus `/health` and `/ask` returning correct real-Oracle-backed responses.

Next in this sub-tier after `oracle_pool.py` is fully split: `state.py`'s distinct state-transition groups, deferring `config.py`/`source_catalog.py` until later.

**2b — Tier B (47 additional files, 150–400 lines, new to this revision):** priority order:
- **Untested files first, smallest first** (of the 23 Tier B files with no matching test — §2.1): starting small keeps each golden-master-test-then-split cycle short while the corrected methodology is still being applied consistently. `models.py` (153 lines) and `action_store.py` (158 lines) are natural starting points.
- **Files already covered by an existing test** (24 of 47): still require the §2.1.1-style coverage-breadth check before splitting (a matching filename is not proof of full coverage), but carry less golden-master-authoring overhead.
- **Defer the two ambiguous-coverage flags** (`ui/api.py`'s uncertain match, `reasoning/engine.py`'s basename collision with `cpq/engine.py`) until their actual coverage is manually confirmed — do not split either on the assumption the automated match is real.
- `cpq/data_table_cache.py` (162 lines, 12 over the limit, itself a product of this session's Phase 2 work) is a **stated exception, not a further split target**, per §6 item 6's "explicitly deferred with a stated reason": its 5 functions share 3 module-level globals and form one cohesive concurrency-safety unit (the cross-process cache-invalidation marker), and most of its length is incident-documenting docstrings (the PR #287 concurrency bug, the `test_pool.py` mock-leak regression that broke ~150 unrelated tests) that are load-bearing, not boilerplate — trimming them to hit 150 would recreate the exact undocumented-fragility risk §5 warns about for the mega-files, at smaller scale, and splitting 5 tightly-coupled functions into two files to save 12 lines has no real structural seam behind it. Revisit only if this file's scope genuinely grows (e.g. a 6th cache adopts this pattern), not to chase the line count on its own.

Function-length violations (§2.2) that live inside files *already* covered by this phase's file-splits get addressed as part of that same split, not as a separate pass — moving a 200-line function into its own module is often also the fix for its length.

**Estimated effort:** originally "several days to a couple of weeks" for 20 files; at 67 files, realistically **4–8 weeks**, file-by-file, test-gated — a genuine scope increase from the threshold revision, not an estimate this plan is trying to minimize. **Risk:** low-to-moderate per file, mitigated by one-file-at-a-time discipline and running tests before moving to the next; Tier B's untested files carry the same risk profile as Tier A's untested files did, just more of them.

**Dependency map:** these 67 files sit in `cpq/`, `pipeline/`, `store/`, `api/`, `graph/`, `ontology/`, `resolution/`, `worker/`, `ui/`, `mcp/`, `broker/`, `demo/`, `connectors/`, and `reasoning/` — i.e. nearly every subpackage in `src/aryx/`, not one corner. Concretely:
- `cpq/data_table_resolver.py`, `cpq/bml.py`, `cpq/rdb.py`, `cpq/state.py`, `cpq/intent_schema.py`, `cpq/bom_gate.py`, `cpq/pending_scope.py`, `cpq/session_guard.py`, `cpq/rule_export.py`, `cpq/rule_trace.py`, `cpq/intent_queue.py` are all imported by `cpq/engine.py` (Phase 4's mega-file) — a split here changes `engine.py`'s import surface even though `engine.py` itself isn't being touched yet. Verify `engine.py`'s own tests (if any) still pass after each of these splits, and grep `engine.py` for direct imports of the specific names being moved before finalizing a module boundary (see step 2 above).
- `store/oracle_pool.py`, `store/shay_bridge_store.py`, `store/ask_thread_store.py`, `store/entity_store.py`, `store/source_purge_store.py`, `store/mcp_token_store.py`, `store/discovery_store.py`, `store/oracle_workspace.py`, `store/datasource_store.py`, `store/action_store.py` are the actual database access layer this session's Oracle-parity fixes (PRs #310–#314) live in — a bad split here has the same blast radius as those bugs did (silent data corruption or hard crashes against real Oracle data, not just a Python import error). Re-run this session's own regression tests (the `ensure_workspace_mapping`/`ensure_chat_mapping` scenarios) after touching any of these.
- `pipeline/doc_discovery.py`, `pipeline/enrich.py`, `pipeline/ingest_validation.py`, `pipeline/dynamic_fk.py`, `pipeline/orchestrate.py`, `pipeline/dimension_link.py` sit in the ingestion pipeline — a split that changes behavior here surfaces as a silently wrong ingest, not a crash, so needs an actual test ingest run, not just an import check.
- `api/data_api.py`, `api/file_ingest_api.py`, `api/main.py`, `api/ask_thread_api.py`, `api/admin_api.py`, `api/workspace_api.py`, `api/doc_discover_api.py`, `api/ontology_api.py`, `api/ontology_browse.py`, `api/rest_ingest_api.py`, `api/shay_bridge_api.py`, `source_catalog.py`, `config.py` are lower-risk in isolation but `config.py` specifically is imported everywhere and `api/main.py` is the app's own entry point — treat any change to either as needing a full smoke-test of the app starting up, not just its own file's tests.
- `graph/falkor_store.py`, `graph/reader.py`, `graph/oracle_graph_reader.py`, `graph/oracle_graph_store.py`, `graph/retrieve.py` and `mcp/server.py` sit under the graph/MCP surface most CPQ conversations don't touch directly but which the ingestion and resolution pipeline depends on — a bad split here is more likely to surface as a resolution/graph-query failure than a CPQ-conversation failure, so verify with those tests specifically, not just `api/ask_api.py`'s.

**What breaks if a split goes wrong:** for the `store/` files, real data corruption or crashes against live Oracle (as this session repeatedly found); for `cpq/*.py` and `pipeline/*.py`, silently wrong CPQ answers or mis-resolved ingest data rather than a crash — the harder failure mode to catch, which is exactly why one-file-at-a-time + test-before-next-file is non-negotiable here, not just a nicety.

### Phase 3 — `apps/web/` (TypeScript) file-length splits

Previously **unassigned to any phase** — §9's summary table originally called this out as "not yet phased," found during this plan's own `/raven-plan` readiness review and closed here rather than left open.

43 files over 150 lines (§3.1 — 13 Tier A + 30 Tier B, up from 13 under the original 400-line threshold), no function-length data available (§3.3's tooling gap — this phase splits by file length only; a function-length pass here needs the `eslint`/TS-compiler-API tooling described in §3.3 first, and is deferred to Phase 6 alongside the naming audit, not done as a guess in this phase).

1. **Lowest risk — page/component files** (Tier A: `app/settings/page.tsx`, `app/page.tsx`, `components/shay/WorkspaceSettingsPage.tsx`, `components/shay/AdminUsersPageView.tsx`, `components/shay/AdminUsersPageParts.tsx`, `components/brand/Header.tsx`, `components/data/DataExplorer.tsx`, `components/shay/WorkspaceIndexPage.tsx`, `components/graph/EntityGraph.tsx`; Tier B adds `components/data/XmlSourceDetail.tsx`, `components/shay/AdminUsersPage.tsx`, `components/shay/WorkspaceOverviewPage.tsx`, `components/model/*.tsx` (5 files), and most of the `app/*/page.tsx` route files): React components split naturally along JSX sub-sections that are already visually distinct in the file (a settings page's separate tabs, a workspace page's separate cards) — similar risk profile to Phase 5's route-file splits, since each rendered section is typically independent of its siblings' state.
2. **Moderate risk — shared library files** (`lib/api.ts`, `lib/shay-api.ts`, `lib/types.ts`, `lib/shay-session.ts`, plus Tier B's `lib/shay-types.ts`): these are imported across most of `apps/web/`, the TypeScript equivalent of `src/aryx/config.py`'s "imported everywhere" risk profile — split by grouping exported functions along the same lines their consuming pages already use them (e.g. `api.ts`'s CPQ-related calls vs. its data-explorer-related calls), and smoke-test the whole app's build (`npm run build`) after each split, not just the one file's own usage.
3. No new-test-case requirement is stated here the way §6 item 1 states it for Python, because this plan has no evidence either way on existing TypeScript test coverage — that itself needs checking (`apps/web`'s own test setup, if any) as the first step of this phase, mirroring §2.1/§5's dedicated-test-file check before assuming any of these 43 files ships with a safety net or not.

**Dependency map:** `apps/web/` is a separate Next.js application from both Python codebases — no shared imports, so this phase's blast radius is contained to the browser-facing UI. **What breaks if a split goes wrong:** a broken page or component in the live UI (visible immediately in manual testing, unlike the silent-corruption risk in Phase 2's `store/` files) — lower severity than Phase 2, but user-visible immediately, which argues for the same staging-before-production step from §6 item 5 rather than skipping it because the failure mode is "only UI."

**Estimated effort:** originally "a few days to a week" for 13 files; at 43 files, realistically **2–3 weeks** — page/component splits are still largely mechanical, so this scales more gently than Phase 2/5's logic-heavy files, but it's still more than 3× the file count.

### Phase 4 — The two mega-files (`cpq/engine.py`, `api/ask_api.py`) — separate initiative, not part of this cleanup pass

This phase is **design work, not refactor-and-go**:
1. Map current responsibilities in each file into proposed target modules (e.g. `ask_api.py`'s `_run_cpq_turn_inner()` at 3,633 lines almost certainly contains several genuinely separable turn-handling stages — but which ones, and in what order they depend on shared local state, needs to be documented before any code moves).
2. Identify or write regression tests that pin today's exact behavior for each responsibility area **before** touching the code — the goal is a split that a test suite can prove is behavior-preserving, not one that "looks equivalent."
3. Execute the split in small, independently-reviewable steps, each gated on its own test run — mirroring the incremental, test-verified pattern already used successfully this session on much smaller Oracle-parity fixes.
4. Function-level compliance in these two files follows naturally once the file-level split happens — do not attempt to shorten `auto_fill()` or `_run_cpq_turn_inner()` in place before the module boundaries exist.

**This phase needs its own planning session and sign-off before starting** — it is explicitly out of scope for "general cleanup" given the correctness risk described in §5.

**Dependency map:** `cpq/engine.py` and `api/ask_api.py` are the two most heavily-depended-on files in the whole application — `engine.py` is imported by every CPQ-touching module in `cpq/`, and `ask_api.py` is the entry point for every `/ask`, `/ask/threads/*` request. **What breaks if this goes wrong:** every CPQ conversation in production, immediately and broadly — not a narrow blast radius like a single store file. This is the concrete reason Phase 4 needs its own sign-off gate rather than proceeding once Phase 2 is done.

### Phase 5 — `shay_backend/` remediation

Confirmed in scope (§4.6). Structurally **lower risk per file than Phase 2**, despite the larger backlog: `app/routes/datasources.py` (the worst offender at 5,518 lines) is 72 separate `@router`-decorated endpoint handlers, not one entangled state machine — FastAPI route handlers in this codebase are largely independent of each other within a file, sharing imports but not the kind of cross-function mutable state that made `src/aryx/`'s mega-files dangerous to split. That changes the sequencing, not the discipline: still one file at a time, still test-gated, just with more files to get through.

**Scope change from the 400→150 revision (§1.1):** 104 files over the limit now (§4.1 — 47 Tier A + 57 Tier B), up from 47 — 50.7% of the codebase, not 22.9%. Split into 2a/2b sub-tiers below, same reasoning as Phase 2.

**Same dedicated-test-file check as §2.1, run against the 36 non-test route/service files in Tier A's list: 23 have no dedicated `tests/test_<name>*.py` file** (verified per-file, not estimated) — a comparable gap ratio to `src/aryx/`'s original 12-of-22. Notably, `app/routes/datasources.py` — the single largest file in this whole plan at 5,518 lines — is *not* one of them: `test_datasources_aryx_integration.py` exists, though its name suggests narrow coverage of the Aryx-bridge endpoints specifically, not all 72 handlers in the file — worth confirming its actual scope before assuming the file is safe to split without an additional characterization test for the untested handlers. Files confirmed genuinely untested include `app/routes/payment_gateway.py` (2,505 lines, handles billing — arguably the highest-stakes file in this phase to be untested), `app/routes/messages.py` (2,513 lines), `app/routes/channels.py` (2,630 lines), and `app/services/email_service.py` (1,821 lines). The golden-master rule (§6, item 1) applies here exactly as it does in Phase 2, at the same "before you touch it, not after" timing. **Tier B's 57 additional files have not yet had this same per-file test-coverage check run** — that check is this sub-tier's own required first step (§6 item 1), the same way it was Tier A's, not assumed complete by extension from Tier A's numbers.

**5a — Tier A (the original 47 files, over 400 lines):**
1. **Type hints first, separately from file-length** (unlike Phase 2, where a length-driven split incidentally fixes function-length): 1,155 missing return type hints is too large to fold into file splits one-for-one. Run this as its own mechanical pass, file group by file group (e.g. all of `app/routes/*.py` together, then `app/services/*.py`), verified by running `shay_backend`'s existing test suite (`tests/test_gg_datasources.py` etc. — note two of the over-400-line files are themselves test files, §4.1) after each group, not after every single file.
2. **File-length splits**, prioritized by risk, lowest first:
   - **Lowest risk — route files** (`app/routes/*.py`, the bulk of Tier A's list): split by sub-resource along existing `@router` groupings (e.g. `datasources.py`'s CRUD endpoints vs. its bulk-upload endpoints vs. its metadata-generation endpoints are already namespaced by function name — `create_datasource` vs. `create_datasources_bulk` vs. `generate_datasource_metadata`). Each split is close to a mechanical file move plus import fixes.
   - **Moderate risk — service files** (`app/services/*.py`, e.g. `email_service.py` at 1,821 lines, `zoho_service.py` at 1,060): these carry more actual business logic per function (§4.2's `build_vault_credentials()`, `fetch_company_subscription_details()`) — treat like Phase 2's `store/` files, not Phase 2's easy wins.
   - **Defer — test files over 400 lines** (`tests/test_gg_datasources.py` at 2,279 lines, etc.): splitting a test file is lower value than splitting the code it tests; only split if the test file itself is hard to navigate, not to chase the line-count number.
3. **`print()` → logging**: 19 call sites, same mechanical Phase-1-style fix, just batched separately since it's a different codebase with its own logging setup to verify against.

**5b — Tier B (57 additional files, 150–400 lines, new to this revision):**
1. Run the dedicated-test-file check (§2.1's corrected methodology) against all 57 before splitting any of them — do not assume Tier A's 23-of-36 untested ratio simply extrapolates.
2. `app/routes/aryx.py` (289 lines, the Shay↔Aryx bridge endpoint file) splits under Phase 2's `store/`-file caution level, not this phase's default route-file risk level — it's the one Tier B file with a direct dependency on this session's own Oracle-parity fixes.
3. Otherwise, same route-files-before-services-before-tests priority order as Tier A, applied within Tier B's own list.

**Dependency map:** `shay_backend/` is a separate FastAPI service from `src/aryx/`'s `api` — it does not import from `src/aryx/` at all (confirmed: this is exactly the boundary the Shay bridge in `src/aryx/api/shay_bridge_api.py` and `shay_backend/app/routes/aryx.py` exists to cross over HTTP, not a Python import). That means Phase 5's blast radius is contained to `shay_backend/` itself and does not risk `src/aryx/`'s Oracle-parity fixes the way Phase 2's `store/` files do — except `app/routes/aryx.py` specifically (see 5b item 2). **What breaks if a split goes wrong:** a broken Shay endpoint (workspace management, datasources, billing via `payment_gateway.py`, chat via `messages.py`/`channels.py`) — real user-facing breakage in the Shay product, but not the kind of silent Oracle data corruption Phase 2's `store/` files risk. Verify with `shay_backend`'s own test suite after each file, same one-at-a-time discipline as Phase 2.

**Estimated effort:** originally "2–4 weeks" for 47 files; at 104 files, realistically **6–10 weeks** — the largest phase in this plan by file count, plus the separate 1,155-item type-hint pass, sequenced route-files-first (safest, most files) before services (fewer files, more logic each) within each sub-tier.

### Phase 6 — Naming convention audit (not yet scanned)

Run a dedicated naming-convention scan (§8) across `src/aryx/*.py` for `snake_case` functions/variables and `apps/web/**/*.tsx` for `camelCase`/`PascalCase`, before claiming this rule is compliant (and `shay_backend/*.py` too, if Phase 5 determines it's in scope). Address findings the same file-by-file, test-gated way as Phase 2.

**Dependency map:** a naming-convention scan itself is read-only and risk-free; the risk is entirely in whatever renames it recommends, which then inherit the same dependency/blast-radius profile as whichever file they land in (Phase 2's map for `src/aryx/`, or Phase 5's for `shay_backend/`) — a rename is a smaller, more mechanical change than a split, but a rename that misses a caller (e.g. a string-based dynamic lookup, or a cross-service reference like Shay calling into `api`'s route names) fails silently rather than at import time.

### Phase 7 — Keep it compliant going forward

Once Phases 1–2 close the backlog for everything except the two mega-files:
1. Confirm `enforce_at: "commit"` is actually wired into the pre-commit hook and blocking on these exact thresholds (verify, don't assume — this plan didn't check hook wiring itself, only the manifest's stated config).
2. Any new file in `src/aryx/` starts under 150 lines and stays there by construction, since the hook blocks non-compliant commits going forward — the backlog in this plan should not recur once Phases 1–2 are done.
3. Re-run the full scan (§8) quarterly (or after any large merge, the way this plan followed the `dev-rv-msi` → `dev_oci` merge) to catch drift early, since a large feature-branch merge is exactly the kind of event that reintroduces a backlog.

---

## 8. How to reproduce or re-run this scan

The scan script used for this plan is AST-based, read-only, and lives at:
`/tmp/claude-1000/-home-halcyoona-giggso-github-repo-aryx-oracle-aryx-aryx/c7a2d70a-f28f-479d-b46c-a02e98302cd5/scratchpad/style_scan.py`

That path is session-scoped and will not persist — if this plan needs to be re-verified later, recreate a small AST script that: walks `src/aryx/**/*.py`, counts lines per file against `MAX_FILE_LINES = 150` (revised 2026-09-03 from 400 — check `.raven/manifest.json` → `style.max_file_lines` for the current live value before hardcoding either number), walks `ast.FunctionDef`/`ast.AsyncFunctionDef` nodes for `end_lineno - lineno + 1 > MAX_FUNC_LINES = 60`, checks `node.returns is None` for missing type hints, and greps for `print(` and `logging\.|logger\.` without a matching `import logging`. All four checks together take under a second against this repo.

Naming-convention and docstring checks (§2.6, and the `require_docstrings: false` rule which needs no action) are not yet implemented in that script and should be added before Phase 6 starts.

---

## 9. Summary — nothing left out

**Threshold revision note:** every "files over ___ lines" row below reflects the revised 150-line threshold (§1.1). Where the original 400-line count is still a useful reference point (e.g. for risk-tiering within a phase), it's called out as "Tier A" in the row.

### `src/aryx/`

| Category | Count | Phase |
|---|---:|---|
| Files over 150 lines (excl. 2 mega-files) — Tier A (20, orig. 400-line count) + Tier B (47, new) | 67 | Phase 2 (2a Tier A / 2b Tier B) |
| Mega-files over 150 lines | 2 | Phase 4 (separate initiative) |
| Functions over 60 lines (excl. mega-file functions) | ~40 (subset of 199, addressed via Phase 2 splits) | Phase 2 |
| Functions over 60 lines inside the 2 mega-files | ~159 | Phase 4 |
| Functions missing return type hints | 15 | Phase 1 (done — verified 0 remaining) |
| `print()` calls | 1 (confirmed legitimate exception, not fixed) | Phase 1 (done) |
| `logging` without import | 0 | none needed |

### `apps/web/` (TypeScript)

| Category | Count | Phase |
|---|---:|---|
| Files over 150 lines — Tier A (13, orig. 400-line count) + Tier B (30, new) | 43 | Phase 3 |
| `console.log` calls | 0 | none needed |
| Function-length / naming | not scanned (no AST tool used) | Phase 6, needs a separate tool for function-length first |

### `shay_backend/`

| Category | Count | Phase |
|---|---:|---|
| Files over 150 lines — Tier A (47, orig. 400-line count) + Tier B (57, new) | 104 | Phase 5 (5a Tier A / 5b Tier B) |
| Functions over 60 lines | 244 | Phase 5 |
| Functions missing return type hints | 1,155 | Phase 5 |
| `print()` calls | 19 | Phase 5 |
| `logging` without import | 0 (1 scan false-positive corrected, §4.5) | none needed |

### Cross-cutting

| Category | Status | Phase |
|---|---|---|
| `max_file_lines` threshold revision (400 → 150) | done — `.raven/manifest.json` v1.0.7, this document fully re-scanned and rewritten | — |
| Naming convention compliance (all 3 codebases) | not yet scanned | Phase 6 |
| `shay_backend/` ownership/scope | resolved 2026-09-03 — governed by this manifest | Phase 5 |
| Ongoing enforcement verification | not yet confirmed wired | Phase 7 |
| `data_table_cache.py` extraction (Phase 2, first split of `data_table_resolver.py`) | done — verified against full CPQ/engine test suite (1,578 tests), zero new failures, all 17 pre-existing | Phase 2 (2a, in progress) |
