# shay-api Oracle connection-pool exhaustion — recurrence (2026-09-30)

Log analyzed: `aryx-shay-api-1.log` (container log, 2026-09-22 14:24:58 →
2026-09-30 13:40:29, captured after the user reported being unable to log
in or do anything in the app).

## Problem

Starting at `2026-09-30 12:47:11` and continuing through the end of the
captured log (`13:40:29`), nearly every DB-backed `shay-api` request
started failing with `500 Internal Server Error`:

- `GET /api/v1/user-auth/profile` — 377 failures
- `GET /api/v1/workspaces/` — 118 failures
- `GET /api/v1/companies/my` — 24 failures
- `GET /api/v1/companies/{id}/invitations` — 24 failures
- `GET /api/v1/users/company/{id}/users` — 23 failures
- `POST /api/v1/user-auth/login` — 4 failures

This is why the user couldn't log in or use the app: the login/profile
path itself was one of the failing endpoints. `GET /health` kept
returning `200 OK` throughout, because it doesn't touch the database —
so the container looked "up" in Docker the whole time even though the
app was unusable. There is no self-recovery anywhere in the captured
log; it stayed broken until something external (a container restart)
reset it.

## Root Cause

Every one of the 1,140 tracebacks bottoms out in the same exception:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 20
reached, connection timed out, timeout 30.00
```

`shay-api`'s SQLAlchemy pool to the shared Oracle ADB instance
(`pool_size=10` + `max_overflow=20` = 30 connections,
`shay_backend/app/core/database.py`) was completely full. New requests
blocked for the full 30s checkout timeout and then failed. This
happened under normal, low traffic (~41 profile calls in the 10 minutes
before the first failure, not a burst) — consistent with a slow,
days-long buildup of stuck connections rather than a sudden spike.

**This is not a new bug — it is an already-diagnosed, already-planned
issue that was never actually fixed:**

1. **2026-09-14** — `docs/oci-oracle/SHAY_API_ORACLE_POOL_EXHAUSTION_PLAN_2026-09-14.md`
   root-caused this exact same error (`QueuePool limit of size 10
   overflow 20 reached`) to two factors: (a) `shay-api`'s Oracle engine
   has no per-call/statement timeout, so a single query that blocks
   server-side holds its connection forever instead of failing and
   releasing it, and (b) Aryx and Shay share **one** Oracle ADB
   instance, and Aryx's own migration runner / heavy ingestion load can
   lock tables Shay is concurrently querying. The plan proposed a fix
   and a branch, `fix/shay-api-oracle-pool-exhaustion-2026-09-14`, was
   created — but it has **zero commits**. The fix was never
   implemented.
2. **2026-09-22** — a *different*, narrower cause of the same symptom
   was found and fixed (PR #347 / commit `ff98bce8`): a
   mention-notification background task held a DB session open across
   a blocking, unbounded `smtplib` call. That fix is real and merged,
   but it only addresses that one code path — it does nothing for the
   general "no timeout on the Oracle engine" gap identified on 09-14.
3. **2026-09-30 (this incident)** — confirmed by re-reading
   `shay_backend/app/core/database.py` today: it still has
   `pool_pre_ping=True` and nothing else. No `pool_recycle`, no
   per-connection `call_timeout`. The exact gap identified on 09-14 is
   still open, and this recurrence is that same failure mode playing
   out again after enough uptime (~8 days) for connections to go bad
   one at a time until the pool was fully exhausted.

## Fixes

**Immediate (unblock):** restart `aryx-shay-api-1` — this resets the
pool to empty and was already done to get the user back into the app.
This is a workaround, not a fix; it will recur.

**Permanent (recommended, not yet applied — carried over verbatim from
the 2026-09-14 plan, which was never implemented):**

1. Add a per-connection call/statement timeout to `shay-api`'s Oracle
   engine in `shay_backend/app/core/database.py` — a SQLAlchemy
   `@event.listens_for(engine.sync_engine, "connect")` listener that
   sets `dbapi_connection.call_timeout = <ms>` on every new physical
   connection, mirroring the existing pattern in
   `aryx/store/oracle_connection_pool.py`. This makes a blocked query
   fail loudly and release its connection instead of holding it
   forever.
2. Add `pool_recycle` to both the Oracle and Postgres
   `create_async_engine(...)` calls in the same file, so long-lived
   pooled connections are proactively retired instead of relying only
   on `pool_pre_ping` at checkout time.
3. Separately (still out of scope, still worth tracking): avoid
   re-running `aryx-api`'s full Oracle migration set against the shared
   ADB instance while `shay-api` is serving live traffic, since
   repeated DDL from `aryx-api` restarts is the suspected trigger that
   puts individual `shay-api` connections into the stuck state in the
   first place.

The call_timeout value needs to be picked from `shay-api`'s real query
latency (not guessed) — same caution called out in the original plan.

## Scope: shay-api only, not aryx

This incident is specific to `shay_backend` — `aryx` (`aryx-api`) was not
affected, even though both services share the same Oracle ADB instance.

**Evidence:** the captured log is only from `aryx-shay-api-1`; a check of
`aryx-api`'s own current logs showed zero `QueuePool`/timeout errors.
That alone isn't conclusive, since `aryx-api` was rebuilt/recreated after
this incident (which wipes any pool history from before the rebuild),
but the architecture explains why it's unlikely to be hit the same way
regardless:

`shay-api` and `aryx` don't share a pooling implementation. `shay-api`
uses SQLAlchemy's `QueuePool` with only `pool_pre_ping=True` — no idle-
connection detection beyond that, and no guarantee against a connection
getting stuck checked-out forever (see Root Cause above). `aryx` uses its
own pool (`src/aryx/store/oracle_connection_pool.py`), built directly on
`oracledb.create_pool()`, with two defenses `shay-api` lacks:

1. `ping_interval=0` — pings every connection before handing it out, so
   a connection ADB silently dropped while idle is caught and replaced
   on acquire, instead of sitting in the pool as "checked-in and valid"
   until something tries to use it and hangs.
2. `getmode=POOL_GETMODE_TIMEDWAIT, wait_timeout=30000` combined with a
   `finally: self._pool.release(raw)` that always runs on
   `connection()` — a connection can't end up "checked out and never
   returned" the way the 09-14 plan describes happening to `shay-api`.

So if aryx hit the same underlying trigger (ADB silently closing an idle
connection, or a lock wait from shared-instance DDL contention), its
pool would catch and replace the bad connection on the next acquire
rather than silently accumulating stuck slots over days. That's
consistent with why only `shay-api` shows the `QueuePool limit of size
10 overflow 20 reached` failure pattern — it's the one service missing
that protection.
