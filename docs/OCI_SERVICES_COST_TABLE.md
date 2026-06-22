# aryx-o — OCI Services Reference Table

**Project:** aryx Knowledge Graph Platform (Oracle Edition)
**Date:** 2026-06-20

---

| # | Service | Purpose in aryx | Configuration | Monthly Cost (Small / Medium / Large) | Scalability |
|---|---|---|---|---|---|
| 1 | **OCI Object Storage** | Staging bucket for uploaded files; stores Spark scripts, logs, RDF exports | Standard tier · 1 bucket · lifecycle policy: delete staging files after 7 days | $0 / $0.05 / $0.26 | Linear — $0.0255/GB/month. Auto-scales to petabytes. No throughput cap. |
| 2 | **OCI Document Understanding** | Replaces pymupdf + pytesseract. Parses PDFs with layout awareness, table detection, and scanned OCR. Fixes P1 parse quality gap. | REST API — no provisioning. Call `analyze_document` per file. Enable: Text Detection + Table Detection. Always Free: 1,000 pages/month. | $46 / $345 / $2,300 | Per-page pricing. Parallel API calls handled by OCI. No concurrency limit documented. |
| 3 | **OCI Generative AI — Embed** | Embeds chunks into 768-dim vectors stored in `aryx_chunk_embedding`. Cohere Embed v3 Multilingual. | No provisioning — REST API via `generativeai.GenerativeAiInferenceClient`. Batch up to 96 texts per call. Region: us-chicago-1. | $0.20 / $1.20 / $8.00 | $0.0001/1K tokens. OCI auto-scales inference fleet. No rate limit at standard tier. |
| 4 | **OCI Generative AI — Command R** | Entity + relationship extraction per chunk. Runs LLMGraphTransformer prompt. Replaces `extract_mentions()` single-entity calls with triple extraction. | Same client as Embed. Model: `cohere.command-r-08-2024`. Set `max_tokens=1024`, `temperature=0`. Use for extraction only (menial tier). | $9.30 / $55.80 / $372 | $0.00015/1K input + $0.00060/1K output. Scales horizontally — concurrent calls supported. |
| 5 | **OCI Generative AI — Command R+** | Ask synthesis and Select AI NL→SQL translation. Frontier tier only — higher accuracy for natural language answers. | Same client. Model: `cohere.command-r-plus-08-2024`. Reserved for Ask flow and CQ generation only. Do not use for bulk extraction. | $46 / $230 / $1,150 | $0.003/1K input + $0.015/1K output. Horizontally scalable. Use Command R for cost control at scale. |
| 6 | **Oracle Autonomous Database 23ai** | Converged store: relational tables (`aryx_entity`, `aryx_chunk`), vector store (`aryx_chunk_embedding`), SQL:2023 property graph (`GRAPH_TABLE`), Select AI NL→SQL, and RDF via Graph Studio. Replaces FalkorDB projection bottleneck (P1). | OCI Console → Oracle Database → Autonomous Database → Create. Workload: Transaction Processing. ECPUs: 2 (Small), 4 (Medium), 8 (Large). Storage: 100 GB (Small), 500 GB (Large). Enable: Vector Search, Graph Studio, Select AI. | $40 / $65 / $180 | Auto-scale ECPUs 1–128. Storage grows on demand. SQL:2023 graph runs on indexed relational tables — no separate projection job. |
| 7 | **Oracle Graph Studio (RDF)** | SPARQL endpoint over OWL/Turtle export from `rdf/exporter.py`. Enables CQ execution via `SEM_MATCH`. Bundled in ADB — no separate service. | Enabled automatically with ADB 23ai. Load RDF model via Graph Studio UI or REST: `POST /rdf/admin/managed/models`. SPARQL endpoint: `https://{adb-host}/rdf/store`. | $0 (bundled in ADB) | Scales with ADB ECPU allocation. RDF reasoning (RDFS++) runs in-database. |
| 8 | **Oracle PGX (Graph Server)** | OWL 2 RL reasoning engine. Replaces Python rule loop in `reasoning/engine.py` (P2 bottleneck — O(rules × entities)). Runs as a batch job after each ingest cycle. | OCI Marketplace → Oracle Graph Server. Shape: VM.Standard.E4.Flex (2 OCPU, 32 GB). Always Free option: VM.Standard.A1.Flex (4 OCPU, 24 GB). Open port 7007 for PGX REST API. | $0 (A1.Flex) / $36 / $73 | PGX is in-memory graph. Scales by loading graph partitions. For >50M edges, use PGX distributed mode (additional VMs). |
| 9 | **OCI Functions** | Serverless pipeline worker. Replaces `BackgroundTasks.add_task()` (P4 bottleneck — single-threaded). Each document upload triggers one function invocation. Multiple documents run in parallel automatically. | OCI Console → Developer Services → Functions → Create Application. Functions: `aryx-ingest-fn` (512 MB, 300s timeout), `aryx-resolve-fn` (1 GB, 600s timeout). Always Free: 2M calls + 400K GB-sec/month. | $0 / $0.36 / $4.89 | Auto-scales to thousands of concurrent invocations. Concurrency limit configurable per function (default 40). 6-minute max per invocation — use Data Flow for large docs. |
| 10 | **OCI Data Flow (Apache Spark)** | Managed Spark batch worker. Alternative to OCI Functions for bulk ingestion (100+ documents, nightly jobs). Distributes pipeline stages across executors — one partition per N documents. Fixes P4 at batch scale. | OCI Console → Analytics & AI → Data Flow → Create Application. Language: Python. Driver: VM.Standard.E4.Flex (2 OCPU). Executors: VM.Standard.E4.Flex (2 OCPU) × 4. Script: stored in Object Storage. | $0.30 / $0.70 / $0.90 | Scale executors 1–64 per job. Auto-scaling supported. Spark handles retry and lineage — replaces `StageRunner` checkpoint logic for batch runs. |

---

## Scalability Summary

| Bottleneck | Bottleneck Source | OCI Service That Fixes It | Mechanism |
|---|---|---|---|
| P1 — fetchall RAM spike | `entity_store.py` — full table to Python list | Oracle ADB 23ai | SQL:2023 property graph runs on ADB indexes — no Python-side projection |
| P2 — Python rule loop | `reasoning/engine.py:115` | Oracle PGX | OWL 2 RL rules execute in native Java graph engine — 10–100× faster |
| P3 — silent 5000 block drop | `resolution/blocking.py:100` | OCI Data Flow | Spark partitions blocks — no in-memory cap |
| P4 — single-threaded worker | `file_ingest_api.py:132` | OCI Functions / Data Flow | Functions: one invocation per doc. Data Flow: one executor per doc partition |
| P5 — 500-result graph cap | `graph/reader.py:63` | Oracle ADB 23ai | No hard cap — query returns full result set via SQL pagination |
| P6 — 50-pair relate cap | `pipeline/orchestrate.py:50` | OCI GenAI (LLMGraphTransformer) | Extracts all triples per chunk in one call — no pair limit |
| P7 — 4-hop transitive limit | `reasoning/edge_axioms.py:17` | Oracle PGX | Full transitive closure computed natively — configurable depth |

---

*OCI public pricing — US Midwest (Chicago) region. Always Free allocations applied at Small scale.*
