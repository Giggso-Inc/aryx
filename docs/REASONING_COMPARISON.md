# Reasoning & Inference — aryx vs OWL 2 RL / RDFS++

This document explains each inferencing feature, what it means in plain language,
what aryx currently supports, and what Oracle Graph Server (PGX) adds via OWL 2 RL.

Oracle have Automated Inferencing: Includes built-in rulebases for RDFS++, OWLSIF, OWLPrime, and OWL 2 RL that allow the database to automatically derive new facts and relationships from existing data

---

## Ontology-Assisted Queries: SEM_RELATED / SEM_DISTANCE

Oracle provides built-in operators `SEM_RELATED` and `SEM_DISTANCE` to query
relational data based on semantic proximity to ontology concepts.

| Oracle Operator | What it does | aryx equivalent | Gap |
|---|---|---|---|
| `SEM_RELATED` | Are two concepts related via ontology hierarchy? | `neighbors()` — 1-hop graph traversal | aryx traverses entity-to-entity edges, not ontology class proximity |
| `SEM_DISTANCE` | How many hops apart are two concepts in the ontology? | `shortest_path()` — Cypher shortest path (max 10 hops) | aryx measures entity distance, not ontology class distance |
| Semantic proximity to OWL class | Query relational rows by closeness to a concept | `pgvector` embeddings exist in `aryx_chunk_embedding` | No API to query relational data by semantic distance to an ontology concept |

**Key distinction:**
- Oracle `SEM_DISTANCE`: measures `row ↔ ontology concept` (class-level semantic distance)
- aryx `shortest_path`: measures `entity ↔ entity` (graph hop count between instances)

**What aryx would need to match this:**
A `GET /search/semantic?concept=FinancialInstrument&threshold=0.8` endpoint that:
1. Embeds the concept name → vector
2. Finds relational rows within cosine distance threshold
3. Ranks results by semantic proximity to the ontology class

The building blocks exist (pgvector, embeddings, type hierarchy) — the combined query operator does not.

---

## Feature Comparison Table

| Feature | aryx | RDFS++ / OWL 2 RL |
|---|---|---|
| if-then rules | ✅ Custom JSON DSL | ✅ (more expressive) |
| Inverse relationships | ✅ `inverse_of` | ✅ |
| Symmetric relationships | ✅ `symmetric` | ✅ |
| Transitive closure | ✅ `transitive` (max 4 hops) | ✅ (unbounded) |
| rdfs:subClassOf inference | ❌ | ✅ |
| rdfs:domain / rdfs:range | ❌ | ✅ |
| owl:sameAs | ❌ | ✅ |
| owl:equivalentClass | ❌ | ✅ |
| owl:FunctionalProperty | ❌ | ✅ |
| Backward chaining | ❌ Forward only | ✅ both |
| Auto-derives from OWL axioms | ❌ Manual rules only | ✅ automatic |
| Standard compliance | ❌ | ✅ W3C |

---

## Feature Explanations

---

### 1. if-then Rules

**What it is:**
A rule that says "IF this condition is true about an entity, THEN do this action."

**Plain example:**
> IF a Customer has revenue > 1,000,000 THEN label them "Platinum"

**aryx (JSON DSL):**
```json
{
  "when": {"type": "Customer", "attr": "revenue", "op": ">", "value": 1000000},
  "then": {"set_label": "Platinum"}
}
```
Supports: `>`, `>=`, `<`, `<=`, `==`, `!=`, `contains`
Actions: `set_label` or `add_relationship`

**OWL 2 RL:**
Rules are defined using standard SWRL (Semantic Web Rule Language) or OWL axioms.
Far more expressive — can reference multiple entities, class hierarchies, property chains,
and negation. Auto-applied when ontology is loaded, no manual trigger needed.

**Gap:** aryx rules must be manually authored one by one. OWL 2 RL derives rules
automatically from the ontology structure itself.

---

### 2. Inverse Relationships

**What it is:**
If A relates to B in one direction, automatically create the reverse relationship.

**Plain example:**
> If "Acme Corp" EMPLOYS "John Smith", then automatically infer "John Smith" WORKS_FOR "Acme Corp"

**aryx:**
```json
{
  "when": {"edge": "employs"},
  "then": {"inverse_of": "works_for"}
}
```
Creates `INF_WORKS_FOR` edge (marked `inferred: true`) via Cypher MERGE.

**OWL 2 RL:**
Declared once in the ontology as `owl:inverseOf`. Engine applies it to all matching
edges automatically — no rule authoring needed per relationship type.

---

### 3. Symmetric Relationships

**What it is:**
A relationship that goes both ways by definition.

**Plain example:**
> If "Acme Corp" IS_PARTNER_OF "Beta Ltd", then automatically "Beta Ltd" IS_PARTNER_OF "Acme Corp"

**aryx:**
```json
{
  "when": {"edge": "is_partner_of"},
  "then": {"symmetric": true}
}
```
Runs Cypher: `MATCH (a)-[:REL {name}]->(b) WHERE id(a)<>id(b) MERGE (b)-[:REL]->(a)`

**OWL 2 RL:**
Declared as `owl:SymmetricProperty` on the property. Applied globally without
per-rule authoring.

---

### 4. Transitive Closure

**What it is:**
If A → B and B → C, then automatically infer A → C.

**Plain example:**
> "London" IS_IN "England", "England" IS_IN "UK" → automatically infer "London" IS_IN "UK"

**aryx:**
```json
{
  "when": {"edge": "is_in"},
  "then": {"transitive": true, "max_depth": 4}
}
```
Runs hop-by-hop Cypher up to 4 levels deep. Hard cap prevents runaway on cyclic graphs.

**OWL 2 RL:**
Declared as `owl:TransitiveProperty`. Closure is unbounded — works across any depth
automatically. PGX handles cycle detection internally.

**Gap:** aryx caps at 4 hops. Deep hierarchies (org charts, taxonomies, geography)
will miss inferences beyond 4 levels.

---

### 5. rdfs:subClassOf Inference

**What it is:**
If B is a subclass of A, then any instance of B is automatically also an instance of A.

**Plain example:**
> `SavingsAccount` is a subclass of `BankAccount`.
> Query for all `BankAccount` → automatically returns `SavingsAccount` instances too.

**aryx:** ❌ Not supported.
The ontology hierarchy exists in Postgres and ancestor labels are written to FalkorDB
nodes at projection time — but querying by parent type does not automatically include
child instances at inference time. It only works if labels were written during projection.

**OWL 2 RL:**
`rdfs:subClassOf` is a first-class inference rule. Any triple `X rdf:type SubClass`
automatically entails `X rdf:type SuperClass` without re-projection.

---

### 6. rdfs:domain / rdfs:range

**What it is:**
Declares what type a property belongs to (domain) and what type its value must be (range).
The engine then infers types from property usage.

**Plain example:**
> `worksFor` has domain `Person` and range `Organization`.
> If you see `worksFor` used on an entity with no type, the engine infers it must be a `Person`.

**aryx:** ❌ Not supported.
Domain and range are stored as axioms in Postgres (`aryx_ontology_axiom`) and validated
on demand (`/axioms/validate`), but they do not trigger automatic type inference.

**OWL 2 RL:**
Using a property automatically entails the domain/range types. No explicit type
declaration needed — the engine derives it from property usage alone.

---

### 7. owl:sameAs

**What it is:**
Declares that two different identifiers refer to the exact same real-world entity.
All properties of one are automatically inherited by the other.

**Plain example:**
> `entity:42` (from CRM) owl:sameAs `entity:187` (from ERP).
> Querying either ID returns the merged view of both.

**aryx:** ❌ Not supported.
aryx handles this at the resolution stage (entity deduplication), but once entities
are written to the graph they are separate nodes. No `owl:sameAs` propagation at query time.

**OWL 2 RL:**
Full `owl:sameAs` closure — all triples about entity A are automatically copied to
entity B and vice versa. Federated queries across data sources just work.

---

### 8. owl:equivalentClass

**What it is:**
Two class names in different ontologies mean exactly the same thing.
Instances of one are automatically instances of the other.

**Plain example:**
> Your ontology calls it `Client`. A partner's ontology calls it `Customer`.
> `owl:equivalentClass` links them — querying `Customer` returns your `Client` instances too.

**aryx:** ❌ Not supported.
Equivalent type pairs can be stored as axioms (kind: `equivalent_to`) but no
inference is triggered from them at query time.

**OWL 2 RL:**
Equivalence is bidirectional and transitive. Merging two ontologies becomes automatic —
no manual mapping layer needed.

---

### 9. owl:FunctionalProperty

**What it is:**
A property that can have at most one value per entity.
The engine can then infer that two entities with the same value for this property are the same entity.

**Plain example:**
> `taxID` is a functional property — no two companies share the same tax ID.
> If entity A and entity B both have `taxID = "12-3456789"`, the engine infers A = B (owl:sameAs).

**aryx:** ❌ Not supported.
Uniqueness constraints exist at the DB level but do not trigger `owl:sameAs` inference.

**OWL 2 RL:**
Automatically derives entity identity from shared functional property values.
Critical for data integration across sources that use different internal IDs.

---

### 10. Backward Chaining

**What it is:**
Two reasoning directions:
- **Forward chaining** (what aryx does): Start from facts, apply all rules, derive new facts eagerly.
- **Backward chaining** (what aryx lacks): Start from a query goal, work backwards to find supporting facts on demand.

**Plain example:**
> Query: "Is John Smith a Platinum Customer?"
>
> Forward (aryx): Must have already run the evaluator and written the `inferred_label`.
> If the evaluator hasn't run since John's revenue changed → stale answer.
>
> Backward (OWL 2 RL): Asks "what rules could make John Platinum?" → checks revenue live → always fresh.

**aryx:** Forward chaining only. Inferences are materialized (written to graph).
Stale if data changes between evaluator runs.

**OWL 2 RL:**
Both modes. Backward chaining answers queries without materializing — always fresh,
no need to re-run the evaluator after every data change.

---

### 11. Auto-derives from OWL Axioms

**What it is:**
In OWL 2 RL, you do not write rules. You define the ontology (classes, properties, axioms)
and the engine derives all the rules automatically from the axioms.

**Plain example:**
> You declare: `Manager rdfs:subClassOf Employee`
> You declare: `manages owl:inverseOf managedBy`
> You declare: `manages owl:TransitiveProperty`
>
> The engine automatically knows: all Manager instances are Employees,
> inverse edges exist, and transitive closure holds — without writing a single rule.

**aryx:** Every inference must be manually written as a JSON rule.
The ontology axioms (subClassOf, domain, range) exist in Postgres but do not
drive the reasoning engine.

**OWL 2 RL:**
The ontology IS the rule base. Load the ontology → inferencing is active immediately.

---

### 12. Standard Compliance (W3C)

**What it is:**
W3C OWL 2 RL is an international standard for knowledge representation and automated reasoning.
Tools, exporters, and reasoners that comply with it interoperate without custom integration.

**aryx:** ❌ Custom, non-standard rule DSL.
Rules written for aryx work only in aryx. No portability to Protégé, Apache Jena,
Oracle PGX, or any other reasoning engine.

**OWL 2 RL:**
Rules and axioms are portable across any W3C-compliant tool. Export your ontology
as OWL/Turtle → import into Protégé, run in Oracle PGX, publish as Linked Data —
all without modification.

---

## The OCI Path

All missing features (rows marked ❌) are available in **Oracle Graph Server (PGX)**.
They are the target capability for the `aryx-o` edition.

**Current state:**
- The `ReasonerPort` contract is defined in `src/aryx/ports/protocols.py` ✅
- The adapter swap mechanism is wired in `src/aryx/ports/config.py` ✅
- The `OraclePgxReasoner` implementation class does **not exist yet** ❌

```bash
# This is the intended configuration once the adapter is built:
ARYX_EDITION=aryx-o
ARYX_ADAPTER_REASONER=aryx.adapters.oracle.pgx:OraclePgxReasoner
```

Running this today throws `ImportError` — `aryx.adapters.oracle.pgx` is an empty module path.
Once `OraclePgxReasoner` is written, all 12 features become available without changing
any business logic in aryx.

---

*Generated: 2026-06-18 | aryx project | giggso*
