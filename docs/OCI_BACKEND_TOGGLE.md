# aryx-o — OCI Backend Toggle

**Branch:** `feat/oci-backend-toggle`
**Owner:** m.munir@giggso.com
**Prepared:** 2026-06-22

---

## Overview

aryx runs entirely on local/self-hosted services today (pymupdf, Ollama,
Postgres, FalkorDB). aryx-o introduces OCI-managed equivalents for each
pipeline stage. This document defines the **per-service backend toggle** —
every component can be switched independently between `local` and `oci`
via environment variables, with no code changes required.

All defaults are `local`. The OCI SDK is never imported unless at least one
backend is explicitly set to `oci`.

---

## Environment Variables

All variables use the `ARYX_` prefix (consistent with existing config).

### Convenience toggle

| Variable | Values | Default | Effect |
|---|---|---|---|
| `ARYX_OCI_MODE` | `true / false` | `false` | Shortcut: sets **all** backends to `oci` unless a per-service var overrides it |

### Per-service backend selectors

| Variable | Values | Default | Controls |
|---|---|---|---|
| `ARYX_PARSE_BACKEND` | `local \| oci` | `local` | Document parsing — pymupdf/pytesseract vs OCI Document Understanding |
| `ARYX_EMBED_BACKEND` | `local \| oci` | `local` | Embedding — Ollama nomic-embed-text vs OCI GenAI Cohere Embed v3 |
| `ARYX_EMBED_MODEL` | model string | *(backend default)* | Override embed model for either backend |
| `ARYX_LLM_CHEAP_BACKEND` | `local \| oci` | `local` | Cheap-tier LLM — Ollama / Anthropic vs OCI GenAI Command R |
| `ARYX_LLM_CHEAP_MODEL` | model string | *(backend default)* | Override cheap-tier model |
| `ARYX_LLM_FRONTIER_BACKEND` | `local \| oci` | `local` | Frontier-tier LLM — Anthropic Claude vs OCI GenAI Command R+ |
| `ARYX_LLM_FRONTIER_MODEL` | model string | *(backend default)* | Override frontier-tier model |
| `ARYX_DB_BACKEND` | `local \| oci` | `local` | Relational store — Postgres vs Oracle ADB 23ai *(Phase 2)* |
| `ARYX_WORKER_BACKEND` | `local \| oci_functions \| oci_dataflow` | `local` | Pipeline worker — ThreadPoolExecutor vs OCI Functions vs OCI Data Flow *(Phase 2)* |
| `ARYX_GRAPH_BACKEND` | `falkordb \| oci_graph` | `falkordb` | Graph store — FalkorDB vs Oracle Graph Studio *(Phase 2)* |

### OCI connection settings

| Variable | Default | Required when |
|---|---|---|
| `ARYX_OCI_COMPARTMENT_ID` | `""` | Any backend = `oci` |
| `ARYX_OCI_REGION` | `us-chicago-1` | Any backend = `oci` |
| `ARYX_OCI_ADB_DSN` | `""` | `ARYX_DB_BACKEND=oci` |
| `ARYX_OCI_INGEST_FN_ID` | `""` | `ARYX_WORKER_BACKEND=oci_functions` |
| `ARYX_OCI_DATAFLOW_APP_ID` | `""` | `ARYX_WORKER_BACKEND=oci_dataflow` |

---

## Resolution Order

Per-service variable wins over the `ARYX_OCI_MODE` shortcut:

```
effective_backend(service) =
    per_service_var           if explicitly set (not equal to default "local")
    "oci"                     if ARYX_OCI_MODE=true
    "local"                   otherwise
```

---

## Example Configurations

### 1 — Pure local (default, no OCI needed)
```bash
# No env vars required — everything runs locally
```

### 2 — Full OCI (all services)
```bash
ARYX_OCI_MODE=true
ARYX_OCI_COMPARTMENT_ID=ocid1.compartment.oc1..xxxx
ARYX_OCI_REGION=us-chicago-1
```

### 3 — Mixed: OCI parsing only, local embed + LLM
```bash
ARYX_PARSE_BACKEND=oci
ARYX_OCI_COMPARTMENT_ID=ocid1.compartment.oc1..xxxx
# embed stays on Ollama nomic-embed-text
# LLM stays on configured Anthropic / Ollama broker
```

### 4 — Full OCI AI layer, local databases
```bash
ARYX_OCI_MODE=true
ARYX_DB_BACKEND=local      # Postgres stays
ARYX_GRAPH_BACKEND=falkordb  # FalkorDB stays
ARYX_WORKER_BACKEND=local    # ThreadPoolExecutor stays
ARYX_OCI_COMPARTMENT_ID=ocid1.compartment.oc1..xxxx
```

### 5 — OCI mode but override embed model
```bash
ARYX_OCI_MODE=true
ARYX_EMBED_MODEL=cohere.embed-english-v3.0   # use English-only model
ARYX_OCI_COMPARTMENT_ID=ocid1.compartment.oc1..xxxx
```

---

## Backend Defaults Per Service

| Service | Local default | OCI default |
|---|---|---|
| Parse | pymupdf + pytesseract (per connector) | OCI Document Understanding — Text + Table Detection |
| Embed | nomic-embed-text · dim=768 | cohere.embed-multilingual-v3.0 · dim=1024 |
| LLM cheap | broker catalog (Ollama / Anthropic cheap) | cohere.command-r-16k |
| LLM frontier | broker catalog (Anthropic claude-3) | cohere.command-r-plus |
| DB | Postgres (psycopg3) | Oracle ADB 23ai (python-oracledb) — Phase 2 |
| Worker | ThreadPoolExecutor | OCI Functions (per-doc) or OCI Data Flow (batch) — Phase 2 |
| Graph | FalkorDB (redis) | Oracle Graph Studio — Phase 2 |

**Embed dim note:** `ARYX_EMBED_DIM` must match the active embed model.
Set `ARYX_EMBED_DIM=1024` when using OCI Cohere Embed v3. The startup check
in `embed.py` will fail fast with a clear error on mismatch.

---

## Component Swap Map

| Stage | Current file | Local implementation | OCI implementation |
|---|---|---|---|
| Document parse | `connectors/doc_router.py` | `PdfConnector`, `DocxConnector`, `PptxConnector`, `ImageConnector` | `OciDocConnector` → Document Understanding API |
| Embedding | `broker/__init__.py` `Broker.embed()` | POST Ollama `/api/embed` | `oci.ai_llm.GenerativeAiClient.generate_embeddings()` |
| LLM cheap | `llm.py` `complete_json()` | Ollama / Anthropic via broker | `oci_genai_json()` → Command R |
| LLM frontier | `llm.py` `complete_json()` | Anthropic Claude via broker | `oci_genai_json()` → Command R+ |
| DB *(Phase 2)* | all `*_store.py` files | psycopg3 + Postgres | python-oracledb + Oracle ADB |
| Worker *(Phase 2)* | `api/file_ingest_api.py` | ThreadPoolExecutor | OCI Functions SDK or Data Flow SDK |
| Graph *(Phase 2)* | `graph/falkor_store.py` | FalkorDB redis client | Oracle Graph Studio REST / SDK |

---

## Phase 1 — AI-Layer Swap (this branch)

**New files:**
- `src/aryx/connectors/oci_doc.py` — `OciDocConnector`: calls OCI Document Understanding, returns same `Page` objects as local connectors
- `src/aryx/oci_client.py` — lazy singleton factory: `get_doc_client()`, `get_genai_client()`; auth via instance principal or `~/.oci/config`

**Modified files:**
- `src/aryx/config.py` — 16 new fields + `effective_*_backend()` helpers
- `src/aryx/connectors/doc_router.py` — `_connector_for()` checks `effective_parse_backend()`
- `src/aryx/broker/__init__.py` — `Broker.embed()` routes to OCI GenAI when `effective_embed_backend() == "oci"`
- `src/aryx/llm_providers.py` — adds `oci_genai_json(spec, system, user)`
- `src/aryx/llm.py` — `complete_json()` adds `elif spec.provider == "oci":` branch
- `src/aryx/broker/catalog.json` — adds OCI model entries for cheap + frontier tiers
- `requirements.txt` — adds `oci~=2.130`

---

## Phase 2 — Database + Worker + Graph (deferred)

Phase 2 implements the three remaining backend vars. Each maps to a new adapter
that satisfies the existing store interface — no pipeline code changes needed:

| Backend var | New adapter | Replaces |
|---|---|---|
| `ARYX_DB_BACKEND=oci` | `OracleAdbStore` (python-oracledb) | psycopg3 Postgres stores |
| `ARYX_WORKER_BACKEND=oci_functions` | OCI Functions SDK trigger in `file_ingest_api.py` | ThreadPoolExecutor |
| `ARYX_WORKER_BACKEND=oci_dataflow` | OCI Data Flow SDK job submit | ThreadPoolExecutor |
| `ARYX_GRAPH_BACKEND=oci_graph` | `OracleGraphStore` (Graph Studio REST) | `falkor_store.py` |

---

## OCI Auth

aryx-o supports two OCI auth methods, auto-detected in order:

1. **Instance principal** — running inside OCI (Compute, Functions, Data Flow). No config file needed.
2. **Config file** — `~/.oci/config` for local development. Default profile used unless `OCI_CONFIG_PROFILE` is set.

```python
# src/aryx/oci_client.py
import oci

def _config():
    try:
        return oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    except Exception:
        return oci.config.from_file()
```

---

*aryx-o · giggso · 2026-06-22*
