# Local OCI-mode stack with a local Oracle container — plan (2026-09-15)

Branch: `feat/local-oci-oracle-stack-2026-09-15` → `dev_oci`

## Goal

Add a new compose file that runs the same OCI code path
(`ARYX_DB_BACKEND=oci`) — `api`, `shay-api`, `web` — against a **local**
Oracle container instead of the real cloud Oracle ADB 23ai instance, so
OCI-specific database/graph behavior can be developed and tested without
touching the shared cloud instance or needing its credentials for the DB
layer specifically.

## Why not Oracle 26ai

Checked directly (Docker Hub) rather than assumed: `gvenzl/oracle-free`
— the standard community image for local Oracle development, and the
only realistic way to get a local Oracle container without Oracle's own
gated container registry — has no `24`, `25`, or `26` tag. Its newest
published tag is `23` (`latest` and `23` point to the same image
digest). I could not reach Oracle's own official release-notes page to
independently confirm or deny a "26ai" product release (`oracle.com`
returned a 403 to the fetch tool available here) — so this isn't a
claim that Oracle 26ai doesn't exist as a product, only that **no
pullable local container image for it exists today** through the
standard route this plan relies on.

This doesn't cost the plan anything: **23ai is the correct version to
use regardless** — it's the same major version family as the real cloud
ADB instance this whole effort is meant to mirror (JSON columns,
`VECTOR`, and SQL/PGQ property graphs — the exact features
`oracle_graph_reader_traverse.py`'s `shortest_path()` depends on — are
all present in 23ai, cloud and free editions alike). Matching versions
is the point; a hypothetical 26ai image, even if one existed, would
risk behavioral drift from the real ADB instance this stack is
supposed to approximate.

## Scope

Explicitly 4 services, matching what was asked for: `oracle` (new),
`api`, `shay-api`, `web`. **Not included:**
- `mcp` (the standalone port-8765 service) and `pgx-server` (graph
  analytics/OWL reasoning) — not in the requested service list, and
  `pgx-server` additionally needs `docker login
  container-registry.oracle.com`, unrelated to this change. Can be
  added later following the same pattern.
- Real ingested data (BOM catalogs, rules — e.g. the SVX catalog this
  session spent a long time debugging). A fresh local Oracle container
  starts empty; this plan is infrastructure only. Reproducing a
  data-dependent issue locally would need a separate ingestion pass
  against this new instance, out of scope here.
- Every **non-database** OCI backend (`ARYX_WORKER_BACKEND=oci_functions`,
  `ARYX_PARSE_BACKEND=oci`, `ARYX_EMBED_BACKEND=oci`,
  `ARYX_LLM_*_BACKEND=oci`, OCI Object Storage, OCI API auth) stays
  exactly as configured in the existing, already-working `.env` —
  these are separate OCI services unrelated to which database backs
  them, and localizing them wasn't asked for. Only the
  database-connection variables change.

## Image choice

`gvenzl/oracle-free:23-slim` — supports mounting first-boot init
scripts (`/container-entrypoint-initdb.d/`) and ships a working
healthcheck out of the box, both load-bearing for this plan (see Risk
Flags).

## File structure

| File | Purpose |
|---|---|
| `docker-compose-oci-local.yml` | New. `oracle` service (new) + `api`/`shay-api`/`web` service blocks copied from `docker-compose-oci.yml`, same `env_file: .env` as the cloud compose file (explicit decision — see below), plus `depends_on: oracle: condition: service_healthy` added to `api` and `shay-api`. Named distinctly from the existing `docker-compose.yml`/`docker-compose.local.yml` (both already-existing, unrelated Postgres+FalkorDB local stacks) to avoid confusion — this one specifically means "OCI code path, local infra." |
| `oracle-init/01-create-app-user.sql` | New. Mounted read-only into the `oracle` container's init-scripts directory; runs once, automatically, after the database is created on first boot. Creates the app schema user and grants privileges mirroring what the real cloud ADB schema user already has: `CREATE SESSION`, `CREATE TABLE`, `CREATE SEQUENCE`, `CREATE PROPERTY GRAPH` (needed for `shortest_path()`'s SQL/PGQ), `UNLIMITED TABLESPACE`. |
| `.env.example.oci-local` | New, real file — mirrors `.env.example.oci`'s existing format (same variable names, same structure), values filled in for the local container instead of the cloud ADB. Not read directly by either compose file at runtime — same relationship `.env.example.oci` already has to `.env` today: copy the relevant values into `.env` by hand when switching modes (see below). |

## Single shared `.env` — explicit decision, not an oversight

`docker-compose-oci.yml` and `docker-compose-oci-local.yml` both use
`env_file: .env` — the **same** file. This means the two compose files
are **mutually exclusive at any given moment**: whichever DB values
`.env` currently holds (cloud ADB vs. local container) is what *both*
compose files would use if run. Switching between local and cloud
testing means editing `ARYX_OCI_ADB_DSN`/`ARYX_RDB_DSN`/
`ARYX_DB_USER`/`ARYX_DB_PASSWORD` (and `ORACLE_PASSWORD` for the local
container) in `.env` each time, by hand.

This was flagged as a real risk (a separate `.env.oci-local` file
would make the two compose files independently runnable without any
manual edit) — the explicit choice made here is to keep one `.env` and
switch its values manually rather than maintain two files. Worth
restating plainly so it's never mistaken for an oversight later: **the
two compose files cannot be run against different databases
simultaneously with this setup** — only one at a time, whichever `.env`
currently points at.

## Env vars that change when switching

| Var | Cloud value (in `.env`) | Local value (in `.env`, when testing locally) |
|---|---|---|
| `ARYX_OCI_ADB_DSN` / `ARYX_RDB_DSN` | TCPS descriptor to `adb.<region>.oraclecloud.com` | plain easy-connect string to the new service, e.g. `oracle:1521/FREEPDB1` — no TCPS/wallet needed for a local container |
| `ARYX_DB_USER` / `ARYX_DB_PASSWORD` | cloud-provisioned schema user | created by `oracle-init/01-create-app-user.sql` |
| `ORACLE_PASSWORD` (new) | n/a | the `oracle` container's own SYS/SYSTEM password (gvenzl image requirement, distinct from the app schema user's password above) |

## Dependency map

**Touches:** 3 new files (compose file, init SQL, env-var reference
doc) plus manual edits to the existing, shared `.env` whenever
switching between local and cloud testing.
**Does not touch:** any application code, any existing compose file's
own content, any migration file — `oracle_migrate.py`'s ~44 migration
files run unmodified against whichever Oracle instance
`ARYX_OCI_ADB_DSN` points to; the DSN is the only thing that changes.
**Breaks if wrong:** (a) `api`/`shay-api` starting before the local
Oracle container has actually finished its (slow) first-boot init
would cause every migration/query to fail immediately — this is why
`depends_on` must gate on `service_healthy`, not `service_started`;
(b) running `docker-compose-oci.yml` (cloud) while `.env` still holds
local-container values (or vice versa) — the shared-`.env` decision
above means this is a real, standing risk on every switch, not a
one-time setup step.

## Risk flags

1. **First-boot time.** Oracle Free's first startup (creating the
   database, then running init scripts) is slow — commonly 1-3 minutes,
   sometimes longer on constrained hardware. `depends_on: condition:
   service_healthy` on `api`/`shay-api` is required, not optional, or
   migrations will race a not-yet-ready listener.
2. **Memory.** Oracle Database Free needs roughly 2GB minimum, 4GB+
   recommended, on top of `api`/`shay-api`/`web`'s own footprint —
   worth stating explicitly as a real local-machine requirement, not
   burying it in a config comment.
3. **Schema-user privilege drift.** The init script's granted
   privileges are a best-effort mirror of the cloud ADB user's actual
   privileges, written without direct access to enumerate the real
   cloud user's full grant list. A migration could pass against ADB
   and fail locally until the init script is corrected — the real
   verification step is running the full migration set against this
   new container once it exists, not assuming parity in advance.
4. **Not a data-parity tool.** Restated from Scope: this gives an
   empty, schema-only local Oracle instance. It's the right tool for
   migration/query-override development iteration; it is not a way to
   reproduce a customer-data-dependent bug locally.

## Stack compliance

No new library. `gvenzl/oracle-free` is a widely-used, actively
maintained community image (the de facto standard for this exact use
case); worth a quick CVE/maintenance check before finalizing per this
repo's own stack-validator discipline, but not a new dependency in the
Python/Node sense.

## End state

New branch off latest `dev_oci` (this branch,
`feat/local-oci-oracle-stack-2026-09-15`, created from `61d16f74`),
implementation of the 3 files above, a live first-boot smoke test
(container starts healthy, init script creates the user, a full
`oracle_migrate.py` run succeeds end-to-end against the fresh local
instance) as the actual acceptance criterion, PR opened against
`dev_oci` once implemented and verified.
