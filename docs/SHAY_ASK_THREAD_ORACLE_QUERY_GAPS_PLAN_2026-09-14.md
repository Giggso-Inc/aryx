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
