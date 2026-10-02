# csv_bml_ingestion

CSV → Oracle ADB tables, where **the BML query in a CPQ XML export decides
which tables are legitimate and what schema/indexes they get**. Built for
`dev_oci` (Oracle ADB); reuses the existing `cpq_ingestion` raw-graph projector
and the pooled Oracle connection (`aryx.store.oracle_pool`).

## Pipeline (per CSV)

| Step | Module | What happens |
|---|---|---|
| 1 | `table_name.py` | Filename stem, **lowercased**, is the table name. Missing → `CBI_TABLE_NAME_MISSING`; unsafe identifier → `CBI_TABLE_NAME_INVALID` (it is interpolated into SQL, so it is validated). |
| 2 | `bml_index.py`, `query_extract.py`, `graph_source.py` | **Any XML.** The XML is projected to a graph with the same projector the XML ingestion uses (one node per element) — generated when the XML is given, nothing about its vendor, tags or layout is assumed. Every node's text/attribute values are scanned for `SELECT … FROM` queries by their *shape* (a string literal or `"a" + "b"` concatenation, or the text itself) — whatever the script calls them (`BMQL(…)`, `db.run(…)`, a variable). `$var` / `${var}` / `:var` / `{var}` table names resolve from `var = "literal"` assignments in the same text; comments are ignored. A match records where the query lives (node, tag, property, ancestor path) and who it belongs to: the short leaf values beside it (id, guid, name, … — whatever tags exist), as a generic `identity`. The target table and the query's table are **both lowercased**, exact match. No match → `CBI_BML_NOT_FOUND`, logged with near misses (`attrToPart_pcrDev` for `attrToPart`); CSV skipped. Built once per XML, reused for every CSV. |
| 3 | `sql_catalog.py`, `sql_author.py`, `sql_validate.py`, `llm_client.py`, `db.py` | Schema + indexes come from `<sql dir>/<table>/{schema,indexes}.sql`. **If they do not exist, an LLM agent authors them at run time** (via the project's `aryx.llm.llm_runtime.chat`) from the CSV header/types, the longest value per column and the BML queries. Only names, sizes and query text are sent — never row data. The answer must pass a strict validator (one `CREATE TABLE IF NOT EXISTS` with exactly the CSV's columns in order, `VARCHAR2(n)` with `longest value <= n <= 4000`, `NUMBER(p)` for Integer, no constraints; at most 6 `idx_<table>_*` indexes over real columns, key under the ORA-01450 limit) — one retry with the validator's complaints, then `CBI_SQL_AUTHOR_FAILED`. Valid files are saved for review and applied (`IF NOT EXISTS`, idempotent); existing files are never overwritten. `--no-author-sql` disables authoring (missing files then give `CBI_SQL_ARTIFACTS_MISSING`). |
| 4 | `csv_reader.py`, `db.py` | Parse the `_start/_end meta data` layout; `Integer` columns converted, empty cells → NULL, malformed rows counted/skipped (`CBI_BAD_ROWS` warning). Default full refresh: `DELETE` + batched `INSERT` in **one transaction** (a failed load rolls back to the previous contents). `--append` keeps existing rows. |
| 4a | `column_limits.py`, `overflow.py` | Before inserting, the table's **real** column limits are read from `user_tab_columns` and every row is checked. A CSV column missing from the table → `CBI_SCHEMA_MISMATCH`. A value that does not fit (text over its byte/char limit, integer over its `NUMBER(p)`) is handled per `--on-overflow`: **`reject`** (default: row skipped, written with the reason to `<table>.rejects.csv`, load continues), **`truncate`** (text cut on a character boundary; numbers still rejected), **`fail`** (abort + rollback, `CBI_VALUE_TOO_LONG`). Text is measured in **bytes** for BYTE columns, so multibyte text (`€`, accents) hits the limit sooner than its character count suggests. Every case logs `CBI_VALUE_TOO_LONG` with per-column counts, longest offending size and samples. To accept long values legitimately, widen the column in `sql/<table>/schema.sql` (keep indexed columns within ORA-01450). |
| 5 | `tracking.py` | Raven logging on every step (`aryx.raven_log`): one `trace_id` per CSV, a span per record, `context.step`, P4 info / P3 warn / P2 error with stable `error_code`s. Raven failures never fail an ingest. |

`ingest_csv` never raises for expected failures — it returns an `IngestResult`
(`loaded` / `skipped` / `failed` + `error_code`), so a batch continues past a bad file.

## Run

```bash
# steps 1-2 only, no DB: what BML query does each CSV map to?
python -m aryx.csv_bml_ingestion inspect --xml SL3500e_config.xml attrSequence.csv attrToPart.csv

# full pipeline (needs ARYX_DB_BACKEND=oci + ARYX_OCI_ADB_DSN / DB user+password)
python -m aryx.csv_bml_ingestion ingest --xml SL3500e_config.xml attrSequence.csv attrToPDNonFrequency.csv
```

## Knowledge-graph route (upload integration)

When an XML is ingested it becomes a knowledge graph; later, a CSV upload finds its BML scripts by
searching **that graph** — the XML is not needed again. Off by default; one switch turns it on.

1. **XML ingest** (existing path, `ARYX_INGEST_FILE_TYPE=xml` + `ARYX_INGEST_PIPELINE=cpq_ingestion`,
   Oracle graph backend): with `ARYX_CSV_BML_ENABLED=true`, `raw_graph/store.py` also records, on every
   graph node whose text holds SQL queries, three short **list** properties — `bml_tables`,
   `bml_queries`, `bml_query_tables` (`bml_graph.py`). They are needed because the graph store clips
   every *string* property to ~200 characters (an Oracle bind-size guard) so the script text itself cannot
   be searched once stored; lists are not clipped.
2. **CSV upload** (`POST /admin/ingest/file`, unchanged API/UI): with the switch on, each uploaded `.csv`
   goes to `upload_hook.ingest_uploaded_csv` instead of the generic CSV path. Step 2 is
   `stored_graph.StoredGraphLookup`: one JSON query over this workspace's raw-graph id range finds the
   enriched nodes (typically a few dozen of hundreds of thousands), across **all** XMLs ingested into the
   workspace; neighbours in the graph give each match its identity and path.
3. Steps 3–4 are unchanged (LLM-authored SQL if needed, validated load). A CSV whose table no stored
   query reads is **skipped** (`CBI_BML_NOT_FOUND`) and the upload job finishes as `failed` with the
   per-file reasons in its error text — it is never silently ingested another way.

| Variable | Meaning |
|---|---|
| `ARYX_CSV_BML_ENABLED` | `true` turns on both halves above (default off: existing XML/CSV ingestion unchanged) |
| `ARYX_INGEST_FILE_TYPE=xml`, `ARYX_INGEST_PIPELINE=cpq_ingestion` | existing switches that make XML ingestion write the raw graph (needed for step 1) |
| `ARYX_CSV_BML_SQL_DIR` | where authored SQL is saved (default: package `sql/`) |
| `ARYX_CSV_BML_REJECTS_DIR` | where `<table>.rejects.csv` goes for uploads (default: `<sql dir>/ws_<id>/_rejects`) |

**Safety — which tables may be touched.** The names a CSV may be loaded into come from queries in an
*uploaded* XML, i.e. from the uploader, so the loader never trusts a name just because a query mentions it:

* `aryx_*` and system-style names (`sys_`, `dba_`, `all_`, `user_`, `dual`, …) are refused outright (`CBI_TABLE_NAME_INVALID`).
* **Ownership:** every table the pipeline creates is stamped with an owner tag as its table `COMMENT`
  (`csv_bml_ingestion`, or `csv_bml_ingestion:ws=<id>` for uploads). An existing table is used only if its
  comment equals the caller's owner tag; otherwise the CSV is refused with `CBI_TABLE_PROTECTED` — checked
  first, before any LLM call, DDL or `DELETE`. Two workspaces therefore cannot overwrite each other's tables.
  To let the pipeline manage a table that already exists, an administrator adopts it explicitly:
  `COMMENT ON TABLE <table> IS 'csv_bml_ingestion';`
* Authored SQL and rejects are kept per workspace (`<sql dir>/ws_<id>/…`).
* One CSV failing never aborts the rest of the upload; XML files in an upload are processed before CSVs.

Order matters: ingest the XML **first**; XMLs ingested before the switch was on carry no query lists and
must be re-ingested. The CLI can use the same graph: `inspect|ingest --workspace-id N csv...`.

## The SQL files (step 3)

Nothing per-table is committed. Files are written the first time a table is ingested to
`ARYX_CSV_BML_SQL_DIR` (default: the package's `sql/` folder) as
`<table>/{schema.sql, indexes.sql, bml_source.md}` — human-readable, stamped "authored by an LLM,
REVIEW before relying on it", and reused (never overwritten) on later runs. Commit them if you want
them as the reviewed reference. A hand-written file placed there is used as is.

Conventions the validator enforces (and the loader depends on): table = lowercase CSV stem; columns =
CSV header cells in order, named by `csv_reader.to_column_name`; `String` → `VARCHAR2(n)`, `Integer` →
`NUMBER(p)`; all nullable, no constraints; one statement per `;`-terminated line, no PL/SQL.

**Any CSV:** steps 1, 2 and 4 are generic, and step 3 now is too — a new CSV whose table has a BML
query needs no manual step.

## Current coverage (against `SL3500e_config.xml`)

| CSV | BML query found | Result |
|---|---|---|
| `attrToPDNonFrequency.csv` | yes (2 scripts, literal table) | SQL authored at run time, ingests |
| `attrSequence.csv` | yes (3 scripts, via `$attrSeqTableName = "attrSequence"`) | SQL authored at run time, ingests |
| `attrToPart.csv` | **no** — only `attrToPart_pcrDev` is queried | skipped, `CBI_BML_NOT_FOUND` |
| `accessoriesToPart.csv` | **no** — name appears only in variable names | skipped, `CBI_BML_NOT_FOUND` |
| `ar1Matrix.csv` | **no** — not in any provided XML | skipped, `CBI_BML_NOT_FOUND` |

## Limits

* DDL is Oracle-specific (ADB 26ai `IF NOT EXISTS`); the connection factory is
  Oracle-only by design (`DatabaseUnavailableError` otherwise).
* A query assembled at run time from non-literal pieces cannot be resolved statically and is skipped.
* Querying the stored graph needs the Oracle graph backend; on FalkorDB use `--xml`. Step 2 with `--xml` builds the graph from the file; with `--workspace-id` it searches the stored graph via the query lists written at XML-ingest time (not the clipped script text).
* Run-time authoring needs the project's LLM configured and its SDK importable (OCI GenAI needs the `oci` package, present in the app image).
* `IF NOT EXISTS` does not alter an existing table: if a column is widened in `schema.sql`, apply the `ALTER TABLE ... MODIFY` (or drop/recreate) yourself.
