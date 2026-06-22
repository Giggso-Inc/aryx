## Version: 1.2
## Last Updated: 2026-06-22
## Project: Aryx

### System Overview
Aryx ingests records from many heterogeneous sources, lands them in a relational
store with full provenance, semantically tags their fields, then reasons over
them to build a knowledge graph: it maps source schemas to a canonical ontology,
resolves duplicate records across systems into single entities, infers
relationships, and projects the result into FalkorDB. The relational database is
the permanent source of truth; the graph is a rebuildable projection. Expensive
frontier-LLM reasoning is rationed by a funnel of cheap, deterministic and local
stages so the model only touches the hard ~1–5% of decisions.

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
  credentials; supports Anthropic, Ollama, OpenAI-compatible, and OCI GenAI
  (4th provider path, activated via `ARYX_OCI_MODE` or per-service backend vars).
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
- **Graph projection** (`graph/falkor_store.py`) — wipe-and-rebuild projection of
  ontology/entities/relationships into FalkorDB with provenance threads.
- **Queries** (`queries/`) — SQL-file loader keeping SQL out of Python (DB-Guard).
- **Config / logging** (`config.py`, `logging_setup.py`) — 12-factor settings from
  `ARYX_`-prefixed env vars; credentials never logged. Scalability caps:
  `ARYX_MAX_BLOCK_SIZE` (5000), `ARYX_GRAPH_QUERY_LIMIT` (500),
  `ARYX_MAX_RELATE_PAIRS` (50), `ARYX_TRANSITIVE_MAX_DEPTH` (4),
  `ARYX_WORKER_THREADS` (4), `ARYX_RULES_DB_WARN_THRESHOLD` (20).
  OCI backend selectors: `ARYX_OCI_MODE` (convenience flag), plus per-service
  overrides `ARYX_PARSE_BACKEND`, `ARYX_EMBED_BACKEND`, `ARYX_LLM_CHEAP_BACKEND`,
  `ARYX_LLM_FRONTIER_BACKEND`. Phase 2 vars (`ARYX_DB_BACKEND`,
  `ARYX_WORKER_BACKEND`, `ARYX_GRAPH_BACKEND`) are defined but not yet wired;
  a `model_validator` warns at startup if they are set to non-default values.

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
  Understanding, GenAI, ADB 23ai, Functions, Data Flow — enabled per-service
  via `ARYX_*_BACKEND` env vars; all OCI services share one compartment ID +
  IAM instance principal auth)
- Compute: containerized 12-factor `worker`; production orchestrator (ECS/EKS/OCI)
  decided at rollout — not yet fixed
- Database: PostgreSQL 16 (source of truth); Oracle ADB 23ai (Phase 2, `ARYX_DB_BACKEND=oci`)
- Graph: FalkorDB (rebuildable projection); Oracle Graph Studio (Phase 2, `ARYX_GRAPH_BACKEND=oci_graph`)
- Local dev: `docker-compose` — `postgres` (host port 55432), `falkordb` (6379),
  `worker` (built from `Dockerfile`); worker waits on a healthy Postgres

### Tech Stack
- Language: Python 3.13 (SQL in `.sql` files; YAML for infra)
- Frontend: none (batch/worker service)
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
| Local Ollama embeddings for blocking | Anthropic has no embeddings API; keeps private data on-box, avoids egress | 2026-05-28 |
| HITL gate for new ontology types + low-confidence merges | Nothing untraceable lands; human decisions become future ER training labels | 2026-05-28 |
| SQL kept out of Python via `queries/*.sql` loader | DB-Guard discipline; reviewable, lint-able SQL | 2026-05-28 |
| OpenAI endpoints blocked in manifest | Prevent private-data egress to non-approved providers | 2026-05-28 |
| OCI backend toggle via env vars | Per-service opt-in to OCI managed services without code changes; local default preserves existing deployments | 2026-06-22 |
| Lazy OCI SDK imports (inside function bodies) | `oci` package never imported at module level — local deployments work without it installed | 2026-06-22 |
| OCI auth singleton with instance-principal fallback | Single `oci_client.py` factory covers all OCI services; uses IAM instance principal on OCI Compute, falls back to `~/.oci/config` for local dev | 2026-06-22 |
| Phase 2 backend vars defined but not wired | Env vars stable across phases; `model_validator` warns operators who set them before implementation ships | 2026-06-22 |
| `input_type` on `Broker.embed()` | Cohere Embed v3 accuracy depends on whether the text is a document being indexed or a query at retrieval time; callers explicitly pass the type | 2026-06-22 |
