# Switch `python-oracledb` from thin to thick mode — `api` and `shay-api` (2026-10-06)

Companion to `docs/oci-oracle/JSON_MERGEPATCH_OSON_V2_INCIDENT_AND_FIX_PLAN_2026-10-06.md`.
That doc's Option B (rewrite each `JSON_MERGEPATCH` call site to avoid the
bug client-side) is not being pursued as the primary fix — it was
implemented for `ActionStore`/`AdjudicationStore`, verified, then explicitly
reverted in favor of this centralized fix instead. Option B's design stays
as the documented fallback if thick mode is ever reverted.

**Scope of this doc: both `api` and `shay-api` get thick mode.** Full plan
below for each — they require materially different implementations because
of an architectural difference between the two services (`shay-api`'s
primary Oracle access is async; `python-oracledb` only supports asyncio in
thin mode, so `shay-api` needs a second, dedicated code path, not a
drop-in switch).

## Why

Oracle ADB is confirmed running **26ai**. `python-oracledb`'s thin mode is a
hand-maintained, pure-Python/Cython reimplementation of Oracle's wire
protocol — confirmed today that it cannot decode "OSON version 2," a binary
JSON encoding Oracle introduced in the 23ai/26ai generation, across every
available client version (2.5.1 installed, 4.0.2, and the latest 26.0.1, all
thin, all fail identically with `DPY-3021: OSON version 2 is not
supported`). The failing code is `oracledb`'s own `impl/base/oson.pyx`
decoder, which only recognizes two hardcoded version constants — a
client-library gap, not a server-side problem, not fixable by a `pip`
version bump.

**Thick mode delegates to Oracle's own Instant Client (OCI) libraries**,
which Oracle ships and updates in lockstep with each Database release.
Installing Instant Client 23.8 and switching to thick mode
(`oracledb.init_oracle_client()`) successfully read entities that otherwise
gave `DPY-3021` in thin mode (tested live today, though against rows already
repaired back to thin-compatible encoding by then — see "Verification"
below for the clean re-test this still needs). Thick mode is a centralized
fix: every `JSON_MERGEPATCH` call site and any future Oracle 26ai feature
thin mode hasn't caught up to yet all become safe at once.

## `api` — straightforward switch

`api`'s Oracle access (`src/aryx/store/oracle_connection_pool.py`'s
`oracledb.create_pool(...)`, used by every store in `src/aryx/store/`) is
entirely synchronous. No architectural blocker — this is a real drop-in
client-mode switch.

### A1. Install Oracle Instant Client in the `api` Dockerfile

- Download Instant Client Basic-Lite, x86_64 (`api`'s container
  architecture, confirmed). Working URL, confirmed live today:
  `https://download.oracle.com/otn_software/linux/instantclient/2380000/instantclient-basiclite-linux.x64-23.8.0.25.04.zip`.
- Extract with `unzip` in the Dockerfile `RUN` step — **not** Python's
  `zipfile` module (confirmed today: `zipfile.extractall()` does not
  preserve the package's internal symlinks, e.g.
  `libclntsh.so -> libclntsh.so.23.1`; `unzip` on Linux does, so this is a
  non-issue in a real Dockerfile `RUN unzip ...`, only an artifact of the
  ad-hoc Python extraction used for today's live test).
- Install the one confirmed missing system dependency:
  `apt-get install -y libaio1t64` (exact package name confirmed today on
  this Debian/`python:3.13-slim` base — note this differs from the
  historically common `libaio1` name, due to Debian's 64-bit `time_t`
  package rename; verify against the actual base image rather than assuming
  the name transfers).
- `ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_23_8` (or wherever placed)
  — confirmed required today: without it, `libclntsh.so`'s own dependency
  `libnnz.so` fails to resolve even when `lib_dir` is passed correctly to
  `init_oracle_client()`.

### A2. Call `init_oracle_client()` at process startup, in every worker

Add a new small module, following the same "runs at import time" pattern
`src/aryx/api/main_logging.py` already uses (imported in `main.py` with
`# noqa: F401 — runs ... setup at import time`):

```python
# src/aryx/api/main_oracle_client.py
"""Initializes python-oracledb thick mode at import time, before any DB
connection is made process-wide -- see docs/oci-oracle/
ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md.

Gated behind ARYX_ORACLE_CLIENT_MODE (default "thin") -- flip back to
"thin" (or unset) to revert instantly, no rebuild needed.

init_oracle_client() is process-wide and may be called at most once per
process -- idempotency-guarded here in case this module is imported more
than once within one process (e.g. test collection).
"""
import logging
import os

logger = logging.getLogger(__name__)
_initialized = False


def _init_thick_mode_if_configured() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True
    if os.environ.get("ARYX_ORACLE_CLIENT_MODE", "thin").strip().lower() != "thick":
        return
    import oracledb
    lib_dir = os.environ.get("ARYX_ORACLE_INSTANT_CLIENT_DIR") or os.environ.get("LD_LIBRARY_PATH")
    oracledb.init_oracle_client(lib_dir=lib_dir)
    logger.info("oracledb: thick mode initialized (lib_dir=%s)", lib_dir)


_init_thick_mode_if_configured()
```

Import it first among `src/aryx/api/main.py`'s `aryx.api.*` imports
(before `main_logging`, so it runs before anything else that could touch
the DB). `api` runs `uvicorn --workers 2` — verify uvicorn's multiprocess
model (each worker re-imports the app module fresh vs. pre-fork-and-inherit)
before assuming the module-level call covers every worker; either way the
idempotency guard above makes it safe regardless of which model it turns
out to be.

### A3. Verify connection pooling still behaves correctly

`oracle_connection_pool.py`'s `oracledb.create_pool(...)` — `python-oracledb`
notes some pool behaviors differ between thin and thick mode (thick mode can
delegate pooling to Oracle's own native session pool rather than the
pure-Python one). Needs a real live test against `dev_oci`: acquire several
connections concurrently, confirm `POOL_GETMODE_TIMEDWAIT` and
`ping_interval=0` (both relied on today, per that file's own comments) still
behave the same way.

## `shay-api` — needs a second, dedicated code path

### Why a drop-in switch is not possible here

`shay-api` connects to Oracle via SQLAlchemy's `create_async_engine(...)`
using the `oracle+oracledb_async` dialect
(`shay_backend/app/core/database.py:93-106`). `python-oracledb`'s async
connection path forces thin mode unconditionally — confirmed directly from
the library's own source, not an assumption:

```python
# oracledb/connection.py:2204, inside Connection._connect() (the asyncio path)
# mandate that thin mode is required; with asyncio, only thin mode is
# supported and only one thread is executing, so the manager can be
# manipulated directly
driver_mode.manager.thin_mode = True
```

This is hardcoded in the library, not a config flag. `shay-api`'s main
engine genuinely cannot run in thick mode as-is.

**A full rewrite off async Oracle access was considered and rejected as
impractical for this change:** `AsyncSession`/`get_db` (the async session
dependency this hardcodes thin mode) is used across **405 files** in
`shay_backend/app` (confirmed by grep). Converting all of that to a sync
engine wrapped in `asyncio.to_thread(...)` is a legitimate architecture
change but is its own multi-week project, not something to bundle into this
migration.

### The real plan: a second, dedicated sync/thick engine alongside the existing async/thin one

`shay-api` already has `get_sync_engine()`
(`shay_backend/app/core/database_sync.py`), today used only for migrations,
built on the plain **sync** `oracle+oracledb` dialect (not `_async`) — this
one is thick-mode-capable, same mechanism as `api`'s pool. This becomes the
thick-mode path for `shay-api`, run alongside the existing async engine,
not replacing it:

### S1. Install Oracle Instant Client in the `shay-api` Dockerfile

Same as A1, applied to `shay_backend/Dockerfile` (also x86_64, confirmed).

### S2. Initialize thick mode at `shay-api` startup

Same `init_oracle_client()` pattern as `api`'s `main_oracle_client.py`
(A2), adapted to `shay-api`'s own startup module (`shay_backend/main.py`),
same `ARYX_ORACLE_CLIENT_MODE` env var so both services share one on/off
switch.

### S3. Stand up a long-lived sync/thick engine + session factory, separate from the main async one

Extend `database_sync.py`'s connection-string logic into a new, persistent
(not per-call) sync engine + `sessionmaker`, distinct from both
`get_sync_engine()` (keep that one migrations-only, unchanged) and the main
async `engine`/`async_sessionmaker` in `database.py` (unchanged). This new
engine is what thick mode actually runs through.

### S4. Route Oracle writes through the sync/thick engine, wrapped for async callers

Every DB call made through the new sync/thick engine needs
`asyncio.to_thread(...)` (or `run_in_executor`) at the call site, since
`shay-api`'s route handlers are `async def` and a sync DB call would
otherwise block the event loop — the standard pattern for running a
sync-only driver from async code.

**Which calls move to the new engine is the one real scoping decision
here**, and it should be informed by what's already been verified, not
re-litigated from scratch:

- `AryxAskThreadStore`'s three `JSON_MERGEPATCH` call sites
  (`ask_thread_update_message_oracle.sql`, `ask_thread_update_request_status.sql`,
  `ask_thread_ensure_channel.sql`) plus `shay_workspace_bridge.py`'s
  `sync_state` merge were tested live today with the exact production SQL
  against real rows (`aryx_shay_workspace_map.sync_state`,
  `gg_messages.message_metadata` — including a large, deeply-nested real
  document, not just a trivial case — and `gg_channels.channel_settings`).
  **All four read back cleanly in thin mode, no `DPY-3021`.** They write to
  `CLOB` columns, not native `JSON` columns — OSON v2 is specific to
  Oracle's native-`JSON` binary storage, and a `CLOB` column never touches
  it. These four are not at risk today, confirmed, not inferred.
- Given that, moving these specific four to the sync/thick engine is not
  required for correctness — but doing it anyway is cheap (four call sites,
  already-known SQL, already-known table/column shapes) and makes `shay-api`
  genuinely thick-mode-protected for its only known `JSON_MERGEPATCH` usage,
  rather than leaving thick mode installed-but-unused. Recommended: migrate
  these four as the initial (and for now, complete) set of call sites on the
  new engine — it validates the whole sync/thick/`to_thread` mechanism end
  to end on real, already-understood code, with no open behavioral question
  left over.
- Any Oracle write discovered later that touches a native `JSON`-typed
  column (none known in `shay-api`'s schema today) is a future candidate for
  the same engine — this is the reason to build the mechanism now rather
  than only patch reactively next time.

### S5. RESOLVED — tested live, 2026-10-06: thin and thick mode do NOT coexist in one process. S3/S4 are not viable as designed.

Built S1/S2 (Instant Client in `shay_backend/Dockerfile`, `init_thick_mode_if_configured()`
called at `shay-api` startup) and set `ARYX_ORACLE_CLIENT_MODE=thick` as a
trial default to run this test for real, not hypothetically. Result:
**`shay-api` crash-looped immediately on startup:**

```
sqlalchemy.exc.ProgrammingError: (oracledb.exceptions.ProgrammingError)
DPY-2019: python-oracledb thick mode cannot be used because a thin mode
connection has already been created
ERROR:    Application startup failed. Exiting.
```

`init_thick_mode_if_configured()` locked the process into thick mode at
startup; the main async engine's first connection then requested thin mode
(`driver_mode.get_manager(requested_thin_mode=True)`, hardcoded for every
async connect per "Why a drop-in switch is not possible here" above) and
`oracledb`'s own `driver_mode` manager raised rather than allow it. This is
not an ordering problem (initializing thick mode *after* the async engine's
first connection would fail the same way, symmetrically — thin would
already be locked in by then) — **`driver_mode` is a one-shot,
whole-process lock, not a per-connection or per-engine setting.** A single
Python process can run python-oracledb in exactly one mode, decided by
whichever connection (sync or async) happens first, for the rest of that
process's life.

**This rules out S3/S4 as designed** — a dedicated sync/thick engine cannot
share a process with `shay-api`'s main async/thin engine, full stop. Real
remaining options for `shay-api`, in order of how much they actually cost:

1. **Do nothing (recommended).** The four call sites this was all for are
   already confirmed safe on thin mode (`CLOB` columns, not native `JSON` —
   see above). There is no live bug in `shay-api` to fix. This was being
   built for defense-in-depth against a hypothetical future native-`JSON`
   column, not a known problem.
2. **Option B** (client-side merge, no `JSON_MERGEPATCH`, no thick mode at
   all) applied to the same four call sites — already designed, already
   proven to work when implemented and reverted earlier today for
   `ActionStore`/`AdjudicationStore` on `api`. Protects against a future
   native-`JSON` column on these four specific sites without touching
   client mode at all. Cheapest real protection if defense-in-depth is
   still wanted.
3. **A genuinely separate process** for anything that needs thick mode in
   `shay-api` (a small subprocess, a separate worker/service, or a call out
   to `api` — which is already thick — instead of touching Oracle directly
   from `shay-api`). Only worth it if a real native-`JSON` column shows up
   in `shay-api`'s schema later; not justified today for four already-safe
   `CLOB` call sites.

**Current state of the repo as of this finding:** Instant Client is
installed in `shay_backend/Dockerfile` and `init_thick_mode_if_configured()`
exists (`shay_backend/app/core/oracle_client.py`) but is **not** wired to
any default — `ARYX_ORACLE_CLIENT_MODE` is deliberately left unset for
`shay-api` in `docker-compose-oci.yml` (thin, the only mode that actually
works for it today). The function exists and is harmless at rest; do not
set the env var for `shay-api` without implementing option 2 or 3 above
first, or it will crash-loop again exactly as it did during this test.

### S6. IMPLEMENTED, 2026-10-06 — option 3 (convert to sync), done and verified live

The user asked for thick mode on `shay-api` specifically (not "leave it on
thin, it's safe enough" — option 1 above), so option 3 was built: converted
`shay-api`'s Oracle access from `create_async_engine`/`AsyncSession` to a
plain synchronous SQLAlchemy engine, the same architecture `api` already
uses, wrapped so none of the ~405 files calling `AsyncSession`/`get_db()`
needed to change.

**Why this was tractable, not a 405-file rewrite**: an Explore pass over
`shay_backend/app` first (before writing any code) found `get_db()`'s own
body only depends on one symbol, `AsyncSessionLocal`:
```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```
Replacing what `AsyncSessionLocal` constructs — not `get_db()` itself, not
any of the 284 `Depends(get_db)` call sites, not the ~16 call sites that
construct `AsyncSessionLocal()` directly (background tasks, the
daily-summary APScheduler job) — was enough. The actual API surface in use
across the whole codebase is narrow (`execute`/`commit`/`rollback`/`flush`/
`refresh`/`add`/`add_all`/`delete`, nothing exotic) and never holds one
session across concurrent `await` points, which is exactly what makes a
thread-wrapped sync `Session` safe here.

**Changes**:
- `shay_backend/app/core/async_session_shim.py` (new) — `AsyncSessionShim`
  wraps a sync `Session`; `execute`/`commit`/`rollback`/`flush`/`refresh`/
  `close` run via `asyncio.to_thread(...)`; `add`/`add_all`/`delete` stay
  plain sync passthroughs (no I/O, never awaited at any real call site
  either). `make_async_session_local(sessionmaker)` returns a zero-arg
  factory matching `async_sessionmaker`'s own callable shape.
- `shay_backend/app/core/database_sync.py` — factored the existing Oracle
  sync-URL-building logic (previously only inside `get_sync_engine()`) out
  into `build_sync_oracle_engine(pool_recycle=None)`, now shared by both
  the migrations-only `get_sync_engine()` and `database.py`'s new
  persistent engine.
- `shay_backend/app/core/database.py` — Oracle branch only (Postgres/
  SQLite untouched): `engine = build_sync_oracle_engine(pool_recycle=...)`
  instead of `create_async_engine(...)`; `AsyncSessionLocal` built via
  `make_async_session_local(sessionmaker(bind=engine, ...))` for Oracle;
  `init_db()`/`close_db()` branch on `_is_oracle` to use the sync engine's
  plain (non-awaited) API instead of the async one.
- `shay_backend/app/core/database_optimizations.py` — added
  `_oracle_repair_partial_unique_indexes_sync()`, a non-async copy of the
  existing repair function, for `init_db()`'s new sync branch (the original
  async version stays, still re-exported and tested independently).
- `docker-compose-oci.yml` — `ARYX_ORACLE_CLIENT_MODE=${ARYX_ORACLE_CLIENT_MODE:-thick}`
  re-added to `shay-api`'s environment (removed during the S5 crash-loop
  finding, safe again now).
- No test changes needed: `tests/test_database_characterization.py`'s
  `TestGetDb` patches `AsyncSessionLocal` directly with its own mock
  context manager — it never exercises the real implementation, so it's
  unaffected by what `AsyncSessionLocal` actually constructs underneath.

**Verified live, 2026-10-06**:
- Rebuilt `shay-api`, recreated the container with `ARYX_ORACLE_CLIENT_MODE`
  unset (thin) first — confirmed the sync-engine conversion itself works
  independent of thick mode: `init_db()` ran successfully against real
  Oracle (`✅ Database tables created successfully`, `Oracle schema
  initialised via init_db()`), full startup sequence completed (socket
  service, APScheduler daily-summary job registered), health check passed.
- Set `ARYX_ORACLE_CLIENT_MODE=thick`, recreated again — **no crash this
  time** (previously: immediate `DPY-2019` crash-loop). Container reached
  `healthy`.
- Confirmed thick mode is genuinely active in the live server process (not
  just "didn't crash"): `grep -c libclntsh /proc/1/maps` inside the
  container returned `11` — Oracle's Instant Client library is loaded into
  the actual running uvicorn process.
- Exercised a real DB-touching route end-to-end: `POST /api/v1/user-auth/login`
  with a nonexistent account returned `404 {"message":"Account not
  found"}` — a genuine Oracle SELECT ran through the new sync/thick engine
  and returned a real result. This is the same login/profile path that
  broke hardest in the 2026-09-30 pool-exhaustion incident — a meaningful
  canary, not an arbitrary endpoint.
- Checked logs for the whole boot + this request: zero `DPY-`/`DPI-`
  errors. The only ERROR line present (`Failed to connect to socket
  server: module aiohttp has no attribute ClientWSTimeout`) is a
  pre-existing, unrelated `aiohttp`/socket.io version issue, confirmed
  present before any of today's changes too.

**Not yet exercised** (reasonable follow-ups, not blockers): an actual
write/commit through the new engine (login-not-found only exercised a read);
the daily-summary scheduler's direct-session path firing for real (next
run is 15 minutes after boot, not forced during this test); the full
`shay_backend` pytest suite run end-to-end in this exact container.

## Rollout safety (both services)

Gate behind `ARYX_ORACLE_CLIENT_MODE=thick` (default `thin` until proven) —
a fast, single-flag revert path matters more here than for a normal code
change, since this touches every Oracle-writing service at once. Remove the
flag once thick mode has run in `dev_oci` for a real stretch without
incident.

## CI / any other environment that connects to real Oracle

Whatever runs the live-integration-style tests (e.g.
`tests/cpq_ingestion/test_csv_land_integration.py`, which already branches
on `ARYX_DB_BACKEND`) needs the same Instant Client + `libaio1t64` + init
call available, or those tests start failing on a missing-client-library
error unrelated to the code under test.

## Explicitly not in this change

- `ActionStore.set_attribute()` / `AdjudicationStore.merge_entities_of()`
  (the two `JSON_MERGEPATCH` call sites on `aryx_entity.attributes`, the one
  column confirmed actually affected by OSON v2) are left as-is — thick
  mode is expected to make them safe without touching their SQL. Option B's
  already-written, already-proven fix for these two is the fallback if
  thick mode is reverted.
- The production-wide sweep for already-corrupted `aryx_entity` rows (Step 4
  in the incident doc) — unaffected by client mode, separate follow-up.
- The OCI Function image (`functions/aryx-ingest-fn`) — its actual Oracle
  usage is unverified (`fn_handler.py`/`fn_handler_dispatch.py` import no
  `aryx.store.*` module at top level; whether the ingestion pipeline it
  dispatches into reaches the DB needs checking). It's also **ARM64**
  (A1.Flex), needing a different Instant Client download than `api`/
  `shay-api`'s x86_64, and is the most size/cold-start-sensitive of the
  three. Don't add Instant Client here until its Oracle usage is confirmed.
- Every other Aryx entry point that talks to Oracle directly stays on thin
  mode and is therefore still exposed to the OSON v2 gap on read: confirmed,
  the CLI/CSV-BML ingestion path (`src/aryx/csv_bml_ingestion/db.py`, which
  connects to Oracle ADB directly under `ARYX_DB_BACKEND=oci`) does not
  import `aryx.api.main_oracle_client` or call `oracledb.init_oracle_client()`
  itself (confirmed by grepping both across the repo — only
  `src/aryx/api/main.py` and `shay_backend/main.py` do). If it reads a row
  that later gets written via `JSON_MERGEPATCH` from a thick-mode process,
  it will still hit `DPY-3021`. (`sales-ui`-related code found while
  checking this, e.g. `src/aryx/api/ask_handle/ask_handle_approval.py`, is
  served by `api` itself, not a separate process — already covered by A1-A3
  above; there is no standalone `sales-ui` backend in this repo.) Not
  addressed here; call this out explicitly in the PR so reviewers don't
  assume the whole Oracle surface is covered.
- `shay-api`'s conversion off async Oracle access is DONE (see S6 below) —
  but scoped to Oracle only, via `AsyncSessionShim`, not the full 405-file
  rewrite to native sync calls that was originally scoped out and rejected.
  The dual-engine approach (S3/S4) that this bullet used to describe as
  "the actual plan" was itself abandoned after S5's live crash; S6 is what
  actually shipped.

## Verification

- **DONE, 2026-10-06, `api`:** the clean, from-scratch reproduction.
  `ARYX_ORACLE_CLIENT_MODE=thick` set, thick mode confirmed initialized
  (`thin mode: False`, client version `(23, 8, 0, 25, 4)`). Applied a fresh,
  no-op `JSON_MERGEPATCH` directly to `aryx_entity.attributes` on a live
  entity (`id=3012529`) -- the exact mechanism that produced OSON v2 and
  corrupted the original 49 rows -- then immediately read the same row back
  through the thick-mode client: `['commerce', 'customer_header',
  'oumapping']`, no `DPY-3021`, no error. This is a genuine from-scratch
  repro (not a read of already-repaired data, unlike the earlier same-day
  test), closing out this verification item for `api`. Also confirmed in
  the same session: 8 concurrent threads against a pool capped at
  `max_size=5` all succeeded (`POOL_GETMODE_TIMEDWAIT` queuing works
  correctly under thick mode) -- closes the "A3" pooling-verification item
  too.
- **DONE, 2026-10-06, `api`:** the startup-safety fallback also verified
  live, not just by code review -- with `libaio.so.1` deliberately still
  missing (before that Dockerfile fix was added), `init_oracle_client()`
  raised `DPI-1047` and the process correctly logged the failure (both
  plain logging and a `raven_log` `ARYX_ORACLE_THICK_MODE_INIT_FAILED`
  event) and fell back to thin mode instead of crashing -- confirms the
  fallback added in response to "what will be the impact" actually works,
  not just that it compiles.
- `shay-api`'s S5 coexistence test (thin async + thick sync, same process)
  — still open, not yet run.
- Full `tests/` suite for both services, paying particular attention to
  anything mocking `oracledb`/cursor behavior that might assume
  thin-mode-specific error classes or timing.
- Live smoke test against `dev_oci`: run the exact same Ask flow used
  throughout today's incident investigation (workspace 1126, "quote for APX
  Next") end to end through both `api` and `shay-api`, confirm no
  `DPY-3021` anywhere in the logs — still open for `shay-api`; `api` has
  not yet had `ARYX_ORACLE_CLIENT_MODE=thick` set as its running default
  (tests above were done via an ad-hoc in-process override, not the
  container's actual env config).
- **DONE, 2026-10-06, `api`:** `ARYX_ORACLE_CLIENT_MODE=thick` is now the
  actual default in `docker-compose-oci.yml` (defaultable to `thin` via
  `${ARYX_ORACLE_CLIENT_MODE:-thick}` for instant rollback). Recreated the
  container: both `--workers 2` processes logged
  `oracle.thick_mode.initialized` independently (confirms the per-worker
  re-import model assumed in "A2" is correct), Oracle migrations ran clean
  (`oracle_migrate: skipped 51 already-applied file(s)`, no errors), and a
  live `POST /ask` for workspace 1126 ("I want a quote for APX Next")
  anchored the product and asked for the destination country exactly as
  expected, with zero `DPY-3021`/`DPI-10xx` anywhere in the logs for that
  request. `api`'s thick-mode migration is complete and running.
