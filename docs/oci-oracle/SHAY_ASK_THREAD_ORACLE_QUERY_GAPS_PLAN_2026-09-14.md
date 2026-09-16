# Shay/Ask-thread Oracle query-override gaps — plan (2026-09-14)

Branch: `fix/shay-askthread-oracle-query-overrides-2026-09-14` → `dev_oci`

## Background

A prior claim ("no Oracle DDL or query overrides exist for the Shay chat
tables at all") was checked directly against `dev_oci` HEAD and found to
be substantially wrong: DDL for `aryx_shay_workspace_map` exists, the
`gg_*` tables are correctly created via Shay's own dialect-aware
SQLAlchemy models, and 12 of 14 `ask_thread_*` query overrides already
exist -- including the hardest one (the retry-safe message upsert,
which deliberately reuses Shay's pre-existing `query_id` column as the
Oracle-side stand-in for Aryx's Postgres-only `request_id` column,
traced end-to-end through `ask_thread_oracle_insert.py`).

What's actually missing, confirmed by direct code inspection:

## Problem

Four SQL query files, called unconditionally (no backend branch) from
two different store modules, have no Oracle override and use
Postgres-only syntax that will raise a real SQL error the first time
they execute against Oracle:

1. **`ask_thread_select_mapping`** (`aryx/store/ask_thread_store.py`,
   `validate_mapping()`) — uses `%s::uuid`/`%s::text` casts.
2. **`ask_thread_touch_channel`** (same file, called from both
   `ensure_thread_and_user_message()` and `append_assistant_message()`)
   — uses `NOW()`; the code already carries its own comment flagging
   this exact gap ("*no queries/oracle/ask_thread_touch_channel.sql
   override exists yet... Postgres-only syntax*").
3. **`sales_chat_claim_thread`** (`sales_streamlit/chat_store.py`,
   `claim_thread()`) — uses `%s::uuid` casts AND
   `INSERT ... ON CONFLICT (thread_id) DO NOTHING ... RETURNING`, a
   real upsert-race primitive Oracle has no direct equivalent for.
4. **`sales_chat_select_thread`** (same file, `claim_thread()` fallback
   and `validate_owner()`) — uses a `%s::uuid` cast.

(3) and (4) were found only by widening the audit beyond
`ask_thread_store.py` to every `gg_*`/Shay-adjacent query call site --
`chat_store.py` is on the exact path the `SALES_CPQ_PURPOSE`+`oci`
guard in `mcp_tokens_api.py` currently blocks, so these two matter more
than the original two: lifting that guard without fixing them would
still break sales-chat on Oracle immediately.

`aryx_sales_chat_thread`'s own DDL already exists on Oracle
(`migrations_oracle/0038_sales_cpq.sql`) — this is purely a query-layer
gap, not a missing-table gap.

## Root cause (per query)

- **select_mapping / select_thread**: plain syntax translation --
  Oracle's `VARCHAR2` columns need no `::uuid`/`::text` cast at all;
  the cast only exists because Postgres stores these as native `uuid`.
- **touch_channel**: `NOW()` → `SYSTIMESTAMP`, no cast needed on the
  `id` column.
- **claim_thread**: the real complexity. Postgres's `INSERT ... ON
  CONFLICT DO NOTHING RETURNING ...` atomically inserts-if-absent and
  hands back the winning row (existing or new) in one round trip.
  Oracle has no `ON CONFLICT`. The existing `ask_thread_oracle_insert.py`
  precedent for the *message* upsert used an explicit
  lock-then-check-then-insert dance -- but that only works because a
  parent row (the thread) already exists to lock. Here there is no
  parent row to lock when the thread genuinely doesn't exist yet, so
  the same pattern doesn't apply. The correct equivalent is a `MERGE
  INTO ... USING (SELECT :1, :2, :3, :4 FROM dual) ON (thread_id
  matches) WHEN NOT MATCHED THEN INSERT` -- atomic, no exception
  handling needed, race-safe. The one behavioral difference: Oracle's
  `MERGE` gives no `RETURNING`-shaped resultset readable via a normal
  `fetchone()` the way Postgres's `RETURNING` does. `chat_store.py`'s
  `claim_thread()` must therefore always follow the Oracle `MERGE`
  with a `sales_chat_select_thread` lookup (not just on `row is None`,
  as it does today for Postgres) -- a small, explicit backend branch,
  mirroring the `_is_oracle_backend()` pattern `ask_thread_store.py`
  already established.

## Fix

1. `src/aryx/queries/oracle/ask_thread_select_mapping.sql` -- new,
   `VARCHAR2` equality, no casts.
2. `src/aryx/queries/oracle/ask_thread_touch_channel.sql` -- new,
   `SYSTIMESTAMP`, no cast.
3. `src/aryx/queries/oracle/sales_chat_claim_thread.sql` -- new,
   `MERGE INTO aryx_sales_chat_thread USING (SELECT :1 thread_id, :2
   actor_id, :3 workspace_id, :4 shay_workspace_id FROM dual) ON
   (aryx_sales_chat_thread.thread_id = :1) WHEN NOT MATCHED THEN
   INSERT (...) VALUES (...)`.
4. `src/aryx/queries/oracle/sales_chat_select_thread.sql` -- new,
   `VARCHAR2` equality, no cast.
5. `sales_streamlit/chat_store.py::claim_thread()` -- add an
   `_is_oracle_backend()` branch: on Oracle, always run
   `sales_chat_select_thread` after the `MERGE`, not only when
   `cur.fetchone()` returns `None` (which it always will for a `MERGE`
   with no `RETURNING`).
6. `src/aryx/api/mcp_tokens_api.py` -- remove the `SALES_CPQ_PURPOSE`
   + `effective_db_backend() == "oci"` 501 guard, only after (1)-(5)
   land and are verified.

## Dependency map

**Touches:** the 4 new SQL files above, `chat_store.py` (one method,
one new branch), `mcp_tokens_api.py` (guard removal, last).

**Does not touch:** `ask_thread_store.py`, `ask_thread_oracle_insert.py`
(both already correct and unchanged), any DDL/migration file (all
required tables already exist on Oracle), `shay_workspace_bridge.py`
(audited -- only mentions `gg_workspace` in a comment explaining why it
deliberately avoids joining to it; no actual query gap there).

**Breaks if wrong:** landing (6) before (1)-(5) trades a clean 501 for
a raw Oracle SQL error the first time any of these four call sites
executes -- explicit ordering requirement, not just a style preference.

## File structure (target line counts)

| File | Change |
|---|---|
| `src/aryx/queries/oracle/ask_thread_select_mapping.sql` | new, ~8 lines |
| `src/aryx/queries/oracle/ask_thread_touch_channel.sql` | new, ~6 lines |
| `src/aryx/queries/oracle/sales_chat_claim_thread.sql` | new, ~12 lines |
| `src/aryx/queries/oracle/sales_chat_select_thread.sql` | new, ~8 lines |
| `sales_streamlit/chat_store.py` | +~6 lines in `claim_thread()` |
| `src/aryx/api/mcp_tokens_api.py` | -~7 lines (guard removed) |

All well under any line-count cap.

## Stack compliance

No new libraries. Pure SQL + one small branch in existing Python using
the already-established `_is_oracle_backend()` pattern.

## Risk flags

- `sales_chat_claim_thread`'s Oracle `MERGE` must be verified under an
  actual retry/replay scenario (same `thread_id` claimed twice), not
  just a fresh-insert happy path, since that's the entire reason
  Postgres uses `ON CONFLICT DO NOTHING` here.
- This audit widened once already (2 files → 4) by checking beyond the
  original single file (`ask_thread_store.py`). Before declaring
  Shay-on-Oracle fully covered and removing the guard, re-grep once
  more after these changes for any other unconditional `gg_*`/
  `aryx_sales_chat_*` query call site this pass may still have missed.
- `mcp_tokens_api.py` guard removal is the correct final step, not a
  parallel one -- explicit ordering enforced by doing it last, in its
  own commit.

## End state

New branch off latest `dev_oci` (this branch,
`fix/shay-askthread-oracle-query-overrides-2026-09-14`, created from
`bb7b48b5`), implementation in the order above, PR opened against
`dev_oci` once implemented and verified.

## Addendum (2026-09-14, post-implementation) — `sales_streamlit/mcp_service.py`'s broken `_reader` import

Recreating `aryx-api-1` with the fixes above and exercising the live
`sales_chat_bootstrap` flow surfaced a second, unrelated pre-existing
bug (confirmed identical against unmodified `dev_oci` before this
branch existed): `sales_streamlit/mcp_service.py` imported `_reader`
from `aryx.api.ask_api`, but that module never re-exported it after
the Phase 2b split moved `_reader`'s actual definition into
`aryx.api.ask_core_helpers`. Every real call to `sales_chat_bootstrap`
crashed with `cannot import name '_reader' from 'aryx.api.ask_api'`
the moment the `sales_cpq` OCI guard removal (item 6 above) let a real
request reach it. Confirmed via grep this is the *only* file importing
`_reader` from `ask_api` directly -- the many test files that also
import from `ask_api` either import unrelated names or already patch
`aryx.api.ask_core_helpers` directly, unaffected. Fixed by importing
`_reader` from its actual current module (`aryx.api.ask_core_helpers`).

## Addendum 2 (2026-09-14) — `gg_messages` missing `request_id` on Oracle

Retrying the chat flow after the above surfaced a third, separate gap:
`gg_messages` on Oracle carried over the full base shape from
Postgres's original `CREATE TABLE gg_messages`
(`migrations/0028_shay_skin.sql` -- confirmed all 19 base columns
present via `user_tab_columns`), but never got the later, separate
`ALTER TABLE ADD COLUMN request_id` from
`migrations/0033_ask_thread_messages.sql`. Whatever ported `gg_messages`
to Oracle carried over the base shape but missed that follow-up
migration.

**Fix:** `migrations_oracle/0043_gg_messages_request_id.sql` -- adds
`request_id VARCHAR2(36)` and `idx_gg_messages_thread_sequence
(thread_id, sequence_number)`, guarded the same way every other Oracle
migration in this repo is (`ORA-01430`/`ORA-01408` = already applied,
safe to re-run).

**Deliberately deferred, not bundled into this fix:** Postgres's
matching index here is a *partial unique* index
(`uq_gg_messages_thread_request_type`, `UNIQUE (thread_id, request_id,
message_type) WHERE request_id IS NOT NULL`), enforcing per-thread
request idempotency. Oracle has no `WHERE`-clause-qualified `CREATE
UNIQUE INDEX` -- Oracle's own equivalent (relying on Oracle's
composite-NULL uniqueness behavior: a row where any indexed column is
NULL is excluded from a unique index's uniqueness check) needs
verification against real data before asserting it here. Get the
column in, confirm the crash clears, decide the uniqueness-porting
question separately.

**Verified live** (not just statically): ran the actual
`oracle_migrate.apply_oracle_migrations()` against the connected
Oracle ADB instance -- confirmed `REQUEST_ID VARCHAR2(36)` and
`IDX_GG_MESSAGES_THREAD_SEQUENCE` now exist via `user_tab_columns`/
`user_ind_columns`, and confirmed the migration re-runs cleanly
(idempotent) a second time.
