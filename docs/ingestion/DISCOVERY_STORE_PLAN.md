# DB-backed Discovery Store — History + Confirm Resume

## Context

`/admin/docs/read` previously stored results in a process-level Python dict (`discoveries.py`). This caused:
- Discovery lost if container restarts between read and confirm
- Can't scale to multiple API instances (each has its own dict)
- Re-running read in the UI loses the previous `discovery_id`
- Failed confirm jobs restart from scratch — no resume

**Scope:** Persist discoveries to both Postgres and Oracle ADB (OCI branch uses Oracle for all metadata via `pool.py`), expose history per workspace, support resuming a failed confirm from the last completed plan. No hard expiry — discoveries persist indefinitely; a warning is shown in the UI when a discovery has been pending for 7+ days.

**Status: IMPLEMENTED** — all steps below reflect the actual code as shipped.

---

## Files Changed

| File | Change |
|---|---|
| `src/aryx/store/migrations/0029_discovery.sql` | NEW — `aryx_discovery` table (Postgres) |
| `src/aryx/store/migrations_oracle/0033_discovery.sql` | NEW — `aryx_discovery` table (Oracle ADB 26ai) |
| `src/aryx/queries/upsert_discovery.sql` | NEW — Postgres `INSERT ... ON CONFLICT` upsert |
| `src/aryx/queries/oracle/upsert_discovery.sql` | NEW — Oracle `MERGE INTO ... USING dual` upsert override |
| `src/aryx/queries/select_discovery.sql` | NEW — workspace-scoped SELECT |
| `src/aryx/queries/delete_discovery.sql` | NEW — DELETE by discovery_id |
| `src/aryx/queries/mark_confirmed_discovery.sql` | NEW — UPDATE status=confirmed |
| `src/aryx/queries/update_discovery_confirm_state.sql` | NEW — UPDATE confirm_state, status=partial |
| `src/aryx/queries/list_recent_discoveries.sql` | NEW — SELECT recent by workspace, newest-first |
| `src/aryx/store/discovery_store.py` | NEW — `DiscoveryStore` using `get_pool` (both backends) |
| `src/aryx/discoveries.py` | Replace in-memory dict with `DiscoveryStore` calls; add `mark_confirmed` |
| `src/aryx/api/doc_discover_api.py` | History endpoint, resume support, null guard, workspace scoping |
| `src/aryx/pipeline/doc_discovery.py` | `ingest_confirmed` resume logic, `_update_confirm_state` helper |
| `apps/web/lib/types.ts` | Added `DiscoveryHistoryItem` interface |
| `apps/web/lib/api.ts` | Added `listDiscoveries`, updated `getDiscoverySummary` + `confirmDiscovery` |
| `apps/web/components/ingest/DocsTab.tsx` | History panel, pending-days warning, Resume/Confirm buttons |
| `tests/test_discovery_store.py` | NEW — 11 unit tests (stubbed pool, no live DB) |
| `src/aryx/store/oracle_pool.py` | Bug fix — `_hint_clob()` for ORA-03146 on large CLOB params |

---

## Step 1 — DB Migrations

### Postgres: `src/aryx/store/migrations/0029_discovery.sql`

Lowercase table name — consistent with all other Postgres tables (`aryx_entity`, `aryx_run`, etc.). No `expires_at` — rows persist indefinitely.

```sql
CREATE TABLE IF NOT EXISTS aryx_discovery (
    discovery_id    TEXT        PRIMARY KEY,
    workspace_id    INTEGER     NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending',
    data_json       TEXT        NOT NULL DEFAULT '{}',
    summary_json    TEXT        NOT NULL DEFAULT '{}',
    file_count      INTEGER     NOT NULL DEFAULT 0,
    confirm_state   TEXT        NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_aryx_discovery_workspace
    ON aryx_discovery (workspace_id, created_at DESC);
```

### Oracle ADB 26ai: `src/aryx/store/migrations_oracle/0033_discovery.sql`

Lowercase table name (Oracle stores unquoted identifiers as uppercase internally — `aryx_discovery` and `ARYX_DISCOVERY` are the same object; lowercase is used in SQL for consistency with the rest of the codebase). Uses `CLOB` for JSON columns, `TIMESTAMP WITH TIME ZONE`, `SYSTIMESTAMP`. Idempotent via `EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955`.

```sql
BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_discovery (
    discovery_id  VARCHAR2(64)              NOT NULL,
    workspace_id  NUMBER(10)                NOT NULL,
    status        VARCHAR2(32)              DEFAULT ''pending'' NOT NULL,
    data_json     CLOB                      DEFAULT ''{}'' NOT NULL,
    summary_json  CLOB                      DEFAULT ''{}'' NOT NULL,
    file_count    NUMBER(10)                DEFAULT 0 NOT NULL,
    confirm_state CLOB                      DEFAULT ''{}'' NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE  DEFAULT SYSTIMESTAMP NOT NULL,
    confirmed_at  TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_aryx_discovery PRIMARY KEY (discovery_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_aryx_discovery_workspace
    ON aryx_discovery (workspace_id, created_at DESC)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/
```

### `confirm_state` JSON schema

```json
{
  "last_job_id": "uuid",
  "completed_plans": ["customers.csv", "Person"],
  "plan_run_ids": {"customers.csv": "run_abc", "Person": "run_def"},
  "failed_plans": []
}
```

---

## Step 2 — DiscoveryStore

**New file: `src/aryx/store/discovery_store.py`**

Uses `from aryx.store.pool import get_pool` — same pattern as `job_store.py`. `pool.py` routes to `OraclePool` when `effective_db_backend() == "oci"`, Postgres `psycopg_pool` otherwise.

**SQL compatibility rules:**
- All timestamps passed as Python `datetime` objects — no `now()` or `SYSTIMESTAMP` in DML queries
- `FETCH FIRST N ROWS ONLY` instead of `LIMIT` (ANSI SQL — works on both backends)
- `oracle_pool.py`'s `_translate_sql` handles `%(name)s` → `:name` automatically
- `load("upsert_discovery")` auto-selects `queries/oracle/upsert_discovery.sql` when OCI backend is active

**No expiry.** `get()` always returns the row regardless of age. `pending_days` is computed in `list_recent()` **only for `status='pending'` rows** — not for `partial` (confirm already running) or `confirmed`. The UI shows the `⚠️` badge when `pending_days >= 7`.

### Custom JSON codec for `data_json`

`data["tabular"][i]["data"]` is raw `bytes` (CSV/JSON file content). `data["mentions"]` is a list of `RawRecord` Pydantic models. Both are non-serializable by `json.dumps`. `discovery_store.py` includes:

- `_DiscoveryEncoder` — encodes `bytes` as `{"__b64__": "<base64>"}`, Pydantic `BaseModel` as `{"__pydantic__": "ClassName", "__module__": "...", "v": {...}}`
- `_discovery_hook` — reverses the above on `json.loads`, reconstructing `bytes` and calling `model_validate()` to restore `RawRecord` objects

This ensures `ingest_confirmed` receives the same types it would from the original in-memory dict.

```python
class DiscoveryStore:
    def __init__(self, dsn: str) -> None:
        self._pool = get_pool(dsn)

    def put(self, discovery_id: str, workspace_id: int,
            data: dict, summary: dict, file_count: int) -> None:
        # data_json serialized via _serialize_data() (handles bytes + Pydantic)
        # summary_json serialized via json.dumps() (plain dict, no special types)

    def get(self, discovery_id: str, workspace_id: int) -> dict | None:
        # SELECT WHERE discovery_id=%s AND workspace_id=%s
        # Returns None if not found OR belongs to a different workspace (multi-tenant isolation)

    def drop(self, discovery_id: str) -> None: ...

    def mark_confirmed(self, discovery_id: str, job_id: str) -> None:
        # UPDATE SET status='confirmed', confirmed_at=%s

    def update_confirm_state(self, discovery_id: str, state: dict) -> None:
        # UPDATE SET confirm_state=%s, status='partial'

    def list_recent(self, workspace_id: int, limit: int = 20) -> list[dict]:
        # ORDER BY created_at DESC  FETCH FIRST %s ROWS ONLY
        # pending_days appended ONLY for status='pending' rows; None otherwise

    def close(self) -> None:
        # No-op — pool is shared/process-scoped
```

---

## Step 3 — discoveries.py

Replaced `_STORE: dict` with `DiscoveryStore`. Interface additions:

```python
def put(discovery_id: str, data: dict, workspace_id: int = 1) -> None: ...
def get(discovery_id: str, workspace_id: int = 1) -> dict | None: ...
def drop(discovery_id: str) -> None: ...
def mark_confirmed(discovery_id: str, job_id: str) -> None: ...  # NEW
```

---

## Step 4 — doc_discover_api.py

**`ConfirmRequest`** — added `workspace_id` and optional `resume_job_id`:
```python
class ConfirmRequest(BaseModel):
    discovery_id: str
    approved_types: list[str] = []
    approved_files: list[str] = []
    workspace_id: int = 1
    resume_job_id: str | None = None
```

**`_read_job`** — passes `workspace_id` to `discoveries.put`.

**`_confirm_job`** — workspace-scoped `get()`, null guard (fails the job cleanly instead of crashing), calls `discoveries.mark_confirmed` on success:
```python
def _confirm_job(did, types, files, job_id, workspace_id=1):
    data = discoveries.get(did, workspace_id)
    if not data:
        jobs.finish(job_id, ..., status="failed", error="discovery not found or workspace mismatch")
        return
    confirm_state = data.get("_confirm_state", {})
    ingest_confirmed(..., confirm_state=confirm_state, discovery_id=did)
    jobs.finish(job_id, ..., status="complete")
    discoveries.mark_confirmed(did, job_id)
```

**`GET /admin/docs/history`** — new endpoint:
```python
@router.get("/history")
def history(workspace_id: int = 1) -> list[dict]:
    store = DiscoveryStore(get_settings().rdb_dsn)
    try:
        return store.list_recent(workspace_id)
    finally:
        store.close()
```

**`GET /admin/docs/summary/{did}`** — gains `workspace_id` query param.

---

## Step 5 — doc_discovery.py: ingest_confirmed Resume

**Updated signature:**
```python
def ingest_confirmed(
    data, approved_types, approved_files, broker, jobs, job_id,
    workspace_id=1,
    confirm_state: dict | None = None,
    discovery_id: str | None = None,
) -> None:
```

**Resume logic:**
```python
state = confirm_state or {}
completed_plans = set(state.get("completed_plans", []))
plan_run_ids = dict(state.get("plan_run_ids", {}))

# valid_plans already filters out completed ones
valid_plans = [p for p in all_valid_plans if p["filename"] not in completed_plans]

# After each plan succeeds:
if discovery_id:
    completed_plans.add(fname)
    _update_confirm_state(discovery_id, {
        "last_job_id": job_id,
        "completed_plans": list(completed_plans),
        "plan_run_ids": plan_run_ids,
        "failed_plans": [],
    })
```

`_update_confirm_state(discovery_id, state)` helper — creates `DiscoveryStore`, calls `update_confirm_state`, closes. Lazy-imported inside the function to avoid circular imports.

---

## Step 6 — Frontend

### `apps/web/lib/types.ts` — new interface

```typescript
export interface DiscoveryHistoryItem {
  discovery_id: string;
  status: "pending" | "partial" | "confirmed";
  summary: DiscoverySummary;
  file_count: number;
  created_at: string;
  confirmed_at: string | null;
  pending_days: number | null;  // only set for status="pending"; null for partial/confirmed
}
```

### `apps/web/lib/api.ts` — additions

```typescript
listDiscoveries: (workspaceId = 1) =>
  fetchJSON<DiscoveryHistoryItem[]>(`/admin/docs/history?workspace_id=${workspaceId}`)

confirmDiscovery: (discoveryId, approvedTypes, approvedFiles = [], workspaceId = 1, resumeJobId?) =>
  fetchJSON("/admin/docs/confirm", { method: "POST", body: JSON.stringify({
    discovery_id: discoveryId, approved_types: approvedTypes,
    approved_files: approvedFiles, workspace_id: workspaceId,
    ...(resumeJobId ? { resume_job_id: resumeJobId } : {}),
  })})
```

### `apps/web/components/ingest/DocsTab.tsx` — history panel

- Loads `api.listDiscoveries(workspaceId)` on mount
- Collapsible history list: status badge, relative timestamp, pending-days warning
- `[Confirm]` / `[Resume]` button on non-confirmed rows — calls `api.getDiscoverySummary` then restores confirm UI
- `⚠️ Pending N days` shown **only** when `status="pending"` and `pending_days >= 7`
- History refreshed on confirm completion

---

## Bug Fixes Applied Post-Implementation

### 1. `bytes` / Pydantic not JSON-serializable (ORA and Postgres)

**File:** `src/aryx/store/discovery_store.py`

`data["tabular"][i]["data"]` is raw `bytes`; `data["mentions"]` is `list[RawRecord]` (Pydantic). Both fail `json.dumps`. Fixed by adding `_DiscoveryEncoder` + `_discovery_hook` — bytes round-trip via base64, Pydantic models via `model_dump(mode="json")` / `model_validate()`.

### 2. ORA-03146: invalid buffer length for TTC field

**File:** `src/aryx/store/oracle_pool.py`

Oracle thin client binds Python `str` as `VARCHAR2` by default (max 32,767 bytes). Large `data_json` payloads (~982KB) exceeded this, causing `ORA-03146`. Fixed by adding `_hint_clob()` — called inside `OracleCursorWrapper.execute()` before every statement. It inspects bound params and calls `cursor.setinputsizes()` for any string > 32,767 bytes, telling Oracle to treat it as `CLOB`. Works for both named (`dict`) and positional (`list`/`tuple`) params. General fix — applies to any future large-string column automatically.

---

## Verification Checklist

1. Restart container mid-confirm → same `discovery_id` resolvable from DB
2. Hit `/read` twice → both appear in `GET /history`; each independently confirmable
3. Kill container during confirm (2 of 5 plans done) → restart → Resume skips completed plans
4. Two users, same workspace → both reads appear in history
5. Discovery pending > 7 days → `pending_days >= 7`; UI shows `⚠️ Pending N days`
6. Discovery pending > 7 days → confirm still works (no expiry)
7. `GET /admin/docs/history?workspace_id=1` returns list sorted newest-first
8. Oracle ADB: `0033_discovery.sql` creates `aryx_discovery` table (lowercase in SQL; stored as uppercase internally)
9. Large file upload (>32KB serialized) → no ORA-03146 error

---

## Test Cases

**`tests/test_discovery_store.py`** — 11 passing unit tests, stubbed pool (no live DB)

### DiscoveryStore — core behaviour
- `test_put_and_get_returns_row` — put then get with correct workspace returns row
- `test_get_wrong_workspace_returns_none` — workspace_id=2 for row stored under workspace_id=1 → None
- `test_get_unknown_id_returns_none` — unknown discovery_id → None
- `test_put_upsert_is_idempotent` — put twice, execute called twice (no duplicate row)
- `test_mark_confirmed_sets_status` — execute called with discovery_id in params
- `test_update_confirm_state_persists_json` — JSON state round-trips correctly

### DiscoveryStore — pending_days logic
- `test_list_recent_pending_days_computed_for_pending` — 9-day-old pending row → `pending_days=9`
- `test_list_recent_pending_days_none_for_partial` — partial row → `pending_days=None`
- `test_list_recent_pending_days_none_for_confirmed` — confirmed row → `pending_days=None`
- `test_list_recent_pending_days_below_threshold` — 3-day-old pending → `pending_days=3`
- `test_close_is_noop` — `close()` must not raise
