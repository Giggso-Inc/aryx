# Aryx Lite — a lightweight ontology layer for quick outcome mapping

> **This repo is Aryx Lite (v1)** — the fast, approachable front door:
> point it at your data, and in minutes you have a deduplicated, linked
> knowledge graph you can ask questions of. Bundled Postgres + FalkorDB +
> an Ollama-backed Ask layer for the shared dev server; built for a single
> team's quick outcome mapping, not yet a
> governed enterprise estate.
>
> **Editions:** **Aryx Lite** (v1, this repo — candidate for GPL) ·
> **Aryx Enterprise** (v2 — scale, governance, sovereignty, the Accuracy
> Lab) · **Aryx-o** (v2.1 — Enterprise native on Oracle ADB and other
> hyperscalers). See [docs/EDITIONS.md](docs/EDITIONS.md).

**Aryx** ingests records from databases and documents, resolves duplicates across sources into single entities, infers relationships, and builds a searchable knowledge graph. Use it to reason over messy, multi-source data — customers from Postgres and Salesforce, support tickets from email and Jira, products from inventory and e-commerce — all deduplicated and linked in one place.

## Features

### Ingest & Discovery
- **Multi-source ingest** — Postgres, MySQL, Oracle connectors; CSV/PDF/DOCX/PPTX/JSON file upload
- **Auto-discovery** — AI agent maps source schemas to entity types; no upfront ontology required
- **Ontology HITL gate** — Proposed types queue for human approval; OWL/Turtle/JSON-LD import + RDF export
- **Streaming pipeline** — One-record-at-a-time extract → land → tag → map (memory-bounded at any scale)

### Entity Resolution
- **Multi-key blocking** — Prefix + token-set + Soundex keys with block-size cap (G2)
- **Four-band adjudication** — Auto-merge (>=0.92), LLM-adjudicate (0.90-0.92), human-review (0.75-0.90), reject (<0.75); thresholds from measured sweep
- **Human-in-the-loop queue** — Ambiguous pairs queue for steward review; every decision persists as labeled training data (data moat)
- **Survivorship policies** — Five strategies (first-non-empty, source-priority, most-recent, most-complete, most-frequent) with per-attribute overrides and conflict audit trail
- **Cluster confidence** — Weakest merge-edge score, clamped [0.5, 0.99]; human edges score 0.99; entities never claim 1.0
- **Chunked resolution** — 3-pass streaming (key → score → cluster) for datasets that exceed memory; memory bound = largest block
- **Stage checkpoints** — Pipeline stages track running/done/failed; crashed runs resume from last completed stage

### Knowledge Graph
- **Interactive graph** — FalkorDB projection with entity drill-down, neighbor traversal, shortest-path queries
- **Incremental projection** — Dirty-set watermark computation; auto-selects full or incremental mode (<30% dirty = incremental)
- **Provenance threads** — Every entity traces back to source records across all contributing systems

### Intelligence
- **Chat (Ask)** — Natural-language queries with LLM reasoning, source provenance, and conversation context
- **MCP integration** — 3 tools (list, ask, act) for external AI agents; SSE transport
- **Actions (kinetic layer)** — Declarative JSON DSL mutations with guard conditions, human approval gate, and before/after audit log; agent-initiated actions are always-pending

### Platform
- **Workspace isolation** — LIST-partitioned Postgres tables; independent graphs, ontologies, and policies per workspace
- **Shared + cloud models** — dev-server Ollama for cheap stages (tagging, scoring); Claude/OpenAI/Gemini for frontier decisions (~1-5% of volume)
- **API-key auth** — Off/optional/required modes; fail-closed (exceptions reject, never pass)
- **Connection pooling** — psycopg3 shared pool singleton; all 10 stores pooled
- **23 idempotent migrations** — Auto-apply on API startup; zero manual migration steps
- **Measured quality** — `make er-bench` on Febrl1: P=1.00 / R=0.59 / F1=0.74; band thresholds derived from measured sweep, not opinion

## Quick Start

```bash
git clone https://github.com/giggsoinc/aryx.git
cd aryx
docker compose -f docker-compose.local.yml up -d
# UI: http://localhost:8501
# API: http://localhost:8088/docs
```

First time? **Ingest tab** → provide context (e.g., "Customer support accounts with company info") → connect a database or upload files.

### Validate CPQ rule evaluation

Run the read-only deterministic checker against an ingested CPQ catalog:

```bash
PYTHONPATH=src python scripts/check_cpq_rule_loop.py \
  --workspace-id 1 \
  --product "APX Next" \
  --strict-unknown \
  --output cpq-rule-report.json
```

The checker exercises every catalog option and discoverable rule branch, runs an
independent `hide → recommend → constrain → auto-fill` oracle to a fixed point,
and compares it with the production engine. Exit codes are `0` for a clean run,
`1` for rule/state mismatches, and `2` for setup or catalog-loading failures.

### Run the CPQ regression suite

The intent classifier and its guardrails are gated by a 50-positive +
50-negative scenario suite in
[`benchmarks/cpq_intent/CPQ_REGRESSION_SUITE.md`](benchmarks/cpq_intent/CPQ_REGRESSION_SUITE.md).
It runs automatically on every `git push` (pre-push hook) and inside
`make test`; run it by hand with:

```bash
make cpq-regression
```

This is offline (no LLM, no DB — finishes in ~1s) and checks: case counts,
intent labels against the `IntentCategory` schema, the quote / off-topic /
undo / guided detectors, and the gateway quarantine + session-snapshot
invariants. Exit `0` = pass, `1` = regression, and a failing run blocks the
push (bypass in emergencies with `git push --no-verify`).

Full LLM scoring of every case (needs Gemini credentials):

```bash
PYTHONPATH=src python3 benchmarks/cpq_intent/run_regression.py --live
```

To add scenarios, append rows to the suite's markdown tables using the next
free `P##`/`N##` id — never renumber existing ids. Details:
[`benchmarks/cpq_intent/README.md`](benchmarks/cpq_intent/README.md).

## Documentation

| Guide | What it covers |
|-------|---------------|
| **[Install Guide](docs/INSTALL.md)** | Local Docker setup, EC2 deployment, git-only update flow, tuning env keys |
| **[User Guide](docs/USER_GUIDE.md)** | UI walkthrough, ingest, Ask, Graph, adjudication queue, actions, survivorship |
| **[Feature Matrix](docs/FEATURES.md)** | All capabilities with status and component references |
| **[Architecture](docs/ARCHITECTURE.md)** | System design, resolution funnel, data flow, 23 API routes, 3 MCP tools |
| **[Ingestion Guide](docs/INGESTION_GUIDE.md)** | Database and document ingest step-by-step |
| **[RDF Export](docs/RDF_EXPORT_GUIDE.md)** | Export to SPARQL, semantic web tools, LLM pipelines |
| **[Benchmarks](docs/wiki/BENCHMARKS.md)** | Append-only P/R/F1 measurements |
| **[Program Close](docs/wiki/PROGRAM_CLOSE.md)** | Gap-closure decisions (DEC-001..006), v2 backlog |

**Interactive diagrams:** [Business View](docs/diagrams/business-view.html) | [Technical Flow](docs/diagrams/technical-flow.html)

## Stack

| Layer | Tech |
|-------|------|
| **API** | FastAPI (23 routers, OpenAPI docs) |
| **UI** | Streamlit |
| **Database** | PostgreSQL 16 (source of truth, LIST-partitioned) |
| **Graph** | FalkorDB (rebuildable projection) |
| **LLM** | Shared/OCI Ollama + Anthropic Claude / OpenAI / Gemini (frontier) |
| **Agent protocol** | MCP (list, ask, act) over SSE |
| **Deployment** | Docker Compose (localhost + OCI dev server) |

## Contributing

See [CLAUDE.md](CLAUDE.md) for development practices (Raven discipline).

## License

MIT
