# OCI Parity Audit — Where Postgres Features Have No Oracle Equivalent

**Date:** 2026-07-27 | aryx project | giggso
**Scope:** Every SQL query file (`src/aryx/queries/*.sql`, 199 files) and every
explicit `effective_db_backend() == "oci"` branch point in Python, checked for
Postgres-specific behavior that the generic `_translate_sql()` auto-translator
(`src/aryx/store/oracle_pool.py`) cannot safely handle, and that has no
`queries/oracle/` override.

**Headline finding: there is exactly one real gap.** Everything else in the
codebase already has full Oracle parity — either via a generic auto-translated
query, or a dedicated `queries/oracle/*.sql` override, or a backend-dispatch
Python class (`OracleWorkspaceStore`, `OracleCpqRdb`, `OracleGraphStore`, etc.).

---

## Method

1. Diffed `src/aryx/queries/*.sql` (199 files) against `src/aryx/queries/oracle/*.sql`
   (45 overrides) to find the 168 files with no override.
2. Grepped all 199 files for patterns the generic translator does not attempt
   to handle: `xmax`, `EXCLUDED.` (complex `ON CONFLICT ... DO UPDATE`), JSONB
   operators (`->>`, `->`), `ILIKE`, full-text search (`to_tsvector`/`@@`),
   `LATERAL`, `DISTINCT ON`, array `= ANY(%s)`.
3. Cross-referenced hits against the no-override list — a hit *with* an
   override is already handled; a hit *without* one is a real gap.
4. Grepped all Python source for `effective_db_backend() == "oci"` to find
   every explicit backend branch, and classified each as dispatch (both sides
   implemented) vs. gate (one side hard-blocked).

---

## Result table

| Pattern | Files using it | Files with NO override | Verdict |
|---|---|---|---|
| `EXCLUDED.` (complex upsert) | 9 | 3 | Gap — see below |
| JSONB `->>`/`->` operators | 5 | 5 | Gap — see below (overlaps with above) |
| `xmax` (insert-vs-update detection) | 1 | 1 | Gap — see below |
| `ILIKE` / full-text search / `LATERAL` / `DISTINCT ON` | 0 | — | None found anywhere in the codebase |
| Array `= ANY(%s)` | 4 | 0 | Already fully ported (all 4 have `JSON_TABLE` overrides) |

**Union of every flagged file: 7, all in one feature family — `ask_thread_*`.**

## Python-level backend branches

| File | What it does | Verdict |
|---|---|---|
| `store/pool.py` | Dispatches to `OraclePool` vs `psycopg_pool` | Dispatch — both implemented |
| `store/migrate.py` | Dispatches to Oracle vs Postgres migration runner | Dispatch — both implemented |
| `workspaces.py` | Dispatches to `OracleWorkspaceStore` vs `WorkspaceStore` | Dispatch — both implemented (208-line Oracle class, not a stub) |
| `cpq/rdb.py` | Dispatches to `OracleCpqRdb(PostgresCpqRdb)` vs `PostgresCpqRdb` | Dispatch — subclass overrides only the incompatible methods, not a stub |
| `config.py:441` | `effective_dsn()` backend selection | Dispatch — returns the right DSN |
| `store/ask_thread_store.py:395`, `api/ask_thread_api.py:34` | Raise `501`/`RuntimeError` unconditionally | **Gate — the one real feature block** |

---

## The gap: `ask_thread_*` (Shay-backed Ask conversation threads)

**Blocked entirely today:**
- `src/aryx/api/ask_thread_api.py:32-36` — `_store_or_unsupported()` raises
  `HTTPException(501, ...)` for every Ask-thread endpoint when
  `effective_db_backend() == "oci"`.
- `src/aryx/store/ask_thread_store.py:392-398` — `get_ask_thread_store()`
  raises `RuntimeError` for the same condition.

Both gates are **unconditional** — they block all 14 `ask_thread_*.sql`
queries even though, as the breakdown below shows, **7 of the 14 need no
porting work at all.** The gate is broader than the actual gap.

### Per-query breakdown (all 14 files)

| Query | Needs porting? | Why |
|---|---|---|
| `ask_thread_ensure_channel.sql` | 🔴 Yes | `ON CONFLICT (...) DO UPDATE` with `EXCLUDED.channel_settings \|\| ...` (JSONB merge) |
| `ask_thread_ensure_thread.sql` | 🔴 Yes | `ON CONFLICT (id) DO UPDATE` with `COALESCE(NULLIF(...))` on `EXCLUDED.title` |
| `ask_thread_insert_message.sql` | 🔴 Yes — the hard one | `(xmax = 0) AS inserted`, partial-index `ON CONFLICT (...) WHERE ... DO UPDATE ... WHERE <CASE logic>`, JSONB `->>`/`\|\|`, `FOR UPDATE`, `INTERVAL '20 minutes'` — five distinct unported features in one query |
| `ask_thread_list_threads.sql` | 🟡 Easy | One `(col->>'key')::boolean` extraction |
| `ask_thread_select_cached_response.sql` | 🟡 Easy | Same `->>'aryx_hidden'` + `->>'error'` pattern |
| `ask_thread_select_thread_owner.sql` | 🟡 Easy | Same `->>'aryx_hidden'` pattern |
| `ask_thread_select_thread_scope.sql` | 🟡 Easy | Same `->>'aryx_hidden'` pattern |
| `ask_thread_list_messages.sql` | ✅ No — already fine | Plain `SELECT`/`WHERE`/`LIMIT`, generic translator handles it |
| `ask_thread_select_history.sql` | ✅ No | Plain CTEs, no JSONB/EXCLUDED/xmax |
| `ask_thread_select_mapping.sql` | ✅ No | Plain lookup |
| `ask_thread_select_request_message.sql` | ✅ No | Plain lookup |
| `ask_thread_touch_channel.sql` | ✅ No | Plain `UPDATE` |
| `ask_thread_touch_thread.sql` | ✅ No | Plain `UPDATE` |
| `ask_thread_update_request_status.sql` | ✅ No | Plain `UPDATE` |

### Why these three are hard — no generic translation exists for them

| Postgres feature | What it does here | Oracle problem | Existing precedent in this codebase |
|---|---|---|---|
| `(xmax = 0) AS inserted` | Detects whether the `ON CONFLICT` branch inserted or updated, so the caller knows if this was a new message | **No Oracle equivalent.** `xmax` is a Postgres MVCC system column; Oracle has nothing analogous | None — this is genuinely novel. Closest existing pattern: `oracle_pool.py`'s `_conflict_ignore` flag, which already tracks "did `ON CONFLICT` fire" for a different purpose (swallowing ORA-00001) |
| Partial-index `ON CONFLICT (...) WHERE ... DO UPDATE ... WHERE <CASE>` | Only overwrites a message under specific retry/failure conditions (idempotent retries must not duplicate or clobber a good answer) | Oracle's `MERGE` can express conditional updates, but not a *partial unique index* as the match target — needs restructuring, not translation | 7 files already use `MERGE INTO` for simpler upserts: `merge_graph_vertex.sql`, `merge_graph_provenance.sql`, `merge_graph_edge.sql`, `merge_graph_source.sql`, `upsert_ontology_type.sql`, `upsert_projection_state.sql`, `upsert_discovery.sql` |
| `message_metadata->>'key'`, `channel_settings->>'aryx_hidden'` | Extract a JSON field as text | Oracle needs `JSON_VALUE(col, '$.key')` instead of the `->>` operator | `src/aryx/queries/oracle/select_entity_by_type_name.sql` already does this |
| `COALESCE(col, '{}'::jsonb) \|\| EXCLUDED.col` | Shallow-merge two JSON objects, keeping new keys and overwriting matching ones | Oracle needs `JSON_MERGEPATCH(col, :new_json)` | `src/aryx/queries/oracle/merge_entity_attributes.sql` and `update_entity_attributes.sql` already do this |
| `NOW() - INTERVAL '20 minutes'` | Staleness check for stuck `in_progress` requests | Oracle needs `CURRENT_TIMESTAMP - INTERVAL '20' MINUTE` or `SYSTIMESTAMP - (20/1440)` | Not yet used elsewhere, but a mechanical one-line translation once decided |
| `SELECT ... FOR UPDATE` | Row lock while computing the next `sequence_number` | Oracle supports `FOR UPDATE` natively — **this one is not actually a gap**, just listed for completeness | N/A |

**Bottom line: every pattern needed to fix this has already been solved once
elsewhere in this codebase.** This is an application of established idioms to
three new queries, not new engineering — except for the `xmax` replacement,
which is genuinely novel and needs a small design decision (below).

---

## Fix plan

### Phase 1 — Unblock the 7 already-safe queries (low effort, immediate value)
Split `_store_or_unsupported()` / `get_ask_thread_store()` so the gate is
per-query, not per-feature — or, more simply, port the 3 hard + 4 easy
queries together (Phase 2/3) and remove the gate entirely once all 14 pass.
Given the small remaining scope, **recommend skipping this phase** and going
straight to a full port — a partial unblock adds branching complexity for
one release cycle of benefit.

### Phase 2 — Port the 4 easy JSON-operator queries
Mechanical: replace every
```sql
COALESCE((gg_channels.channel_settings->>'aryx_hidden')::boolean, FALSE)
```
with
```sql
COALESCE(JSON_VALUE(gg_channels.channel_settings, '$.aryx_hidden' RETURNING BOOLEAN), FALSE)
```
(or `JSON_VALUE(..., '$.aryx_hidden') = 'true'` if targeting an older Oracle
version without `RETURNING BOOLEAN`). Same substitution for
`message_metadata->>'error'`. Write as `queries/oracle/ask_thread_list_threads.sql`,
`ask_thread_select_cached_response.sql`, `ask_thread_select_thread_owner.sql`,
`ask_thread_select_thread_scope.sql`. **Est. effort: under a day**, including tests.

### Phase 3 — Port `ask_thread_ensure_channel.sql` and `ask_thread_ensure_thread.sql`
Rewrite as Oracle `MERGE INTO` statements, using `JSON_MERGEPATCH` for the
settings-merge and `NULLIF`/`COALESCE` exactly as the Postgres version does.
Template directly off `upsert_ontology_type.sql`'s existing `MERGE` structure.
**Est. effort: 1-2 days**, including retry-safety tests (concurrent
channel/thread creation must not duplicate rows or lose settings).

### Phase 4 — Port `ask_thread_insert_message.sql` (the hard one)
This is the one requiring a real design decision, not just translation.
Two viable approaches:

**Option A — Two-step insert-or-update (recommended):**
1. `SELECT` the existing message row by `(thread_id, request_id, message_type)`
   under `FOR UPDATE` (Oracle supports this natively).
2. If no row: `INSERT`, and the Python caller knows `inserted=True` because it
   took the insert branch — no `xmax` needed, the branch taken **is** the flag.
3. If a row exists: apply the same conditional-overwrite logic (CASE-based
   user/system + failed/in-progress checks) as a plain `UPDATE`, still inside
   the same `FOR UPDATE`-locked transaction so it's race-free.
This mirrors the existing `_conflict_ignore` pattern in `oracle_pool.py`
(Python-side branch = the signal) rather than inventing a SQL-side flag.

**Option B — Oracle `MERGE ... RETURNING` with a computed flag column:**
Add a bind variable the `MERGE` sets differently on `INSERT` vs `UPDATE`
(e.g. `RETURNING (CASE WHEN ... ) INTO :inserted_flag`). More SQL-native but
harder to get right given the existing conditional-overwrite logic already
spans a large `CASE` block per column — Option A is very likely simpler to
implement and test correctly.

**Est. effort: 2-3 days**, including idempotent-retry tests (the whole point
of this query is safe retries — this needs the most test coverage of the
three).

### Phase 5 — Remove the gate, verify end-to-end
Delete the `HTTPException(501, ...)` / `RuntimeError` gates. Run a real
multi-turn Ask conversation against OCI mode, including a simulated retry
(duplicate `request_id`) to confirm no duplicate/corrupted messages.

**Total estimated effort: 4-6 days** for a fully tested port — not the "days
of unscoped porting work" implied by treating this as one big unknown; the
codebase's existing Oracle patterns cover all but one novel piece.

---

## What's NOT a gap (confirmed clean)

- All 4 `= ANY(%s)` array-parameter queries already have `JSON_TABLE`-based
  Oracle overrides (`select_landed_by_ids`, `select_chunk_ids_by_doc`,
  `select_provenance_for_entities`, `select_relationships_for_entities`).
- No `ILIKE`, full-text search (`to_tsvector`/`@@`), `LATERAL` joins, or
  `DISTINCT ON` anywhere in the 199-file query set — these Postgres-only
  constructs were never introduced, so there's nothing to port for them.
- Every other `effective_db_backend() == "oci"` branch in Python is a real
  dispatch to a working Oracle-side implementation, not a stub or a block
  (`OracleWorkspaceStore` — 208 lines; `OracleCpqRdb` — a working subclass of
  `PostgresCpqRdb`, not empty).

---

*Source analysis: src/aryx/queries/*.sql (199 files), src/aryx/queries/oracle/*.sql
(45 files), src/aryx/api/ask_thread_api.py, src/aryx/store/ask_thread_store.py,
src/aryx/store/oracle_pool.py, src/aryx/workspaces.py, src/aryx/cpq/rdb.py,
src/aryx/store/pool.py, src/aryx/store/migrate.py*
