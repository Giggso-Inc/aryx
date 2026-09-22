# dev-rv-msi → dev_oci Integration Plan — 2026-09-21

## Status as of 2026-09-21 session close

**All 6 of 6 planned commits landed** on
`integration/dev-rv-msi-into-dev_oci-2026-09-21`:

| # | Commit | Landed as | Notes |
|---|---|---|---|
| 1 | `e7691115` (#326) | `140411c0` | Low risk, as planned |
| 2 | `a8414af9` (#329) | `6cd26573` | Reimplemented, not ported — see §2 below |
| 3 | `d0f5aa3a` (#334) | `766b1ff5` | High risk confirmed, as planned |
| 4 | `e691bea0` (#331) | `e564b6bb` | Biggest so far — 23 files, new Oracle gap found |
| 5 | `9fad76d4` (#336) | `4a873b40` | Low risk, as planned |
| 6 | `8e60e0ca` (#339) | `67c3d72f` | Biggest single-file delegation depth — see its section |

**Follow-up work: landed.** `OracleGraphReader.find_entities(attrs=...)`
(flagged under "Second non-negotiable constraint" below, deferred out of
commit #4) shipped in response to a Raven Review finding on PR #344 — see
Part B below for the fix and an important correction to this section's
original SQL design (the originally-planned bind-the-JSON-path approach
doesn't work against real Oracle; caught before merge, but still not
verified against a live ADB instance). Nothing else remains open from this
plan.

## Execution plan for the two remaining items (2026-09-21 follow-up)

Both items below were re-investigated after the first attempt at #339 was
reverted for being bigger than expected — this section replaces guesswork
with exact, verified file:line targets so the follow-up session can execute
directly instead of re-discovering the same ground.

### Part A — #339: exact call-site map

The commit touches 3 files on `dev-rv-msi`: `api/ask_api.py` (13260 lines
there), `cpq/engine.py`, `cpq/state.py`. On this branch, `ask_api.py` is an
84-line shim — its logic has been extracted not once but **twice**: first
into per-handler files (the Phase 9/10 split), then a second time into
`ask_attr_recompute/`, `ask_dispatch/`, `ask_gateway/`, and
`ask_turn_steps/` sibling files. Only 3 of the 13 touched functions still
contain their patch's target text directly in the file where the function
NAME lives — the other 10 delegate to a further sibling file.

**Verbatim matches — no delegation, patch lands directly (3 functions):**

| Function | File | What to add |
|---|---|---|
| `_build_show_summary_response` | `api/ask_response_building/ask_build_show_summary_response.py:75-76` | `workspace_id=req.workspace_id, catalog_prefix=catalog_prefix` to the `apply_hiding_rules(...)[2]` call (`catalog_prefix` already computed at line 56) |
| `_build_json_preview_response` | `api/ask_json_preview_and_decline.py:39-40` | same `apply_hiding_rules` kwargs (`catalog_prefix` already computed at line 38) |
| `_handle_approval` | `api/ask_handle/ask_handle_approval.py:51-52` | same `apply_hiding_rules` kwargs |

**Delegated — patch lands in a sibling file, simple kwarg insertion (6 functions):**

| Function (name lives here) | Actual patch file:line | What to add |
|---|---|---|
| `_handle_cascade` | `api/ask_attr_recompute/ask_cascade_recompute.py:58-75` | `product_anchor_hint=session.product_anchor_question,` in both call blocks (after line 61's close, and between lines 73/74) |
| `_handle_multi_select_removal` | `api/ask_attr_recompute/ask_multi_select_removal_recompute.py:68-85` | same, same two-block shape |
| `_handle_attr_activation` | `api/ask_attr_recompute/ask_attr_activation_recompute.py:72-89` | same |
| `_handle_attr_clear` | `api/ask_attr_recompute/ask_attr_clear_recompute.py:65-82` | same |
| `_handle_bulk_quantity_change` | `api/ask_attr_recompute/ask_bulk_quantity_recompute.py:59-76` | same |
| `_handle_cascade_multi` | `api/ask_attr_recompute/ask_cascade_multi_recompute.py:54-71` | same |
| `_build_country_change_response` | `api/ask_country_change_revalidate.py:60-69` (via `_rederive_and_revalidate_for_country_change`) | `product_anchor_hint=session.product_anchor_question,` after line 67, before line 68's `)`; `session` already in scope |

**Delegated AND needs a new parameter threaded through (3 functions — the
real risk in this commit):**

| Function (name lives here) | Actual patch file:line | Problem |
|---|---|---|
| `_dispatch_intent_result` (branch 1) | `api/ask_dispatch/ask_dispatch_ambiguous_and_scope.py:34-36`, inside `_dispatch_ambiguous(...)` | That function has **no `catalog_prefix` param** — must add one and thread it from `ask_dispatch_intent_result.py`'s own call to `_dispatch_ambiguous(...)` (which itself needs `attrs[0].catalog_prefix if attrs else ""` computed and passed, matching the original diff's new line `catalog_prefix = attrs[0].catalog_prefix if attrs else ""`) |
| `_dispatch_intent_result` (branch 2) | `api/ask_dispatch/ask_dispatch_attr_activation.py:49-53`, inside `_dispatch_attr_activation(...)` | Same problem — no `catalog_prefix` param, same fix shape |
| `_llm_first_gateway_turn` (both original hunks) | `api/ask_gateway/ask_gateway_resolve_or_reask.py:55-57`, inside `_resolve_or_reask_ambiguous(...)` | Same problem. Bonus finding: this branch's own earlier refactor already **deduplicated** the two near-identical inline blocks dev-rv-msi still has separately into this one shared helper — so this needs only ONE edit, not two, once `catalog_prefix` is threaded in |

**`_run_cpq_turn_inner`'s 3 fragments** (this function itself is a 1-line
dispatcher to `ask_turn_dispatch.py`, itself pure dispatch — the real body
is one level further, in `ask_turn_steps/`):

| Fragment | File:line | What to add |
|---|---|---|
| Top-of-turn `_hidden_for_payload` | `api/ask_turn_steps/ask_step2_rule_consistency.py:32-33` | `workspace_id=req.workspace_id, catalog_prefix=catalog_prefix` — both already in scope |
| `evaluate_rules_loop`/`auto_fill` pair | `api/ask_turn_steps/ask_step10_recompute_pending.py:35-44` and `:47-58` | `product_anchor_hint=session.product_anchor_question,` in both calls |
| Nested `_hidden_now` in JSON-preview branch | `api/ask_turn_steps/ask_step11_on_request_response.py:38-39` | `workspace_id=req.workspace_id, catalog_prefix=catalog_prefix` — both in scope |

**`engine.py` (same file on both branches, but internally reorganized —
9 conflict blocks, not because of a file split but because of this
branch's own separate "shrink engine.py further" extraction history):**

| Piece | Location | Note |
|---|---|---|
| New `_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES` frozenset | **New** — put it in `cpq/hiding_rules/type11.py`, not next to `_CONFIRMED_DEAD_ATTRS` | The dev-rv-msi diff places it next to `_CONFIRMED_DEAD_ATTRS` in the monolith purely by file-proximity coincidence; on this branch `_CONFIRMED_DEAD_ATTRS` moved to `data_table_bridge/attr_governance.py` (unrelated context) while the actual *consumer* of the new constant — the script-missing branch — moved to `cpq/hiding_rules/type11.py`. Define it where it's used. |
| `dt_whitelist_substitute=True` carve-out in the script-missing branch | `cpq/hiding_rules/type11.py:69` (right after `script_missing += 1`, before the `logger.warning` at line 72) | Verbatim match confirmed |
| New `dt_whitelist_substitute: bool = False` field on `HidingRule` | `cpq/state/state_rules.py:75` (after `condition_operator: str = "4"`) | Verbatim match confirmed. `cpq/state/__init__.py`'s cherry-pick conflict was **pure merge noise** — it only re-exports the `HidingRule` class by reference, needs zero changes for a new dataclass field. |
| `apply_hiding_rules` signature (+3 kwargs) and body (`dt_whitelist_substitute` branch) | `cpq/engine.py:1149` (method still lives here, unchanged path) | Apply the diff hunk directly — this method itself was NOT extracted |
| `auto_fill`'s `product_anchor_hint` param + Hardware-Version decision-attr check | `cpq/engine.py:1568` | Same — still a `CpqEngine` method here |
| New `_hardware_version_confirmed_not_applicable` staticmethod | `cpq/engine.py` (new method, place near `auto_fill`/`_order_pending_hardware_before_product`) | New code, no placement conflict |
| `_order_pending_hardware_before_product` signature + body changes | `cpq/engine.py:1633` | Still a `CpqEngine` method here |
| 2 more `apply_hiding_rules` call-site kwarg additions (`calibrate_config` area, `_ADD_VERB_RE` handler) | `cpq/engine.py`, same file, apply directly | Both still local to `engine.py` per the original diff |

**New test files** (dev-rv-msi ships 3, no path issues expected since they
only import from `cpq.engine`/`cpq.state`, both unchanged top-level paths):
`test_cpq_apx900_hybrid_combiner_missing_script_2026_09_21.py`,
`test_cpq_hardware_version_apx3000_scoping_2026_09_21.py`,
`test_cpq_resolve_product_cpq_models_from_hint_2026_09_21.py` — verify their
imports resolve as-is before assuming so, same discipline as every prior
commit in this series.

**Suggested execution order:** state_rules.py field → engine.py (self-
contained, testable in isolation via the 3 new test files) → type11.py →
the 3 verbatim ask_api.py files → the 6 simple-delegation files → the 3
parameter-threading files last (highest risk of a subtle scoping mistake).

### Part B — OracleGraphReader.find_entities(attrs=...)

**Status: LANDED** (fix for a Raven Review finding on PR #344, aryx-
enterprise — the review correctly identified this gap as a live-breaking
bug, not just a theoretical limitation: every graph-side region/feature
search crashed on `dev_oci`'s own Oracle backend, masked as a silent empty
result via chat and a hard 500 via the direct API, and none of `e564b6bb`'s
own 8 new test files covered `OracleGraphReader` at all).

**Target:** `src/aryx/graph/oracle_graph_reader_basic.py:76-110`, added a
keyword-only `attrs: dict[str, str] | None = None`.

**Design actually shipped — corrected from this section's original plan.**
The design below (kept struck through for the record) proposed binding the
JSON key itself via `'$.' || :key_N`. **This does not work**: Oracle raises
`ORA-40454: path expression not a literal` — `JSON_VALUE`'s path argument
must be a compile-time literal, not a bind variable or a runtime-built
expression (Oracle's `PASSING` clause lets you bind *values* referenced
inside an otherwise-literal path, e.g. a filter threshold, but not the
field/key name itself). Caught by web research before implementing, not
by a live Oracle instance (none available in this environment) — exactly
the kind of untested-SQL mistake this whole finding was about, so treat as
still needing live verification against a real ADB before fully trusting.

The actual fix keeps the same regex-validated-key approach (`re.fullmatch
(r"[A-Za-z_][A-Za-z0-9_]*", key)`, `ValueError` on failure) but embeds the
validated key directly into the literal SQL path text, binding only the
value:
```
LOWER(JSON_VALUE(attributes, '$.{key}')) LIKE '%' || LOWER(:attr_val_N) || '%'
```
This is safe because the key has already been validated to contain only
`[A-Za-z_][A-Za-z0-9_]*` — no way to break out of the string literal —
the same reasoning Cypher's `e.{key}` property-name interpolation already
uses elsewhere in this codebase for an identical "can't bind a name"
constraint.

~~append a clause using Oracle's native JSON path syntax against the
existing `attributes` column:~~
~~`LOWER(JSON_VALUE(attributes, '$.' || :key_N)) LIKE '%' || LOWER(:val_N) || '%'`~~

Uses the same named-dict-bind style (`:ws`, `:typ`, `:name`) this method
already used — did not switch to the positional `:1`/`:2` style some
sibling methods in the same file use.

**New import added:** `re`, plus a module-level `_ATTR_KEY_RE` compiled
pattern (not currently imported anywhere else in `oracle_graph_reader*.py`
— confirmed via grep; only the Falkor-side files import it).

**Test coverage:** new file `tests/test_oracle_graph_reader_find_entities_
attrs.py`, mirroring `tests/test_graph_find_entities_attrs_2026_09_15.py`'s
4 cases (adds-JSON_VALUE-clause-and-binds-the-value, multiple-attrs-ANDed,
invalid-key-rejected, no-attrs-backward-compat) but asserting Oracle SQL/
bind shape instead of Cypher — plus an explicit assertion that the key
itself is never bound as a parameter (`attr_key_0` not in params), since
that would silently reintroduce the ORA-40454 mistake.

**Verified duck-typing end-to-end** (not just unit tests against a fake
reader): constructed a real `OracleGraphReader` with a mocked connection
pool and called `search_by_feature()` (`graph/feature_search.py`) against
it directly — confirms the exact `TypeError` scenario from the Raven
Review no longer reproduces. **Still not verified against a live Oracle
instance** (none available here) — the JSON_VALUE syntax itself should be
smoke-tested against the real OCI stack before fully trusting it, same
caution this section already carried before the fix landed.

## Goal, one sentence

Port the 6 `dev-rv-msi` commits dated 2026-09-10 or later that are not yet in
`dev_oci` (see below), on a new branch `integration/dev-rv-msi-into-dev_oci-
2026-09-21` (already created, based off `enterprise/dev_oci`), **without
reverting or disturbing `dev_oci`'s current file structure** — `dev_oci` went
through a Phase 8a package restructuring that `dev-rv-msi` never received, so
every ported change lands in the *current* split-file location, never by
recreating the old flat monolith files.

## Why this is needed / what's already been ruled out

- `dev-rv-msi` has 522 commits not in `dev_oci` in total — far too much to
  port wholesale. Scoped to just commits dated 2026-09-10+ (the date of the
  last known integration, PR #321), that narrows to 7 commits.
- One of those 7 (`9eddfa3f`, PR #319, exactly 2026-09-10) is **already
  ported** — it exists in `dev_oci`'s history as `a59ac792`, whose own commit
  message documents the port. Excluded from this plan.
- The remaining 6 are the scope of this plan.

## Non-negotiable constraint

`dev_oci`'s current package layout (from the Phase 8a restructuring) is
authoritative. Every hunk below gets applied to the file that layout says
holds that code **today** — never to a recreated flat file, even though
`dev-rv-msi`'s patches were written against the old flat paths.

## Second non-negotiable constraint: Oracle compatibility

`dev-rv-msi` is developed and tested against Postgres. `dev_oci` runs on
Oracle ADB (`effective_db_backend() == "oci"`) with a parallel
`OracleGraphReader`/Oracle-SQL implementation next to the FalkorDB/Postgres
one wherever the codebase has both backends. **Two of the six commits carry
Postgres-specific assumptions that do not transfer to Oracle as-is** — these
are not just path remaps, they need real backend-aware code, confirmed by
reading both implementations directly:

### #331's `find_entities(attrs=...)` only exists for FalkorDB

The patch to `src/aryx/graph/reader.py` (`GraphReader.find_entities`) adds
the `attrs=` keyword using **raw Cypher**:
```python
clauses.append(f"toLower(toString(e.{key})) CONTAINS toLower(toString(${pname}))")
```
`dev_oci`'s Oracle-backed reader, `OracleGraphReader.find_entities()`
([oracle_graph_reader_basic.py:76-110](../../src/aryx/graph/oracle_graph_reader_basic.py#L76-L110)),
is a **separate implementation** — plain SQL against a flat
`aryx_graph_vertex` table with a JSON `attributes` column, no Cypher, no
`attrs=` parameter at all today. On `dev_oci`/any OCI stack
(`ARYX_GRAPH_BACKEND=oci_graph`), everything built on top of the ported
`attrs=` feature — `search_by_feature()`, `search_products_combined()`, the
new `POST /entities/search` attribute filtering, and the Ask-integration
feature/region search — **will not work** unless `OracleGraphReader.find_entities()`
gets an equivalent `attrs=` implementation as part of this port, not as a
follow-up. The natural equivalent, mirroring the existing
`LOWER(name) LIKE '%' || LOWER(:name) || '%'` pattern already in that file:
`LOWER(JSON_VALUE(attributes, '$.' || :key)) LIKE '%' || LOWER(:val) || '%'`,
with the same key-format validation (`^[A-Za-z_][A-Za-z0-9_]*$`) the Cypher
version uses, for the same injection reason — Oracle's `JSON_VALUE` path
expression can't be bind-parameterized any more than a Cypher property name
can.

**This means step 4 (`e691bea0`) gains a new file to write, not just move:**
add the `attrs=` branch to `OracleGraphReader.find_entities()` alongside the
`GraphReader` version, with its own test coverage (mirroring whatever test
`dev-rv-msi` wrote for the Cypher path, e.g.
`tests/test_graph_find_entities_attrs_2026_09_15.py`) run against the Oracle
reader too, not assumed to pass by symmetry.

### #334's `_MAX_ENCODED_B64_BYTES` cap is derived from a Postgres-only limit

The commit's own comment is explicit about why the 170 MiB raw / ~227 MiB
encoded cap exists:
> "Postgres hard limit: a single jsonb scalar string cannot exceed
> 268,435,455 bytes"

`aryx_datasource.config_json` — the column this cap protects — is `JSONB`
on Postgres ([migrations/0024_datasource.sql:8](../../src/aryx/store/migrations/0024_datasource.sql#L8))
but **native Oracle `JSON`** on the Oracle schema
([migrations_oracle/0024_datasource.sql:9](../../src/aryx/store/migrations_oracle/0024_datasource.sql#L9)),
which does not share Postgres's 268,435,455-byte scalar-string ceiling —
Oracle's native JSON type stores large values via LOB internally, with a
vastly higher practical limit. Applying this cap unconditionally on Oracle
means large legitimate uploads get `content_b64=None` (silently degraded
download/preview) for a limit that doesn't actually apply to that backend.

**Fix while porting:** branch `_safe_content_b64()`'s cap on
`get_settings().effective_db_backend()`, the same pattern already used
elsewhere in this codebase
([entity_store.py:84](../../src/aryx/store/entity_store.py#L84),
[migrate.py:72](../../src/aryx/store/migrate.py#L72)) — keep the 170 MiB cap
for Postgres, use a materially higher (or no) cap for Oracle. Confirm the
real practical ceiling (LOB/JSON storage limits, plus whatever the upload
path's own `_MAX_FILE`/`_MAX_TOTAL` already bound it to) before picking the
Oracle-side number, rather than guessing one.

### #326 and #329 — checked, no Oracle-incompatible assumptions found

Neither commit's diff contains backend-specific SQL (`ON CONFLICT`, `jsonb`
operators, etc.) — `#329`'s `discoveries.py` change is pure Python
(de-dup logic over in-memory structures before storage), and `#326`'s cap
changes are plain integer constants with no backend branching needed. Both
ports should be backend-agnostic as planned.

## Dependency order

Three of the six commits touch the same file
(`src/aryx/cpq/data_table_resolver.py` in `dev-rv-msi`'s layout, now split
across several files in `dev_oci`) and must be applied **in this order**,
since #336 and #339 build on code #331 adds:

```
1. e7691115 (#326) -> independent
2. a8414af9 (#329) -> independent
3. d0f5aa3a (#334) -> independent
4. e691bea0 (#331) -> must precede 5 and 6
5. 9fad76d4 (#336) -> depends on 4
6. 8e60e0ca (#339) -> depends on 4 and 5
```

## File structure — exact target mapping

Every symbol below was located by grepping `dev_oci`'s current tree for its
definition, not guessed from directory names.

### 1. `e7691115` — fix(ingest): raise file-size caps to 500MB/1500MB (#326)

| `dev-rv-msi` path (patch target) | `dev_oci` current path |
|---|---|
| `src/aryx/api/doc_discover_api.py` | `src/aryx/api/doc_discover/doc_discover_api.py` |
| `src/aryx/api/file_ingest_api.py` | `src/aryx/api/file_ingest/file_ingest_api.py` |
| `tests/test_doc_discover_size_limit_*.py` | same (test paths unaffected by Phase 8a) |
| `tests/test_file_ingest_size_limits_*.py` | same |

Path-only remap, same shape as the already-completed `a59ac792` port of
#319 — low risk. **Landed as `140411c0`** — one extra fix needed:
`_MAX_FILE`/`_MAX_TOTAL`/`_MAX_FILES` actually live in a third file,
`file_ingest_limits.py` (not `file_ingest_api.py` itself), and the
cherry-pick's 3-way merge silently let several test files keep the dead
pre-Phase-8a import path (`aryx.api.file_ingest_api` /
`aryx.api.doc_discover_api`) without flagging a conflict — fixed those too.

### 2. `a8414af9` — fix(discovery): dedupe source XML/XLSX bytes (#329)

**Corrected after attempting the cherry-pick (2026-09-21): this was NOT
low-risk.** The path is unchanged, but `dev-rv-msi`'s `discoveries.py` still
has its own monolithic `_serialize`/`_deserialize`/`put`/`get`/`drop`
functions — an architecture that predates this branch's
`DiscoveryStore`/`discovery_store_codec.py` split entirely. The raw patch
doesn't apply as code; it targets a module structure that no longer exists
here. **Done:** reimplemented the same dedup fix
(`_dedupe_tabular_source_bytes`/`_rehydrate_tabular_source_bytes`) directly
in `discovery_store_codec.py`, composing with the existing generic
`_DiscoveryEncoder` bytes-handling instead of duplicating manual base64
calls, and ported 3 of the 4 dedup-specific tests into the existing
`tests/test_discovery_store.py` (skipped porting the other ~10 tests in
`dev-rv-msi`'s 414-line `test_discoveries_durable.py`, since those retest
generic bytes/Pydantic round-tripping this branch's codec already covers
separately). Landed as `6cd26573`.

### 3. `d0f5aa3a` — fix(source-catalog): cap inline content_b64 (#334)

`source_catalog.py` was split into 5 files. Touched symbols and their
current homes:

| Symbol touched | `dev_oci` current file |
|---|---|
| `xml_catalog_config` | `src/aryx/source/source_catalog_upsert.py` |
| `xml_asset_record` | `src/aryx/source/source_catalog_upsert.py` |
| `xlsx_catalog_config` | `src/aryx/source/source_catalog_upsert.py` |
| `xlsx_asset_record` | `src/aryx/source/source_catalog_upsert.py` |
| `upsert_xlsx_catalog_entry` | `src/aryx/source/source_catalog_upsert.py` |
| `find_legacy_xml_row` | `src/aryx/source/source_catalog_upsert.py` |
| `xlsx_download_payload` | `src/aryx/source/source_catalog_delete_download.py` |

`src/aryx/store/entity_store.py` and `src/aryx/worker/fn_handler.py` are
unchanged paths — apply directly. New test files
(`test_...oversized_attribute_diagnostic_2026_09_16.py`,
`test_fn_handler_size_limit_sync_2026_09_16.py`,
`test_...source_catalog_oversized_content_2026_09_16.py`) land as new files,
no remap needed.

**Actual outcome (2026-09-21): High risk confirmed, plus one extra layer.**
Both `entity_store.py` and `fn_handler.py`'s incoming sides also carried
`dev-rv-msi`'s OLDER monolithic code — inline `_fetch_entity_ids`/`_dumps`
in `entity_store.py`, inline `_dispatch()` in `fn_handler.py` — that
predates this branch's own later splits into `entity_store_ids.py` and
`fn_handler_dispatch.py`. Had to hand-merge each conflict to add only the
genuinely new logic (`_log_oversized_entity_attributes`,
`_MAX_ENCODED_B64_BYTES`) without reintroducing duplicate definitions of
code already split elsewhere. Landed as `766b1ff5`.

### 4. `e691bea0` — feat(graph/cpq): attribute-aware graph search (#331)

| `dev-rv-msi` change | `dev_oci` treatment |
|---|---|
| `src/aryx/graph/feature_search.py` (new) | New file, no conflict — add as-is. |
| `src/aryx/api/graph_api.py` | **Already exists on `dev_oci`** (143 lines) — this is a reconciliation, not a clean add. Read both versions, merge the new `/entities/search` endpoint in without clobbering whatever `dev_oci`'s version has that `dev-rv-msi`'s doesn't. |
| `src/aryx/api/ask_api.py` | Unchanged path — apply directly, but check for overlap with `dev_oci`-only changes to this file since it's a frequently-touched file. |
| `src/aryx/graph/reader.py` | Unchanged path — apply directly, **and** add the parallel `attrs=` implementation to `OracleGraphReader.find_entities()` (`oracle_graph_reader_basic.py`) in the same step — see "Second non-negotiable constraint" above. Not optional on an OCI/Oracle stack. |
| `src/aryx/cpq/intent_gateway.py` → `hard_off_topic` | `src/aryx/cpq/intent_gateway/intent_gateway.py` |
| `src/aryx/cpq/data_table_resolver.py` → `_is_hierarchy_shaped` | `src/aryx/cpq/data_table/data_table_shapes.py` |
| `src/aryx/cpq/data_table_resolver.py` → `find_inconsistent_filled_pairs` | `src/aryx/cpq/data_table/data_table_consistency.py` |
| `docker-compose-oci.yml` | Clean additive block (new `sales-ui` service + memory-budget comment update) — verified via diff, no overlap with this session's `docker-compose-oci-local.yml` work (different file). Low risk. |
| `sales_streamlit/app.py` | Check whether this file exists on `dev_oci` at all before applying. |

Note: this one `dev-rv-msi` commit's single `data_table_resolver.py` patch
splits across **two different** current files
(`data_table_shapes.py` and `data_table_consistency.py`) — apply each hunk
to its own target file, not both to one.

**Actual outcome (2026-09-21): Landed as `e564b6bb`, 23 files.** The
biggest and highest-risk commit in this whole effort, as predicted.
`_is_attr_var_mapping_shaped` went to `data_table_shapes.py`, but the 3
new resolver functions went to `data_table_product.py` (not
`data_table_consistency.py` — they're reverse-lookups of
`resolve_region_allow_value`, which lives there) — re-checked against the
real target file's existing contents rather than assumed from the plan.
`api/graph_api.py` auto-merged cleanly and correctly, no manual work
needed. `ask_api.py`'s reconciliation required creating a brand new file
(`api/ask_feature_region_search.py`) since the patch's target
(a 4500-line monolithic `ask_api.py`) doesn't exist here at all — this
branch's is an 84-line shim. `intent_gateway.py`'s incoming side also
carried duplicate `ValueCandidate`/`AttrCandidateBundle` class definitions
that already exist in `intent_gateway_candidates.py` here — dropped them.
The `OracleGraphReader.find_entities(attrs=...)` gap flagged above was
**deliberately deferred to a follow-up**, not included in this commit.

### 5. `9fad76d4` — fix(cpq): memoize resolve_whitelist_values (#336)

| Symbol touched | `dev_oci` current file |
|---|---|
| `_row_conditions_match` | `src/aryx/cpq/data_table/data_table_whitelist.py` |
| `resolve_whitelist_values` | `src/aryx/cpq/data_table/data_table_whitelist.py` |

Both hunks land in the same current file — apply together. Must come after
#331 is already applied (touches code #331 may have shifted).

### 6. `8e60e0ca` — fix(cpq): scope Hardware Version / 900MHz Hybrid Combiner (#339)

| `dev-rv-msi` change | `dev_oci` current path |
|---|---|
| `src/aryx/api/ask_api.py` | Unchanged path |
| `src/aryx/cpq/engine.py` | Unchanged path |
| `src/aryx/cpq/data_table_resolver.py` → `resolve_product_cpq_models_from_rows` | `src/aryx/cpq/data_table/data_table_product.py` |
| `src/aryx/cpq/state.py` → `class HidingRule` | `src/aryx/cpq/state/state_rules.py` |
| 3 new test files (`*_2026_09_21.py`) | New files, no remap |

Must come after #331 and #336 (same `data_table` files touched again).

**Status (2026-09-21): LANDED as `67c3d72f`.**
First attempt was reverted cleanly (no partial state left on this
branch) after discovering the true scope was far bigger than the
"unchanged path" assumption below. Second attempt (this session)
completed it — see "Actual outcome" at the end of this section for what
the real delegation chain turned out to be (deeper than even the
Explore-agent-assisted re-investigation below found). The original
scope writeup is kept as-is for the historical record of what the
investigation looked like before implementation. Turned out far bigger
than the "unchanged path" assumption above: the
*files* (`ask_api.py`, `engine.py`) are unchanged paths, but their
*content* has diverged heavily from separate refactoring histories on
each branch:

- `src/aryx/cpq/engine.py` produced **9 separate conflict blocks**, not
  because the file was split (it wasn't — same path on both branches),
  but because this branch's own "shrink engine.py further" extraction
  series (documented in this repo's own commit history, unrelated to
  `dev-rv-msi`) removed large blocks of code the two branches once
  shared, shifting line-context enough that git's 3-way merge can't
  reconcile most of the ~10 real, individually-small hunks (new
  `_DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES` constant, a
  `dt_whitelist_substitute` branch inside the hiding-rule loader, an
  `apply_hiding_rules` signature change (+3 new kwargs) with new
  substitute-check logic in its body, a new `product_anchor_hint` param
  threaded through `auto_fill`/`calibrate_config`/
  `_order_pending_hardware_before_product`, and a new
  `_hardware_version_confirmed_not_applicable` staticmethod).
- `src/aryx/api/ask_api.py`'s patch touches **~15 scattered call sites**
  across ~13 different handler functions (`_handle_cascade`,
  `_handle_multi_select_removal`, `_handle_attr_activation`,
  `_handle_attr_clear`, `_build_show_summary_response`,
  `_handle_bulk_quantity_change`, `_handle_cascade_multi`,
  `_dispatch_intent_result`, `_build_country_change_response`,
  `_llm_first_gateway_turn`, `_build_json_preview_response`,
  `_handle_approval`, `_run_cpq_turn_inner`) — each now very likely living
  in its own file after this branch's Phase 9/10 `ask_api.py`
  decomposition (same pattern as #331's `ask_run_ask.py`/
  `ask_feature_region_search.py` split), needing individual location.
- `src/aryx/cpq/state/__init__.py` also conflicted (1 block) — likely the
  same lazy re-export pattern as `intent_gateway/__init__.py` needing a
  new entry, not yet investigated in depth.

**For whoever picks this up:** don't trust the file-path-based risk
assessment above at face value — re-verify current call-site locations
for each of the ~15 `ask_api.py` touch points and each of the ~10
`engine.py` hunks individually (the same "reset to HEAD, apply each hunk
via exact-text Edit, don't fight the conflict markers" method used for
#331 and this commit's own `data_table_resolver.py` conflict should work,
it's just a larger number of individually-simple edits). This is real CPQ
business logic (Hardware Version mandatory-ness, hiding-rule fallback
behavior for a live-confirmed customer-facing bug) — a missed call site
is a silent correctness bug, not a test failure, so budget time for
careful verification against the 3 new test files
(`test_cpq_apx900_hybrid_combiner_missing_script_2026_09_21.py`,
`test_cpq_hardware_version_apx3000_scoping_2026_09_21.py`,
`test_cpq_resolve_product_cpq_models_from_hint_2026_09_21.py`) rather than
rushing it in the same session as everything else.

**Actual outcome (landed as `67c3d72f`):** the pre-implementation
"Execution plan" section further up this doc (Part A) got the call-site
locations right for `data_table_product.py`
(`resolve_product_cpq_models_from_hint`) and `hiding_rules/type11.py`,
but — like the writeup above — undersold the delegation depth on the
`engine.py` side. Discovered only during implementation, by reading each
target function's real body instead of trusting the plan:

- `CpqEngine.apply_hiding_rules`, `.auto_fill`,
  `._order_pending_hardware_before_product`, and `.evaluate_rules_loop`
  are ALL thin wrappers (this branch's Phase 4 `cpq/engine.py`
  decomposition) delegating to `hiding_rules/apply.py`,
  `auto_fill/auto_fill_run.py`, `auto_fill/auto_fill_hw_order.py`, and
  `rules_loop/rules_loop.py` respectively — each needed the new
  `workspace_id`/`catalog_prefix`/`dt_cache`/`product_anchor_hint`
  params threaded one layer further than either the original commit or
  the Explore-agent report anticipated.
- `_hardware_version_confirmed_not_applicable` was drafted as a
  delegate to `auto_fill_hw_order.py` (matching the above pattern) but
  had to be moved back to real logic directly in `engine.py`: its own
  new test file patches `aryx.cpq.engine.dt_resolve_product_cpq_models_
  from_hint`/`dt_attr_ever_governed_for_cpq_model` by dotted path, and a
  delegate module binds its own separate copies of those names at
  import time, silently missing the patch (the same re-export-hub
  pitfall already hit twice earlier this session, now hit a third time
  in the opposite direction — a test assuming the OLD, pre-split
  location).
- `hiding_rules/apply.py` had the identical bug in the other direction:
  it imported `dt_resolve_whitelist_values` from `engine.py` at module
  scope, so a test patching `aryx.cpq.engine.dt_resolve_whitelist_values`
  silently didn't intercept it. Fixed by switching to `import aryx.cpq.
  engine as _engine_module` and calling `_engine_module.dt_resolve_
  whitelist_values(...)` — looked up fresh on every call, same fix
  pattern as the module-object convention `ask_handle_approval.py`/
  `ask_json_preview_and_decline.py` already use for `_ask_api_module`.
- 3 real call sites (not part of the original commit's own diff) needed
  `workspace_id=`/`catalog_prefix=` threaded into their
  `apply_hiding_rules(...)` calls: `recommendation_and_constraint_rules/
  inconsistencies.py`, `rules_loop/rules_loop_pass_early.py`,
  `cpq/turn_intent/attr_toggle.py`.
- Verified via 251 targeted tests (all 3 new test files plus every
  directly touched module's own existing suite) — green except 3
  pre-existing `test_cpq_auto_fill_data_table_tier.py` failures,
  confirmed unrelated by re-running the same 3 tests against `HEAD`
  before this commit's changes (same failures, same assertions).
  A full-repo `pytest tests/` run was attempted for extra confidence but
  stalled indefinitely (`hrtimer_nanosleep`, 0% CPU, no open sockets —
  consistent with a retry/backoff loop against a service this sandbox
  doesn't have, e.g. a live DB) and was killed after 15+ minutes with no
  progress; the scoped 251-test run was judged sufficient given it
  covers every module this commit actually touches.

## Stack compliance

No new dependencies, no new services. `sales-ui` (Streamlit) is a new
docker-compose service in #331 — confirm it doesn't already exist on
`dev_oci` under a different name before adding, and that `ARYX_SALES_MSI_BASE_URL`
is a real, already-approved env var.

## Risk flags

- **Highest risk: `OracleGraphReader.find_entities()` has no `attrs=` today.**
  This is the one item in this plan that's genuinely new code, not a port —
  everything else is relocating/adapting an existing patch. Test it against
  a real Oracle-backed workspace (not just unit tests with a fake reader)
  before considering #331 done, since this is exactly the kind of gap that
  looks fine in isolated tests and only surfaces on the real OCI stack —
  the same lesson this session's SVX investigation kept relearning.
- **`_MAX_ENCODED_B64_BYTES` (#334) must not ship Oracle-unaware.** If the
  backend branch is skipped "to keep the port simple," Oracle deployments
  silently inherit a Postgres-only limit that doesn't protect against
  anything real on that backend, for no benefit.
- **`api/graph_api.py` reconciliation in #331** — the only
  file that's both already-modified on `dev_oci` AND targeted by an
  incoming patch. Read both full versions before touching it.
- **`ask_api.py` and `engine.py`** are touched by #331 and #339
  respectively at unchanged paths, but both are large, frequently-edited
  files — verify line-anchor context still matches before trusting a clean
  `git apply`/cherry-pick; a stale line offset silently applying to the
  wrong function is the real danger here, not an outright conflict.
- **Ordering violation risk**: applying #336 or #339 before #331 will
  either fail outright (missing context) or, worse, silently apply against
  pre-#331 code — always verify #331 is committed on this branch before
  starting #336.
- Every reconciled file should be diffed against its pre-port `dev_oci`
  version after each step, not just after all 6 are done, so a bad merge is
  caught at the commit that caused it.

## Procedure per commit

1. `git cherry-pick -n <hash>` (no auto-commit).
2. For every conflicted/new-content file, manually move the hunk to its
   `dev_oci`-current target file per the tables above.
3. Run that commit's own test file(s) against the ported code.
4. `git diff --stat` review, then commit with a message noting the original
   `dev-rv-msi` hash and PR number (matching the `a59ac792` precedent's
   "Ported from dev-rv-msi (#NNN, <hash>)" convention).
5. Move to the next commit only after the current one is green.

No commit has been ported yet under this plan — this document is the plan,
written before execution, per explicit instruction not to disturb `dev_oci`'s
structure while doing so.
