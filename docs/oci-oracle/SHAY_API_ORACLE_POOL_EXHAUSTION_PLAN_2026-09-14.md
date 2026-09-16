# shay-api Oracle connection-pool exhaustion — permanent fix plan (2026-09-14)

Branch: `fix/shay-api-oracle-pool-exhaustion-2026-09-14` → `dev_oci`

## Incident

`localhost:3000/workspaces` hung on "Loading Aryx workspaces..." — the
Next.js `web` container's API proxy logs showed
`Failed to proxy http://shay-api:8000/api/v1/workspaces/ [Error: socket
hang up] { code: 'ECONNRESET' }` on every request. `shay-api`'s own
container logs showed the real error:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 20
reached, connection timed out, timeout 30.00
```

`docker restart aryx-shay-api-1` cleared it immediately (confirmed: no
new proxy errors in the 30s after restart, `/api/v1/workspaces/`
returned a normal `401` instead of hanging). That's a workaround, not a
fix — `shay-api` had been running 4 days straight; restarting it just
resets the pool to empty. This plan is the real fix so it doesn't
recur.

## Root cause

Two contributing factors, confirmed by reading
`shay_backend/app/core/database.py`:

1. **No per-call timeout on `shay-api`'s Oracle connections.**
   `get_db()`'s cleanup is correct (`async with AsyncSessionLocal() as
   session: try: yield session; finally: await session.close()` — every
   request that completes, errors, or is cleanly cancelled returns its
   connection). The engine sets `pool_pre_ping=True` but nothing bounds
   how long a single DB call inside a request is allowed to block.
   Aryx's own Oracle pool (`aryx/store/oracle_connection_pool.py`) sets
   `conn.call_timeout` explicitly for exactly this reason; `shay-api`'s
   `create_async_engine(...)` call has no equivalent. One query that
   blocks server-side (a lock wait, a stuck session) holds its
   connection **forever** instead of failing and releasing it back to
   the pool.

2. **Likely trigger: shared-instance DDL contention.** Per
   `.raven/architecture.md`, Aryx and Shay share **one** Oracle ADB
   instance (Shay's schema created via SQLAlchemy on boot, no Alembic
   on Oracle). This session repeatedly rebuilt/recreated `aryx-api-1`
   while `shay-api` kept serving live traffic against the same
   instance — each `aryx-api-1` start re-runs the *entire* Oracle
   migration set (`oracle_migrate.apply_oracle_migrations()`, ~40+
   files, idempotent via `IF NOT EXISTS`/`ORA-01430`/`ORA-01408`
   guards, but every file still executes a real DDL statement every
   time). We already observed `ORA-14411: DDL cannot be run
   concurrently with other DDLs` from two of `aryx-api`'s own workers
   colliding with each other during one such run. If one of those DDL
   statements briefly locked a table (e.g. `gg_messages`,
   `gg_threads`) that a `shay-api` request was concurrently querying,
   and `shay-api` has no timeout (per point 1), that single blocked
   query holds its connection indefinitely. Repeated over 4 days and
   several `aryx-api-1` rebuilds this session, that's enough to drain
   a 30-slot pool (`pool_size=10` + `max_overflow=20`) permanently —
   no application-level leak required, just no way for a stuck
   connection to ever come back.

## Fix

1. **Add a call/statement timeout to `shay-api`'s Oracle engine**
   (`shay_backend/app/core/database.py`) — a SQLAlchemy `"connect"`
   event listener on `engine.sync_engine` that sets
   `dbapi_connection.call_timeout = <ms>` on every new physical
   connection (mirrors `OracleConnectionWrapper.call_timeout`'s own
   pattern in `aryx/store/oracle_connection_pool.py`). A blocked query
   now fails loudly and releases its connection instead of hanging
   forever.
2. **Add `pool_recycle`** to both the Oracle and Postgres
   `create_async_engine(...)` calls in the same file — standard
   hygiene for a long-lived pool, unrelated to the timeout fix but
   cheap to add alongside it.
3. **Do not re-run the full migration set from a live, traffic-serving
   `aryx-api` restart against a shared Oracle instance.** Out of scope
   for this branch (touches `aryx.store.oracle_migrate`, a separate
   module with its own test surface) — tracked as a follow-up, not
   bundled here. Options to evaluate separately: real per-file
   "already applied" tracking (a migrations-log table) instead of
   "attempt and catch `ORA-01430`/`ORA-01408`", or running migrations
   as a one-off step outside the API container's normal startup path.

## Dependency map

**Touches:** `shay_backend/app/core/database.py` only (the engine
construction blocks for Oracle and Postgres).

**Does not touch:** `aryx.store.oracle_migrate` / the migration-runner
behavior itself (item 3 above is a separate, deliberately deferred
follow-up); anything in `src/aryx/` (this is entirely shay-api-side).

**Breaks if wrong:** setting a `call_timeout` too low would abort
genuinely slow-but-legitimate queries; needs a value comfortably above
this app's real p99 query latency, not a guess — verify against
`shay-api`'s own logs/metrics before picking a number, not just picking
something that "feels safe."

## File structure (target line counts)

| File | Change |
|---|---|
| `shay_backend/app/core/database.py` (135 lines currently) | +~15 lines: one `@event.listens_for` block for the Oracle branch, `pool_recycle=` kwarg added to both engine constructions |

Stays well under any line-count cap.

## Stack compliance

No new library — `sqlalchemy.event` is already part of the installed
SQLAlchemy dependency; `oracledb`'s `call_timeout` attribute is already
in use elsewhere in this codebase (`aryx/store/oracle_connection_pool.py`).

## Risk flags

- The `call_timeout` value needs a real number, not a placeholder —
  check `shay-api`'s actual query latency distribution (or start
  conservative, e.g. 30-60s, well above the connection-pool's own 30s
  checkout timeout, and tighten later with real data).
- This fix treats the symptom's mechanism (connections that never come
  back), not the root trigger (shared-instance DDL contention from
  `aryx-api` restarts) — item 3 is the actual root-cause fix and is
  deliberately out of scope here; flagging so it doesn't get lost.
- Changing pool/engine construction touches something imported by
  "nearly every route file" per this module's own docstring — verify
  `shay_backend`'s existing test suite (if any covers `database.py`)
  still passes after the change.

## End state

New branch off latest `dev_oci` (this branch,
`fix/shay-api-oracle-pool-exhaustion-2026-09-14`, created from
`bb7b48b5`), implementation of items 1-2 above, PR opened against
`dev_oci` once implemented and verified. Item 3 tracked as a separate
follow-up, not blocking this PR.
