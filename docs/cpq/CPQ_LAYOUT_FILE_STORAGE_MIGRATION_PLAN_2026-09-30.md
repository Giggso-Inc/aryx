# CPQ Layout File Storage Migration Plan — 2026-09-30

## 1. Problem

`config_layouts/` is a 5-file folder baked into the Docker image
(`Config Layout APX Next.txt`, `Config Layout APXNext.txt`, `Config
Layout AstroApx.txt`, `ConfigLayout_SVX.txt`, `manifest.json`) that
`LocalDirLayoutFileSource` (`src/aryx/cpq/layout_source.py`) reads at
runtime to drive CPQ summary attribute visibility/ordering and
rule-conflict ranking. New catalogs, or updated layout exports for
existing ones, require editing this folder and rebuilding/redeploying
the image — a hardcoded, operator-only path with no self-service story.

**Goal:** when a `.txt` or `.json` layout-export file is uploaded (same
upload surface `cpq_ingestion` already hooks into), store its content
in Oracle ADB, keyed by workspace and catalog, and read it back at
runtime through the *same* `LayoutFileSource` abstraction the engine
already consumes — no changes to `engine.py`, `components.py`,
`display_order.py`, or the ~20 API call sites that use them. Once this
is live and verified, delete `config_layouts/` from the repo/image
entirely.

## 2. Current state (verified against the live code)

- `LayoutFileSource` is a `Protocol` (one method: `get(catalog_name) ->
  str | None`) with a single implementation today,
  `LocalDirLayoutFileSource`. Its own module docstring says it
  deliberately "mirrors the same shape `src/aryx/broker/secrets.py`
  already uses for secrets... room for a lazy-import cloud backend
  later without touching any caller" — this migration is exactly the
  seam it was built for.
- Instantiated once at process start
  (`src/aryx/cpq/engine_caches.py`: `_DEFAULT_LAYOUT_FILE_SOURCE`),
  then consulted per `(workspace_id, catalog_prefix)` and cached for
  the process lifetime in `_LAYOUT_COMPONENTS_CACHE`.
  `manifest.json` maps `catalog_prefix -> filename` explicitly; catalogs
  not listed fall through to fuzzy substring matching against `.txt`
  filenames in the directory.
- Content is plain JSON text despite the `.txt` extension. Parsed via
  `json.loads`, gated on `status == "Active"`, then walked for every
  node carrying `resourceAttributeVarName`.
- **`.txt` is not currently an accepted upload extension anywhere** —
  `file_ingest_limits.py`'s `_DATA_EXTS = {".json", ".csv", ".xml",
  ".xlsx"}` has no `.txt`; a `.txt` upload today 400s with
  `"unsupported type .txt"`. `.json` is already accepted, but today
  every `.json` upload is treated as *catalog data* to run through the
  normal ingest pipeline, not as a layout-export file.
- `cpq_ingestion_pipeline_active(filename)` (`routing.py`) is a single
  `(ARYX_INGEST_FILE_TYPE, ARYX_INGEST_PIPELINE)` gate keyed on one file
  extension (today: `xml`). It is not, by itself, the right switch to
  reuse unmodified for layout files — see §4.2.

## 3. Storage backend decision: Oracle ADB (CLOB) vs. OCI Object Storage bucket

| | Oracle ADB (CLOB) | OCI Object Storage (bucket) |
|---|---|---|
| Existing prior art in this codebase | Extensive: `src/aryx/store/oracle_clob.py` (bind-size/MERGE-safety helpers, already solved a class of production bugs), 11+ migrations already store JSON payloads in CLOB columns, `discovery_store.py` is a directly analogous workspace-scoped keyed-content store | **None.** `oci_client.py` has no `ObjectStorageClient` factory; the only place bucket names are even read is a pass-through into an OCI Function's env config. `connectors/oci_doc.py` explicitly punts on this ("files over ~15MB must use Object Storage instead" — and that path was never built) |
| New code required | A new table + a ~50-line `LayoutFileSource` implementation reusing `oracle_clob.py`'s bind helpers | A new SDK client, auth wiring (instance principal or config file), retry/error handling, and a first-ever integration test — all from scratch |
| Read latency for this workload | One CLOB read on the same connection pool every other per-request Oracle query already uses — no extra network hop, no extra auth handshake. Result is cached process-lifetime per `(workspace_id, catalog_prefix)` after first read, so this only matters on cache miss | A separate HTTPS round trip to the Object Storage endpoint, with its own TLS handshake and request-signing overhead, on top of whatever DB work already happens in the same request. For a KB–low-MB text file, this is strictly slower and adds a new failure mode |
| Fits the data | Content is plain JSON text (not binary) — CLOB is the natural, already-proven fit. The `discovery_store_codec.py` gzip+base64 wrapper exists for *binary* payloads embedded in a JSON column; not needed here since the layout content already *is* the JSON | Buckets are the right tool for large binary blobs (PDFs, images, big XLSX/XML exports) — which is exactly what `aryx-doc-output`/`aryx-rdf-exports` are reserved for. Layout exports (a few hundred KB–low MB of JSON) don't hit that scale |
| Operational surface added | Zero new services; same pool, same backup/restore/HA story ADB already has | A new service dependency, a new bucket to provision/secure/monitor, new IAM policy surface |

**Decision: Oracle ADB, CLOB column, following the `discovery_store.py`
pattern exactly (workspace-scoped rows, `oracle_clob.py` bind
helpers).** It reuses fully-hardened code, adds no new service
dependency, and is faster for this specific workload (small JSON text,
already cached at the application layer). Object Storage would only
win if these files were large and binary, or needed to be directly
browsable/downloadable outside the app — neither applies here. If a
future catalog's layout export ever grows to genuinely large-binary
territory, that's a re-evaluation trigger, not a reason to build both
paths now.

## 4. Target architecture

### 4.1 Schema

New migration, one file per existing pattern
(`src/aryx/store/migrations/00NN_cpq_layout_files.sql` +
`migrations_oracle/00NN_cpq_layout_files.sql`), mirroring
`0033_discovery.sql`'s idiom:

```sql
-- Oracle ADB version
BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_cpq_layout_file (
    layout_id      VARCHAR2(64)              NOT NULL,
    workspace_id   NUMBER(10)                NOT NULL,
    catalog_prefix VARCHAR2(256)              NOT NULL,
    filename       VARCHAR2(256)              NOT NULL,
    content_clob   CLOB                       NOT NULL,
    status         VARCHAR2(32)  DEFAULT ''active'' NOT NULL,
    uploaded_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_aryx_cpq_layout_file PRIMARY KEY (layout_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE UNIQUE INDEX idx_aryx_cpq_layout_ws_catalog
    ON aryx_cpq_layout_file (workspace_id, catalog_prefix)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/
```

- One row per `(workspace_id, catalog_prefix)` — a re-upload for the
  same catalog **replaces** the row (upsert), matching the "last
  export wins" semantics `manifest.json` already implies today. No
  versioning/history in v1 — flagged as an open question in §7, not
  blocking.
- `status` mirrors the existing in-content `"status": "Active"` gate,
  kept as a real column so a deactivated layout can be hidden without
  deleting the row (audit trail).
- No gzip/base64 wrapping needed (unlike `discovery_store_codec.py`,
  which exists for *binary* payloads inside a JSON column) — the
  content already is JSON text, stored directly in `content_clob`.

### 4.2 Upload flow

Two real changes needed, not just wiring:

1. **`file_ingest_limits.py`**: add `.txt` to `_DATA_EXTS` (or a new
   `_LAYOUT_EXTS = {".txt", ".json"}` set, kept distinct so it's clear
   these aren't "catalog data" extensions).
2. **A distinct routing decision from the XML path.** Reusing
   `cpq_ingestion_pipeline_active()` unmodified is wrong: that function
   gates on a *single* configured extension
   (`ARYX_INGEST_FILE_TYPE=xml` today), and a layout `.json`/`.txt`
   upload has a completely different downstream purpose (store raw
   content for later retrieval, not parse into entities/CSVs). Add a
   sibling check in `cpq_ingestion/routing.py`:

   ```python
   _LAYOUT_UPLOAD_SUFFIXES = frozenset({"txt", "json"})

   def cpq_layout_upload_active(filename: str) -> bool:
       """True when `filename` should be stored as a CPQ layout file
       instead of run through the normal ingest pipeline. Gated on the
       same ARYX_INGEST_PIPELINE=cpq_ingestion master switch as the XML
       raw-graph path, but keyed on its own suffix set -- independent of
       ARYX_INGEST_FILE_TYPE, which stays XML-specific."""
       settings = get_cpq_ingestion_settings()
       if settings.ingest_pipeline.strip().lower() != PIPELINE_CPQ_INGESTION:
           return False
       suffix = Path(filename).suffix.lower().lstrip(".")
       return suffix in _LAYOUT_UPLOAD_SUFFIXES
   ```

   At the `file_ingest_run.py` call site: check
   `cpq_layout_upload_active(filename)` **before** the existing
   `cpq_ingestion_pipeline_active(filename)` check. If true, call a new
   `store_layout_file(data, filename, workspace_id, catalog_prefix)`
   (in a new `src/aryx/cpq_ingestion/layout_store.py`, parallel to
   `raw_graph/store.py`) and **skip** the normal CSV/entity ingest path
   entirely for that file — a layout export is not catalog data and was
   never accepted by the FK-detection/type-classification path anyway.
   Same best-effort-but-visible-failure posture as the raw-graph write
   (log + continue, don't fail the whole batch upload over one bad
   layout file) — but unlike the raw-graph write, this file's *entire*
   purpose in this upload is the store write, so a failure here should
   surface in the job's result summary, not be silently swallowed.
3. **`catalog_prefix` at upload time.** The current fuzzy-match system
   exists because layout files were never uploaded with an explicit
   catalog association — the filename was the only signal. Now that
   this is a real upload, require an explicit `catalog_prefix` (a query
   param or multipart field on the ingest request), removing the need
   to guess. Keep `LocalDirLayoutFileSource`'s fuzzy-match logic
   available as a fallback path inside the new store implementation
   only (see §4.3) for the migration window, not as the primary
   mechanism going forward.

### 4.3 `OracleLayoutFileSource`

**DECIDED (2026-09-30): `workspace_id` is an explicit second parameter
on `LayoutFileSource.get()`, not a factory.** Tracing the actual call
chain shows this is a much smaller change than it first looked:
`load_layout_display_order(workspace_id, catalog_prefix, ...)` and
`_load_layout_full_order(workspace_id, catalog_prefix, ...)`
(`display_order.py`) **already take `workspace_id`** and already pass
it to `engine._load_layout_components(workspace_id, catalog_prefix,
layout_source)` — and every one of the ~20 API call sites already
passes `req.workspace_id`/`workspace_id` into those two functions
today. The only place `workspace_id` is currently in scope but *not*
forwarded is one line:
`src/aryx/cpq/layout_and_join_data/components.py:63`:

```python
text = source.get(catalog_prefix)          # current
text = source.get(catalog_prefix, workspace_id)   # after this change
```

So the real edit surface is exactly four spots, nothing upstream of
them:

1. `LayoutFileSource` Protocol: `get(self, catalog_name: str,
   workspace_id: int) -> str | None`.
2. `LocalDirLayoutFileSource.get()`: accepts `workspace_id` and ignores
   it (local files were never workspace-scoped) — kept only for the
   migration window per §5, deleted in Phase 5.
3. New `OracleLayoutFileSource.get()` (below): uses it in the `WHERE`
   clause — this is the whole point.
4. `components.py:63`: forward the parameter it already has.

```python
class OracleLayoutFileSource:
    """Reads layout files from aryx_cpq_layout_file (Oracle ADB CLOB),
    keyed by (workspace_id, catalog_prefix). Same Protocol as
    LocalDirLayoutFileSource -- callers pass workspace_id explicitly,
    so a single process-wide instance (no per-workspace factory) is
    enough; the isolation guarantee lives in the WHERE clause, not in
    which instance you're holding."""

    def __init__(self, dsn: str) -> None:
        self._pool = get_pool(dsn)  # same shared pool as everything else

    def get(self, catalog_name: str, workspace_id: int) -> str | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                load("select_cpq_layout_file"),
                (workspace_id, catalog_name),
            )
            row = cur.fetchone()
        return row[0] if row else None
```

`_DEFAULT_LAYOUT_FILE_SOURCE` in `engine_caches.py` stays a single
process-wide singleton (no factory-per-workspace complexity needed) —
`OracleLayoutFileSource` itself carries no workspace state; isolation
is enforced per-call by the SQL `WHERE workspace_id = :ws` binding,
the same pattern `discovery_store.get()` already uses.

**DECIDED (2026-09-30): the backend switch is a combination of two env
vars, not a standalone new one** — `ARYX_CPQ_LAYOUT_SOURCE` alone is
never sufficient; it only takes effect when `ARYX_INGEST_PIPELINE=
cpq_ingestion` is *also* set, the same master switch that already
gates every other `cpq_ingestion` feature (the XML raw-graph write,
and now the layout-file upload routing in §4.2). This mirrors the
existing nesting pattern in this package exactly:
`ARYX_CPQ_RAW_GRAPH_ENABLED` is a fine-grained flag that only matters
once `cpq_ingestion_pipeline_active()` has already said yes to the
outer switch — `ARYX_CPQ_LAYOUT_SOURCE` is that same shape, one level
up (read-path backend selection instead of a feature toggle):

```python
# aryx/cpq_ingestion/config.py — new field on CpqIngestionSettings
cpq_layout_source: str = Field(
    default="local",
    description=(
        "Which LayoutFileSource backend engine_caches.py wires in: "
        "'local' (LocalDirLayoutFileSource, config_layouts/ on disk) or "
        "'oracle' (OracleLayoutFileSource, aryx_cpq_layout_file table). "
        "Only takes effect when ARYX_INGEST_PIPELINE=cpq_ingestion is "
        "also set -- same master switch as every other cpq_ingestion "
        "feature. Env var: ARYX_CPQ_LAYOUT_SOURCE."
    ),
)
```

```python
# aryx/cpq/engine_caches.py
def _resolve_layout_file_source() -> LayoutFileSource:
    settings = get_cpq_ingestion_settings()
    use_oracle = (
        settings.ingest_pipeline.strip().lower() == PIPELINE_CPQ_INGESTION
        and settings.cpq_layout_source.strip().lower() == "oracle"
    )
    if use_oracle:
        return OracleLayoutFileSource(dsn=get_settings().effective_dsn())
    return LocalDirLayoutFileSource()

_DEFAULT_LAYOUT_FILE_SOURCE: LayoutFileSource = _resolve_layout_file_source()
```

Practical effect: setting `ARYX_CPQ_LAYOUT_SOURCE=oracle` without also
setting `ARYX_INGEST_PIPELINE=cpq_ingestion` silently stays on the
local path — deliberately, matching how `ARYX_CPQ_RAW_GRAPH_ENABLED=
true` alone (without the outer switch) does nothing today. This keeps
one on/off story for the whole feature area during rollout, instead of
two independently-settable flags that could disagree.

## 5. Migration / cutover steps

1. **Phase 1 — build, no behavior change. DONE (2026-09-30).** Migration
   files (`0046_cpq_layout_files.sql`, both backends), `select_cpq_
   layout_file.sql`/`upsert_cpq_layout_file.sql` (+ Oracle MERGE
   override, following `upsert_ontology_type.sql`'s proven pattern for
   a bound VARCHAR2 alongside a force-CLOB-coerced column),
   `OracleLayoutFileSource` (`layout_source.py`), `workspace_id` threaded
   through the Protocol + the one real call site it was missing
   (`components.py:63`), `_resolve_layout_file_source()`'s combined-flag
   switch (`engine_caches.py`), `cpq_layout_upload_active()`
   (`routing.py`), `store_layout_file()`/`catalog_prefix_from_filename()`
   (new `cpq_ingestion/layout_store.py`), `.txt` added to accepted
   upload extensions, and the `_run_files()` wiring that pulls layout
   uploads out of the batch before both the datasource-registration
   loop and the `_DATA_EXTS`/`_DOC_EXTS` split. `ARYX_CPQ_LAYOUT_SOURCE`
   defaults to `local` — nothing changes for existing traffic.

   27 new unit tests across 5 files (`test_cpq_layout_visibility_
   order.py`'s `OracleLayoutFileSource` section, `test_cpq_engine_
   caches_layout_source_resolution_2026_09_30.py`'s combined-flag
   matrix, `cpq_ingestion/test_layout_store.py`, `cpq_ingestion/
   test_routing.py`'s new `cpq_layout_upload_active` section,
   `test_cpq_layout_upload_extension_and_dispatch_2026_09_30.py`'s
   `_run_files` dispatch test), all passing. Targeted regression
   (`test_cpq_layout_visibility_order.py` + `cpq_ingestion/` +
   `file_ingest_size_limits` suites — the actual blast radius): only
   the same 6 pre-existing, environment-specific failures (an Oracle
   client `tnsnames.ora` config gap in this dev sandbox, confirmed via
   `git stash` to predate this branch) — zero regressions caused by
   this change. Full-suite run also completed clean of new failures.

   **Live-validated against the real dev_oci Oracle ADB** (not just
   mocked): applied `0046_cpq_layout_files.sql` via `oracle_migrate.py`
   inside the running `aryx-api-1` container (`blocks=2`, clean);
   rebuilt/recreated the container with all Phase 1 code; then, against
   the live database: stored a layout file, read it back byte-for-byte,
   confirmed a different `workspace_id` correctly gets `None` (with the
   exact isolation warning log firing) rather than the other workspace's
   content, and confirmed a re-upload for the same `(workspace_id,
   catalog_prefix)` overwrites in place (upsert semantics). Test row
   cleaned up afterward. `ARYX_INGEST_PIPELINE` is not set in the shared
   dev_oci deployment today, so the live HTTP upload path itself (which
   would also activate the raw-graph feature for all uploads) was
   deliberately left for Phase 4's cutover rather than flipped now.
2. **Phase 2 — one-time backfill.** A small script (or an
   `/admin/cpq/layouts/backfill` one-shot endpoint, whichever matches
   how `discovery_store` migrations were seeded) reads the 5 existing
   `config_layouts/*.txt` files + `manifest.json`, and inserts one row
   per catalog into `aryx_cpq_layout_file` for every real workspace
   that uses CPQ (or a single "default" workspace_id if layouts are
   genuinely global today — confirm against real usage before writing
   this, per this session's own established practice of ground-truthing
   before assuming).
3. **Phase 3 — parity verification.** For every backfilled
   `(workspace_id, catalog_prefix)`, assert
   `OracleLayoutFileSource.get(catalog_prefix) ==
   LocalDirLayoutFileSource.get(catalog_prefix)` byte-for-byte, run
   against the live dev_oci container (same ground-truthing discipline
   as the CPQ_Hardcode_Audit fixes this session did) before trusting
   the migration.
4. **Phase 4 — cutover.** Set `ARYX_CPQ_LAYOUT_SOURCE=oracle` in
   dev_oci (already has `ARYX_INGEST_PIPELINE=cpq_ingestion` set from
   the existing XML raw-graph rollout, so this one var flips the
   read-path over — see §4.3's combined-flag design); watch the exact
   warning log lines `layout_source.py` already emits on any no-match
   ("no manifest entry and no fuzzy-matched layout file found...") for
   regressions across a few real `/ask` turns per known catalog.
5. **Phase 5 — remove the old path.** Once cutover is stable for a
   full deploy cycle: delete `config_layouts/` from the repo,
   `LocalDirLayoutFileSource`, `ARYX_CPQ_LAYOUT_DIR` from
   `.env.example*` (both currently carry an explicit warning comment
   about this exact directory — those comments get deleted too, not
   just the env var line), and the "must point at the config_layouts/
   dir baked into the image" Dockerfile `COPY` step.

## 6. Testing plan

- Unit: `OracleLayoutFileSource.get()` against a mocked pool/cursor —
  hit, miss, workspace-isolation (a row in workspace A must not be
  visible to workspace B, matching `discovery_store.get()`'s existing
  isolation test).
- Unit: `store_layout_file()` — upsert-on-re-upload, `.txt` vs `.json`
  content both accepted, oversized-content guard (reuse
  `discovery_max_payload_mb`-style cap, sized appropriately smaller
  since these files are KB–low-MB, not the 512MB discovery ceiling).
- Unit: `cpq_layout_upload_active()` — the full env-var matrix, mirroring
  `test_routing.py`'s existing style for `cpq_ingestion_pipeline_active()`.
- Unit: `_resolve_layout_file_source()` — the combined
  `(ingest_pipeline, cpq_layout_source)` matrix from §4.3: both set →
  `OracleLayoutFileSource`; `cpq_layout_source=oracle` alone (pipeline
  not `cpq_ingestion`) → stays `LocalDirLayoutFileSource`; neither set
  → `LocalDirLayoutFileSource` (today's unchanged default).
- Integration (gated behind `ARYX_RUN_LOCAL_INTEGRATION_TESTS=1`, same
  convention as `test_pipeline_integration.py`): real upload → real
  Oracle row → `OracleLayoutFileSource.get()` round-trip.
- Parity test (one-time, run manually during Phase 3, not a permanent
  CI test): byte-identical comparison against all 5 real existing
  layout files.

## 7. Open questions

1. ~~Are layout files per-workspace or global?~~ **RESOLVED (2026-09-30):
   strictly per-workspace. Each workspace has its own layout file(s);
   one workspace must never be able to read or be served another
   workspace's layout content.** This confirms:
   - The schema in §4.1 is correct as written —
     `(workspace_id, catalog_prefix)` is a hard uniqueness and isolation
     boundary, not just an optimization. No shared/global fallback row.
   - Every read (`OracleLayoutFileSource.get()`) must filter by
     `workspace_id` in the SQL itself (`WHERE workspace_id = :ws AND
     catalog_prefix = :cp`), never by `catalog_prefix` alone — the same
     discipline `discovery_store.get()` already enforces (a row from
     another workspace is treated as if it doesn't exist, never
     returned and never distinguished from "not found" in the response,
     closing the same class of cross-tenant IDOR this session's own
     T11 fix (`jobs_api.py`) just closed elsewhere in this codebase).
   - **Backfill (§5 Phase 2) must ask, per existing real workspace that
     uses CPQ today, which catalog(s) it's actually on** (via
     `aryx_workspace`/existing CPQ product-config association, not
     guessed) and insert one row per `(workspace_id, catalog_prefix)`
     pair — not one shared row per catalog. If two workspaces happen to
     use the identical catalog today, they still each get their own
     independent copy of that layout's content post-migration; a later
     edit to one workspace's copy must never affect the other's.
   - Upload must always carry an authenticated caller's own
     `workspace_id` (or a workspace_id explicitly scoped to their
     access) — cannot be a bare unauthenticated field on the request,
     or workspace isolation is trivially bypassable at write time even
     with perfect read-time isolation. This ties into open question 3
     below (upload auth) — that decision now has a hard requirement,
     not just a nice-to-have.
2. ~~`LayoutFileSource.get()`'s signature?~~ **RESOLVED (2026-09-30):
   explicit `workspace_id` second parameter, not a factory.** See §4.3 —
   the actual edit surface turned out to be 4 spots (Protocol,
   `LocalDirLayoutFileSource`, `OracleLayoutFileSource`,
   `components.py:63`), not the ~20 API call sites, since every caller
   already threads `workspace_id` down to that one line today.
3. ~~Upload surface?~~ **RESOLVED (2026-09-30): reuse the existing
   `/admin/ingest/file` endpoint** — add `.txt` to the accepted
   extensions (§4.2 item 1) and a `catalog_prefix` field, gated by
   `cpq_layout_upload_active()` (§4.2 item 2). Same auth as every other
   upload through this endpoint today; no new route/auth surface to
   build. The caller's own authenticated `workspace_id` (already a
   required field on this endpoint) is what gets written into
   `aryx_cpq_layout_file.workspace_id` — never a client-supplied,
   unauthenticated value, satisfying the isolation requirement in §7.1.
4. ~~Versioning?~~ **RESOLVED (2026-09-30): overwrite-only for v1** —
   matches `manifest.json`'s current "last export wins" behavior
   exactly. Upsert on `(workspace_id, catalog_prefix)`, no history
   table. Revisit only if rollback capability becomes a real, requested
   operational need — not built preemptively.

All four open questions are now resolved. Nothing left blocking
implementation start.

## 8. Non-goals for this pass

- No change to the JSON *content* format itself, or to
  `_walk_layout_components`'s parsing logic — only where the bytes come
  from.
- No Object Storage integration (per §3's decision).
- No versioning/history table (per §7.4) — overwrite-only, add later
  only if actually needed.
- No new dedicated API endpoint or auth surface (per §7.3) — rides the
  existing ingest endpoint.
- No per-workspace factory/cache of `LayoutFileSource` instances (per
  §7.2) — one singleton, `workspace_id` passed per call.
