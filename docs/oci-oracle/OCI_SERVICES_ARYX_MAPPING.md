# OCI Services — What Each Does and Where It Fits in aryx

This document explains three Oracle/OCI services in plain language, maps each
one to the exact aryx component it replaces or extends, and shows what changes
in aryx to use them.

---

## Service 1 — Oracle Graph Studio & RDF Semantic Graph

### What This Service Is

Oracle Graph Studio is the dedicated environment inside Oracle Autonomous
Database for storing, querying, and reasoning over semantic web data.

It is not a standalone product — it is a feature of Oracle Autonomous Database
that activates when you work with RDF (Resource Description Framework) data.

**What it does technically:**

- Stores knowledge in the form of **triples** — every fact is `(Subject, Predicate, Object)`
  e.g. `(Acme Corp, suppliedBy, Beta Ltd)`
- Understands OWL (Web Ontology Language) — the formal standard for declaring
  what types exist, how they relate, and what can be inferred from them
- Understands SKOS (Simple Knowledge Organisation System) — the standard for
  thesauri, taxonomies, and controlled vocabularies
- Provides a **SPARQL endpoint** — a REST API that accepts standard W3C SPARQL
  queries and returns JSON results, identical in structure to any SPARQL store
  (Apache Jena, GraphDB, Protégé)
- Applies **automated reasoning** — when you query, it can apply RDFS++ or
  OWL 2 RL rules automatically, deriving new facts that were never explicitly
  stored

**Plain example of automated reasoning:**

```
Stored:    SavingsAccount  rdfs:subClassOf  BankAccount
Stored:    entity:42       rdf:type         SavingsAccount

Query:     "Give me all BankAccount instances"
Returns:   entity:42      ← even though it was typed SavingsAccount, not BankAccount
```

This entailment is automatic. aryx today cannot do this — it only returns
entities that were explicitly typed `BankAccount` at projection time.

---

### Where aryx Connects to This Service

aryx already exports to RDF/Turtle on demand via
`src/aryx/ontology/rdf/exporter.py`. The exporter converts the aryx property
graph into the exact OWL format Oracle Graph Studio expects:

| aryx concept | OWL export | Oracle Graph Studio reads it as |
|---|---|---|
| `aryx_ontology_type` row | `owl:Class` | A type in the semantic model |
| attribute on a type | `owl:DatatypeProperty` with `rdfs:domain` | A typed data property |
| relationship between types | `owl:ObjectProperty` | A semantic relationship |
| resolved entity | `owl:NamedIndividual` | An instance of the class |
| ontology axiom (`disjoint_with`, `domain`, `range`) | `owl:disjointWith`, `rdfs:domain`, `rdfs:range` | Formal constraints, enforced during reasoning |
| entity hierarchy (`parent_type`) | `rdfs:subClassOf` | Inheritance — queries for parent type return child instances |

**The exporter is already production-quality.** No changes needed to start
feeding Oracle Graph Studio.

---

### What aryx Port This Maps To

**`GraphStorePort` and `GraphReaderPort`** in `src/aryx/ports/protocols.py`.

Today both ports are backed by FalkorDB:

```
ARYX_ADAPTER_GRAPH_READER=aryx.graph.reader:GraphReader       (FalkorDB)
ARYX_ADAPTER_GRAPH_STORE=aryx.graph.falkor_store:FalkorStore  (FalkorDB)
```

Oracle Graph Studio replaces FalkorDB as the graph substrate by providing
a new adapter class for each port:

```bash
ARYX_ADAPTER_GRAPH_READER=aryx.adapters.oracle.graph:OracleGraphReader
ARYX_ADAPTER_GRAPH_STORE=aryx.adapters.oracle.graph:OracleGraphStore
```

The call-sites in aryx — `project.py`, `reader.py`, the Ask flow — never change.
They call `find_entities()`, `add_entity()`, `neighbors()`, `shortest_path()` on
the port contract. The adapter translates those calls into PGQL or SPARQL
against Oracle Graph Studio.

---

### What aryx Gains

| Current (FalkorDB) | After Oracle Graph Studio |
|---|---|
| Cypher queries — no reasoning | SPARQL queries with RDFS++ / OWL 2 RL inference during query |
| Hard cap at 500 results (`reader.py:63`) | No cap — full result sets via SPARQL pagination |
| `rdfs:subClassOf` only written at projection time | `rdfs:subClassOf` entailment applied live at query time |
| No SPARQL endpoint exposed | Built-in SPARQL REST endpoint — external AI pipelines can query aryx directly |
| W3C portability: none | Full W3C SPARQL 1.1 compliance |
| Transitive closure: max 4 hops | Unbounded (`owl:TransitiveProperty`) |

The SPARQL REST endpoint is the biggest operational gain: external AI agents,
analytics tools, and compliance systems can query the aryx knowledge graph
using standard SPARQL without any aryx-specific client code.

---

## Service 2 — Oracle Autonomous Database 23ai (Converged Semantic Layer)

### What This Service Is

Oracle Autonomous Database 23ai is the operational database — the source of
truth for all persistent data. The "23ai" label marks two specific features
added in the Oracle Database 23 release:

**Feature 1: SQL:2023 Property Graphs**

Property graphs are a query model where nodes and edges have attributes
(properties), and you can query patterns across them using a graph-specific
syntax. The SQL:2023 standard built this natively into SQL.

What this means in practice:

```sql
-- Define a property graph view over existing relational tables
CREATE PROPERTY GRAPH aryx_supply_chain
  VERTEX TABLES (aryx_entity LABEL entity PROPERTIES (id, name, ontology_type))
  EDGE TABLES   (aryx_relationship LABEL relates
                 SOURCE KEY (source_entity_id) REFERENCES aryx_entity(id)
                 DESTINATION KEY (target_entity_id) REFERENCES aryx_entity(id));

-- Query the graph without exporting to FalkorDB
SELECT * FROM GRAPH_TABLE(aryx_supply_chain
  MATCH (s IS entity WHERE s.ontology_type = 'Supplier')
        -[r IS relates]->
        (p IS entity WHERE p.ontology_type = 'Product')
  COLUMNS (s.name AS supplier, p.name AS product));
```

The `aryx_entity` and `aryx_relationship` tables that aryx already writes to
Postgres **become a queryable property graph** without any ETL, export, or
secondary store. The projection stage (`project_graph()` in `src/aryx/project.py`)
that writes to FalkorDB becomes unnecessary for query purposes — Oracle queries
the Postgres tables directly as a graph.

**Feature 2: Select AI (DBMS_CLOUD_AI)**

Select AI is a database package that connects Oracle Autonomous Database to
an LLM and uses the database schema as context to convert natural language
questions into SQL or SPARQL queries, execute them, and return results.

```sql
-- One-time setup: tell Oracle which LLM to use and which tables are the schema context
EXEC DBMS_CLOUD_AI.CREATE_PROFILE(
  profile_name => 'ARYX_AI',
  attributes   => '{
    "provider": "cohere",
    "credential_name": "OCI_CRED",
    "object_list": [
      {"owner": "aryx", "name": "ARYX_ENTITY"},
      {"owner": "aryx", "name": "ARYX_RELATIONSHIP"},
      {"owner": "aryx", "name": "ARYX_ONTOLOGY_TYPE"}
    ]
  }'
);

-- At query time: natural language → SQL, executed, results returned
SELECT AI 'Which suppliers provide components used in recalled products?';
-- Oracle generates the JOIN query, executes it, returns rows.
-- No Python, no LLM round-trip in your code, no hallucinated column names.
```

The key difference from aryx's current Ask flow: aryx's Ask converts NL to a
Cypher query via an LLM call in Python, then executes it against FalkorDB.
Select AI does the same conversion but **inside the database**, using the real
schema as context, which eliminates the hallucinated-column-name problem.

---

### Where aryx Connects to This Service

Two connection points in aryx:

**Connection Point 1 — RelationalPort (`src/aryx/ports/protocols.py`)**

aryx's entire source of truth — `aryx_entity`, `aryx_relationship`,
`aryx_ontology_type`, `aryx_ontology_axiom`, `aryx_chunk`, all 29 migrations —
lives in Postgres. Oracle Autonomous Database 23ai is a drop-in replacement
for Postgres at this level. The same tables, same schema, same migration
scripts (with minor SQL dialect changes) run on Oracle ADB.

The adapter swap:

```bash
ARYX_ADAPTER_RELATIONAL=aryx.adapters.oracle.rdb:OracleRelationalAdapter
```

**Connection Point 2 — The Ask flow and `LlmPort`**

aryx's Ask flow is in `src/aryx/api/ask_api.py`. It currently:
1. Calls the LLM to convert the user's question to a Cypher query
2. Executes the Cypher query against FalkorDB
3. Returns entity results to the LLM for a final answer

With Select AI on Oracle ADB 23ai:
1. The NL question goes directly to `DBMS_CLOUD_AI.GENERATE` inside Oracle
2. Oracle generates and executes a SQL/PGQL query against its own tables
3. Results come back as SQL rows — no Cypher, no FalkorDB round-trip

The `LlmPort` adapter for this path routes through the database rather than
an external LLM API:

```bash
ARYX_ADAPTER_LLM=aryx.adapters.oracle.selectai:SelectAiLlm
```

---

### What aryx Gains

| Current (Postgres + FalkorDB + LLM) | After Oracle ADB 23ai |
|---|---|
| Two stores to keep in sync (Postgres source of truth + FalkorDB projection) | One store — property graph queries run directly on `aryx_entity` / `aryx_relationship` |
| Project stage (`project_graph()`) required before Ask can answer | Project stage optional — SQL:2023 graph queries run against source tables |
| Ask generates Cypher via LLM — may hallucinate column/property names | Select AI uses real schema metadata — generated SQL references real column names |
| Scalability bottleneck P1: fetchall() RAM spike during projection | Streaming cursors + Oracle ADB distributed query — no single-process RAM limit |
| Scalability bottleneck P2: Python rule loop (10M iterations at 1M entities) | SQL pushdown into Oracle ADB — indexed query, Python never iterates |

The elimination of the two-store architecture (Postgres + FalkorDB) is the
largest structural simplification. The projection stage (`project_graph()`)
exists solely to copy data from Postgres into FalkorDB so graph queries can
run. With SQL:2023 property graphs on Oracle ADB, that stage is redundant.

---

## Service 3 — OCI Generative AI & Orchestration Pipelines

### What This Service Is

This is a combined pipeline of three OCI services that together automate the
extraction of ontologies directly from raw company documents — PDFs, Word
files, strategy decks, contracts, SOWs — without requiring a human to manually
define types, relationships, or rules.

The three components are:

**Component A: OCI Document Understanding**

A managed OCR and document analysis service. It takes a PDF, image, or scanned
document and produces structured output — not raw text, but a layout-aware
JSON or Markdown document that preserves:
- Which text is a heading vs body vs table cell vs footnote
- Table structure (row/column positions, cell spans)
- Page number, bounding box coordinates for each text block
- Key-value pairs detected in forms (e.g. "Invoice Date: 2024-01-15")

This is architecturally different from what aryx uses today.

aryx uses `pymupdf` (fitz) for PDF text extraction and `pytesseract` for image
OCR in `src/aryx/connectors/pdf.py`:

```python
# aryx current: pymupdf extracts raw text flow, tesseract OCRs embedded images
doc = fitz.open(str(self._path))
for page_num, page in enumerate(doc, start=1):
    parts = [page.get_text()]                         # raw text, no layout
    for img_info in page.get_images(full=True):
        ocr_text = _ocr_image_bytes(...)              # tesseract OCR
```

OCI Document Understanding produces:
```json
{
  "pages": [{
    "pageNumber": 1,
    "blocks": [
      {"blockType": "TABLE", "cells": [...]},
      {"blockType": "PARAGRAPH", "text": "...", "confidence": 0.98},
      {"blockType": "KEY_VALUE_PAIR", "key": "Contract Date", "value": "2024-01-15"}
    ]
  }]
}
```

The layout-aware output means the LLM extraction step receives structured context
("this text is a table header", "this is a key-value pair") rather than a flat
text dump, which dramatically improves entity extraction quality for structured
documents like contracts, financial reports, and invoices.

**Component B: OCI Generative AI (enterprise models)**

OCI hosts enterprise-grade LLMs (Cohere Command R+, Meta Llama 3, Mistral)
within the customer's OCI tenancy. Data sent to these models never leaves the
customer's cloud boundary — unlike external API calls to OpenAI or Anthropic.

For ontology learning specifically, OCI GenAI runs the extraction step:
reading the structured Document Understanding output, identifying entities,
their attributes, and the relationships between them, and expressing them as
RDF triples or as aryx-compatible `RawRecord` objects.

**Component C: LangChain LLMGraphTransformer (orchestration layer)**

LangChain's `LLMGraphTransformer` is an open-source Python class that takes
document text and asks an LLM to extract a property graph from it. It outputs
a list of `(node, relationship, node)` triples.

```python
from langchain_experimental.graph_transformers import LLMGraphTransformer

transformer = LLMGraphTransformer(llm=oci_llm)
graph_docs = transformer.convert_to_graph_documents(documents)
# Each graph_doc has: nodes=[Node(id, type, properties)], relationships=[Relationship(...)]
```

This is the "ontology learning" piece — the pattern of entity types and
relationships that the LLM extracts from documents becomes the basis of the
ontology, rather than requiring a human to define it first.

---

### Where aryx Connects to This Service

Three connection points, one per component:

**Connection Point 1 — PdfConnector (Document Understanding replaces pymupdf)**

File: `src/aryx/connectors/pdf.py`

Today: `PdfConnector.extract_pages()` calls `fitz.open()` → raw text, plus
`pytesseract` for embedded images.

With OCI Document Understanding: a new `OciDocumentConnector` replaces
`PdfConnector` for the `aryx-o` edition. Instead of returning raw page text,
it returns layout-aware blocks — tables, key-value pairs, paragraphs with
confidence scores. The `DocumentRouterConnector` in `doc_router.py` which
dispatches to the right connector per file extension becomes the integration
point:

```python
# doc_router.py — current
_EXT_MAP: dict[str, type] = {
    ".pdf": PdfConnector,                  # pymupdf + tesseract
    ...
}

# doc_router.py — aryx-o edition
_EXT_MAP: dict[str, type] = {
    ".pdf": OciDocumentConnector,          # OCI Document Understanding
    ...
}
```

The output of `OciDocumentConnector.extract_pages()` is richer text — tables
become structured markdown, form fields become explicit key-value strings, and
each block carries a confidence score. The downstream chunk → PII → embed →
extract pipeline is unchanged.

**Connection Point 2 — extract_mentions (LLMGraphTransformer replaces the aryx LLM extractor)**

File: `src/aryx/ontology/extract.py`

Today: `extract_mentions()` calls the aryx LLM broker at the "menial" tier
with a hand-crafted system prompt that asks the LLM to return entity type,
name, attributes, and a verbatim span.

With LLMGraphTransformer on OCI GenAI: the transformer is wired as an
alternative extraction backend. It returns `(node, relationship, node)` triples
rather than flat entity mentions, which means relationship discovery happens at
extraction time — not in a separate expensive `relate=True` pipeline stage.

```python
# src/aryx/ontology/extract.py — new OCI path

def extract_mentions_oci(chunks: list[DocumentChunk], oci_llm,
                          context: str) -> list[RawRecord]:
    transformer = LLMGraphTransformer(llm=oci_llm)
    docs = [Document(page_content=c.text) for c in chunks]
    graph_docs = transformer.convert_to_graph_documents(docs)
    records = []
    for gd in graph_docs:
        for node in gd.nodes:
            records.append(RawRecord(
                type=node.type,
                name=node.id,
                attributes=node.properties,
                source_ref=SourceRef(system="document", dataset="doc", record_id=node.id)
            ))
    return records
```

The verbatim-span gate (`_verbatim_ok` in `extract.py`) still applies — any
entity whose name is absent from the source text is rejected before reaching
resolution, preventing hallucinated nodes regardless of which extractor produced them.

**Connection Point 3 — LlmPort (`src/aryx/ports/protocols.py`)**

OCI Generative AI is the provider behind both the extraction LLM call and the
Select AI NL-to-query flow. The `LlmPort` adapter routes aryx broker calls to
OCI GenAI:

```bash
ARYX_ADAPTER_LLM=aryx.adapters.oracle.genai:OracleGenAiLlm
```

When `ARYX_EDITION=aryx-o`, the broker's `"frontier"` tier calls OCI Cohere
Command R+ or Meta Llama 3 instead of Anthropic Claude or OpenAI GPT-4.
The `complete_json()` and `complete_text()` method signatures on `LlmPort`
are unchanged — the adapter absorbs the OCI API differences.

---

### What aryx Gains

| Current (pymupdf + tesseract + aryx LLM extractor) | After OCI GenAI pipeline |
|---|---|
| Raw text dump from PDF — no layout context | Layout-aware blocks: tables, key-value pairs, paragraphs with confidence scores |
| tesseract OCR — degrades on complex layouts | OCI Document Understanding — deep layout analysis, confidence scores per block |
| Relationship discovery requires separate `relate=True` stage (50-pair cap) | LLMGraphTransformer extracts `(entity, relationship, entity)` triples at extraction time — no separate stage |
| LLM calls go to external provider (OpenAI/Anthropic) — data leaves boundary | OCI GenAI runs inside customer's OCI tenancy — zero data egress |
| Ontology built by human defining types first, then ingesting | Ontology learning: types and relationships emerge from document content automatically |

The ontology learning capability is the most structurally significant change:
today aryx requires a human to define ontology types before ingest
(`ontology_type` is a required parameter in `run_pipeline()`). With
LLMGraphTransformer, types emerge from the documents themselves — aryx
discovers the ontology rather than being told it.

---

## Full Integration Map — All Three Services Together

```
aryx pipeline today:

PDF file
  → PdfConnector (pymupdf + tesseract)       [raw text]
  → chunk_pages()                             [text chunks]
  → screen_chunks() PII                      [clean chunks]
  → embed_chunks() (nomic-embed-text)        [768-dim vectors → aryx_chunk_embedding]
  → extract_mentions() (aryx LLM, menial)   [entity mentions only, no relationships]
  → resolve_run() (blocking + scoring)       [canonical entities → aryx_entity]
  → run_pipeline(relate=True)               [50-pair relationship inference, expensive]
  → project_graph() (FalkorDB write)         [graph projection, P1 RAM spike]

aryx-o pipeline (all three OCI services):

PDF file
  → OciDocumentConnector                     [layout-aware JSON — tables, KV pairs]
  → chunk_pages()                             [same — unchanged]
  → screen_chunks() PII                      [same — unchanged]
  → embed_chunks() (OCI embed model)         [vectors → Oracle ADB vector store]
  → LLMGraphTransformer (OCI GenAI)          [entities + relationships as triples]
  → resolve_run()                            [same resolution logic — unchanged]
  → Oracle ADB 23ai write                    [entities + relationships into SQL:2023 graph]
  → Oracle Graph Studio SPARQL endpoint      [queries served by Oracle — no FalkorDB]
```

**What stays the same:** chunk_pages, PII screening, entity resolution
(blocking + scoring + UnionFind), all port contracts, all API endpoints,
all UI surfaces. The aryx business logic is untouched.

**What changes:** the PDF parser, the entity extractor, the LLM provider,
the graph store, and the query engine — all swapped via env vars.

---

## Adapter Env Vars to Enable aryx-o with All Three Services

```bash
ARYX_EDITION=aryx-o

# Service 1 — Oracle Graph Studio (GraphReaderPort + GraphStorePort)
ARYX_ADAPTER_GRAPH_READER=aryx.adapters.oracle.graph:OracleGraphReader
ARYX_ADAPTER_GRAPH_STORE=aryx.adapters.oracle.graph:OracleGraphStore

# Service 2 — Oracle ADB 23ai (RelationalPort + Ask flow)
ARYX_ADAPTER_RELATIONAL=aryx.adapters.oracle.rdb:OracleRelationalAdapter

# Service 3 — OCI GenAI (LlmPort — covers extraction + NL querying)
ARYX_ADAPTER_LLM=aryx.adapters.oracle.genai:OracleGenAiLlm

# OCI Document Understanding replaces PdfConnector — set via connector config
ARYX_DOCUMENT_CONNECTOR=oci
```

All five classes listed above are the implementation gap — the port contracts
are defined and ready, the env var wiring exists, the adapter module path
`aryx.adapters.oracle.*` needs to be built.

---

## Status — What Exists vs What Needs to Be Built

| Component | aryx today | aryx-o gap |
|---|---|---|
| RDF/OWL export | `rdf/exporter.py` ✅ | Feed to Oracle Graph Studio — no code change |
| Port contracts | `ports/protocols.py` ✅ | Oracle adapter classes need to be written |
| Adapter swap mechanism | `ports/config.py` ✅ | Works today — just needs adapter classes |
| Edition flag | `edition.py` ✅ | `ARYX_EDITION=aryx-o` already handled |
| OracleGraphReader | Not exists ❌ | Wraps PGQL / SPARQL calls to Oracle Graph Studio |
| OracleGraphStore | Not exists ❌ | Writes entities as OWL NamedIndividuals via Oracle API |
| OracleRelationalAdapter | Not exists ❌ | psycopg → cx_Oracle / python-oracledb swap |
| OracleGenAiLlm | Not exists ❌ | OCI SDK call to OCI GenAI inference endpoint |
| OciDocumentConnector | Not exists ❌ | Replaces PdfConnector — calls OCI Document Understanding |
| LLMGraphTransformer wiring | Not exists ❌ | New extraction path in ontology/extract.py |

---

*Generated: 2026-06-19 | aryx project | giggso*
*Source files: src/aryx/ports/protocols.py, src/aryx/ports/config.py,*
*src/aryx/edition.py, src/aryx/connectors/pdf.py, src/aryx/connectors/doc_router.py,*
*src/aryx/ontology/extract.py, src/aryx/ontology/rdf/exporter.py,*
*src/aryx/pipeline/orchestrate.py, src/aryx/graph/falkor_store.py*
