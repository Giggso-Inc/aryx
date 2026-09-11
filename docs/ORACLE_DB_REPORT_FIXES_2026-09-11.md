# Oracle DB Report — Fixes (2026-09-11)

PR: [#322 — Fix missing workspace_id indexes found in Oracle ADB data-map review](https://github.com/Giggso-Inc/aryx-enterprise/pull/322)
Branch: `fix/oracle-db-report-issues-2026-09-11` → `dev_oci`
Source investigation: `docs/Oracle_ADB_Data_Map.xlsx` (Issues sheet)

Fixes the 2 High-severity, code-actionable findings from the full Oracle ADB
data-map review, and documents the disposition of the 2 Medium findings that
don't get a code fix. See `docs/ORACLE_DB_REPORT_FOLLOWUPS_2026-09-11.md` for
the full reasoning behind the two deliberately-not-code-fixed items.

---

## 1. `aryx_job` had no index on `workspace_id`

**Problem:** every job-status poll, job-count badge, and workspace purge
queries `aryx_job` filtered by `workspace_id` — with no index covering it.

**Root cause:** the only index on `aryx_job` was `idx_job_finished
(finished_at)`. But `workspace_id` is the actual filter in 6+ real call
sites: `select_job_total.sql`, `select_job_summary.sql` (a `GROUP BY status`
aggregate), `select_active_workspace_job.sql`, `delete_jobs_by_workspace.sql`,
and twice in `purge_workspace_data.sql`. None of them can use an index seek
— every one does a full table scan.

**Fix:** `CREATE INDEX idx_job_workspace ON aryx_job (workspace_id, status)`
— covers both the count/summary queries and the purge delete. Added on both
Postgres (`migrations/0041_job_workspace_index.sql`) and Oracle
(`migrations_oracle/0041_job_workspace_index.sql`).

**Impact:** this table grows without bound (one row per ingest job, ever)
and is on a **user-visible hot path** — job status polling fires
continuously during any active ingest. A full scan here gets linearly
slower as the system accumulates history, with no query-shape change needed
to trigger it; the fix is a pure, zero-risk index add with no behavior
change.

---

## 2. Two Shay chat-bridge tables have an unindexed, cascading foreign key

**Problem:** `aryx_shay_chat_map` and `aryx_shay_chat_turn` both have a
foreign key to `aryx_workspace` with no index covering it.

**Root cause:** both tables declare `aryx_workspace_id NOT NULL REFERENCES
aryx_workspace(id) ON DELETE CASCADE` with no index on that column at all —
unlike their sibling bridge tables (`aryx_shay_workspace_map`'s FK is
`UNIQUE`, implicitly indexed; `aryx_shay_datasource_map` is covered by a
composite index). This pair is the exception to an otherwise-consistent
pattern, on both Postgres and Oracle.

**Fix:** added `idx_shay_chat_map_workspace` and
`idx_shay_chat_turn_workspace` on both backends
(`migrations/0042_shay_chat_workspace_index.sql`,
`migrations_oracle/0042_shay_chat_workspace_index.sql`).

**Impact:** deleting a workspace cascades into both tables with no index to
find the matching rows — a full table scan per delete, on
`aryx_shay_chat_turn` specifically, the table most likely to grow the
largest in the whole bridge (one row per chat turn, ever). Any future "list
this workspace's Shay chat activity" query has the identical cost. Fix is
additive-only, no behavior change.

---

## Not code-fixed

### 3. Shay's `datasource.py`/`gg_datasource.py` naming inversion

**Problem:** `gg_datasource.py` declares `__tablename__ = "datasources"`;
`datasource.py` declares `__tablename__ = "gg_datasources"` — each file maps
to the table its own name suggests the *other* file should.

**Root cause:** historical naming drift; both models are genuinely live
(`/api/v1/datasources` and `/api/v1/gg-datasources`, confirmed via
`app_routers.py`) — not dead code.

**Decision, not a fix:** leave as-is. A rename touches routes referencing
either model across ~40 files for a maintainability improvement only, not a
functional one — the risk/reward doesn't justify it as a standalone change.

**Impact if left alone:** a real onboarding/code-navigation hazard
(grepping the wrong filename), but zero runtime risk — both paths already
work as coded.

### 4. Alembic/SQLAlchemy Oracle-index-drift risk

**Problem:** an index added only via a hand-written Alembic migration could
silently never reach Oracle deployments.

**Root cause:** `SHAY_RUN_MIGRATIONS=false` disables Alembic entirely in
OCI mode; `SHAY_INIT_DB=true` creates every Oracle table via SQLAlchemy's
own `create_all()`, which only emits indexes declared in each model's
`__table_args__`. No specific missing index was confirmed — Shay's Alembic
migration files aren't present in this checkout to diff against.

**Decision, not a fix:** process guidance instead of a pinpointed change —
treat each model's `__table_args__` as the single source of truth for
indexes going forward.

**Impact if left alone:** a future Postgres-only index addition (via
Alembic, without mirroring it into the model) would create a silent
Postgres/Oracle parity gap with no error at creation time.

---

## Informational only (no action)

- **Embedding pipeline (`aryx_chunk_embedding`) is write-only.** No
  retrieval code exists anywhere in the codebase, and no `CREATE VECTOR
  INDEX` exists on the column either. Likely an intentionally incomplete
  feature (`requirements.txt` tags `pgvector` as "Increment 9"), not a bug —
  needs a product decision on whether document-embedding retrieval
  (RAG-style Q&A over documents) is meant to exist yet.
- **The Oracle Property Graph object is used by only 1 of 8 read methods.**
  Not a bug — plain SQL joins are often more efficient than `GRAPH_TABLE`
  for simple 1-hop patterns, and this is a deliberate, reasonable choice
  already in place.

---

## Verification

- Both new migration files verified to parse correctly under each runner's
  own statement/block splitter (`_split_statements` for Postgres,
  `_split_blocks` for Oracle) before committing.
- Both migration runners (`migrate.py`, `oracle_migrate.py`) confirmed to
  have no per-file "already applied" tracking — they unconditionally
  re-apply every file, relying on `IF NOT EXISTS`/`ORA-01408` idempotent
  guards, so these will safely backfill on already-migrated instances.
- Committed content re-verified via a `git worktree` checkout before
  pushing.
