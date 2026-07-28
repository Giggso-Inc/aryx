# Oracle ADB Native AI Features — Embeddings & Chat: Analysis

This document evaluates whether aryx should move embedding generation and/or
LLM chat/completion calls from the current app-side approach (Python →
OCI GenAI) into Oracle ADB-native mechanisms, for the OCI-mode deployment —
covering both in-database models (ONNX) and ADB-mediated calls to external
models (OCI GenAI, Cohere, OpenAI, etc. via `DBMS_VECTOR_CHAIN`/`DBMS_CLOUD_AI`).

**Scope:** analysis only — no code changes proposed here. Grounded against
the live ADB instance used by this deployment (`docker exec aryx-api-1`
introspection, 2026-07-28):

| Check | Result |
|---|---|
| ADB version | `Oracle AI Database 26ai Enterprise Edition Release 23.26.3.1.0` |
| `DBMS_VECTOR` package (in-DB ONNX embedding generation) | Present |
| ONNX models currently loaded (`user_mining_models`) | **None** — not set up |
| `DBMS_VECTOR_CHAIN` package (external-provider embedding/chat calls from SQL) | Present, incl. `UTL_TO_EMBEDDING(S)`, `UTL_TO_GENERATE_TEXT`, `CREATE_CREDENTIAL` |
| `DBMS_VECTOR_CHAIN.LIST_PROVIDERS()` result | `["anthropic","cohere","database","ocigenai","googleai","huggingface","llamafile","mistralai","ollama","openai","privateai","vertexai"]` — **`ocigenai` confirmed supported** |
| `DBMS_CLOUD_AI` package (AI Profile / Select AI) | Present on the instance |
| AI Profile / external credential currently configured | **None** — not set up |
| `aryx_chunk_embedding.embedding` column type | Already native Oracle `VECTOR` |

All three native mechanisms are technically available; none is configured
today. Everything below is a from-scratch comparison, not "flip a switch."

---

## Part 1 — Embeddings: in-database generation vs. app-side OCI GenAI

Three distinct Oracle mechanisms apply here, and they need separating —
"AI Profile" colloquially gets used for all of them:

- **`DBMS_VECTOR.LOAD_ONNX_MODEL` + `VECTOR_EMBEDDING()`** — a SQL function
  that generates the embedding *inside* ADB using an ONNX model imported into
  the database. Zero external network call, but constrained to whatever model
  you can get into ONNX format.
- **`DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDING(S)`** — a SQL function that calls OUT
  to an external embedding provider (confirmed on this instance: `ocigenai`,
  `cohere`, `openai`, `huggingface`, `vertexai`, `ollama`, others) using a
  stored credential (`DBMS_VECTOR_CHAIN.CREATE_CREDENTIAL`). This is the
  answer to "can we use an external model instead of ONNX" — **yes**, and
  critically, `ocigenai` as a provider means this can call the exact same
  `cohere.embed-multilingual-v3.0` model aryx already uses, just issued from
  SQL instead of from Python.
- **`DBMS_CLOUD_AI` embedding action** — the AI Profile package can also proxy
  an embedding call to an external provider from SQL. Functionally
  overlapping with `DBMS_VECTOR_CHAIN` for this purpose; `DBMS_VECTOR_CHAIN`
  is the more direct, purpose-built mechanism for embeddings specifically.

That gives three real options to weigh against the current approach, not two.

### Current state
`pipeline/embed.py`'s `embed_chunks()` calls `Broker.embed()` →
`_oci_embed()` → OCI GenAI `cohere.embed-multilingual-v3.0` (1024-dim,
multilingual), batched at `ARYX_EMBED_BATCH_SIZE` (fixed this session, P11).
Vectors are inserted into `aryx_chunk_embedding.embedding` (already a native
`VECTOR` column).

### Comparison

| | Current: app-side, OCI GenAI Cohere Embed | In-DB ONNX (`DBMS_VECTOR`) | External model via SQL (`DBMS_VECTOR_CHAIN`, provider `ocigenai`) |
|---|---|---|---|
| Where compute happens | OCI GenAI (separate managed service) | ADB's own OCPU/ECPU | OCI GenAI — same as today, just called by ADB instead of the app |
| Model quality | Cohere Embed v3, 1024-dim, multilingual | Whatever ONNX model is imported — typically smaller (e.g. all-MiniLM-L6-v2, 384-dim) | **Same as today** — can target the identical `cohere.embed-multilingual-v3.0` model |
| Network hop for embedding | 1 per batch (already batched), app → OCI GenAI | **0** | 1 per batch, but ADB → OCI GenAI instead of app → OCI GenAI |
| Per-call $ cost | OCI GenAI usage-based pricing | **None** — uses ADB compute already paid for | Same OCI GenAI usage-based pricing as today — **no cost saving** |
| ADB compute contention | None — embedding never touches ADB CPU | Competes with regular query/DML workload during bulk ingest | Minimal — ADB issues an HTTP call and waits, doesn't run inference itself |
| Backend symmetry (Postgres/Oracle) | Preserved — same `broker.embed()` call site either way | **Broken** — Oracle-only; Postgres would need pgvector + a separate mechanism | **Broken** — Oracle-only, same as ONNX |
| Setup cost today | Already built and live-tested | Import/convert an ONNX embedding model, verify dimension compatibility with the existing `VECTOR` column | `CREATE_CREDENTIAL` (OCI GenAI auth stored in DB) + network ACL for ADB's outbound call — no model conversion needed |
| Maturity in this codebase | Tested this session (P11 batching fix) | Zero existing code — new work | Zero existing code — new work; package present but no credential configured, not yet called live |

### Advantages of the in-DB ONNX route (`DBMS_VECTOR`)
- Zero network hop and zero per-call API cost for embedding generation.
- Embedding could become part of the same SQL statement as the insert
  (`INSERT ... SELECT id, VECTOR_EMBEDDING(model USING content AS data) ...`),
  removing `embed.py`'s batching logic entirely for that step.

### Advantages of the external-model-via-SQL route (`DBMS_VECTOR_CHAIN`)
- **No model-quality regression** — the same `cohere.embed-multilingual-v3.0`
  model can be targeted, so this is the only native-ADB option that doesn't
  trade off Ask/grounding accuracy for infrastructure simplification.
- Collapses "call OCI GenAI, get vectors, then INSERT" into one SQL statement
  issued by the DB — a real (if modest) round-trip reduction from the app's
  perspective: two round-trips (app→OCI GenAI, app→DB) become one (app→DB,
  with the OCI GenAI call happening inside that).
- If the app container isn't itself hosted inside OCI (this session's
  docker-compose stack calls out to Oracle Cloud over the public internet via
  TCPS), an ADB→OCI GenAI call may ride entirely within OCI's own network —
  potentially lower and more consistent latency than the app's current
  external path, though this is a hypothesis, not something measured this
  session.
- Credential/auth centralized in the DB (`DBMS_VECTOR_CHAIN.CREATE_CREDENTIAL`)
  rather than app-side `.env` — a minor ops consolidation, not a functional
  win.

### Drawbacks
**In-DB ONNX (`DBMS_VECTOR`):**
- Model choice is constrained to whatever's available in ONNX format —
  materially lower-dimensional/lower-quality than Cohere Embed v3 in
  practice, which affects grounding/retrieval accuracy in Ask.
- Consumes ADB compute (OCPU/ECPU) directly, competing with the same
  database's query workload during large ingests — the current approach
  scales embedding generation independently of ADB.

**External model via SQL (`DBMS_VECTOR_CHAIN`):**
- Does not reduce cost or eliminate the external network call — it only
  relocates which side issues it. The actual benefit is narrower (one fewer
  app-side round-trip, possible intra-OCI latency edge) and unverified
  without a live measurement.
- Still requires new credential/ACL provisioning and new code — no less
  setup work than the ONNX route, just a different kind of setup.
- Batch behavior (`UTL_TO_EMBEDDINGS`, plural) needs to be verified against
  a real payload before relying on it to preserve the P11 batching win —
  confirmed present in the package, not yet exercised live.

**Both native routes:**
- Oracle-only: adds a third "generates differently per backend" branch
  alongside `cpq/rdb.py` and `ask_thread_store.py` — the same category of
  divergence that produced this session's live-only bugs (CPQ N+1, the
  `$type` Cypher leftover in `oracle_graph_reader.py`).
- No existing code, tests, or live verification — this would be new,
  unproven work, not a refinement of something already tested.

### Recommendation
Keep the current app-side approach as the default. Of the two native
alternatives, `DBMS_VECTOR_CHAIN` (external model via SQL) is the more
credible one to prototype **if** a follow-up spike shows a real round-trip
or latency win — it carries no model-quality regression, unlike ONNX, since
it can call the identical `cohere.embed-multilingual-v3.0` model. But its
benefit is unproven and modest by design (same external call, same cost,
just relocated), so it's only worth adopting with a measured number behind
it, not on architectural appeal. The ONNX route's upside (true zero-cost,
zero-network-hop compute) is larger in principle but comes bundled with a
real embedding-quality tradeoff that would need to be validated against
Ask/grounding accuracy before it could be justified — it's the higher
ceiling, higher-risk option of the two.

---

## Part 2 — Chat/completion: in-database `DBMS_CLOUD_AI` vs. app-side LLM calls

### Current state
aryx has two distinct LLM-call patterns, both entirely app-side:

1. **`llm_runtime.chat(role, system, user)`** — the Ask flow's plain-text
   completion path (`_extract_terms()`, `_synthesise()` in `ask_api.py`).
   Builds a single-model `Broker` per call, calls `complete_text()`, and logs
   every call to `aryx_llm_call` (workspace-scoped audit trail with prompt
   tokens, completion tokens, latency, and model — already present in both
   Postgres and Oracle migrations).
2. **`Broker.complete_json(...)`** — structured-JSON completions used across
   ontology extraction (`ontology/extract.py`), schema mapping
   (`ontology/mapping.py`), relationship inference (`relationships.py`),
   resolution adjudication (`resolution/adjudicate.py`), field tagging
   (`pipeline/tag.py`), and brief drafting (`brief_draft.py`) — each with its
   own hand-built system prompt and JSON schema aryx's Python code parses.

Neither pattern is a generic "ask a question, get an answer" call — every
call site is coupled to a specific JSON schema, a specific system prompt, and
(for CPQ especially) a stateful multi-turn conversation the LLM call is only
one step inside.

### What `DBMS_CLOUD_AI` actually offers
`DBMS_CLOUD_AI.CREATE_PROFILE` binds a credential + provider (OCI GenAI,
Cohere, OpenAI, etc.) to the database. Once created, `DBMS_CLOUD_AI.GENERATE`
(or `SELECT AI ...` syntax) supports actions like `chat`, `narrate`, `showsql`,
`runsql`, `explainsql` — single-shot prompt/response or natural-language-to-
SQL, issued directly from a SQL session.

Note: `DBMS_VECTOR_CHAIN.UTL_TO_GENERATE_TEXT` (confirmed present alongside
the embedding procedures used in Part 1) offers functionally the same
capability — single-shot external-provider text generation from SQL, same
`ocigenai`/`cohere`/etc. provider list. Everything in this section applies
equally to either package; `DBMS_CLOUD_AI` is used as the reference name
since it's the one Oracle markets for this purpose ("Select AI").

### Comparison

| | Current: app-side (`llm_runtime.chat` / `complete_json`) | `DBMS_CLOUD_AI` chat/narrate/runsql from SQL |
|---|---|---|
| Call shape | Custom system prompt + JSON schema per feature, parsed in Python | Single-shot prompt → text (or NL2SQL), no custom schema enforcement |
| Multi-step / stateful orchestration | Full support — CPQ's turn-by-turn `CpqSession` state machine, rule evaluation interleaved with LLM calls | **Not supported** — one prompt in, one response out; no place to run aryx's business logic |
| Structured JSON output for downstream parsing | Yes — `complete_json()` is built around this | Not a first-class feature of `GENERATE()`; would need prompt-engineered JSON with no schema guarantee |
| Model tier selection (cheap vs. frontier) | Per-call, via `Broker`/`ModelSpec` registry | Per-profile — would need multiple profiles, more DB-side config to manage |
| Audit trail | `aryx_llm_call` table, populated automatically by every call | Not populated automatically — would need to be wired separately, or reconciled with Oracle's own audit views |
| Credential management | App-side (`oci_client.py`, `.env`) | DB-side wallet (`DBMS_CLOUD.CREATE_CREDENTIAL`) + network ACL for outbound calls |
| Data egress | Only curated/grounded context is sent (aryx already minimizes this via graph retrieval + `render_context`) | Real advantage only when the LLM needs to see large raw DB result sets directly — not aryx's actual usage pattern |
| Backend symmetry (Postgres/Oracle) | Preserved | Broken — Oracle-only |
| NL2SQL overlap with aryx's own Ask pipeline | N/A | `runsql`/`showsql` actions functionally **compete** with aryx's own term-extraction + graph-retrieval + synthesis pipeline, but without ontology/graph awareness or CPQ rule logic |

### Advantages of `DBMS_CLOUD_AI`
- Reduces data egress for the specific case of "summarize a large SQL result
  set" — not a pattern aryx actually uses today, since Ask already curates a
  small grounded context before calling the LLM.
- Centralizes credential/network config for outbound LLM calls in the
  database layer rather than the app.
- Could be genuinely useful for one narrow, already-single-shot step:
  `_cpq_summary_text()`'s final natural-language summary of a completed
  configuration — a case where structured data goes in and a plain-language
  narration comes out, the shape `DBMS_CLOUD_AI narrate` is actually built for.

### Drawbacks
- Cannot replace the CPQ engine's conversational flow at all — that's a
  stateful, rule-driven, multi-turn process (`CpqSession`, rule evaluation via
  `cpq/rdb.py`, BML script execution) with the LLM as one small piece, not a
  single prompt/response the database could run standalone.
- Cannot replace `complete_json()` call sites without losing schema
  enforcement — ontology extraction, adjudication scoring, and relationship
  inference all depend on parsing a specific JSON shape reliably.
- No automatic population of `aryx_llm_call` — the existing audit trail would
  need separate, DB-side reconciliation work.
- Same backend-symmetry break as the embedding option — Oracle-only,
  Postgres gets nothing equivalent.
- `runsql`/`showsql` NL2SQL actions are a lesser, ontology-blind substitute
  for aryx's own Ask pipeline, not an upgrade to it — adopting them for
  question-answering would be a functional regression, not a simplification.

### Recommendation
Do not use `DBMS_CLOUD_AI` as a general replacement for aryx's LLM calls —
the fit is much weaker here than for embeddings, because chat/completion in
aryx is inseparable from Python-side orchestration (CPQ state machine,
JSON-schema-driven extraction) that a single-shot SQL `GENERATE()` call
cannot reproduce. The only place worth a narrow, low-risk experiment is the
final CPQ summary narration step, where the shape (data in, prose out, no
further state to manage) actually matches what `DBMS_CLOUD_AI narrate` does —
and even that should be judged against the same bar as Part 1: real
cost/latency numbers, not assumed benefit.

---

## Part 3 — Verdict: can CPQ use Select AI directly against the graph?

Direct follow-up questions this section answers: *"can we use Select AI?"*
and *"CPQ also takes data from the graph — can't we directly link the graph
with the AI Profile and have it do the task in between?"*

### Can Select AI be used at all?
Yes, technically — `DBMS_CLOUD_AI` is present on this ADB instance today,
just not configured (no profile, no stored credential). Whether it *should*
be used splits cleanly by task shape:

| Use case | Fit | Why |
|---|---|---|
| CPQ's final summary narration (`_cpq_summary_text()`) | **Good** | Structured data in, prose out, no further state to manage after — exactly the single-shot shape `DBMS_CLOUD_AI narrate` is built for |
| Ad-hoc ops/admin querying (a DBA asking `SELECT AI runsql '...'` directly against the schema for debugging) | **Good** | A genuinely different use case from aryx's own Ask feature — Select AI is built for exactly this |
| Any part of aryx's own Ask/CPQ pipeline (term extraction, synthesis, adjudication, CPQ conversation) | **Poor** | See below — these need orchestration and state Select AI doesn't provide |

Setup for either "good fit" use, if pursued: `DBMS_CLOUD_AI.CREATE_CREDENTIAL`
(store an OCI GenAI credential in the DB) → `DBMS_CLOUD_AI.CREATE_PROFILE`
(bind provider `ocigenai` + model) → a network ACL grant for ADB's outbound
call. None of this exists yet on this instance.

### Why not have Select AI read the graph directly and drive CPQ end to end?
The graph tables (`aryx_graph_vertex`/`aryx_graph_edge`) are plain relational
tables, so Select AI could technically write SQL against them — that part is
true. But "having it do the task in between" doesn't work for CPQ, because
CPQ's job is not "look up data and answer a question" (the pattern Select AI
is built for) — it's a stateful, multi-turn **algorithm**:

1. **Rule evaluation is procedural, not queryable in one shot.** Deciding
   which configuration question to ask next depends on chained logic across
   `fetch_rules` / `fetch_rule_inputs` / `fetch_rule_actions` /
   `fetch_rule_chain_links` / `fetch_marked_attrs` — Python code resolves
   rule priority, conflicts, and cascading (one rule firing triggers
   re-checking others). That's imperative control flow spanning several
   tables and several passes, not a single SQL statement an LLM could
   generate.
2. **BML script execution isn't SQL at all.** `cpq/bml.py` is a real
   interpreter for BigMachines' proprietary scripting language — genuine code
   execution (loops, conditionals, string manipulation) against live session
   state. There is no SQL form of "run this script," generated or otherwise.
3. **Conversation state must persist across turns.** `CpqSession`/
   `session_data` carries filled attributes, pending questions, and cascade
   history between calls. Select AI has no memory of its own — every call is
   stateless unless the entire state is resent as prompt text, at which point
   it's being used as a plain string-in/string-out function, not as
   something "doing the task."

**And even narrowing the idea to just the data-fetch step** (replace
`neighbors_batch()`/`find_entities()` with Select AI-generated SQL) is a
step backward, not forward:
- `aryx_graph_vertex`/`aryx_graph_edge` store everything generically
  (`entity_id`, `type`, `name`, `attributes` JSON blob) — there is no
  semantic column naming for an LLM to reason about. It has no way to infer
  that `attributes->>'variable_name'` matters, that ontology-type matching
  needs the `REPLACE(LOWER(...))` normalization the CPQ code applies, or that
  `catalog_prefix` scoping exists specifically to stop rule/function IDs
  colliding across two products sharing a workspace.
- This session already found and fixed exactly this class of bug in the
  **hand-written, reviewed, tested** version of these queries — the CPQ
  `neighbors()` N+1 (P13) and the missing `workspace_id` filter in
  `find_entities()`. An LLM regenerating that SQL non-deterministically on
  every call reintroduces the same risk (e.g. silently dropping the
  workspace scope) with no way to catch it in code review, since the query
  text differs call to call.

### Verdict
Select AI is a good fit for the narrow single-shot steps (CPQ's final
narration, ops/debugging queries) precisely *because* those don't need state
or custom logic — and it's disqualified from CPQ's core conversational loop
for the exact opposite reason: that loop's whole job is running stateful,
rule-driven, script-executing logic no SQL-generation tool is built to do.
This isn't a maturity gap to wait out — it's a mismatch between what Select
AI is (a single-shot NL2SQL/narration tool) and what CPQ needs (a persistent
algorithm), so no amount of profile configuration or prompt engineering
closes it.

---

## Part 4 — Implementation Plan: Row-Level Security (VPD) for Workspace Isolation

Three other native ADB capabilities are unused in this deployment today
(verified live — no vector indexes, no `VECTOR_DISTANCE` usage anywhere in
code, no `DBMS_RLS` policies, and the SQL/PGQ property graph object is
declared but exercised by exactly one query). Of the three, VPD/RLS is the
only one justified by a **proven bug**, not a performance hypothesis, so it
gets a full implementation plan here. Vector search and the property-graph
rewrite are covered at analysis depth in Part 5.

### Problem Statement
Multi-tenant workspace isolation in OCI mode is enforced **entirely by
convention in application code** — every query against a workspace-scoped
table (`aryx_entity`, `aryx_graph_vertex`, `aryx_chunk`, `aryx_document`,
`aryx_job`, and ~15 others) must remember to include
`WHERE workspace_id = :N`. Nothing in the schema, the query layer, or the
connection pool ties a query's result set to the caller's actual workspace —
the database will happily return rows for *any* workspace to *any* caller
who forgets the filter.

This is not theoretical. This session found and fixed exactly that failure:
`OracleGraphReader.find_entities()` ([oracle_graph_reader.py](../src/aryx/graph/oracle_graph_reader.py))
had no `workspace_id` predicate at all — every call returned entities from
every workspace in the database, not just the caller's. It was caught only
by manual code reading during an unrelated live-debugging session, not by
any test, lint rule, or database-level control. Code review already failed
to catch this once; there's nothing structural stopping it from happening
again in a future store method, API endpoint, or hurried bug fix.

### Root Cause
- **Workspace scoping is a per-query convention, not a system invariant.**
  `workspace_id` travels as an ordinary bind parameter that each query
  author must remember to add — there's no single choke point that enforces
  it universally.
- **The connection pool is workspace-agnostic.** `get_oracle_pool(dsn)`
  ([oracle_pool.py](../src/aryx/store/oracle_pool.py)) pools connections by
  DSN only; a borrowed connection has no notion of "this session currently
  belongs to workspace X" that Oracle itself could use to filter rows.
- **No compensating control exists.** No RLS/VPD policies, no static
  analysis flagging a query against a scoped table with no `workspace_id`
  predicate, no regression test that would fail if a new store method
  omitted the filter — the `find_entities()` bug could recur in any new code
  tomorrow and nothing would flag it before a live incident does.

### Fix — Oracle VPD (`DBMS_RLS`)

**1. Session context.**
```sql
CREATE CONTEXT aryx_ctx USING aryx_ctx_pkg;  -- trusted: only this package may set it

CREATE OR REPLACE PACKAGE aryx_ctx_pkg AS
  PROCEDURE set_workspace(p_workspace_id IN NUMBER);
END aryx_ctx_pkg;
/
CREATE OR REPLACE PACKAGE BODY aryx_ctx_pkg AS
  PROCEDURE set_workspace(p_workspace_id IN NUMBER) IS
  BEGIN
    DBMS_SESSION.SET_CONTEXT('ARYX_CTX', 'WORKSPACE_ID', TO_CHAR(p_workspace_id));
  END;
END aryx_ctx_pkg;
/
```
A *trusted* context means only `aryx_ctx_pkg.set_workspace` can set it — raw
session variables can't be spoofed by any other SQL running on the same
connection.

**2. Policy function — fail closed, not fail open.**
```sql
CREATE OR REPLACE FUNCTION aryx_ws_policy(schema_var VARCHAR2, table_var VARCHAR2)
RETURN VARCHAR2 IS
  v_ws VARCHAR2(20) := SYS_CONTEXT('ARYX_CTX', 'WORKSPACE_ID');
BEGIN
  IF v_ws IS NULL THEN
    RETURN '1 = 0';   -- no context set → zero rows, never "everything"
  END IF;
  RETURN 'workspace_id = ' || v_ws;
END;
```
The `IF v_ws IS NULL THEN RETURN '1=0'` line is the single most important
line in this plan — it's what makes RLS fail closed. Skipping it (or
defaulting to an unfiltered predicate) would turn "forgot to set context"
into "see everything," the exact opposite of the intended fix.

**3. Attach the policy per table.**
```sql
BEGIN
  DBMS_RLS.ADD_POLICY(
    object_schema   => 'ARYX_APP',
    object_name     => 'ARYX_GRAPH_VERTEX',
    policy_name     => 'aryx_ws_isolation',
    function_schema => 'ARYX_APP',
    policy_function => 'aryx_ws_policy',
    statement_types => 'SELECT,INSERT,UPDATE,DELETE'
  );
END;
```
Repeated per workspace-scoped table. `aryx_workspace` itself (the workspace
*registry*, queried by `list_workspaces()` in `workspace_api.py`) is
correctly **excluded** — it isn't workspace-scoped data, it's the table that
defines workspaces, and no other cross-workspace admin/reporting query was
found touching a scoped data table (verified by grep across `workspace_api.py`
and the store layer) — no bypass role is needed for this rollout.

**4. Wire context-setting into the app.** This is the real engineering work,
not the SQL above. Every Oracle store class already carries or receives
`workspace_id` (some at construction — `OracleGraphReader.__init__(dsn,
workspace_id)` — others per call — `cpq/rdb.py`'s `fetch_*(workspace_id,
...)` methods), so there's no single existing choke point. The fix:
`OraclePool.connection()` gains an optional `workspace_id` parameter and
calls `aryx_ctx_pkg.set_workspace` immediately after acquiring the raw
connection, every time — connections are reused across requests for
*different* workspaces, so the context must be (re)set on **every**
checkout, not once. Every `with self._pool.connection() as conn:` call site
across the Oracle store classes needs updating to pass its known
`workspace_id` through.

### Rollout Plan (ordered to avoid a self-inflicted outage)
RLS policies fail closed — if they go live before the app reliably sets
context on every request, every query against a protected table returns
zero rows, everywhere, immediately. The order below exists specifically to
prevent that:

1. **Build the context-setting infrastructure first, with no policies yet.**
   Ship the `connection(workspace_id=...)` change and update all Oracle
   store call sites. With no `DBMS_RLS` policy attached to any table yet,
   this step is inert — it sets a context nothing reads. Add logging/a debug
   endpoint to confirm `SYS_CONTEXT('ARYX_CTX','WORKSPACE_ID')` is correctly
   populated for real request traffic before proceeding.
2. **Attach the policy to one table first** — `aryx_graph_vertex`, the table
   where the bug was actually found. Run the same live-verification
   discipline used all session (real Ask/CPQ requests against the running
   `api` container, not just unit tests) to confirm no regression.
3. **Roll out to the remaining scoped tables** in small batches, each
   verified live before moving to the next, rather than all at once.
4. **Keep `DBMS_RLS.DROP_POLICY` / `DISABLE_POLICY` as the rollback** for any
   table — since app-side context-setting is harmless without an attached
   policy, rollback never requires an app code change or redeploy, only a DB
   change, at any point in the rollout.

### Testing Plan
This cannot be verified with mocked `oracledb` the way most of this
codebase's Oracle-path unit tests work — it requires live ADB, the same
constraint that made every fix this session (P8-P13, the Ask-thread port)
ultimately depend on real testing over static review or mocks:
- **Fail-closed check:** run a query against a protected table with no
  context set — must return zero rows, not an error and not all rows.
- **Isolation check:** two sequential requests for two different
  workspace_ids against the *same physical pooled connection* (force reuse)
  must never see each other's data — this is the specific new failure mode
  RLS rollout could introduce if context isn't reset correctly on every
  checkout, so it needs its own dedicated test, not just "does workspace A
  see workspace A's data."
- **Regression check:** re-run the exact live smoke tests already used this
  session (the Ask-thread persistence test, the CPQ two-turn conversation)
  after each table's policy goes live, confirming identical results to
  today's unprotected behavior for legitimate same-workspace access.

### Why this over the alternatives already ruled out
Both the embedding and chat native-ADB options (Parts 1-3) were held to "no
Oracle-only branch without a measured performance number." This one clears a
different, higher bar: it isn't chasing a hypothetical speed-up, it's closing
a demonstrated correctness/security gap with a fix Oracle provides natively.
The added Oracle-only surface area (context package, policies, pool API
change) is the same *kind* of cost as the ruled-out options, but here it's
buying a structural guarantee against an entire bug class already proven to
occur, not an unverified latency edge.

---

## Part 5 — Other Identified but Lower-Priority ADB Features

Two more native capabilities are available on this instance and unused, but
neither clears the bar for a full implementation plan right now — one is a
genuinely new feature (not a fix), the other would optimize a path this
session already fixed.

### Vector / semantic search over document chunks
`aryx_chunk_embedding.embedding` is a real `VECTOR` column (P10/P11 this
session fixed its write-path batching), but live checks confirm:
- No vector index exists (`user_indexes` shows only a LOB index and two
  constraint indexes on that table — no HNSW/IVF vector index)
- Zero `VECTOR_DISTANCE`/similarity-search queries anywhere in the codebase
- **Zero rows** currently in `aryx_chunk_embedding`, across the entire database

So this is dormant infrastructure, not a working feature waiting on one
missing index. Ask's grounding today is 100% graph-entity retrieval (term
extraction → `find_entities`/`neighbors` → synthesis) — any information
present only in raw document prose, never captured as a structured entity
or attribute by ontology extraction, is invisible to Ask.

**Why this isn't a "fix," it's a new feature:** implementing it means (1)
confirming the ingestion pipeline is actually populating this table at all
in this deployment before anything else, (2) creating a vector index
(`CREATE VECTOR INDEX ... ORGANIZATION INMEMORY NEIGHBOR GRAPH` for HNSW),
(3) designing a merge strategy between vector-retrieved raw chunks and the
existing graph-entity grounding — the current `grounding.entity_count`/
`cited_count` scoring is entity-shaped, not chunk-shaped, so chunk-level
citations need their own representation, and (4) picking a retrieval
strategy (top-k, similarity threshold, optional re-ranking). This is a
feature-design project on the scale of the original Ask-thread Oracle port,
not an infra cleanup — worth doing, but not something to fold into a
performance or security pass.

### Property Graph (SQL/PGQ) rewrite of hand-rolled traversal queries
`migrations_oracle/graph_schema.sql` declares a genuine
`CREATE PROPERTY GRAPH aryx_knowledge_graph` over `aryx_graph_vertex`/
`aryx_graph_edge` — but `oracle_graph_reader.py` uses it for exactly one
query, `shortest_path()`'s `GRAPH_TABLE(... MATCH SHORTEST ...)`. Every other
traversal — `neighbors()`/`neighbors_batch()`, `subgraph()`,
`find_entities()` — is hand-rolled relational joins against the same
underlying tables instead of `GRAPH_TABLE ... MATCH` against the already-
declared graph.

**Why this is low priority right now:** this is the exact traversal pattern
behind the CPQ N+1 (P13) — but that problem is **already fixed** this
session (235 entities: ~175s projected → 14.5s measured, via a hand-rolled
batched `neighbors_batch()` query, not PGQ). A PGQ rewrite would be
optimizing an already-working, already-verified path, with genuine
uncertainty about whether Oracle's PGQ optimizer actually outperforms the
current hand-rolled joins for this access pattern — it could go either way,
and would need the same live-measurement discipline as `neighbors_batch()`
(a correctness check against the old results, then a real timing comparison)
before trusting it. Not worth prioritizing without a demonstrated further
performance need beyond the current 14.5s — chasing it now would be
optimization for its own sake, not a response to an actual problem.

---

## Overall takeaway

All three native ADB AI mechanisms exist and are provisionable on this
instance, but none is a drop-in win for aryx today:

- **Embeddings** are the stronger candidate for a future spike — the
  operation is simple, stateless, and genuinely swappable. Within that,
  `DBMS_VECTOR_CHAIN`'s external-provider route (same `cohere.embed-
  multilingual-v3.0` model, called from SQL) is the lower-risk of the two
  native options since it doesn't trade away model quality — but its actual
  benefit (fewer round-trips, possible intra-OCI latency) is unmeasured. The
  in-DB ONNX route has a larger theoretical upside (true zero-cost,
  zero-network compute) bundled with a real quality tradeoff that would need
  validating against Ask/grounding accuracy before it could be justified.
- **Chat/completion** is a much weaker fit across the board — nearly every
  LLM call site in aryx is coupled to custom orchestration or structured-
  output parsing that neither `DBMS_CLOUD_AI` nor `DBMS_VECTOR_CHAIN`'s
  single-shot text-generation actions can provide, so adopting either beyond
  one narrow narration step would be a capability regression dressed up as
  an infrastructure simplification.
- All three options add a backend-specific code path that only exists for
  Oracle, the same category of divergence (`cpq/rdb.py`, `ask_thread_store.py`,
  `oracle_graph_reader.py`) that has produced every live-only bug found and
  fixed this session (P8-P13, the Ask-thread port, the CPQ N+1). Any decision
  to add a fourth such branch should be justified by measured numbers, not
  architectural appeal.
- **Row-Level Security (Part 4) is the one exception to that bar.** It's the
  only native ADB feature in this document justified by a proven
  correctness/security gap — the `find_entities()` workspace-scoping bug this
  session already found and fixed — rather than an unmeasured performance
  hope. It has a real implementation cost (connection-lifecycle changes
  across every Oracle store class) and a real new failure mode to guard
  against (stale context on a reused pooled connection), but the fix
  addresses an entire bug *class*, not one instance of it.
- **Vector search and the PGQ rewrite (Part 5)** are lower priority: vector
  search is a genuine new feature (and currently has zero data to work with),
  and the PGQ rewrite would optimize a traversal path already fixed this
  session (P13) — neither is an open problem today the way the RLS gap is.

---

*Generated: 2026-07-28 | aryx project | giggso*
*Grounded against live ADB introspection (version, package availability,*
*column types) via `docker exec aryx-api-1`, and against actual LLM/embed*
*call sites in `src/aryx/pipeline/embed.py`, `src/aryx/broker/__init__.py`,*
*`src/aryx/llm_runtime.py`, `src/aryx/api/ask_api.py`, `src/aryx/cpq/engine.py`,*
*`src/aryx/cpq/bml.py`, `src/aryx/cpq/rdb.py`, `src/aryx/graph/oracle_graph_reader.py`,*
*and the `complete_json()` call sites across `src/aryx/ontology/`,*
*`src/aryx/resolution/adjudicate.py`, `src/aryx/relationships.py`,*
*`src/aryx/pipeline/tag.py`, `src/aryx/brief_draft.py`.*
*Updated: 2026-07-28 — added Part 3, the Select AI usability verdict and the*
*graph-direct-linking analysis for CPQ's conversational loop.*
*Updated: 2026-07-28 — added Part 4 (VPD/RLS implementation plan: problem*
*statement, root cause, fix, phased rollout, testing plan) and Part 5*
*(vector search and SQL/PGQ rewrite, analysis-level, lower priority).*
