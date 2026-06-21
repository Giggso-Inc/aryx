# aryx-o — OCI Services Cost Estimation

**Project:** aryx — Knowledge Graph & Ontology Platform
**Edition:** aryx-o (Enterprise with Oracle adapter set)
**Prepared:** 2026-06-20
**Owner:** m.munir@giggso.com

This document covers every OCI service required to run aryx-o, including
the configuration needed to create each service, its purpose in the aryx
pipeline, the pricing model, and the estimated monthly cost across three
deployment tiers.

---

## Deployment Tiers

| Tier | Use Case | Scale |
|---|---|---|
| **Dev / Always Free** | Local development, proof of concept | 1 developer, <10K entities |
| **Small Production** | Team deployment, live workloads | 5 users, ~500K entities |
| **Enterprise Scale** | Full production, large datasets | 20+ users, 5M+ entities |

---

## Service 1 — Oracle Autonomous Database 23ai (ADB)

### Purpose in aryx

ADB 23ai is the **central relational store** for aryx-o. It replaces both
Postgres (source of truth) and the FalkorDB projection layer by hosting:

- All 29 aryx migration tables (`aryx_entity`, `aryx_relationship`,
  `aryx_chunk`, `aryx_ontology_type`, `aryx_ontology_axiom`, etc.)
- SQL:2023 Property Graph views over `aryx_entity` and `aryx_relationship`
  — enabling direct graph queries without a separate FalkorDB store
- Oracle Graph Studio — the RDF semantic graph and SPARQL endpoint
  (bundled inside ADB, no separate service needed)
- pgvector replacement — Oracle ADB 23ai has native vector storage
  (768-dim embeddings from `aryx_chunk_embedding` migrate here)
- Select AI (`DBMS_CLOUD_AI`) — NL-to-SQL/PGQL for the Ask flow

### Why ADB and not self-managed Oracle DB

- ADB auto-patches, auto-tunes, and auto-scales — no DBA needed
- Graph Studio is pre-installed and activated in ADB — no manual setup
- Select AI is only available in ADB (not self-managed Oracle DB)
- ADB Serverless scales ECPUs to zero when idle — dev cost = $0 when not running

### Configuration to Create

**Step 1 — Provision the ADB instance**

```
OCI Console → Oracle Database → Autonomous Database → Create Autonomous Database

  Display name:       aryx-db
  Database name:      ARYXDB
  Workload type:      Transaction Processing (OLTP)
  Deployment type:    Serverless
  Database version:   23ai
  ECPU count:         2 (auto-scaling enabled, max: 8)
  Storage (TB):       1
  Password:           [set admin password]
  Network:            Allow secure access from everywhere (or VCN-only)
  License:            License Included
```

**Step 2 — Enable Graph Studio**

Graph Studio is auto-enabled. Access via:
`Tools → Open Graph Studio` from the ADB console.

**Step 3 — Configure Select AI**

```sql
-- Run inside ADB SQL Worksheet
EXEC DBMS_CLOUD_AI.CREATE_PROFILE(
  profile_name => 'ARYX_SELECTAI',
  attributes   => '{
    "provider": "oci",
    "credential_name": "OCI_GENAI_CRED",
    "object_list": [
      {"owner": "ARYX", "name": "ARYX_ENTITY"},
      {"owner": "ARYX", "name": "ARYX_RELATIONSHIP"},
      {"owner": "ARYX", "name": "ARYX_ONTOLOGY_TYPE"},
      {"owner": "ARYX", "name": "ARYX_ONTOLOGY_AXIOM"}
    ]
  }'
);

EXEC DBMS_CLOUD_AI.SET_PROFILE('ARYX_SELECTAI');
```

**Step 4 — Create the SQL:2023 Property Graph**

```sql
CREATE PROPERTY GRAPH aryx_ws_graph
  VERTEX TABLES (
    aryx_entity LABEL Entity
      PROPERTIES (id, name, ontology_type, attributes)
  )
  EDGE TABLES (
    aryx_relationship LABEL RELATES
      SOURCE KEY (source_entity_id) REFERENCES aryx_entity(id)
      DESTINATION KEY (target_entity_id) REFERENCES aryx_entity(id)
      PROPERTIES (name)
  );
```

**Step 5 — Migrate aryx schema**

Run the 29 aryx migration SQL files (0001–0029) against ADB using SQL*Plus
or SQL Developer, adjusting `BIGSERIAL` → `NUMBER GENERATED ALWAYS AS IDENTITY`
and `JSONB` → `JSON` (Oracle 23ai supports ISO JSON).

### aryx Adapter

```bash
ARYX_ADAPTER_RELATIONAL=aryx.adapters.oracle.rdb:OracleRelationalAdapter
ARYX_ADAPTER_GRAPH_READER=aryx.adapters.oracle.graph:OracleGraphReader
ARYX_ADAPTER_GRAPH_STORE=aryx.adapters.oracle.graph:OracleGraphStore
```

### Pricing Model

| Component | Unit | Price |
|---|---|---|
| ECPU (compute) | per ECPU/hr | $0.2072/ECPU/hr |
| Storage | per GB/month | $0.0218/GB/month |
| Graph Studio | Included | $0 |
| Select AI | Included | $0 |
| SQL:2023 Property Graphs | Included | $0 |
| Always Free allocation | 2 ADB instances, 1 OCPU, 20 GB each | $0 |

### Monthly Cost Estimate

| Tier | ECPUs | Storage | Uptime | Monthly Cost |
|---|---|---|---|---|
| Dev / Always Free | 1 OCPU (free) | 20 GB (free) | Always on | **$0** |
| Small Production | 2 ECPUs (auto-scale off-hours) | 100 GB | 12 hrs/day avg | **~$40** |
| Enterprise Scale | 4 ECPUs (auto-scale to 8) | 500 GB | 20 hrs/day | **~$180** |

---

## Service 2 — OCI Generative AI

### Purpose in aryx

OCI Generative AI is the **LLM provider** for aryx-o. It replaces the local
Ollama models (`qwen3.5:0.8b` for menial, `lfm2.5-thinking` for reasoning)
and external APIs (Anthropic, OpenAI) with enterprise models hosted inside
the customer's OCI tenancy.

aryx uses LLMs at three points in the pipeline:

| aryx stage | Model tier | OCI GenAI model |
|---|---|---|
| Entity + relationship extraction | menial | Cohere Command R (fast, low cost) |
| Brief drafting, NL→SPARQL, CQ generation | frontier | Cohere Command R+ (highest quality) |
| Ask flow — final answer synthesis | frontier | Cohere Command R+ |
| Embeddings (`aryx_chunk_embedding`) | embed | Cohere Embed v3 (Multilingual) |

**Key advantage over external APIs:** Data never leaves the OCI tenancy.
No GDPR/data residency concerns for enterprise customers.

### Configuration to Create

**Step 1 — Enable OCI Generative AI**

```
OCI Console → Analytics & AI → Generative AI → Get Started
Region: US Midwest (Chicago) — currently the primary GenAI region

No provisioning needed — it is a managed service accessed via API.
```

**Step 2 — Create API credentials**

```
OCI Console → Identity → API Keys → Add API Key
Download the private key → store in aryx secrets store
```

**Step 3 — Create the OCI credential in ADB (for Select AI)**

```sql
-- Run inside ADB SQL Worksheet
BEGIN
  DBMS_CLOUD.CREATE_CREDENTIAL(
    credential_name => 'OCI_GENAI_CRED',
    user_ocid       => 'ocid1.user.oc1...',
    tenancy_ocid    => 'ocid1.tenancy.oc1...',
    private_key     => '[contents of private key file]',
    fingerprint     => '[key fingerprint]'
  );
END;
```

**Step 4 — Configure aryx LlmPort adapter**

```bash
ARYX_ADAPTER_LLM=aryx.adapters.oracle.genai:OracleGenAiLlm
OCI_GENAI_ENDPOINT=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com
OCI_GENAI_COMPARTMENT_ID=ocid1.compartment.oc1...
OCI_GENAI_MENIAL_MODEL=cohere.command-r-08-2024
OCI_GENAI_FRONTIER_MODEL=cohere.command-r-plus-08-2024
OCI_GENAI_EMBED_MODEL=cohere.embed-multilingual-v3
```

### Pricing Model

| Model | Input tokens | Output tokens |
|---|---|---|
| Cohere Command R (menial) | $0.00015/1K tokens | $0.00060/1K tokens |
| Cohere Command R+ (frontier) | $0.00300/1K tokens | $0.01500/1K tokens |
| Cohere Embed v3 (embed) | $0.00010/1K tokens | — |
| Meta Llama 3.1 70B (alternative) | $0.00060/1K tokens | $0.00060/1K tokens |

### Usage Assumptions for Cost Estimate

aryx processes documents in chunks of 1,000 characters (config: `chunk_size=1000`).
Each chunk generates one extraction call (menial) and one embed call.
A typical 20-page PDF produces ~40 chunks.

| Operation | Tokens per call | Calls per doc | Cost per doc |
|---|---|---|---|
| Entity extraction (Command R) | 1,500 in + 400 out | 40 chunks | ~$0.019 |
| Embedding (Embed v3) | 250 per chunk | 40 chunks | ~$0.001 |
| Brief draft (Command R+) | 2,000 in + 800 out | 1 per workspace | ~$0.018 |
| Ask query answer (Command R+) | 3,000 in + 500 out | per question | ~$0.017 |

### Monthly Cost Estimate

| Tier | Docs/month | Ask queries/month | Monthly Cost |
|---|---|---|---|
| Dev / Always Free | 50 | 200 | **~$4** |
| Small Production | 500 | 2,000 | **~$50** |
| Enterprise Scale | 5,000 | 20,000 | **~$480** |

*Note: OCI GenAI has no Always Free tier. All usage is billed from first call.*

---

## Service 3 — OCI Document Understanding

### Purpose in aryx

OCI Document Understanding replaces `PdfConnector` (pymupdf + pytesseract)
in the document ingestion pipeline. It provides **layout-aware document
analysis** — instead of raw text extraction, it returns structured output
with table structure, form field detection, key-value pairs, and per-block
confidence scores.

aryx's `doc_router.py` dispatches to a connector per file extension. For
aryx-o, `OciDocumentConnector` replaces `PdfConnector` for PDF files and
`ImageConnector` for scanned images and TIFF files.

**What it handles that aryx's current stack cannot:**

- Multi-column PDF layouts (newsletters, reports, legal documents)
- Scanned PDFs — direct OCR with 98%+ accuracy on clean scans
- Table extraction — cells, spans, headers preserved in structured JSON
- Form field detection — `"Invoice Date": "2024-01-15"` as explicit KV pairs
- Handwriting recognition (premium tier)

### Configuration to Create

**Step 1 — Enable the service (no provisioning)**

```
OCI Console → Analytics & AI → Document Understanding
No instance needed — it is a REST API service, pay-per-page.
```

**Step 2 — Create an Object Storage bucket for output**

```
OCI Console → Storage → Object Storage → Create Bucket

  Bucket name:    aryx-doc-output
  Storage tier:   Standard
  Encryption:     Oracle-managed keys
```

**Step 3 — Create IAM policy**

```
Allow group aryx-group to use ai-service-document-family in compartment aryx-compartment
Allow group aryx-group to manage object-family in compartment aryx-compartment
```

**Step 4 — Configure in aryx**

```bash
ARYX_DOCUMENT_CONNECTOR=oci
OCI_DOCUMENT_NAMESPACE=<object-storage-namespace>
OCI_DOCUMENT_BUCKET=aryx-doc-output
OCI_DOCUMENT_FEATURES=TEXT_DETECTION,TABLE_DETECTION,KEY_VALUE_DETECTION
```

**Step 5 — Processor configuration (per API call)**

```json
{
  "processorType": "GENERAL",
  "documentType": "INVOICE",
  "features": [
    {"featureType": "TEXT_DETECTION"},
    {"featureType": "TABLE_DETECTION"},
    {"featureType": "KEY_VALUE_DETECTION"}
  ],
  "outputLocation": {
    "namespaceName": "<namespace>",
    "bucketName": "aryx-doc-output",
    "prefix": "results/"
  }
}
```

### Pricing Model

| Feature | Price |
|---|---|
| Text Detection (OCR) | $1.50 per 1,000 pages |
| Table Detection | $10.00 per 1,000 pages |
| Key-Value Detection | $10.00 per 1,000 pages |
| Document Classification | $10.00 per 1,000 pages |
| Always Free | First 1,000 pages/month across all features |

*Most aryx documents use Text Detection + Table Detection = $11.50/1,000 pages.*

### Monthly Cost Estimate

| Tier | Pages/month | Features used | Monthly Cost |
|---|---|---|---|
| Dev / Always Free | <1,000 | All | **$0** (free tier covers it) |
| Small Production | ~5,000 (500 docs × 10 pages) | Text + Table | **~$52** |
| Enterprise Scale | ~50,000 (5,000 docs × 10 pages) | Text + Table + KV | **~$575** |

---

## Service 4 — Oracle Graph Server (PGX)

### Purpose in aryx

Oracle Graph Server (PGX) is the **reasoning engine** for aryx-o. It replaces
aryx's Python rule loop (`src/aryx/reasoning/engine.py`) with a native graph
engine that applies OWL 2 RL and RDFS++ rules inside the graph, with zero
Python iterations.

aryx uses PGX through the `ReasonerPort` adapter for:

- OWL 2 RL inference — `rdfs:subClassOf`, `owl:sameAs`, `owl:equivalentClass`,
  `owl:FunctionalProperty`, `owl:TransitiveProperty` (unbounded closure)
- Inverse / symmetric relationship materialisation
- Competency Question path validation — verifying that a CQ's property chain
  is structurally declared in the ontology before query execution
- PGQL graph queries as an alternative to FalkorDB Cypher

### Configuration to Create

**Step 1 — Deploy from OCI Marketplace**

```
OCI Console → Marketplace → Search "Oracle Graph Server"
Publisher: Oracle
→ Launch Stack

  Shape:          VM.Standard.E4.Flex
  OCPUs:          2
  Memory:         16 GB
  OS:             Oracle Linux 8
  VCN:            aryx-vcn
  Subnet:         aryx-private-subnet
  HTTPS port:     7007
```

**Step 2 — Configure PGX to connect to ADB**

```properties
# /etc/oracle/graph/pgx.conf
{
  "pgx_realm": {
    "implementation": "oracle.pgx.realm.ADBRealm",
    "adb_wallet": "/opt/oracle/wallet/aryx_wallet.zip"
  },
  "enable_tls": true,
  "port": 7007
}
```

**Step 3 — Load the aryx OWL ontology at startup**

```python
# aryx.adapters.oracle.pgx — OraclePgxReasoner.__init__
session = server.create_session("aryx_reasoner")
graph = session.read_graph_with_properties(
    "/opt/aryx/ontology_export.ttl",   # from rdf/exporter.py output
    file_format="RDF/TURTLE"
)
# Apply OWL 2 RL ruleset
analyst = session.create_analyst()
analyst.compute_inferencing(graph, rulesets=["OWL2RL"])
```

**Step 4 — Configure aryx ReasonerPort**

```bash
ARYX_ADAPTER_REASONER=aryx.adapters.oracle.pgx:OraclePgxReasoner
OCI_PGX_HOST=https://<pgx-vm-ip>:7007
OCI_PGX_USERNAME=pgx_aryx
OCI_PGX_PASSWORD=<password>
```

### Pricing Model

PGX is software — pricing is compute cost of the VM it runs on.

| Shape | OCPUs | Memory | Price/hr | Monthly (24×7) |
|---|---|---|---|---|
| VM.Standard.E4.Flex (2 OCPU) | 2 | 16 GB | $0.025/OCPU/hr | **~$36** |
| VM.Standard.E4.Flex (4 OCPU) | 4 | 32 GB | $0.025/OCPU/hr | **~$73** |
| VM.Standard.A1.Flex (4 OCPU) | 4 | 24 GB | Always Free | **$0** |

*VM.Standard.A1.Flex 4 OCPU / 24 GB is part of the OCI Always Free tier —
PGX can run on this VM at $0/month for dev and small production.*

### Monthly Cost Estimate

| Tier | Shape | Monthly Cost |
|---|---|---|
| Dev / Always Free | A1.Flex 4 OCPU (Always Free) | **$0** |
| Small Production | E4.Flex 2 OCPU | **~$36** |
| Enterprise Scale | E4.Flex 4 OCPU (dedicated) | **~$73** |

---

## Service 5 — OCI Object Storage

### Purpose in aryx

Object Storage provides two functions in aryx-o:

1. **RDF staging bucket** — aryx's `rdf/exporter.py` generates Turtle/OWL files
   on demand. These are uploaded to Object Storage so Oracle Graph Studio and
   PGX can load them without file transfer. The pipeline triggers: export →
   upload to bucket → Graph Studio loads from bucket URL.

2. **Document Understanding output** — OCI Document Understanding writes its
   structured JSON results to Object Storage. aryx's `OciDocumentConnector`
   reads results from the bucket after processing completes.

### Configuration to Create

```
OCI Console → Storage → Object Storage → Create Bucket (×2)

Bucket 1 — RDF exports:
  Name:           aryx-rdf-exports
  Storage tier:   Standard
  Versioning:     Enabled (keep last 5 versions per workspace)

Bucket 2 — Document Understanding results:
  Name:           aryx-doc-output
  Storage tier:   Standard
  Lifecycle policy: Delete objects older than 7 days (results are transient)
```

### Pricing Model

| Component | Price |
|---|---|
| Storage (Standard tier) | $0.0255/GB/month |
| Outbound data transfer | First 10 TB/month free |
| Always Free | 20 GB storage included |
| PUT/GET requests | $0.0034 per 10,000 requests |

### Monthly Cost Estimate

| Tier | Storage needed | Monthly Cost |
|---|---|---|
| Dev / Always Free | <20 GB | **$0** |
| Small Production | ~50 GB | **~$0.76** |
| Enterprise Scale | ~200 GB | **~$5.10** |

---

## Service 6 — OCI Compute (aryx API + Worker)

### Purpose in aryx

The aryx API (`uvicorn aryx.api.main:app`) and worker process run on an OCI
Compute VM. This VM hosts the aryx Python application — the same containers
from `docker-compose.yml` — replacing the self-hosted server.

aryx-o still needs a compute VM to run:
- FastAPI API server (port 8088)
- aryx pipeline worker (background ingestion)
- Streamlit UI (port 8501)
- MCP server (port 8765)
- Next.js web UI (port 3001)

The local Ollama container and FalkorDB container are **removed** in aryx-o —
LLM calls go to OCI GenAI, graph queries go to ADB/PGX.

### Configuration to Create

```
OCI Console → Compute → Instances → Create Instance

  Name:           aryx-app-server
  Image:          Oracle Linux 8 (or Ubuntu 22.04)
  Shape:          VM.Standard.A1.Flex (Always Free: 4 OCPU, 24 GB RAM)
  Boot volume:    100 GB
  VCN:            aryx-vcn
  Subnet:         aryx-public-subnet
  Public IP:      Yes (or use OCI Load Balancer)

Post-provision:
  Install Docker + Docker Compose
  Deploy aryx containers (without ollama, without falkordb)
  Configure .env with OCI adapter env vars
```

### Pricing Model

| Shape | OCPUs | Memory | Price | Notes |
|---|---|---|---|---|
| VM.Standard.A1.Flex | 4 | 24 GB | **Always Free** | ARM-based, sufficient for aryx API + worker |
| VM.Standard.E4.Flex | 2 | 32 GB | $0.025/OCPU/hr ≈ $36/month | x86, higher single-thread performance |
| VM.Standard.E4.Flex | 4 | 64 GB | $0.025/OCPU/hr ≈ $73/month | For high-concurrency production |

### Monthly Cost Estimate

| Tier | Shape | Monthly Cost |
|---|---|---|
| Dev / Always Free | A1.Flex 4 OCPU 24 GB (Always Free) | **$0** |
| Small Production | E4.Flex 2 OCPU 32 GB | **~$36** |
| Enterprise Scale | E4.Flex 4 OCPU 64 GB | **~$73** |

---

## Service 7 — OCI Container Registry (OCIR)

### Purpose in aryx

OCIR stores the aryx Docker images (`docker build .` from the root
`Dockerfile`). The Compute VM pulls from OCIR on deployment. This replaces
building images locally and removes dependency on Docker Hub.

### Configuration to Create

```
OCI Console → Developer Services → Container Registry → Create Repository

  Repository name:  aryx/aryx-app
  Access:           Private
  Region:           Same as Compute VM
```

Tag and push aryx images:

```bash
docker tag aryx-app:latest <region>.ocir.io/<namespace>/aryx/aryx-app:latest
docker push <region>.ocir.io/<namespace>/aryx/aryx-app:latest
```

### Pricing Model

| Component | Price |
|---|---|
| Storage | $0.0255/GB/month |
| Always Free | 500 MB per month |
| Outbound (pulls within OCI) | Free |

### Monthly Cost Estimate

All tiers: **~$0.50/month** (aryx images are ~500 MB–1 GB compressed).

---

## Service 8 — Oracle Analytics Cloud (OAC) — Optional

### Purpose in aryx

OAC provides the **CQ coverage dashboard** and ontology health reporting —
showing which competency questions pass per workspace, which roles have full
coverage, and how coverage improves over ingest cycles.

This is optional. A simpler alternative is APEX (included free with ADB) or
the existing Streamlit UI with a new CQ panel.

### Configuration to Create

```
OCI Console → Analytics & AI → Analytics Cloud → Create Instance

  Name:               aryx-analytics
  Capacity:           1 OCPU (Professional)
  License type:       License Included
  Edition:            Professional
```

Connect to ADB:

```
Analytics → Create Connection → Oracle Autonomous Database
→ Select aryx-db → Authenticate → Done
```

### Pricing Model

| Edition | Price per OCPU/month | Minimum |
|---|---|---|
| Professional | $16/user/month | 2 users |
| Enterprise | $80/user/month | 2 users |
| Developer | $14/OCPU/month | 1 OCPU |

### Monthly Cost Estimate

| Tier | Option | Monthly Cost |
|---|---|---|
| Dev | Use ADB APEX (included) | **$0** |
| Small Production | OAC Professional, 2 users | **~$32** |
| Enterprise Scale | OAC Professional, 5 users | **~$80** |

---

## Service 9 — OCI Networking (VCN)

### Purpose in aryx

A Virtual Cloud Network (VCN) provides private networking between all aryx-o
services — ADB, PGX VM, App VM, Object Storage — so no traffic crosses the
public internet internally.

### Configuration to Create

```
OCI Console → Networking → Virtual Cloud Networks → Create VCN

  Name:        aryx-vcn
  CIDR block:  10.0.0.0/16

Create subnets:
  aryx-public-subnet   10.0.0.0/24   (App VM — public IP)
  aryx-private-subnet  10.0.1.0/24   (ADB, PGX — no public IP)

Create Security List rules:
  Ingress: 22 (SSH), 8088 (API), 8501 (UI), 3001 (Web), 7007 (PGX)
  Egress:  All
```

### Pricing Model

VCN, subnets, security lists, route tables: **$0** (always free).

Load Balancer (optional, for production HA):

| Component | Price |
|---|---|
| Flexible Load Balancer (10 Mbps) | $0.006/hr = ~$4.38/month |
| Data processed | $0.008/GB |

### Monthly Cost Estimate

| Tier | Monthly Cost |
|---|---|
| Dev / Always Free | **$0** |
| Small Production | **$0** (no Load Balancer needed) |
| Enterprise Scale | **~$10** (Load Balancer + data transfer) |

---

## Total Monthly Cost Summary

### Dev / Always Free Tier — $0/month

Everything runs on OCI Always Free resources. Limitations apply (1 OCPU ADB,
20 GB storage, 4 OCPU ARM compute). Suitable for proof of concept and
development.

| Service | Config | Monthly Cost |
|---|---|---|
| Oracle ADB 23ai | 1 OCPU, 20 GB (Always Free) | $0 |
| OCI GenAI | ~50 docs, ~200 Ask queries | ~$4 |
| OCI Document Understanding | <1,000 pages (Always Free) | $0 |
| Oracle Graph Server (PGX) | A1.Flex VM (Always Free) | $0 |
| OCI Object Storage | <20 GB (Always Free) | $0 |
| OCI Compute (App VM) | A1.Flex (Always Free) | $0 |
| OCI Container Registry | <500 MB (Always Free) | $0 |
| OCI Networking (VCN) | Always Free | $0 |
| **Total** | | **~$4/month** |

*Only OCI GenAI has no Always Free allocation — all other services run free.*

---

### Small Production Tier — ~$167/month

Suitable for a team of 5, processing ~500 documents/month, ~2,000 Ask queries.

| Service | Config | Monthly Cost |
|---|---|---|
| Oracle ADB 23ai | 2 ECPUs, 100 GB, 12 hrs/day avg | ~$40 |
| OCI GenAI | 500 docs, 2,000 Ask queries | ~$50 |
| OCI Document Understanding | ~5,000 pages | ~$52 |
| Oracle Graph Server (PGX) | E4.Flex 2 OCPU (or A1.Flex free) | ~$0–36 |
| OCI Object Storage | ~50 GB | ~$1 |
| OCI Compute (App VM) | A1.Flex 4 OCPU (Always Free) | $0 |
| OCI Container Registry | ~1 GB | ~$1 |
| Oracle Analytics Cloud | 2 users Professional | ~$32 |
| OCI Networking | No Load Balancer | $0 |
| **Total (PGX on Always Free)** | | **~$176/month** |
| **Total (PGX on E4.Flex)** | | **~$212/month** |

---

### Enterprise Scale Tier — ~$900/month

Suitable for 20+ users, ~5,000 documents/month, ~20,000 Ask queries, 5M+ entities.

| Service | Config | Monthly Cost |
|---|---|---|
| Oracle ADB 23ai | 4 ECPUs (auto-scale to 8), 500 GB, 20 hrs/day | ~$180 |
| OCI GenAI | 5,000 docs, 20,000 Ask queries | ~$480 |
| OCI Document Understanding | ~50,000 pages | ~$575 |
| Oracle Graph Server (PGX) | E4.Flex 4 OCPU dedicated | ~$73 |
| OCI Object Storage | ~200 GB | ~$5 |
| OCI Compute (App VM) | E4.Flex 4 OCPU 64 GB | ~$73 |
| OCI Container Registry | ~2 GB | ~$1 |
| Oracle Analytics Cloud | 5 users Professional | ~$80 |
| OCI Networking | Load Balancer + data transfer | ~$10 |
| **Total** | | **~$1,477/month** |

*Note: Enterprise cost is dominated by OCI GenAI ($480) and Document Understanding ($575).
Switching Document Understanding to batch processing and using Meta Llama 3.1 (10× cheaper
than Command R+) for menial extraction reduces this to ~$620/month.*

---

## Cost Optimisation Options

| Optimisation | Saving | Trade-off |
|---|---|---|
| Use Meta Llama 3.1 70B instead of Cohere Command R+ for frontier tier | ~60% LLM cost | Slightly lower quality on complex extraction |
| Use Cohere Command R (not R+) for Ask synthesis | ~80% LLM cost | Less nuanced answers on complex queries |
| ADB auto-stop when idle (dev) | Up to 100% ADB compute | Manual start needed |
| Batch Document Understanding jobs (off-peak) | No pricing difference but predictable | Adds latency |
| Skip OAC — use ADB APEX or Streamlit CQ panel instead | $32–$80/month | Less polished dashboard |
| Run PGX on Always Free A1.Flex (arm64) | $36–$73/month | ARM — PGX supports arm64 |
| Use OCI Data Flow (Spark) only for large batch runs | Pay per run (~$0.02/OCPU/hr) | No persistent compute |

---

## Implementation Sequence

The services must be created in this order due to dependencies:

```
1. OCI Networking (VCN + subnets)          ← prerequisite for all
2. Oracle ADB 23ai                          ← prerequisite for Select AI, Graph Studio
3. OCI Object Storage (buckets)            ← prerequisite for Document Understanding
4. OCI Generative AI (credentials)         ← prerequisite for Select AI config in ADB
5. Configure Select AI in ADB              ← depends on ADB + OCI GenAI credentials
6. OCI Document Understanding              ← no dependencies, managed service
7. Oracle Graph Server (PGX) VM            ← depends on VCN + ADB wallet
8. OCI Compute (App VM)                    ← depends on VCN
9. OCI Container Registry                  ← depends on App VM for docker push
10. Oracle Analytics Cloud                 ← depends on ADB for connection
```

---

## What is NOT Needed in OCI

| Component | Reason |
|---|---|
| OCI Streaming (Kafka) | aryx uses BackgroundTasks or Celery — not event streaming |
| OCI Functions (serverless) | aryx is a long-running service — not event-triggered functions |
| OCI Data Science | aryx uses OCI GenAI models — no custom model training needed |
| OCI Search (OpenSearch) | Replaced by ADB full-text search + pgvector for semantic search |
| Oracle APEX | Optional alternative to OAC for dashboards — free but lower capability |
| Oracle Integration Cloud | aryx has its own API + MCP — no middleware orchestration needed |

---

*Generated: 2026-06-20 | aryx project | giggso*
*Pricing sourced from OCI public pricing page (oracle.com/cloud/cost-estimator)*
*Prices are US region USD estimates and may vary by region and negotiated discounts.*
