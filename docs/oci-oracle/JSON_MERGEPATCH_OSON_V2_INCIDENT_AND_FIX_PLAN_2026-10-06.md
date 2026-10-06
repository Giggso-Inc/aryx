# JSON_MERGEPATCH → OSON v2 unreadable-row incident, and a fix plan for every call site (2026-10-06)

## Problem

While backfilling CSV_BML query-table metadata onto workspace 1126
(`scripts/backfill_bml_query_tables.py --apply`, merging `bml_tables`/
`bml_queries`/`bml_query_tables` onto 105 already-confirmed entities), **49
of those 105 entities became unreadable by the application** immediately
after the merge:

```
oracledb.exceptions.NotSupportedError: DPY-3021: OSON version 2 is not supported
```

Any later `SELECT attributes FROM aryx_entity WHERE id = ...` on one of
these rows raises this exception — not a slow query, not empty data, a hard
client-side decode failure. The failure first surfaced as the subsequent
full graph rebuild crashing partway through `EntityStore.list_entities()`
(`src/aryx/project/project_full.py:97`), then reproduced directly against
the specific patched rows.

**The underlying JSON content is not lost.** `JSON_SERIALIZE(attributes
RETURNING CLOB)` (which asks Oracle to hand back the document as plain
text instead of its native binary encoding) reads every affected row back
with no error, full content intact, `bml_tables` and all. The problem is
specifically in the python-oracledb **client's binary JSON decoder**,
not the server-side data.

## Root cause

`backfill_bml_query_tables.py`'s merge query
(`_MERGE_BML_ATTRIBUTES`) writes via:

```sql
UPDATE aryx_entity SET attributes = JSON_MERGEPATCH(attributes, %s)
WHERE id = %s AND workspace_id = %s
```

This was a deliberate choice (see the script's own comment) to route around
a *different*, already-known bug: `load("merge_one_attribute")`'s shared
psycopg→Oracle SQL translator appends a bogus `INTO` out-bind clause
(`ORA-03048`) for `%s`-style binds. Writing the equivalent `JSON_MERGEPATCH`
UPDATE directly, bypassing `load()`, avoided that translator bug — but
traded it for a worse one that nobody had verified end-to-end before today:

**Oracle ADB re-encodes the JSON column's storage format to "OSON version
2" whenever it is written through a server-side `JSON_MERGEPATCH()` call,
and the installed `python-oracledb` thin-mode client cannot decode OSON
v2 back.** Confirmed empirically, today, against the live, affected rows:

| Client | Mode | Result reading an affected row |
|---|---|---|
| `oracledb` 2.5.1 (installed, pinned `oracledb~=2.4` in `requirements.txt`) | thin | `DPY-3021: OSON version 2 is not supported` |
| `oracledb` 4.0.2 (tested in an isolated venv) | thin | Same failure |
| `oracledb` 26.0.1 — the current latest release (tested in an isolated venv) | thin | Same failure |

**This is not a version gap closable by a dependency bump.** Every thin-mode
client version available today fails identically. The only client-side path
that might support OSON v2 is Oracle's **thick mode** (requires installing
Oracle Instant Client libraries into the image and switching
`oracledb.init_oracle_client()` on) — not tested or pursued as part of this
incident; confirming that is the first open question in the plan below.

Rows written by a **plain client-side JSON string bind** (e.g.
`UPDATE aryx_entity SET attributes = :1` with a JSON-text parameter, or
psycopg's `Json(...)` wrapper) do **not** trigger this — those are the
majority of rows in every workspace, including the other 56/105 entities
this same backfill touched that happened to already carry the merged key
unchanged, or other merges that only ever used the plain-UPDATE path (e.g.
`backfill_cpq_display_names.py`'s `_UPDATE_ATTRIBUTES`, `scripts/
backfill_raw_graph_ontology_type_naming.py`). Those scripts are not at risk.

### Immediate repair (already applied, workspace 1126 only)

For each of the 49 broken rows: read the full document back via
`JSON_SERIALIZE(attributes RETURNING CLOB)` (bypasses the binary decoder
entirely — the translator's `ORA-03048` bug also had to be routed around
here, by issuing the query on the raw underlying `oracledb` connection
instead of through the pooled wrapper's translated-SQL path), parse it in
Python, and rewrite it with a plain `UPDATE aryx_entity SET attributes = :1
WHERE id = :2` binding the JSON as a text string. Verified: all 49 rows
read normally again afterward, `bml_tables` intact. The subsequent full
graph rebuild (`project_graph`) then completed cleanly: 72,274 entities /
75,099 provenance / 75,098 relationships, matching every count from before
the incident.

**This repair was row-specific and manual.** It has not been applied
anywhere else, and nothing currently prevents the same corruption from
happening again on any other `JSON_MERGEPATCH` call that actually executes
against live data.

## Blast radius — every `JSON_MERGEPATCH` call site

Found via `grep -rl JSON_MERGEPATCH src/`. Column type confirmed live via
`all_tab_columns` (`DATA_TYPE`) — this matters because the OSON v2 failure
is specific to Oracle's **native `JSON` column type**; a `CLOB` column that
happens to hold JSON *text* may not be affected the same way (Oracle's
`JSON_MERGEPATCH()` output would just be serialized to the CLOB's text
representation on write, not stored as binary OSON) — **this distinction
is not yet verified empirically for any of the CLOB-typed columns below**,
only inferred from the column type. Treat every row in this table as
"confirmed" only where marked so.

| # | File | Table.column | Column type | Call site(s) | Live production path? | OSON risk |
|---|---|---|---|---|---|---|
| 1 | `src/aryx/queries/oracle/merge_one_attribute.sql` | `aryx_entity.attributes` | **JSON** (native) | `ActionStore.set_attribute()` (`src/aryx/store/action_store.py:120-133`) | **Yes — CPQ action-execution effect log, live production code, not a one-off script** | **CONFIRMED** (same column/mechanism as the workspace 1126 incident) |
| 2 | `src/aryx/queries/oracle/merge_entity_attributes.sql` | `aryx_entity.attributes` | **JSON** (native) | `AdjudicationStore` entity-merge survivorship (`src/aryx/store/adjudication_store.py:111`) | **Yes — every entity-resolution adjudication merge with a conflicting attribute key, during every XML confirm** | **CONFIRMED** (same column/mechanism) |
| 3 | `scripts/backfill_bml_query_tables.py` (`_MERGE_BML_ATTRIBUTES`, inline, not a `.sql` file) | `aryx_entity.attributes` | **JSON** (native) | This incident | One-off admin script, but reusable | **CONFIRMED** — this is the incident itself |
| 4 | `src/aryx/queries/oracle/ask_thread_update_message_oracle.sql` | `gg_messages.message_metadata` | `CLOB` | `AryxAskThreadStore._insert_message_oracle` (`src/aryx/store/ask_thread_oracle_insert.py:70,98`) | Yes — every Ask-thread message overwrite | **Unverified** |
| 5 | `src/aryx/queries/oracle/ask_thread_update_request_status.sql` | `gg_messages.message_metadata` | `CLOB` | `ask_thread_store.py:288,312,320` | Yes — every Ask request-status update | **Unverified** |
| 6 | `src/aryx/queries/oracle/ask_thread_ensure_channel.sql` | `gg_channels.channel_settings` | `CLOB` | `ask_thread_store.py:120` (channel upsert, `WHEN MATCHED` branch) | Yes — every Ask channel upsert where the channel already exists | **Unverified** |
| 7 | `src/aryx/store/shay_workspace_bridge.py:95-120` (inline SQL) | `aryx_shay_workspace_map.sync_state` | `CLOB` | Shay↔Aryx workspace-mapping sync, existing-row branch | Yes — every repeat workspace sync | **Unverified** |

Row 1 and row 2 are the most urgent: they are the **same column, same
native-JSON type, same `JSON_MERGEPATCH` mechanism** already proven to
corrupt readability in this incident, and both are everyday production
code paths (not admin scripts), meaning **any entity that has ever gone
through a CPQ action execution or an entity-resolution merge with a
conflicting key may already be silently unreadable in production right
now**, with no symptom until something tries to read that specific entity.

## Fix plan

**The proven-safe pattern** (already used correctly elsewhere —
`backfill_cpq_display_names.py`'s `_UPDATE_ATTRIBUTES`,
`backfill_raw_graph_ontology_type_naming.py`): read the full JSON client-side,
merge in Python, write the *whole* document back with a plain
`UPDATE ... SET attributes = :1` string bind. Never let Oracle's
server-side `JSON_MERGEPATCH()` touch a native-`JSON`-typed column.

### Step 0 — close the open question: does thick mode actually support OSON v2?

Before committing to "rewrite every call site," spend an hour confirming
whether installing Oracle Instant Client and switching to thick mode
(`oracledb.init_oracle_client()`) makes `JSON_MERGEPATCH`-written rows
readable again. If yes, that is a smaller, more centralized fix (one
client-mode switch covers every call site, including future ones) than
rewriting six call sites by hand — worth ruling in or out first. If thick
mode is impractical here (image size, licensing, OCI Function
compatibility — `aryx_oracle_migrate` and the OCI Function image are
mentioned elsewhere in this codebase as thin-only), proceed with Step 1.

### Step 1 — audit, don't just trust the column type, for rows 4–7

For each of `gg_messages.message_metadata`, `gg_channels.channel_settings`,
`aryx_shay_workspace_map.sync_state`: write one row through its existing
`JSON_MERGEPATCH` call site in a disposable test row/workspace, then try
reading it back through the normal client path. This is a 10-minute check
per column and turns three "unverified" rows into either "confirmed safe"
(CLOB really does behave differently — no further action on those three)
or "confirmed affected" (treat identically to rows 1–2 below).

### Step 2 — fix the two confirmed, live production call sites (rows 1–2)

- **`ActionStore.set_attribute()`** (`action_store.py:120`): change from
  `UPDATE ... SET attributes = JSON_MERGEPATCH(attributes, :1)` to a
  read-modify-write: `SELECT attributes ... FOR UPDATE`, merge `{key:
  value}` into the Python dict, `UPDATE ... SET attributes = :1` with the
  whole document as a JSON string bind. Needs the `FOR UPDATE` (or
  equivalent locking) to stay safe against concurrent `set_attribute`
  calls on the same entity, which the current single-statement
  `JSON_MERGEPATCH` get for free — call this out explicitly in the PR,
  since a naive read-then-write reintroduces a lost-update race the
  current code doesn't have.
- **`AdjudicationStore` survivorship merge** (`adjudication_store.py:111`):
  same pattern — read both `src.attributes` and `dst.attributes`, do the
  dst-wins-on-conflict merge in Python (the exact same semantics the SQL
  comment already documents), write the merged document back with a plain
  UPDATE. This one runs inside the entity-resolution pipeline, so confirm
  it has the same transactional guarantees (the whole adjudication step
  already runs inside one transaction per the surrounding code — reuse
  that, don't add a new one).

### Step 3 — fix (or confirmedly skip) rows 4–7, per Step 1's findings

If Step 1 shows the CLOB columns are affected too, apply the same
read-modify-write pattern to all three. If not, add a one-line comment at
each `JSON_MERGEPATCH` call site in those `.sql` files noting that CLOB
storage was verified safe from the OSON v2 issue on 2026-10-06, so a future
reader doesn't have to re-litigate this.

### Step 4 — scan for already-corrupted production rows

Before closing this out, run a read-only sweep across every workspace (not
just 1126) for rows unreadable via the normal client path — the same
per-row try/except `SELECT attributes` pattern used to find the 49 broken
rows in workspace 1126, generalized to every table from the inventory
above. Any already-corrupted row found needs the same `JSON_SERIALIZE`
recovery + plain-UPDATE rewrite applied in this incident. Do **not** apply
any code fix from Step 2/3 and assume existing data is fine — the bug has
presumably been live since `merge_one_attribute.sql`/
`merge_entity_attributes.sql` were first used in production, so there may
already be a non-trivial number of silently-unreadable entities out there.

### Step 5 — regression test

Add a test that writes through each fixed call site against a column
declared as native Oracle `JSON`, then reads it back through the actual
`oracledb` client (not mocked) and asserts no `DPY-3021`/`NotSupportedError`.
Existing unit tests for `action_store.py`/`adjudication_store.py` likely
mock the cursor and would never have caught this — this incident was only
found by accident, during a live backfill against real Oracle ADB data,
not by any test in the suite.

## Open questions

- Does thick mode actually fix this (Step 0)? Unanswered — needs the
  Instant Client install tried once, deliberately, to close it off either
  way.
- Are rows 4–7 actually affected (Step 1)? Unverified — see the table.
- How many already-corrupted entities exist in production today, across
  every workspace, from rows 1–2's ordinary use before this incident was
  known (Step 4)? Unknown until the sweep runs.
