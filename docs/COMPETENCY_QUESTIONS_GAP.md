# Competency Questions — Gap Analysis & Implementation Paths

Competency Questions (CQs) are the formal mechanism in ontology engineering to test whether
an ontology is complete and correct. A CQ is a natural language question the ontology
**must** be able to answer. If the answer is unreachable — either because the data is missing
or because the ontology does not model the required relationship — the CQ fails.

This document covers:
- What aryx has today and where the gap is
- Path A: filling the gap **within aryx, without OCI**
- Path B: filling the gap **with OCI Oracle services**

---

## What aryx Has Today

### The Brief (5-field METHONTOLOGY-style)

Defined in `src/aryx/brief.py`, stored via migration `0016_workspace_brief.sql`.

The brief captures five fields **before** ingest:

| Field | Purpose |
|---|---|
| Domain | Which subject area the graph covers |
| Aim | What outcome the knowledge model should enable |
| Objectives | 3–6 measurable goals |
| Scope | What entity kinds are IN and OUT |
| Roles | Who uses the graph and what question each role asks |

**The brief is intent-setting, not ontology testing.** It seeds every extraction,
discovery, and inference prompt via `brief.serialize()` → prompt context. It does not
generate executable test questions and does not verify that the ontology can answer them.

### Ingest Questions (`aryx_ingest_question`)

Defined in `0025_ingest_questions.sql`, implemented in
`src/aryx/store/ingest_question_store.py`.

These are **pipeline HITL clarifying questions** raised mid-ingest:
- Entity collapse candidates ("should record A and B merge into one entity?")
- Ambiguous type mappings ("is this a Person or an Organisation?")
- FK match disambiguation ("which entity does this foreign key refer to?")

These are not CQs. They resolve data ambiguity during ingestion, not ontology coverage.

### RDF/OWL Export

Defined in `src/aryx/ontology/rdf/exporter.py`.

aryx exports the full workspace graph to OWL/Turtle on demand:
- ontology types → `owl:Class`
- attributes → `owl:DatatypeProperty` with `rdfs:domain`
- relationships → `owl:ObjectProperty`
- entities → `owl:NamedIndividual`
- axioms → `owl:disjointWith`, `owl:equivalentClass`, `rdfs:domain`, `rdfs:range`

**This export is the bridge.** Any SPARQL-capable store can consume it.
The comment in the file explicitly names: "Protégé, GraphDB, Apache Jena, any SPARQL store."

---

## The Gap — What True CQs Require

A complete CQ system has four sub-problems:

| # | Sub-problem | aryx today | Status |
|---|---|---|---|
| CQ-1 | Generate testable questions from brief + ontology | Brief captures intent only | ❌ Gap |
| CQ-2 | Execute CQ against the ontology/graph | No SPARQL endpoint | ❌ Gap |
| CQ-3 | Validate that the ontology path exists for a CQ | Axiom table exists but no CQ validator | ❌ Gap |
| CQ-4 | Score CQ coverage per workspace | Nothing | ❌ Gap |

---

## Path A — Fill the Gap Without OCI (aryx-native)

This path uses aryx's existing LLM broker (`brief_draft.py` pattern), PostgreSQL,
rdflib, and the existing RDF exporter. No new infrastructure required.

### Step A1 — CQ Generation

**What to build:** A new `cq_draft.py` module, mirroring `brief_draft.py`.

The LLM receives the serialised brief (`brief.serialize()`) plus the list of
ontology types and relationships from `OntologyStore`, and returns 5–10 natural
language CQs specific to the workspace domain.

```python
# src/aryx/cq_draft.py  (new file — mirrors brief_draft.py)

_SYSTEM = (
    "You are an ontology engineer. From the brief and the ontology structure below, "
    "generate 5 to 10 Competency Questions. Each question must be answerable by "
    "traversing the ontology — name exactly which entity types and relationships are "
    "involved. Return JSON: {questions: [{nl: str, types: [str], properties: [str]}]}"
)

def draft_cqs(broker, brief: dict, types: list[str],
              relationships: list[str]) -> list[dict]:
    user = (
        f"Brief:\n{brief_lib.serialize(brief)}\n\n"
        f"Ontology types: {', '.join(types)}\n"
        f"Relationships: {', '.join(relationships)}"
    )
    data = complete_json(broker, "frontier", _SYSTEM, user, _CQ_SCHEMA)
    return data.get("questions", [])
```

**Example output for a supplier/product domain:**

```
CQ1: Which suppliers provide components used in products that were recalled
     in the last 12 months?
     → types: [Supplier, Component, Product]   properties: [supplies, usedIn, recallDate]

CQ2: Which employees report (directly or transitively) to a given manager?
     → types: [Employee, Manager]   properties: [reportsTo]

CQ3: Which contracts are associated with customers in a high-risk jurisdiction?
     → types: [Contract, Customer, Jurisdiction]   properties: [signedWith, locatedIn]
```

### Step A2 — CQ Storage

**What to build:** Migration `0029_competency_questions.sql`

```sql
CREATE TABLE IF NOT EXISTS aryx_cq (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT NOT NULL REFERENCES aryx_workspace(id) ON DELETE CASCADE,
    nl              TEXT NOT NULL,
    types_json      JSONB NOT NULL DEFAULT '[]',
    properties_json JSONB NOT NULL DEFAULT '[]',
    sparql          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'draft',
    last_result     TEXT NOT NULL DEFAULT '',
    passed          BOOLEAN,
    checked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS aryx_cq_ws_status_idx
    ON aryx_cq(workspace_id, status, created_at);
```

`status` values: `draft` → `sparql_ready` → `passed` / `failed`

### Step A3 — NL to SPARQL (aryx-native)

**What to build:** A second LLM call that converts each CQ's natural language +
types/properties into an executable SPARQL SELECT query.

```python
_SPARQL_SYSTEM = (
    "You are a SPARQL expert. Convert the natural language question into a "
    "valid SPARQL SELECT query using the provided prefixes and ontology terms. "
    "Return only the SPARQL string, no explanation."
)

def nl_to_sparql(broker, nl: str, types: list[str],
                 properties: list[str], base_uri: str) -> str:
    user = (
        f"Base URI: {base_uri}\n"
        f"Types available: {', '.join(types)}\n"
        f"Properties available: {', '.join(properties)}\n\n"
        f"Question: {nl}"
    )
    text, _, _ = complete_text(broker, "frontier", _SPARQL_SYSTEM, user)
    return text.strip()
```

### Step A4 — CQ Execution Against RDF Export

**What to build:** A `cq_runner.py` module that uses `rdflib` (already a dependency
via the RDF exporter) to execute SPARQL directly against the exported graph.

```python
# src/aryx/cq_runner.py  (new file)
from rdflib import ConjunctiveGraph
from aryx.ontology.rdf.exporter import build_graph

def run_cq(bundle, base_uri: str, sparql: str) -> dict:
    graph = build_graph(bundle, base_uri, include_provenance=False)
    try:
        results = list(graph.query(sparql))
        return {
            "passed": len(results) > 0,
            "row_count": len(results),
            "sample": [str(r) for r in results[:5]],
            "error": None,
        }
    except Exception as exc:
        return {"passed": False, "row_count": 0, "sample": [], "error": str(exc)}
```

**No new infrastructure.** rdflib SPARQL runs in-process. The same `GraphBundle`
used by the RDF exporter is reused here — no second export step.

### Step A5 — CQ Coverage Score

**What to build:** A simple aggregation query over `aryx_cq`.

```sql
SELECT
    workspace_id,
    COUNT(*)                                        AS total_cqs,
    COUNT(*) FILTER (WHERE passed = TRUE)           AS passed,
    COUNT(*) FILTER (WHERE passed = FALSE)          AS failed,
    COUNT(*) FILTER (WHERE status = 'draft')        AS not_run,
    ROUND(
        COUNT(*) FILTER (WHERE passed = TRUE)::numeric
        / NULLIF(COUNT(*) FILTER (WHERE status != 'draft'), 0) * 100, 1
    )                                               AS coverage_pct
FROM aryx_cq
GROUP BY workspace_id;
```

**UI integration:** The existing Brief depth meter in `brief_panel.py` uses five levels
(`Generic NER → Grounded → Sharp → Expert`). CQ coverage adds a sixth measurable dimension:

```
Brief depth:  Expert   ||||||||||||||||||||  (brief filled)
CQ coverage:  78%      |||||||||||||||░░░░░  (7 of 9 CQs pass)
```

### Path A — Full Flow Diagram

```
User fills Brief (5 fields)
        │
        ▼
cq_draft.py — LLM generates 5–10 CQs from brief + ontology types
        │
        ▼
aryx_cq table — CQs stored with status=draft
        │
        ▼
nl_to_sparql() — LLM converts each CQ to SPARQL SELECT
        │
        ▼
aryx_cq.sparql updated, status=sparql_ready
        │
        ▼
cq_runner.run_cq() — rdflib executes SPARQL against RDF export (in-process)
        │
        ├── results found  → status=passed,  passed=TRUE
        └── no results     → status=failed,  passed=FALSE
                                    │
                                    ▼
                            Surface to UI: "CQ failed — ontology gap detected"
                            → user adds missing type or relationship → re-run
        │
        ▼
Coverage score = passed / (passed + failed) × 100
```

### Path A — Files to Create

| File | Description |
|---|---|
| `src/aryx/cq_draft.py` | LLM-based CQ generation from brief + ontology |
| `src/aryx/cq_runner.py` | rdflib SPARQL executor, reuses RDF exporter bundle |
| `src/aryx/store/cq_store.py` | CRUD over `aryx_cq` table |
| `src/aryx/api/cq_api.py` | REST endpoints: generate, list, run, score |
| `src/aryx/store/migrations/0029_competency_questions.sql` | Schema |
| `src/aryx/ui/cq_panel.py` | Streamlit UI panel for CQ management |

**No new services. No new dependencies beyond rdflib (already installed).**

---

## Path B — Fill the Gap with OCI

OCI provides production-grade equivalents for every step in Path A, replacing
the in-process rdflib execution with Oracle's native semantic engine and replacing
the LLM-to-SPARQL step with Oracle Select AI.

### OCI Component Map

| CQ sub-problem | Path A (aryx-native) | Path B (OCI) |
|---|---|---|
| CQ generation | LLM via `brief_draft.py` pattern | OCI Generative AI (Cohere/Llama via API) |
| CQ → SPARQL translation | LLM `nl_to_sparql()` | Oracle Select AI (Autonomous DB) |
| SPARQL execution | rdflib in-process | Oracle `SEM_MATCH` (Semantic Technologies) |
| Ontology path validation | Manual axiom check | OWL 2 RL reasoner in Oracle Graph Server (PGX) |
| Coverage scoring | SQL aggregation on `aryx_cq` | Oracle Analytics Cloud dashboard |

---

### OCI Step 1 — CQ Generation via OCI Generative AI

**Oracle service:** OCI Generative AI (endpoint: `inference.generativeai.{region}.oci.oraclecloud.com`)

The same `draft_cqs()` function from Path A works unchanged — the only difference
is the `LlmPort` adapter. With `ARYX_ADAPTER_LLM=aryx.adapters.oracle.genai:OracleGenAiLlm`,
the broker routes to OCI Generative AI instead of Ollama/Anthropic.

```python
# aryx.adapters.oracle.genai — LlmPort adapter (to be built)
import oci

class OracleGenAiLlm:
    def complete_json(self, tier, system, user, schema):
        client = oci.ai_language.AIServiceLanguageClient(config=oci.config.from_file())
        # Route to Cohere Command R+ or Meta Llama 3 via OCI GenAI
        ...
```

**Why OCI GenAI for CQ generation:**
- Runs inside OCI tenancy — no data leaves the customer's cloud boundary
- OCI Always Free tier includes limited GenAI inference
- Cohere Command R+ in OCI is optimised for structured JSON generation (exactly what CQ drafting needs)

---

### OCI Step 2 — NL to SPARQL via Oracle Select AI

**Oracle service:** Oracle Autonomous Database — Select AI feature

Select AI converts a plain English question into an executable SQL or SPARQL query
using the database schema as context.

```sql
-- Enable Select AI for the aryx semantic model
EXEC DBMS_CLOUD_AI.CREATE_PROFILE(
  profile_name => 'ARYX_CQ_PROFILE',
  attributes   => '{"provider": "cohere",
                    "credential_name": "OCI_CRED",
                    "object_list": [{"owner": "aryx", "name": "ONTOLOGY_CLASSES"},
                                    {"owner": "aryx", "name": "ONTOLOGY_PROPERTIES"}]}'
);

-- Natural language → SPARQL at query time
SELECT AI NARRATE
  'Which suppliers provide components used in products recalled in the last 12 months?';
```

Select AI uses the ontology schema metadata (`aryx_ontology_type`, `aryx_ontology_axiom`)
as context to generate the right SPARQL triple patterns — the same tables aryx already
maintains in Postgres, mirrored to Oracle ADB.

**Why this is better than LLM-to-SPARQL in Path A:**
- Select AI is aware of the actual data schema — it generates queries that reference
  real class names and property names that exist, not hallucinated ones
- The generated query runs immediately inside the database — no round-trip to Python
- Query results are cached — repeated CQ runs are instant

---

### OCI Step 3 — SPARQL Execution via Oracle SEM_MATCH

**Oracle service:** Oracle Database Semantic Technologies (built into Oracle DB / Autonomous DB)

`SEM_MATCH` is the Oracle table function that executes SPARQL SELECT, CONSTRUCT,
and ASK queries against RDF semantic models stored in Oracle.

**Step 3a — Load the aryx RDF export into Oracle Semantic Store**

```sql
-- Create the semantic model (one-time per workspace)
EXEC SEM_APIS.CREATE_SEM_MODEL('ARYX_WS1', 'ARYX_RDF_TABLE', 'TRIPLE_COL');

-- Load the Turtle export from aryx RDF exporter
EXEC SEM_APIS.LOAD_INTO_STAGING_TABLE(
  'ARYX_STAGING', 'N-TRIPLE',
  'https://objectstorage.{region}.oraclecloud.com/n/{ns}/b/{bucket}/o/aryx_ws1.ttl'
);

EXEC SEM_APIS.BULK_LOAD_INTO_SEMI_APDELS('ARYX_WS1');
```

aryx's `rdf/exporter.py` already generates the Turtle file. OCI Object Storage
is the staging area. The load is a one-time setup per workspace; incremental
exports re-load only changed triples.

**Step 3b — Execute a CQ as SPARQL via SEM_MATCH**

```sql
-- CQ: "Which suppliers provide components used in recalled products?"
SELECT supplier_label, product_label, recall_date
FROM TABLE(
  SEM_MATCH(
    'PREFIX aryx: <http://aryx.giggso.com/ontology#>
     SELECT ?supplierLabel ?productLabel ?recallDate
     WHERE {
       ?supplier rdf:type aryx:Supplier .
       ?supplier aryx:supplies ?component .
       ?component aryx:usedIn ?product .
       ?product aryx:recallDate ?recallDate .
       ?supplier rdfs:label ?supplierLabel .
       ?product rdfs:label ?productLabel .
     }',
    SEM_Models('ARYX_WS1'),
    SEM_Rulebases('RDFS'),    -- apply RDFS++ inference during query
    NULL, NULL, NULL, ' ', NULL, NULL
  )
) AS (supplier_label VARCHAR2(200), product_label VARCHAR2(200),
      recall_date VARCHAR2(100));
```

**The key difference from Path A:**
- Path A: rdflib executes SPARQL in Python process — no reasoning applied during query
- Path B: `SEM_MATCH` applies `SEM_Rulebases('RDFS')` or `SEM_Rulebases('OWL2RL')`
  **during** query execution — `rdfs:subClassOf` entailments apply automatically

This means a CQ for "all BankAccount transactions" automatically includes
`SavingsAccount` and `CurrentAccount` transactions without modifying the query,
because OWL 2 RL infers `SavingsAccount rdfs:subClassOf BankAccount`.

---

### OCI Step 4 — Ontology Path Validation via Oracle Graph Server (PGX)

**Oracle service:** Oracle Graph Server (PGX) — OWL 2 RL reasoner

When a CQ fails (returns 0 results), there are two possible causes:
1. The data is missing — the entities exist but have no matching facts
2. The ontology is incomplete — the required property chain is never declared

PGX resolves this distinction automatically.

```python
# aryx.adapters.oracle.pgx — ReasonerPort adapter (to be built)
class OraclePgxReasoner:
    def validate_cq_path(self, types: list[str],
                          properties: list[str]) -> dict:
        """Check whether the property chain in a CQ is declared in the ontology."""
        # PGX loads the OWL export, applies OWL 2 RL closure,
        # checks that each property in the chain has domain/range axioms
        session = self._server.create_session("cq_validator")
        graph = session.read_graph_with_properties(self._owl_path)
        analyst = session.create_analyst()
        # Returns: {valid: bool, missing_axioms: [str]}
        ...
```

**What PGX validates for each CQ:**
- Every type in `types_json` has an `owl:Class` declaration
- Every property in `properties_json` has an `owl:ObjectProperty` or
  `owl:DatatypeProperty` declaration
- The domain/range chain is consistent — property P connecting type A to type B
  has `rdfs:domain A` and `rdfs:range B` declared

If validation fails, PGX returns the specific missing axioms — e.g.
"property `usedIn` has no `rdfs:range` declaration for type `Product`."
This is surfaced as an actionable message to the ontology modeller.

---

### OCI Step 5 — Coverage Scoring via Oracle Analytics Cloud

**Oracle service:** Oracle Analytics Cloud (OAC)

OAC connects directly to Oracle Autonomous Database and reads the `aryx_cq` table.
A pre-built dashboard shows:

- CQ coverage % per workspace (passed / total run)
- CQ failure reasons (data gap vs ontology gap — distinguished by PGX validation)
- Coverage trend over time (as ontology matures through ingest cycles)
- Per-role coverage (which CQs associated with "Data Analyst" role are passing)

**The roles field in the Brief directly feeds this view.** Each role entered in the
Brief maps to a set of CQs. OAC groups the coverage score by role, showing which
business user personas can be served by the current ontology and which cannot.

---

## Comparison — Path A vs Path B

| Dimension | Path A (aryx-native) | Path B (OCI) |
|---|---|---|
| **Setup time** | ~2 days (4 new files, 1 migration) | ~1 week (OCI provisioning + adapter build) |
| **Infrastructure** | None — runs in existing aryx stack | Oracle ADB + Graph Server + OAC |
| **Monthly cost** | $0 (rdflib in-process) | ~$50–200/month (ADB Always Free tier + OAC) |
| **Reasoning during query** | None — rdflib SPARQL is plain query | Full OWL 2 RL + RDFS++ inference applied |
| **Ontology validation** | Manual axiom check only | PGX validates full property chain |
| **NL→SPARQL quality** | LLM may hallucinate property names | Select AI uses real schema — no hallucination |
| **Scale** | Degrades with large graphs (in-process) | Oracle ADB scales to any size |
| **Data boundary** | All data stays on-prem / self-hosted | Data enters Oracle Cloud tenancy |
| **CQ coverage dashboard** | SQL query in Streamlit | OAC full dashboard with drill-down |
| **W3C SPARQL compliance** | rdflib SPARQL 1.1 | Oracle SEM_MATCH SPARQL 1.1 + Oracle extensions |

---

## Recommendation — Which Path to Take First

**Start with Path A.** The investment is small (4 files, 1 migration) and it produces
a working CQ system immediately. The data flow is:

```
Brief → draft_cqs() → aryx_cq table → nl_to_sparql() → cq_runner.run_cq() → score
```

All on existing infrastructure, no new dependencies beyond rdflib (already installed).

**Migrate to Path B when:**
- Dataset exceeds 500K entities (Path A rdflib becomes slow)
- Ontology hierarchy is >3 levels deep (OWL 2 RL subclass inference becomes valuable)
- Business users need role-level coverage dashboards (OAC)
- Compliance requires CQ audit trails (Oracle ADB audit logging)

The migration is adapter-only — no changes to `cq_draft.py`, `cq_store.py`, or the
UI panel. The `LlmPort`, `ReasonerPort`, and `RelationalPort` adapters swap via env var:

```bash
ARYX_EDITION=aryx-o
ARYX_ADAPTER_LLM=aryx.adapters.oracle.genai:OracleGenAiLlm
ARYX_ADAPTER_REASONER=aryx.adapters.oracle.pgx:OraclePgxReasoner
```

The business logic — generate CQs, run CQs, score coverage — is identical in both paths.

---

## The aryx Bridge That Already Exists

`src/aryx/ontology/rdf/exporter.py` is the adapter between aryx's property graph
and any SPARQL store — Oracle or rdflib. It is already production-quality:
- Exports `owl:Class`, `owl:ObjectProperty`, `owl:DatatypeProperty`, `owl:NamedIndividual`
- Emits `rdfs:subClassOf`, `rdfs:domain`, `rdfs:range`, `owl:disjointWith` from the
  `aryx_ontology_axiom` table
- Supports Turtle, JSON-LD, RDF/XML, N-Triples formats

Both Path A (rdflib) and Path B (Oracle SEM_MATCH) consume this file without modification.
The exporter is not a gap — it is the foundation both paths build on.

---

*Generated: 2026-06-19 | aryx project | giggso*
*Source files: src/aryx/brief.py, src/aryx/brief_draft.py, src/aryx/ontology/rdf/exporter.py,*
*src/aryx/store/ingest_question_store.py, src/aryx/store/migrations/0016_workspace_brief.sql*
