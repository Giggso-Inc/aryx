# aryx-o — Pipeline Stage-by-Stage Cost Estimation

**Project:** aryx — Knowledge Graph & Ontology Platform
**Scope:** OCI cost for every stage of the aryx-o ingestion + query pipeline,
          including two worker options (OCI Functions vs OCI Data Flow / Spark)
**Prepared:** 2026-06-20
**Owner:** m.munir@giggso.com

---

## How to Read This Document

The aryx-o pipeline has **13 stages** from file upload to graph query.
Each stage is owned by a specific OCI service. This document covers:

- What the stage does
- Which OCI service runs it
- Exact pricing unit and rate
- Cost per document and per month at three scales

**Volume assumptions used throughout:**

| Scale | Docs/month | Pages/doc (avg) | Ask queries/month | Entities total |
|---|---|---|---|---|
| Small | 500 | 10 | 2,000 | ~500K |
| Medium | 2,000 | 15 | 10,000 | ~2M |
| Large | 10,000 | 20 | 50,000 | ~10M |

---

## Worker Architecture — Two Options

The aryx pipeline worker is the process that orchestrates all pipeline
stages for a document batch. Today aryx uses `BackgroundTasks.add_task()`
from FastAPI — a single thread inside the API process, no parallelism.

For aryx-o on OCI, two options replace this:

### Option A — OCI Functions (Serverless)

Each document upload triggers an OCI Function invocation. The function runs
one document through all pipeline stages (parse → chunk → embed → extract →
resolve) and writes results to Oracle ADB. Multiple documents run in parallel
as independent function executions — no coordination needed.

**Best for:** Variable workloads, low average volume, cost-per-invocation
billing means zero cost when no documents are being processed.

```
User uploads file
       ↓
OCI API Gateway → triggers OCI Function (per document)
       ↓
Function runs: parse → chunk → embed → extract → ADB write
       ↓
Function exits — billed only for execution time
```

### Option B — OCI Data Flow (Apache Spark)

Documents are batched and submitted as a Spark job to OCI Data Flow.
Spark distributes the pipeline across multiple executors — one executor
per document partition. The job finishes when all documents in the batch
are processed.

**Best for:** High-volume batch ingestion, predictable large loads, need
for parallel processing of large documents (legal contracts, annual reports).

```
User uploads batch of files
       ↓
OCI Object Storage (staging bucket)
       ↓
OCI Data Flow job submitted (Spark application)
       ↓
Spark Driver coordinates N Executors
Each executor: parse → chunk → embed → extract → ADB write
       ↓
Job completes — billed only for OCPU-hours used
```

---

## Stage-by-Stage Cost Breakdown

### Stage 1 — File Upload & Storage

**OCI Service:** OCI Object Storage

Files are uploaded via the aryx API and stored in Object Storage before
processing begins. The staging bucket holds raw files during pipeline
execution. Processed files are archived or deleted per lifecycle policy.

| Item | Rate | Per doc (10 pages, ~1 MB) |
|---|---|---|
| Storage (Standard tier) | $0.0255/GB/month | ~$0.000026/month |
| PUT request (upload) | $0.0034/10K requests | ~$0.00000034 |
| GET request (read by worker) | Free intra-OCI | $0 |
| Always Free | 20 GB included | $0 |

**Monthly cost:**

| Scale | Storage needed | Monthly Cost |
|---|---|---|
| Small (500 docs) | ~500 MB | **$0** (within free tier) |
| Medium (2,000 docs) | ~2 GB | **~$0.05** |
| Large (10,000 docs) | ~10 GB | **~$0.26** |

---

### Stage 2 — Document Parse & OCR

**OCI Service:** OCI Document Understanding

Replaces `PdfConnector` (pymupdf + pytesseract). OCI Document Understanding
provides layout-aware parsing — tables, key-value pairs, per-block confidence
scores, scanned PDF OCR — in a single managed API call per document.

The output (structured JSON) is written to Object Storage. The pipeline
worker reads the JSON and proceeds to chunking.

**Trigger by worker:**
- Option A (Functions): each Function invocation calls Document Understanding API
- Option B (Data Flow): each Spark executor calls Document Understanding API per partition

| Feature | Rate | Per 10-page doc |
|---|---|---|
| Text Detection (OCR) | $1.50/1,000 pages | $0.015 |
| Table Detection | $10.00/1,000 pages | $0.10 |
| Key-Value Detection | $10.00/1,000 pages | $0.10 |
| Always Free | First 1,000 pages/month | $0 |

*Most aryx documents use Text + Table = $11.50/1,000 pages = $0.115 per 10-page doc.*

**Monthly cost:**

| Scale | Pages/month | Monthly Cost |
|---|---|---|
| Small (500 docs × 10 pages) | 5,000 | **~$46** (after 1K free) |
| Medium (2,000 docs × 15 pages) | 30,000 | **~$345** |
| Large (10,000 docs × 20 pages) | 200,000 | **~$2,300** |

---

### Stage 3 — Chunk + PII Screening

**OCI Service:** OCI Functions (Option A) or OCI Data Flow (Option B)

Chunking (`chunk_pages()` — 1,000 char window, 100 char overlap) and PII
screening (`presidio`) are pure Python computation. No external API call.
Cost is compute time only.

A 10-page document produces ~40 chunks. PII screening on 40 chunks takes
~2 seconds on a standard runtime.

**Option A — OCI Functions**

```
Memory:    512 MB (presidio requires ~400 MB loaded)
Duration:  ~5 seconds per document (chunking + PII)
```

| Item | Rate | Per document |
|---|---|---|
| Invocation | $0.0000002/call | $0.0000002 |
| Compute (512 MB × 5s) | $0.00001417/100ms | $0.000709 |
| Always Free | 2M calls + 400K GB-sec/month | $0 |

**Option B — OCI Data Flow (Spark)**

Chunking + PII runs inside the Spark executor. No separate billing.
Cost is included in the overall Data Flow job (see Worker Cost section).

**Monthly cost (Option A):**

| Scale | Monthly Cost |
|---|---|
| Small (500 docs) | **~$0.36** (likely within free tier) |
| Medium (2,000 docs) | **~$1.43** |
| Large (10,000 docs) | **~$7.09** |

---

### Stage 4 — Embedding

**OCI Service:** OCI Generative AI — Cohere Embed v3 (Multilingual)

Each chunk (1,000 chars ≈ 250 tokens) is embedded to produce a 768-dim
vector stored in `aryx_chunk_embedding` (Oracle ADB vector store).
A 10-page document produces ~40 chunks → 40 embed API calls batched as one.

aryx config: `embed_dim=768`, `chunk_size=1000`, `chunk_overlap=100`

| Model | Rate | Per 40-chunk doc |
|---|---|---|
| Cohere Embed v3 Multilingual | $0.0001/1K tokens | $0.001 |
| Input: 40 chunks × 250 tokens = 10,000 tokens | | $0.001 |

**Monthly cost:**

| Scale | Docs/month | Chunks/month | Monthly Cost |
|---|---|---|---|
| Small | 500 | 20,000 | **~$0.20** |
| Medium | 2,000 | 120,000 | **~$1.20** |
| Large | 10,000 | 800,000 | **~$8.00** |

---

### Stage 5 — Entity + Relationship Extraction

**OCI Service:** OCI Generative AI — Cohere Command R (menial tier)
with LangChain LLMGraphTransformer

This is the most LLM-intensive stage. Each chunk is sent to the LLM to
extract `(entity, relationship, entity)` triples. aryx sends one extraction
call per chunk — 40 calls per 10-page document.

Each call: ~1,500 input tokens (system prompt + chunk text) + ~400 output
tokens (extracted triples as JSON).

| Model | Input | Output | Per call | Per 40-chunk doc |
|---|---|---|---|---|
| Cohere Command R | $0.00015/1K | $0.00060/1K | $0.000465 | $0.0186 |
| Cohere Command R+ | $0.00300/1K | $0.01500/1K | $0.01050 | $0.4200 |
| Meta Llama 3.1 70B | $0.00060/1K | $0.00060/1K | $0.00144 | $0.0576 |

*Recommended: Cohere Command R for extraction (fast, accurate for structured JSON output).
Reserve Command R+ for Ask synthesis and brief drafting only.*

**Monthly cost (using Cohere Command R):**

| Scale | Docs/month | Extraction calls | Monthly Cost |
|---|---|---|---|
| Small | 500 | 20,000 | **~$9.30** |
| Medium | 2,000 | 120,000 | **~$55.80** |
| Large | 10,000 | 800,000 | **~$372.00** |

---

### Stage 6 — Land to Oracle ADB

**OCI Service:** Oracle Autonomous Database 23ai

Raw records, chunks, embeddings, and extracted entities are written to
Oracle ADB. This stage includes:
- `aryx_raw_record` — one row per source record
- `aryx_chunk` — one row per chunk (text + metadata)
- `aryx_chunk_embedding` — one row per chunk (vector)
- `aryx_entity` (tentative) — pre-resolution entity candidates

Write cost is ADB ECPU time consumed during INSERT operations.

At 40 chunks per document, a batch INSERT takes ~0.5 seconds of ECPU time.

| Component | Rate | Per document |
|---|---|---|
| ADB ECPU (write ops) | $0.2072/ECPU/hr | ~$0.000029 |
| ADB Storage | $0.0218/GB/month | ~$0.00005/doc/month |

**Monthly cost:**

| Scale | Monthly Cost |
|---|---|
| Small (500 docs) | **~$0.20** |
| Medium (2,000 docs) | **~$0.80** |
| Large (10,000 docs) | **~$4.00** |

*ADB write cost is negligible — dominated by compute stages.*

---

### Stage 7 — Resolution

**OCI Service:** OCI Functions (Option A) or OCI Data Flow (Option B)

Resolution runs MultiKeyBlocker (prefix + token-set + Soundex), scoring
(string similarity + cosine distance), routing (auto/LLM/human/reject),
and UnionFind golden record merge. This is CPU-intensive Python computation.

Resolution at 500 entities takes ~10 seconds. At 5,000 entities, ~2 minutes.

**LLM adjudication (0.90–0.92 score band):**
Borderline pairs go to the LLM (Cohere Command R) for adjudication.
Typically 5–10% of candidate pairs land in this band.

| Item | Rate | Per 1,000 entities |
|---|---|---|
| Adjudication LLM calls (~50 pairs) | $0.000465/call | $0.023 |

**Option A — OCI Functions (per workspace resolution run)**

```
Memory:    1 GB (blocking + scoring in-memory)
Duration:  ~30 seconds per 1,000 entities
```

| Item | Rate | Per 1,000-entity run |
|---|---|---|
| Compute (1 GB × 30s) | $0.00001417/100ms | $0.00425 |
| LLM adjudication | $0.000465/call × 50 | $0.023 |
| Total per run | | $0.027 |

**Option B — OCI Data Flow (Spark)**

Resolution runs as a Spark stage inside the pipeline job. Blocking is
parallelised across partitions — each executor handles one block key subset.
No separate billing beyond the Data Flow job cost.

**Monthly cost (Option A):**

| Scale | Resolution runs | Monthly Cost |
|---|---|---|
| Small (500 docs → ~2 resolution runs) | 2 runs/month | **~$0.05** |
| Medium | 8 runs | **~$0.22** |
| Large | 40 runs | **~$1.08** |

---

### Stage 8 — SQL:2023 Property Graph

**OCI Service:** Oracle Autonomous Database 23ai (included)

The `CREATE PROPERTY GRAPH` view over `aryx_entity` and `aryx_relationship`
is a DDL statement — one-time setup, no per-use cost. Graph queries execute
as SQL:2023 GRAPH_TABLE queries against ADB, billed as ECPU time.

Graph queries are fast (indexed lookups) — a typical `find_entities()` call
consumes <5ms of ECPU.

| Query type | ECPU time | Cost per query |
|---|---|---|
| find_entities (type lookup) | ~5ms | $0.0000003 |
| shortest_path (6-hop) | ~50ms | $0.000003 |
| neighbors (1-hop) | ~10ms | $0.0000006 |

**Monthly cost:**

All scales: graph queries are a rounding error against the ADB ECPU budget.
Included in the ADB ECPU allocation below. **~$0 additional.**

---

### Stage 9 — Oracle Graph Studio (RDF Semantic Store)

**OCI Service:** Oracle Graph Studio — bundled in ADB

Graph Studio is loaded from the RDF/Turtle export (`rdf/exporter.py`).
Export takes ~30 seconds for 100K entities. The Turtle file is uploaded to
Object Storage, then Graph Studio loads it via the OCI API.

| Operation | Cost |
|---|---|
| RDF model creation | Included in ADB |
| SPARQL endpoint (REST) | Included in ADB |
| Reasoning (RDFS++) | Included in ADB |
| Export generation (compute) | Charged as ADB ECPU time |

Export of 100K entities: ~30s × 2 ECPU = $0.0034.

**Monthly cost (one export per ingest cycle):**

| Scale | Exports/month | Monthly Cost |
|---|---|---|
| Small | 2 | **~$0.01** |
| Medium | 8 | **~$0.03** |
| Large | 40 | **~$0.14** |

---

### Stage 10 — Graph Query via Select AI (Ask Flow)

**OCI Service:** Oracle ADB 23ai (Select AI) + OCI Generative AI

The Ask flow has two sub-costs:
1. **Select AI (NL → SQL/PGQL):** `DBMS_CLOUD_AI.GENERATE()` calls OCI GenAI
   inside ADB to translate the question into a query, then executes it.
   Charged as OCI GenAI tokens.
2. **Answer synthesis:** The query results are sent to OCI GenAI (Command R+)
   to compose the final natural language answer.

| Sub-step | Model | Tokens per Ask | Cost per Ask |
|---|---|---|---|
| Select AI NL→SQL (frontier) | Command R+ | 1,000 in + 200 out | $0.006 |
| Answer synthesis (frontier) | Command R+ | 3,000 in + 500 out | $0.017 |
| Total per Ask query | | | $0.023 |

**Monthly cost:**

| Scale | Ask queries/month | Monthly Cost |
|---|---|---|
| Small | 2,000 | **~$46** |
| Medium | 10,000 | **~$230** |
| Large | 50,000 | **~$1,150** |

*Ask is the second-largest cost driver after Document Understanding at scale.*

---

### Stage 11 — OWL 2 RL Reasoning

**OCI Service:** Oracle Graph Server (PGX) — VM compute

PGX applies OWL 2 RL rules to the graph after each ingest cycle. A reasoning
run over 500K entities takes ~5 minutes on a 2-OCPU VM. This is a batch
operation — not triggered per document, but per ingest cycle (once all
documents in a batch are resolved and landed).

| Compute | Rate | Per 5-min reasoning run |
|---|---|---|
| VM.Standard.E4.Flex (2 OCPU) | $0.025/OCPU/hr | $0.0042 |
| VM.Standard.A1.Flex (4 OCPU) | Always Free | $0 |

**Monthly cost:**

| Scale | Reasoning runs/month | Shape | Monthly Cost |
|---|---|---|---|
| Small (2 runs) | 2 | A1.Flex (Always Free) | **$0** |
| Medium (8 runs) | 8 | E4.Flex 2 OCPU | **~$0.03** |
| Large (40 runs × 20 min) | 40 | E4.Flex 4 OCPU | **~$0.67** |

*PGX VM is a standing server — fixed monthly cost ($36–73) dominates,
not the reasoning runs themselves. See Service 4 in OCI_COST_ESTIMATION.md.*

---

### Stage 12 — Competency Question Testing

**OCI Service:** Oracle ADB (SEM_MATCH) + OCI GenAI (CQ generation)

CQ testing runs on-demand, not per document. Triggered after ontology
changes or by the user from the Brief panel.

| Sub-step | Service | Cost per workspace test |
|---|---|---|
| CQ generation (LLM drafts 5–10 CQs) | OCI GenAI Command R+ | $0.04 |
| NL→SPARQL translation (per CQ) | OCI GenAI Command R+ | $0.03 per CQ × 7 = $0.21 |
| CQ execution (SEM_MATCH) | ADB (included) | $0 |
| PGX path validation | PGX VM (standing cost) | $0 |
| Total per CQ test run | | **~$0.25** |

**Monthly cost:**

| Scale | CQ runs/month | Monthly Cost |
|---|---|---|
| Small | 4 | **~$1.00** |
| Medium | 16 | **~$4.00** |
| Large | 80 | **~$20.00** |

---

## Worker Cost — Option A: OCI Functions

OCI Functions is the **serverless pipeline worker**. Each document upload
triggers one Function invocation that runs all compute stages (parse call,
chunk, PII, embed, extract). Resolution runs as a separate periodic Function
triggered on a schedule or by a threshold.

### Function Configuration

```
OCI Console → Developer Services → Functions → Create Application

  Application name:  aryx-pipeline
  VCN:               aryx-vcn
  Subnet:            aryx-private-subnet

Create Functions:
  aryx-ingest-fn     → runs stages 2–6 per document
  aryx-resolve-fn    → runs stage 7 on schedule or threshold
  aryx-reason-fn     → triggers PGX reasoning run post-resolve
```

### Pricing

| Component | Rate | Always Free |
|---|---|---|
| Invocations | $0.0000002/call | First 2,000,000/month |
| Compute (GB-seconds) | $0.00001417/100ms at 128 MB | First 400,000 GB-sec/month |
| Memory options | 128 MB – 2 GB | — |

### Resource Sizing per Function

| Function | Memory | Avg duration | GB-sec per call |
|---|---|---|---|
| `aryx-ingest-fn` (chunk + PII + embed call + extract call) | 512 MB | 30 sec | 15 |
| `aryx-resolve-fn` (blocking + scoring, 1K entities) | 1024 MB | 45 sec | 45 |
| `aryx-reason-fn` (PGX trigger, lightweight) | 256 MB | 5 sec | 1.25 |

*External API calls (Document Understanding, OCI GenAI) are made from inside
the Function. Their costs are counted separately in stages 2 and 5.*

### OCI Functions Monthly Cost

| Scale | Invocations | GB-seconds | Monthly Cost |
|---|---|---|---|
| Small (500 docs) | ~1,000 | ~15,000 | **~$0** (within free tier) |
| Medium (2,000 docs) | ~4,500 | ~72,000 | **~$0.36** |
| Large (10,000 docs) | ~21,000 | ~345,000 | **~$4.89** |

*OCI Functions compute cost is negligible — dominated by API calls (GenAI, Doc Understanding).*

---

## Worker Cost — Option B: OCI Data Flow (Apache Spark)

OCI Data Flow is the **managed Spark worker**. Documents are batched,
uploaded to Object Storage, and a Spark job is submitted. Spark distributes
the pipeline across executors — one partition per N documents.

### Data Flow Configuration

```
OCI Console → Analytics & AI → Data Flow → Create Application

  Application name:   aryx-pipeline-spark
  Language:           Python
  Spark version:      3.3
  Driver shape:       VM.Standard.E4.Flex (2 OCPU, 32 GB)
  Executor shape:     VM.Standard.E4.Flex (2 OCPU, 32 GB)
  Number of executors: 4 (auto-scale 1–10)
  Script:             oci://aryx-doc-output/spark/aryx_pipeline.py
  Logs:               oci://aryx-doc-output/logs/
```

### Spark Job Structure for aryx Pipeline

```
aryx_pipeline.py (Spark application)

  SparkContext initialises
       ↓
  Read file list from staging bucket (Object Storage)
       ↓
  RDD.map(doc → parse → chunk → PII → embed → extract)
       → Each executor handles N docs in parallel
       ↓
  RDD.reduceByKey(resolve entities within blocks)
       ↓
  Write resolved entities to Oracle ADB (via cx_Oracle JDBC)
       ↓
  Trigger PGX reasoning run (REST call)
       ↓
  Job exits — billing stops
```

### Pricing

| Component | Rate |
|---|---|
| OCPU-hours (Driver + all Executors) | $0.02/OCPU/hr |
| Minimum: 1 Driver + 1 Executor (4 OCPUs) | $0.08/hr |
| Storage (logs + staging) | Object Storage rates |

### Job Duration Estimates

| Scale | Docs | Executors | Job duration | Total OCPUs | Cost/job |
|---|---|---|---|---|---|
| Small batch (50 docs) | 50 | 2 | ~15 min | 6 | $0.03 |
| Medium batch (200 docs) | 200 | 4 | ~20 min | 10 | $0.07 |
| Large batch (1,000 docs) | 1,000 | 8 | ~30 min | 18 | $0.09 |

### OCI Data Flow Monthly Cost

| Scale | Jobs/month | Monthly Cost |
|---|---|---|
| Small (10 batches × 50 docs) | 10 | **~$0.30** |
| Medium (10 batches × 200 docs) | 10 | **~$0.70** |
| Large (10 batches × 1,000 docs) | 10 | **~$0.90** |

*Data Flow compute cost is extremely low because jobs are short and OCPUs
are shared across documents. API call costs (GenAI, Doc Understanding) dominate.*

---

## Worker Comparison — Functions vs Data Flow

| Dimension | OCI Functions | OCI Data Flow (Spark) |
|---|---|---|
| **Trigger** | Per-document event (real-time) | Batch submission (scheduled or manual) |
| **Latency** | Near-real-time — each doc processed within seconds of upload | Batch — all docs in a batch processed together |
| **Parallelism** | Automatic — N docs = N concurrent invocations | Controlled — set executor count per job |
| **Max doc size** | 6 min execution limit per invocation | No time limit on Spark jobs |
| **Worker cost** | ~$0–5/month | ~$0.30–0.90/month |
| **Infrastructure** | Zero — fully managed | Zero — fully managed Spark |
| **Resume on failure** | aryx `StageRunner` checkpoint per invocation | Spark RDD lineage — automatic retry |
| **Best for** | Interactive ingestion, real-time feedback | Large batch ingestion, nightly jobs |
| **aryx integration** | Replace `background_tasks.add_task()` with OCI Events → Function trigger | Submit Data Flow job via OCI SDK from aryx API |

**Recommendation:** Use OCI Functions for interactive single-document uploads
(the standard UI flow). Use OCI Data Flow for bulk ingestion (100+ documents,
nightly batch jobs, initial data loading).

Both can coexist — the aryx API submits to Functions for <10 files and
triggers a Data Flow job for >10 files.

---

## Complete Pipeline Cost Summary

### Cost Per Document (10-page PDF)

| Stage | OCI Service | Cost/doc |
|---|---|---|
| 1. File upload | Object Storage | ~$0.00003 |
| 2. Document parse | OCI Document Understanding | $0.115 |
| 3. Chunk + PII | OCI Functions or Data Flow | ~$0.001 |
| 4. Embed | OCI GenAI (Cohere Embed v3) | $0.001 |
| 5. Entity extraction | OCI GenAI (Cohere Command R) | $0.019 |
| 6. Land to ADB | Oracle ADB 23ai | ~$0.00003 |
| 7. Resolution | OCI Functions or Data Flow | ~$0.0001 |
| 8–9. Graph + Graph Studio | Oracle ADB 23ai (included) | $0 |
| 11. OWL 2 RL reasoning | Oracle PGX (batch, standing VM) | ~$0.001 |
| **Total per document** | | **~$0.14** |

*Ask queries and CQ testing are user-initiated, not per-document.*

### Monthly Total by Scale

#### Small — 500 docs/month, 2,000 Ask queries

| Stage / Service | Monthly Cost |
|---|---|
| Object Storage | $0 |
| OCI Document Understanding | ~$46 |
| OCI Functions (worker) | ~$0 |
| OCI GenAI — Embedding | ~$0.20 |
| OCI GenAI — Extraction (Command R) | ~$9.30 |
| Oracle ADB 23ai (compute + storage) | ~$40 |
| OCI GenAI — Ask (Command R+) | ~$46 |
| Oracle PGX VM (standing) | $0 (A1.Flex Always Free) |
| CQ Testing | ~$1 |
| **Total** | **~$143/month** |

#### Medium — 2,000 docs/month, 10,000 Ask queries

| Stage / Service | Monthly Cost |
|---|---|
| Object Storage | ~$0.05 |
| OCI Document Understanding | ~$345 |
| OCI Functions (worker) | ~$0.36 |
| OCI GenAI — Embedding | ~$1.20 |
| OCI GenAI — Extraction (Command R) | ~$55.80 |
| Oracle ADB 23ai (2 ECPUs, 200 GB) | ~$65 |
| OCI GenAI — Ask (Command R+) | ~$230 |
| Oracle PGX VM (E4.Flex 2 OCPU) | ~$36 |
| CQ Testing | ~$4 |
| **Total** | **~$737/month** |

#### Large — 10,000 docs/month, 50,000 Ask queries

| Stage / Service | Monthly Cost |
|---|---|
| Object Storage | ~$0.26 |
| OCI Document Understanding | ~$2,300 |
| OCI Data Flow (worker) | ~$0.90 |
| OCI GenAI — Embedding | ~$8.00 |
| OCI GenAI — Extraction (Command R) | ~$372 |
| Oracle ADB 23ai (4 ECPUs, 500 GB) | ~$180 |
| OCI GenAI — Ask (Command R+) | ~$1,150 |
| Oracle PGX VM (E4.Flex 4 OCPU) | ~$73 |
| CQ Testing | ~$20 |
| **Total** | **~$4,104/month** |

---

## Cost Reduction Options

| Option | Monthly saving (Large scale) | Trade-off |
|---|---|---|
| Switch extraction to Meta Llama 3.1 70B instead of Command R | ~$180/month | Slightly lower JSON extraction accuracy |
| Switch Ask synthesis from Command R+ to Command R | ~$920/month | Less nuanced long-form answers |
| Enable ADB auto-stop nights/weekends (16 hrs/day instead of 24) | ~$50/month | Manual start for off-hours queries |
| Batch Document Understanding — skip Table Detection for text-only docs | ~$920/month | No table structure in non-tabular documents |
| Use OCI Data Flow for all ingestion (more predictable than Functions) | ~$4/month | Adds 5–10 min batch latency |
| Cache Ask results for repeated questions | ~$100/month | Stale answers if graph updates frequently |

**Largest lever:** Document Understanding at large scale costs $2,300/month.
Skipping Table Detection for plain text documents (reports, emails, policies)
and keeping it only for structured documents (invoices, contracts, forms)
reduces this by ~60%.

**Second largest:** Ask queries at $1,150/month. Caching and using Command R
instead of Command R+ for synthesis reduces this by ~80%.

---

## Implementation Note — Worker Integration with aryx

### OCI Functions path

Replace `background_tasks.add_task()` in `file_ingest_api.py:132` with an
OCI Functions invocation:

```python
# src/aryx/api/file_ingest_api.py — aryx-o edition
import oci

fn_client = oci.functions.FunctionsInvokeClient(config)

# Instead of: background_tasks.add_task(_run_files, ...)
fn_client.invoke_function(
    function_id=settings.oci_ingest_fn_id,
    invoke_function_body=json.dumps({
        "job_id": job_id,
        "workspace_id": workspace_id,
        "files": names,
        "ontology_type": ontology_type,
    })
)
```

### OCI Data Flow path

The aryx pipeline stages map directly to Spark RDD transformations. The
existing `StageRunner` checkpoint logic in `pipeline/stages.py` maps to
Spark's native RDD lineage (automatic retry on executor failure):

```python
# aryx_pipeline_spark.py (submitted to OCI Data Flow)
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("aryx-pipeline").getOrCreate()
docs_rdd = spark.sparkContext.parallelize(file_list, numPartitions=num_executors)

parsed   = docs_rdd.map(oci_document_parse)
chunked  = parsed.flatMap(chunk_and_pii)
embedded = chunked.map(embed_chunk)          # OCI GenAI Embed
extracted = chunked.map(extract_entities)   # OCI GenAI + LLMGraphTransformer
extracted.foreach(write_to_adb)             # cx_Oracle JDBC → aryx_entity
```

---

*Generated: 2026-06-20 | aryx project | giggso*
*Pricing from OCI public pricing page (oracle.com/cloud/cost-estimator)*
*All prices USD, US Midwest (Chicago) region. Subject to negotiated discounts.*
