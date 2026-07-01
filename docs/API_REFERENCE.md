# Aryx API Reference

All routes are served by FastAPI under the base path `/api` (proxied by Next.js).
Workspace-scoped routes accept `?workspace_id=<int>` unless noted otherwise.

---

## Summary

| Module | Prefix | Purpose |
|--------|--------|---------|
| [Workspace](#workspace) | `/admin/workspaces` | Create, configure, and purge workspaces |
| [File Ingest](#file-ingest) | `/admin/ingest/file` | Upload files (PDF, DOCX, CSV, images) for entity extraction |
| [DB Ingest](#db-ingest) | `/admin/ingest/db` | Trigger structured database ingest pipeline |
| [REST Ingest](#rest-ingest) | `/ingest/rest` | Fetch and ingest remote REST/JSON sources |
| [Doc Discover](#doc-discover) | `/admin/docs` | Discover, classify, and confirm document uploads |
| [Jobs](#jobs) | `/admin/jobs` | Monitor, cancel, resume, and archive ingest jobs |
| [Ingest Questions](#ingest-questions) | `/admin/ingest-questions` | Clarifying questions raised mid-pipeline; human answers unblock pipeline |
| [Connect](#connect) | `/admin/connect` | Test DB connections, discover schema, ingest confirmed tables |
| [Datasources](#datasources) | `/admin/datasources` | Store and manage encrypted datasource credentials |
| [Graph](#graph) | `/` (root) | Query entity graph — neighbors, paths, Cypher, provenance |
| [Data](#data) | `/data` | Summarise entities, list with filters, derive relationships |
| [Ask](#ask) | `/ask` | Natural-language Q&A over the knowledge graph |
| [Ask History](#ask-history) | `/ask/history` | Retrieve past Q&A turns for a workspace |
| [Ontology](#ontology) | `/ontology` | Manage types, approve proposals, export/import RDF/OWL |
| [Ontology Versions](#ontology-versions) | `/ontology-versions` | Snapshot and audit ontology change history |
| [Ontology Assist](#ontology-assist) | `/ontology/assist` | AI-suggested attribute names for entity types |
| [Axioms](#axioms) | `/ontology/axioms` | Create and validate logical axioms; serve SHACL shapes |
| [Relationship Types](#relationship-types) | `/ontology/relationships` | Declare and manage relationship type vocabulary |
| [Rules](#rules) | `/rules` | Create, toggle, delete, and evaluate workspace rules |
| [Adjudication](#adjudication) | `/adjudication` | Human-in-the-loop merge decisions for entity resolution |
| [Actions](#actions) | `/actions` | Define, execute, approve/reject governed pipeline actions |
| [Admin](#admin) | `/admin` | Graph rebuild, run history, observability dashboard |
| [Observability](#observability) | `/admin/observability` | Aggregated dashboard: jobs, LLM stats, graph counts |
| [Brief](#brief) | `/admin/workspaces/{id}/brief` | AI-drafted knowledge modelling brief for a workspace |
| [Lab](#lab) | `/lab` | Experimental: A/B ontology comparison, axiom contradiction check |
| [MCP Tokens](#mcp-tokens) | `/admin/mcp/tokens` | Issue and revoke MCP bearer tokens |
| [Demo](#demo) | `/demo` | Load synthetic support-ticket demo data |

---

## Workspace

**Prefix:** `/admin/workspaces`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List all workspaces |
| `POST` | `/` | Create a new workspace |
| `PATCH` | `/{workspace_id}/context` | Set free-text context for a workspace |
| `GET` | `/{workspace_id}/survivorship` | Get survivorship (merge confidence) policy |
| `PUT` | `/{workspace_id}/survivorship` | Replace survivorship policy |
| `PATCH` | `/{workspace_id}/brief` | Set the knowledge-modelling brief |
| `POST` | `/nuke` | Factory reset — truncate all data, drop non-Default workspaces |
| `POST` | `/{workspace_id}/purge` | Delete all data in a workspace but keep the workspace row |
| `DELETE` | `/{workspace_id}` | Delete entire workspace including graph projection |

---

## File Ingest

**Prefix:** `/admin`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest/file` | Upload one or more files (JSON / CSV / PDF / DOCX / PPTX / images) and run the full entity extraction pipeline |
| `GET` | `/ingest/supported` | Return supported file types and per-type upload size limits |

---

## DB Ingest

**Prefix:** `/admin`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest/db` | Trigger the structured DB ingest pipeline with durable job tracking |
| `POST` | `/graph/rebuild` | Rebuild the FalkorDB graph projection from the relational store (safe to run at any time) |
| `GET` | `/runs` | List the 50 most recent ingestion runs |

---

## REST Ingest

**Prefix:** `/ingest/rest`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/preview` | Fetch a remote URL and return the first 10 records with inferred type |
| `POST` | `/ingest` | Fetch all pages from a remote endpoint and run the full entity pipeline |

---

## Doc Discover

**Prefix:** `/admin/docs`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/read` | Upload files and start a background discovery job to classify document types |
| `GET` | `/summary/{did}` | Poll discovery results for a given `discovery_id` |
| `POST` | `/confirm` | Confirm approved document types and start the ingest job |

---

## Jobs

**Prefix:** `/admin`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/jobs` | List recent ingest jobs for a workspace |
| `GET` | `/jobs/{job_id}` | Get full details for a specific job |
| `GET` | `/jobs/{job_id}/events` | Paginated live progress events (newest first) |
| `POST` | `/jobs/{job_id}/cancel` | Mark a job cancelled so the UI can unlock |
| `POST` | `/jobs/{job_id}/resume` | Return durable per-stage rows for resume |
| `POST` | `/jobs/archive` | Archive and purge jobs older than N days |

---

## Ingest Questions

**Prefix:** `/admin/ingest-questions`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List clarifying questions with optional status filter |
| `POST` | `/` | Pipeline-side enqueue — raise a question that blocks the pipeline |
| `POST` | `/{question_id}/answer` | Persist a human answer to unblock the pipeline |
| `GET` | `/stats` | Per-status counts for a workspace (and optional job) |

---

## Connect

**Prefix:** `/admin`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/connect` | Test a DB connection and introspect its schema |
| `POST` | `/discover` | Run agent discovery to propose an ontology mapping for discovered tables |
| `POST` | `/ingest/multi` | Ingest confirmed tables and create relationship edges |

---

## Datasources

**Prefix:** `/admin/datasources`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/kinds` | List supported datasource kinds and key configuration status |
| `GET` | `/quiz` | Return the field list for a datasource kind |
| `GET` | `/` | List datasources for a workspace (metadata only — no ciphertext) |
| `POST` | `/` | Encrypt credentials and store a new datasource |
| `POST` | `/{datasource_id}/test` | Decrypt, open, and ping a stored datasource |
| `DELETE` | `/{datasource_id}` | Hard-delete a datasource and cascade its audit trail |

---

## Graph

**Prefix:** `/` (root)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/entities` | Find entities by type, name substring, or limit |
| `GET` | `/graph` | All entities + all relationships in one call (graph canvas) |
| `POST` | `/graph/cypher` | Execute a read-only Cypher `MATCH` query |
| `GET` | `/entities/{entity_id}` | Get a single entity by id |
| `GET` | `/entities/{entity_id}/neighbors` | Get neighbouring entities |
| `GET` | `/entities/{entity_id}/provenance` | Get source provenance records for an entity |
| `GET` | `/entities/{entity_id}/path/{target_id}` | Find shortest path between two entities |

---

## Data

**Prefix:** `/data`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/summary` | Type counts, source breakdown, and dedup summary |
| `GET` | `/entities` | List entities with attributes and provenance, optionally filtered by type |
| `GET` | `/graph` | Type-level knowledge map (nodes = types, edges = relationships) |
| `POST` | `/relate` | Derive relationships from FK links and reproject the graph |

---

## Ask

**Prefix:** `/` (root)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ask` | Answer a natural-language question over the knowledge graph |
| `GET` | `/llm/config` | Get current LLM provider and model configuration |
| `POST` | `/admin/llm/config` | Update LLM provider, model, and endpoint settings |

---

## Ask History

**Prefix:** `/ask/history`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Return the most recent N Q&A turns for a workspace |

---

## Ontology

**Prefix:** `/ontology`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/config` | Get current interchange config and available export formats |
| `POST` | `/config` | Update interchange config (enable, formats, base URI, provenance) |
| `GET` | `/formats` | List supported export formats with media type and file extension |
| `GET` | `/types` | Return ontology types and relationships (Browse tab) |
| `POST` | `/types/{name}/approve` | Approve a proposed type |
| `POST` | `/types/{name}/parent` | Set or clear the parent type |
| `POST` | `/types` | Create a new ontology type manually |
| `DELETE` | `/types/{name}` | Remove a type from the workspace (schema-level only) |
| `GET` | `/export` | Serialize the workspace graph to RDF/OWL as a downloadable file |
| `POST` | `/import` | Parse an RDF/OWL file into proposed types |

---

## Ontology Versions

**Prefix:** `/ontology-versions`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/` | Create a new version snapshot of current types and rules |
| `GET` | `/` | List recent version snapshots (newest first) |
| `GET` | `/changes` | Recent ontology change-log rows |

---

## Ontology Assist

**Prefix:** `/ontology/assist`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/suggest-attrs` | Return AI-proposed attribute names for a given entity type |

---

## Axioms

**Prefix:** `/ontology/axioms` and `/ontology/shapes`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/ontology/axioms` | List all axioms in a workspace with valid kinds |
| `POST` | `/ontology/axioms` | Create an axiom (idempotent on payload hash) |
| `DELETE` | `/ontology/axioms/{axiom_id}` | Remove an axiom from a workspace |
| `POST` | `/ontology/axioms/validate` | Run axiom validation and return a summary |
| `GET` | `/ontology/shapes` | Serve the SHACL shapes graph derived from axioms as a downloadable file |

---

## Relationship Types

**Prefix:** `/ontology/relationships`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List declared relationship types for a workspace |
| `POST` | `/` | Idempotent declare of a relationship type (safe to call from canvas) |
| `DELETE` | `/{rel_id}` | Hard-delete a declared relationship type |

---

## Rules

**Prefix:** `/rules`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Return all rules in a workspace (oldest first) |
| `POST` | `/` | Create or replace a rule by `(workspace, name)` |
| `PATCH` | `/{name}/enabled` | Flip a rule's enabled flag |
| `DELETE` | `/{name}` | Delete a rule by name |
| `POST` | `/evaluate` | Run every enabled rule over the workspace; return fire counts |

---

## Adjudication

**Prefix:** `/adjudication`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List queue rows paginated (default: pending, oldest first) |
| `POST` | `/{adjudication_id}/decide` | Record a human verdict and merge entities if approved |
| `GET` | `/stats` | Pending count, approval rate, human/LLM agreement rate |

---

## Actions

**Prefix:** `/actions`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List current (non-superseded) action definitions |
| `POST` | `/` | Register a new action definition version |
| `POST` | `/{name}/execute` | Run guard + params; queue or apply based on approval setting |
| `GET` | `/executions` | Paginated list of executions (default: pending approvals) |
| `POST` | `/executions/{execution_id}/decide` | Approve or reject a pending execution |

---

## Admin

**Prefix:** `/admin`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest/db` | Trigger DB ingest pipeline |
| `POST` | `/graph/rebuild` | Rebuild FalkorDB projection from the relational store |
| `GET` | `/runs` | List 50 most recent ingestion runs |

---

## Observability

**Prefix:** `/admin`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/observability` | Aggregated dashboard: job counts, LLM call stats, graph counts, active model config |

---

## Brief

**Prefix:** `/admin/workspaces`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/{workspace_id}/draft-brief` | Start a background brief-drafting job; returns `job_id` |
| `GET` | `/{workspace_id}/brief-result/{job_id}` | Retrieve a completed brief draft |

---

## Lab

**Prefix:** `/lab`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ab` | Ontology on/off A/B comparison for one question |
| `GET` | `/reasoner` | Report how many contradictions enabled axioms would block |

---

## MCP Tokens

**Prefix:** `/admin/mcp/tokens`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List all tokens (metadata only — raw token never returned after issue) |
| `POST` | `/` | Issue a new bearer token (raw value visible once) |
| `DELETE` | `/{token_id}` | Revoke a token by id |

---

## Demo

**Prefix:** `/demo`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/load` | Load synthetic support-ticket demo data |
| `GET` | `/tickets` | List tickets, optionally filtered by status and/or priority |
| `GET` | `/agents` | List agents, optionally filtered by level |
| `GET` | `/resolutions/{ticket_id}` | Get the resolution chain for one ticket |

---

*Generated from `src/aryx/api/` — branch `dev_oci`.*
