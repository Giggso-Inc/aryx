# Oracle DB report — accepted, deliberately-not-code-fixed findings (2026-09-11)

Full investigation: `docs/Oracle_ADB_Data_Map.xlsx` (Issues sheet). This note
records the disposition of the two findings from that review that don't get a
code fix in `fix/oracle-db-report-issues-2026-09-11` (which addresses the two
missing-index findings as `migrations/0041`, `0042` +
`migrations_oracle/0041`, `0042`).

## #3 — Shay's `datasource.py`/`gg_datasource.py` naming inversion (Medium)

`gg_datasource.py` declares `__tablename__ = "datasources"`; `datasource.py`
declares `__tablename__ = "gg_datasources"` — each file maps to the table its
own name suggests the *other* file should. Both are genuinely live
(`/api/v1/datasources` and `/api/v1/gg-datasources` respectively, confirmed
via `app_routers.py`) — not dead code, and not a correctness bug today.

**Decision: leave as-is, documented here rather than renamed.** A rename
touches routes referencing either model across ~40 files
(`app/routes/datasources/`, `app/routes/gg_datasources/`) for a
maintainability improvement, not a functional one — the risk/reward doesn't
justify it as a standalone change. Revisit only as part of a larger,
deliberate refactor of the datasource subsystem, not in isolation.

**For anyone reading the code:** if you're looking for the model backing the
`datasources` table, it's `gg_datasource.py`, not `datasource.py` (and vice
versa) — the filenames are swapped relative to what they define. The two
models also name what's presumably the same vault-credential reference
differently: `giggso_vault_id` (in `datasource.py` / table `gg_datasources`)
vs. `vault_unique_id` (in `gg_datasource.py` / table `datasources`).

## #4 — Shay's Oracle schema is created from SQLAlchemy models alone (Medium)

`SHAY_RUN_MIGRATIONS=false` disables Alembic entirely in OCI mode;
`SHAY_INIT_DB=true` creates every Oracle table via SQLAlchemy's own
`create_all()`, which only emits indexes declared in each model's own
`__table_args__`. No specific missing index is confirmed — Shay's Alembic
migration files aren't present in this checkout to diff against — this is a
structural risk, not a pinpointed instance.

**Decision: no code change; process guidance instead.** Going forward,
**treat each SQLAlchemy model's own `__table_args__` as the single source of
truth for indexes** — never add one only via a hand-written Alembic
migration, since anything added that way silently never reaches Oracle
deployments. A CI check comparing Alembic-declared indexes against each
model's declared set would catch this class of drift automatically; not
built here since it's a tooling investment independent of this specific
finding, not a fix to the finding itself.

## Not carried forward as action items (informational only)

- **#5 — embedding pipeline (`aryx_chunk_embedding`) is write-only.** No
  retrieval code exists anywhere in the codebase, and no `CREATE VECTOR
  INDEX` exists on the column either. Likely an intentionally incomplete
  feature (`requirements.txt` tags `pgvector` as "Increment 9"), not a bug —
  needs a product decision on whether document-embedding retrieval (RAG-style
  Q&A over documents) is meant to exist yet, which is outside this pass's
  scope.
- **#6 — the Oracle Property Graph object is used by only 1 of 8 read
  methods.** Not a bug — plain SQL joins are often more efficient than
  `GRAPH_TABLE` for simple 1-hop patterns, and this is a deliberate,
  reasonable choice already in place.
