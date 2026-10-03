## Version: 1.5
## Last Updated: 2026-09-03
## Project: Aryx

### System Overview
Aryx ingests records from many heterogeneous sources, lands them in a relational
store with full provenance, semantically tags their fields, then reasons over
them to build a knowledge graph: it maps source schemas to a canonical ontology,
resolves duplicate records across systems into single entities, infers
relationships, and projects the result into FalkorDB (or Oracle's SQL/PGQ
property graph in OCI mode). The relational database is the permanent source of
truth; the graph is a rebuildable projection. Expensive frontier-LLM reasoning
is rationed by a funnel of cheap, deterministic and local stages so the model
only touches the hard ~1–5% of decisions.

Two additional subsystems sit alongside the ingestion/graph core, merged in
from the `dev-rv-msi` feature branch (2026-08/09): a **CPQ configuration
engine** that turns a natural-language sales conversation into a rule-checked,
never-guessed quote, and a **Shay bridge** connecting a separate sales-assistant
service (its own FastAPI backend + Next.js UI) to Aryx's ingested catalog data.
See `docs/diagrams/cpq-engine-technical-flow.html` and
`docs/aryx_oracle_adb_architecture.html` for detailed, code-verified flow
diagrams of both.

### Components
- **Connectors** (`connectors/`) — pluggable source readers behind a `Connector`
  protocol; `postgres.py` is the first concrete reader. Stream rows via `extract()`.
- **Pipeline spine** (`pipeline/`) — `run.run_spine` streams extract → `clean` →
  `profile` one record at a time (never materializes the full dataset); `tag.py`
  applies semantic field tags via the cheap model tier.
- **Store** (`store/`) — the RDB source of truth: `migrate` applies numbered SQL
  migrations, `postgres_store`/`entity_store`/`ontology_store` persist landed
  records, resolved entities and ontology, `batch_sink` is the landing sink.
- **Broker** (`broker/`) — provider-agnostic model gateway. `registry` holds
  `ModelSpec`s queryable by `Tier` (local/cheap/frontier); `governor` enforces
  budget/routing; `discovery` finds available models; `secrets` resolves
  credentials; supports Anthropic, Ollama, OpenAI-compatible, OCI GenAI, and
  Gemini's native embedding API. `ARYX_EMBED_BACKEND=gemini` selects
  `gemini-embedding-2`, pins output to the schema's 768 dimensions, and sends
  credentials in the `x-goog-api-key` header. Persisted embedding model IDs
  follow the effective backend, including configured model overrides.
  `embed()` accepts an `input_type` param (`SEARCH_DOCUMENT` for indexing,
  `SEARCH_QUERY` for retrieval) forwarded to the OCI Cohere Embed v3 path.
- **Ontology mapping** (`ontology/`) — `mapping.py` is the frontier-tier agent
  that maps source table→canonical type and field→attribute and proposes new
  types; `sources.py` plugs seed vocabularies (schema.org / DD / MDM / RDF).
- **Resolution funnel** (`resolution/`) — `classical.block`+`score_pair` (cheap),
  `adjudicate` (frontier, ambiguous middle only), `cluster` (UnionFind transitive
  closure + golden record); `run.resolve` wires them into entities + members.
- **Relationships** (`relationships.py`) — infers entity→entity edges from foreign
  keys and co-occurrence (deterministic) plus LLM for implied links.
- **Graph projection** (`graph/`) — wipe-and-rebuild projection of
  ontology/entities/relationships. Local: `falkor_store.py` → FalkorDB with
  Cypher/provenance threads. OCI: `oracle_graph_store.py` + `oracle_graph_reader.py`
  → ADB 26ai backing tables (`aryx_graph_vertex/edge/source/provenance`) with
  `CREATE PROPERTY GRAPH` DDL and SQL/PGQ traversals; activated by
  `ARYX_GRAPH_BACKEND=oci_graph`. Container and pipeline routing points updated
  transparently in `ports/container.py` and `pipeline/orchestrate.py`.
- **Worker** (`worker/`) — async document dispatch. Local: `ThreadPoolExecutor`
  in `api/file_ingest_api.py`. OCI Functions: `worker/oci_functions_worker.py`
  fires one `invoke_function(invoke_type="detached")` per file (base64 payload,
  202-detached). OCI Data Flow: `worker/oci_dataflow_worker.py` submits a
  `create_run()` for a pre-deployed PySpark application. Routing in
  `file_ingest_api.py` keyed on `effective_worker_backend()`.
- **Queries** (`queries/`) — SQL-file loader keeping SQL out of Python (DB-Guard).
  Oracle overrides in `queries/oracle/` (e.g. `adjudication_stats.sql` replaces
  `COUNT(*) FILTER` with `COUNT(CASE WHEN ...)`). Not every caller uses this
  loader — a few stores (`shay_bridge_store.py`) build SQL inline and must
  branch on `effective_db_backend() == "oci"` themselves for anything Oracle
  has no equivalent syntax for (Postgres `ON CONFLICT ... DO UPDATE` has no
  Oracle counterpart; `oracle_pool.py`'s `_translate_sql()` raises loudly on
  it rather than silently degrading).
- **CPQ engine** (`cpq/`) — turns a conversational sales request into a
  rule-checked quote. `intent_gateway.py` is an LLM-first router
  (`dispatch`/`clarify`/`fallback`) that resolves a value only against
  candidate lists built in our own code, never free text from the model.
  `engine.py` holds the per-session state machine and three attribute tiers:
  user-answered, rule/default-filled, and catalog-mandatory
  (`mandatory_tier_c_vns()`, reading the ingested `AttrSequence` Data Table's
  `optionOrReqFlag == "R"` live — not hardcoded per catalog).
  `data_table_resolver.py` detects Data Table CSVs by column shape, not
  filename (sequence/hierarchy/region-rule/series-mapping shaped).
  `layout_source.py` reads a separate, purely cosmetic `.txt` layout export
  (`config_layouts/*.txt`, dir from `ARYX_CPQ_LAYOUT_DIR`) for beautify/summary
  display order only. `ask_api.py`'s turn loop refuses to ever present a
  quote with an unresolved mandatory field, even at the turn cap. See
  `docs/diagrams/cpq-engine-technical-flow.html` for the full flow.
- **Attribute-first discovery** (`cpq/attribute_search/`, `api/ask_attribute_*.py`,
  flag `ARYX_CPQ_ATTR_SEARCH_ENABLED`, off by default) — a cold-start message
  that names an attribute instead of a product ("a product with ATT as a
  carrier") is routed by `classify_ask_route` to `attribute_search`. The
  phrase is grounded deterministically against real catalog labels (no
  LLM), matched against each family's menu options / yes-no attributes and
  the Data Table, then hands off into the normal quote: 1 family starts it
  with the value pre-filled as a "hint" (still re-validated by the engine's
  constraint check), 2..N are offered via the existing `pending_scope`
  product choice, "which value?" is remembered in `CpqSession.
  pending_attribute_label`. Read-only over the catalog; per-family menu
  snapshots are cached 5 min and cleared on re-ingest. See
  `docs/cpq/CPQ_ATTRIBUTE_FIRST_DISCOVERY_PLAN_2026_10_02.md`.
- **Shay bridge** (`api/shay_bridge_api.py`, `store/shay_bridge_store.py`) —
  connects Shay (a separate sales-assistant FastAPI service + Next.js UI,
  `shay_backend/`, its own schema in the same Oracle ADB in OCI mode) to
  Aryx. Shay never touches Aryx's schema directly — every one of its 9+
  outbound calls (workspace bridge ensure/update/delete/mapping, chat ask,
  doc read/summary/confirm, job status) goes through this API surface.
  Workspace/chat bridge rows use an Oracle `MERGE`/plain-`INSERT` upsert
  (not `ON CONFLICT`), and `sync_state` merges via `JSON_MERGEPATCH` with a
  `CASE WHEN ... IS JSON` guard that self-heals any row corrupted by an
  earlier version of this code that used Postgres's `||` jsonb-merge
  operator (Oracle treats `||` as string concatenation).
- **MCP** (`mcp/`) — tool server for Claude Desktop / Cursor / Continue over
  SSE (`aryx.mcp.sse:app`, port 8765). Most tool calls proxy to `api` over
  HTTP (`ARYX_API_URL`); only bearer-token authentication (`McpTokenStore`)
  and direct action execution (`ActionStore`) connect to the database
  directly.
- **Web** (`apps/web/`, Next.js/TypeScript) — the only user-facing UI in the
  OCI deployment. Never talks to Oracle or to `api`/`shay-api` from the
  browser directly; a server-side route handler
  (`app/api/[...path]/route.ts`, `_aryxProxy.ts`) proxies same-origin and
  injects the shared `x-aryx-api-key`, so the browser never holds it.
- **Config / logging** (`config.py`, `logging_setup.py`) — 12-factor settings from
  `ARYX_`-prefixed env vars; credentials never logged. Scalability caps:
  `ARYX_MAX_BLOCK_SIZE` (5000), `ARYX_GRAPH_QUERY_LIMIT` (500),
  `ARYX_MAX_RELATE_PAIRS` (50), `ARYX_TRANSITIVE_MAX_DEPTH` (4),
  `ARYX_WORKER_THREADS` (4), `ARYX_RULES_DB_WARN_THRESHOLD` (20).
  OCI backend selectors: `ARYX_OCI_MODE` (convenience flag), plus per-service
  overrides `ARYX_PARSE_BACKEND`, `ARYX_EMBED_BACKEND`, `ARYX_LLM_CHEAP_BACKEND`,
  `ARYX_LLM_FRONTIER_BACKEND`, `ARYX_DB_BACKEND`, `ARYX_WORKER_BACKEND`,
  `ARYX_GRAPH_BACKEND`. All Phase 2 vars are fully wired (Phase 2 complete).

### Data Flow
```
Sources (Postgres, + Drive/Salesforce/Odoo planned)
  → Connector.extract()
  → clean → profile          (stages 1–3, streaming spine)
  → land in RDB w/ provenance (stage 2 sink)
  → tag fields               (stage 4, cheap tier)
  → ontology mapping agent   (stage 5a, frontier + HITL gate)
  → resolution funnel        (stage 5b: normalize→block→score→adjudicate→cluster)
  → relationship inference   (stage 5c)
  → FalkorDB projection       (stage 5d, rebuildable from RDB)
```

### Deployment Topology
- Cloud: AWS (secrets via `boto3` / Secrets Manager / SSM) or OCI (Document
  Understanding, GenAI, ADB 26ai, Functions, Data Flow — enabled per-service
  via `ARYX_*_BACKEND` env vars; all OCI services share one compartment ID +
  IAM instance principal auth)
- Compute: containerized 12-factor `worker`; production orchestrator (ECS/EKS/OCI)
  decided at rollout — not yet fixed
- Database: PostgreSQL 16 (source of truth) OR Oracle ADB 26ai (`ARYX_DB_BACKEND=oci`; 42 Oracle migrations, oracledb wrapper pool, dialect-aware query loader). One Oracle ADB instance holds both the Aryx schema and Shay's own schema (created via SQLAlchemy on first boot, no Alembic on Oracle).
- Graph: FalkorDB (rebuildable projection) OR Oracle Property Graph (`ARYX_GRAPH_BACKEND=oci_graph`; backing relational tables + `CREATE PROPERTY GRAPH` + SQL/PGQ)
- Worker: ThreadPoolExecutor (local) OR OCI Functions (`ARYX_WORKER_BACKEND=oci_functions`, per-doc detached invoke) OR OCI Data Flow (`oci_dataflow`, batch Spark)
- Local dev: `docker-compose.yml` — `postgres` (host port 55432), `falkordb`
  (6379), `worker` (built from `Dockerfile`); worker waits on a healthy Postgres
- OCI deployment: `docker-compose-oci.yml` — `api` (FastAPI, :8088), `shay-api`
  (Shay's own FastAPI, :8090), `mcp` (SSE tool server, :8765), `web` (Next.js,
  :3000), `pgx-server` (Oracle PGX, optional — `--profile pgx`, and note:
  `PGX_SERVER_URL` is declared in this compose file but not currently read by
  any application code — `api`'s graph reads go directly to Oracle's SQL/PGQ,
  not through pgx-server). See `docs/aryx_oracle_adb_architecture.html` for
  the full service-to-database connectivity map.

### Tech Stack
- Language: Python 3.13 (SQL in `.sql` files; YAML for infra); TypeScript
  (Next.js 15, `apps/web/`) for the OCI deployment's web UI
- Frontend: `apps/web/` (Next.js/TypeScript) in OCI mode; none in the plain
  batch/worker local deployment
- Data / models: pydantic 2.x, pydantic-settings, psycopg 3 (binary), anthropic,
  falkordb; local embeddings via Ollama
- Infra: Docker, Docker Compose; AWS (boto3)

### Architecture Decisions
| Decision | Rationale | Date |
|---|---|---|
| RDB is source of truth; FalkorDB is a rebuildable projection | Graph can be wiped and rebuilt from Postgres anytime; no graph-only state to lose | 2026-05-28 |
| Streaming, one-record-at-a-time spine (no full-dataset load) | Same code path serves a small table or a terabyte — slower, not crashing | 2026-05-28 |
| Resolution funnel; frontier LLM only on the ambiguous ~1–5% | Cheap/local/deterministic layers shrink n² so frontier dollars are rationed | 2026-05-28 |
| Provider-agnostic Broker with tiered routing | Decouple from any single vendor (Anthropic/Ollama/OpenAI-compatible) | 2026-05-28 |
| Local Ollama is the default embedding backend | Keeps private data on-box unless an operator explicitly selects a managed backend | 2026-05-28 |
| HITL gate for new ontology types + low-confidence merges | Nothing untraceable lands; human decisions become future ER training labels | 2026-05-28 |
| SQL kept out of Python via `queries/*.sql` loader | DB-Guard discipline; reviewable, lint-able SQL | 2026-05-28 |
| OpenAI endpoints blocked in manifest | Prevent private-data egress to non-approved providers | 2026-05-28 |
| OCI backend toggle via env vars | Per-service opt-in to OCI managed services without code changes; local default preserves existing deployments | 2026-06-22 |
| Lazy OCI SDK imports (inside function bodies) | `oci` package never imported at module level — local deployments work without it installed | 2026-06-22 |
| OCI auth singleton with instance-principal fallback | Single `oci_client.py` factory covers all OCI services; uses IAM instance principal on OCI Compute, falls back to `~/.oci/config` for local dev | 2026-06-22 |
| `input_type` on `Broker.embed()` | Cohere Embed v3 accuracy depends on whether the text is a document being indexed or a query at retrieval time; callers explicitly pass the type | 2026-06-22 |
| Gemini embeddings are explicit opt-in | `ARYX_EMBED_BACKEND=gemini` sends source text to Google; deployments must approve that egress and applicable data-handling terms. API keys travel in the `x-goog-api-key` header, never the URL | 2026-07-21 |
| Embedding identity follows the effective backend | Every persisted vector is labeled with the model that produced it, preventing Gemini vectors from being stored as `nomic-embed-text` | 2026-07-21 |
| Oracle pool wrapper (oracle_pool.py) translates psycopg3 → oracledb | All 19 store classes work unchanged; translation (param style, RETURNING, Json unwrap) happens in wrapper — no store edits needed | 2026-06-22 |
| Oracle Property Graph uses relational backing tables | Vertex/edge/source/provenance stored as plain Oracle tables; `CREATE PROPERTY GRAPH` maps them for SQL/PGQ traversals — rebuildable same as FalkorDB path | 2026-06-22 |
| OCI Functions worker uses `invoke_type="detached"` | Fire-and-forget (HTTP 202) — function runs async; ingest API returns immediately; job progress written from inside the function via DSN in payload | 2026-06-22 |
| Postgres `ON CONFLICT ... DO UPDATE` gets an explicit Oracle branch, never a generic translation | `_translate_sql()` raises loudly instead of silently degrading to insert-or-ignore — a prior silent-degrade caused real, hard-to-detect data corruption (`sync_state` doubled as text on every repeat call) before this was caught | 2026-09-03 |
| CPQ mandatory-field detection reads the ingested catalog live, not a hardcoded rule | `mandatory_tier_c_vns()` keys off the real `AttrSequence` Data Table's `optionOrReqFlag`, so two environments with different catalog ingests will legitimately ask different questions for the same product — this is correct behavior, not a routing bug | 2026-09-03 |
| Shay never queries Aryx's Oracle schema directly | Every Shay→Aryx interaction goes through `api`'s `/admin/shay/*` surface, authenticated by a shared `x-aryx-api-key`; keeps the schema boundary and the auth boundary at the same place | 2026-09-03 |
