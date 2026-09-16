# CPQ Graph-RAG Fix Plan — 6 Diagnostic Issues

**Status:** Phases 1–4 implemented on branch `fix/cpq-graph-rag-issues` (PR #69) — S1–S7 green. **§6a (rule-target resolution follow-up) is a newly discovered, NOT-YET-implemented gap** — found via live audit against workspace 12, see §6a for details before treating this plan as fully closed.
**Date:** 2026-07-09
**Source:** "Aryx Graph-RAG Configuration Engine: Diagnostic Findings & Action Items" (customer debugging report)
**Sample test asset:** `SL3500e_Dummy_Config.xml` (BigMachines `bm_config_zip_cache` export, ~6 MB) — used as the *default* test input only; nothing in the implementation or tests may hardcode values from this file.

---

## 1. Background

Debugging of the Aryx AI configuration agent against a customer FalkorDB deployment
identified 6 issues causing hallucinated configurations, skipped rules, and dropped
attributes (e.g. Battery, Encryption, Region). This plan maps each finding to the
actual code on the current branch and defines the fixes plus a fully generic test
harness.

### Diagnostic findings vs. current code reality

| # | Report finding | Verified reality in current branch |
|---|---|---|
| 1 | Attributes trapped in a stringified `attrs` JSON blob on graph nodes | Worse on current code: `FalkorStore.add_entity` (`src/aryx/graph/falkor_store.py:72-104`) drops attributes entirely — only `id`, `type`, `name`, `iri` are lifted. **No FalkorDB indexes exist at all.** The deployed graph's `attrs` blob came from an older projection version. The CPQ engine survives by side-reading attrs from Postgres (`aryx_entity.attributes` JSONB) via `_batch_fetch` (`src/aryx/cpq/engine.py:236-258`). |
| 2 | Data ingested as generic `Entity` nodes + `REL` edges instead of ontology labels/semantic edges | Writes attach *both* the generic `:Entity` label and specific ontology labels (`falkor_store.py:89-101`); relationships are `[:REL {name}]` with the semantic name as a property (`falkor_store.py:133`). All reads use the generic pattern (`src/aryx/graph/reader.py:59-119`). Any AI-generated Cypher targeting the theoretical ontology (semantic edge types) fails. |
| 3 | BML scripts behind `function_id` invisible to the AI | Confirmed and deliberate: all three rule loaders filter out script-backed rules by requiring `condition_function_id = -1` (`engine.py:439-440`, `engine.py:567`, `engine.py:688`). No code anywhere references `BmFunction` or fetches BML script text. Script-backed rules are silently dropped. |
| 4 | Rules use numeric `attribute_id`, conversation uses `variable_name` | A mapping exists via `by_eid` dicts (`engine.py:518-523`, `643-647`, `776-780`) but **assumes the rule's numeric `attribute_id` equals the aryx `entity_id`** (`engine.py:396-397`). If ingestion does not preserve BM-native ids as entity ids, every rule join silently misses and rules never fire. |
| 5 | Confirmed variables (e.g. Region=NA) dropped from final payload | Two exact drop sites: **(a)** `build_payload` (`engine.py:1373-1382`) filters through `_valid()`, whose `_NONE_VALUES` set (`engine.py:38-47`) rejects `"na"`, `"0"`, `"any"`, `"-1"`, `"false"` — a user-confirmed Region "NA" is discarded. **(b)** The rule loop pops any filled key not in `visible_vns` (`engine.py:830-836`) and `session.filled` is wholesale-replaced (`src/aryx/api/ask_api.py:586`). |
| 6 | Pipeline forces a full config payload every turn | A FORMAT A (question-only) / FORMAT B (full BOM) split already exists (`ask_api.py:590-609`), but `MAX_TURNS = 5` (`engine.py:171`) force-emits FORMAT B with pending attrs remaining — the "guessed" payload behavior. |

Architecture note: the CPQ turn loop (`_run_cpq_turn`, `ask_api.py:374-621`) is a
deterministic state machine — the LLM never generates the payload. LLM calls occur
only in `_extract_terms` / `_synthesise` for side-Q&A. Fixes are therefore in
deterministic Python, not prompt engineering.

---

## 2. Phase 1 — Native attribute ingestion into FalkorDB (Issues 1 + 2)

### 1a. Lift ALL scalar attributes as native node properties

Replace blob/drop behavior with a parameter-bound property map:

```cypher
MERGE (e:Entity:<TypeLabels> {id: $id})
SET e.type = $type, e.name = $name, e += $props
```

`$props` is bound as a Cypher parameter map — values are never string-interpolated,
so there is no injection risk and no per-key escaping. Applies to both
`FalkorStore.add_entity` and `add_entities_batch` (`falkor_store.py:72-157`),
invoked from `project_graph` (`src/aryx/project.py:26-83`).

Sanitization rules (generic — no CPQ- or customer-specific hardcoding):

- **Scalars pass through natively** (str/int/float/bool). `variable_name`,
  `attribute_id`, `function_id`, `rule_type`, `guid` etc. become directly
  queryable: `MATCH (a {variable_name: 'batteryType_astro'})` works.
- **Nested dicts/lists:** JSON-stringify per key (config flag to skip instead).
  Never a single all-attributes blob.
- **Value cap:** truncate long strings to a configurable max — **default 500
  chars** (same mechanism as the Oracle backend's `_GRAPH_ATTR_STR_MAX`,
  `src/aryx/graph/oracle_graph_store.py:22-39`, raised from 200 based on
  measured data: in the sample export 99% of values are ≤ 73 chars and the only
  systematic >500 field is `script_text`, which is read from the RDB by design).
  **Key-like properties (`*_id`, `guid`, `variable_name`, match keys) are exempt
  from truncation** — a truncated identifier silently breaks exact-match joins,
  the exact bug class this plan eliminates; log a warning if a key exceeds a
  sanity bound instead of trimming it. The RDB (Postgres or Oracle ADB) remains
  the full-fidelity source of truth.
- **Reserved-key guard:** attr keys `id`, `type`, `name`, `iri` never overwrite
  the canonical lifted fields.
- **Key normalization:** property names validated with the same safe-identifier
  rule used for labels (`_LABEL_RE`, `falkor_store.py:20`).

Config additions (`src/aryx/config.py`): lift mode (`all_scalars` default /
`allowlist` / `off`), value-length cap, nested-value handling flag.

### 1b. Graph indexes

Add `FalkorStore.ensure_indexes()` called from `project_graph`:

- `Entity(id)`, `Entity(type)`, `Entity(name)` — currently every lookup is an
  unindexed scan.
- Key-like lifted properties, discovered per workspace by pattern
  (`*_id`, `*_name`, `guid`, `variable_name`-style keys) — FalkorDB indexes are
  per-property, so index creation is driven by the observed property set, not a
  hardcoded list.

### 1c. Reprojection / migration path

Projection already rebuilds the whole workspace graph. Add/verify a `reproject`
entry point so existing deployments (including the customer graph with the legacy
stringified `attrs` blob) are rebuilt with native properties by re-running
projection with the new store code. No in-place graph migration needed.

### 1d. Read side catches up

- `GraphReader._entity()` (`reader.py:364-366`) returns full `properties(e)`
  instead of only `(id, type, name)`, populating `RetrievedEntity.attributes`
  (currently always empty on FalkorDB) so `render_context`'s existing
  attribute-rendering path (`src/aryx/graph/retrieve.py:124-135`) becomes live.
- Add `describe_schema()` to the reader port: returns the *actual* schema —
  generic `Entity`/`REL {name}` pattern, distinct types, lifted property names —
  so any AI-generated Cypher (text-to-Cypher, MCP tools) is grounded in the real
  data schema instead of the theoretical ontology (Issue 2's root cause).

### 1e. Oracle graph backend parity

Aryx runs on two backend pairs — FalkorDB + Postgres, or OCI Oracle ADB 23ai for
both graph and RDB (`effective_graph_backend`, `src/aryx/config.py`). The lift
must be equivalent on both:

- `OracleGraphStore` already persists the full attributes as a JSON column
  (`aryx_graph_vertex.attributes`, `src/aryx/store/migrations_oracle/graph_schema.sql:11`)
  — no write change needed beyond honoring the same reserved-key/cap semantics.
- **Queryability:** add function-based indexes (or a JSON search index) on the
  key-like fields, e.g.
  `JSON_VALUE(attributes, '$.variable_name')`, mirroring the FalkorDB property
  indexes from 1b. Same pattern-driven key discovery, no hardcoded field list.
- **Read parity:** `OracleGraphReader` currently selects only
  `(entity_id, type, name)` and ignores the attributes column it stores — return
  the attributes JSON like the FalkorDB reader (1d), and implement
  `describe_schema()` for this backend too.

---

## 3. Phase 2 — Rule engine completeness (Issues 3 + 4)

### 2·0. RDB dialect abstraction (prerequisite)

The CPQ engine's rule loaders and `_batch_fetch` issue **Postgres-only SQL** —
JSONB operators and casts like `attributes->>'rule_type'` and
`(attributes->>'condition_function_id')::int` (`engine.py:236-258`,
`421-500`, `558-628`, `679-761`) via `get_pool(rdb_dsn)`. On an Oracle ADB
deployment these queries fail outright (Oracle needs
`JSON_VALUE(attributes, '$.rule_type')`).

Fix: route all CPQ attribute/rule reads through a backend-agnostic accessor —
either the existing entity-store/ports layer or a small dialect helper that
renders the JSON-extraction expression per backend (Postgres JSONB vs. Oracle
`JSON_VALUE`). Every Phase 2 and Phase 3 query goes through it; no raw
dialect-specific SQL remains in `cpq/`.

### 2a. BM-native ID mapping layer (Issue 4)

*Builds directly on Phase 1a/1b: `variable_name`, `attribute_id`, `function_id`
etc. are now native, indexed graph properties, so the bridge can be assembled
with indexed graph lookups instead of scanning RDB JSON.*

Build the ID bridge once per `load_product_config` (`engine.py:266-407`):

- Map each `ConfigAttr`'s **source-native id** (now readable straight off the
  node as a lifted property, e.g. `id` / `attribute_id`) ↔ `variable_name` ↔
  aryx `entity_id`.
- The report's two-step lookup becomes two indexed graph queries:
  `MATCH (a {variable_name: $v}) RETURN a.<id-key>` then rule inputs/actions by
  that numeric id.
- Rule joins (`by_eid` in hiding/recommendation/constraint evaluation) resolve
  via BM-native id first, aryx entity id as fallback.
- Derive the id keys generically from whatever lifted properties the entities
  carry — do not assume BigMachines field names beyond a configurable
  key-priority list.
- The RDB `_batch_fetch` (via the 2·0 dialect layer, Postgres or Oracle ADB)
  remains the fallback path and stays authoritative for values longer than the
  Phase 1a cap.

### 2b. BML function resolution (Issue 3)

New module `src/aryx/cpq/bml.py`:

- **Loader:** given a rule whose condition or action carries a
  `function_id != -1`, locate the function entity via an indexed graph lookup on
  its lifted id property (`bm_function` / `...BmFunction` — type resolved by the
  same normalized-suffix discovery used in `engine.py:290-304`). **The script
  text itself is fetched from the RDB** (`aryx_entity.attributes`, via the 2·0
  dialect layer — Postgres or Oracle ADB), not the graph: BML scripts exceed the Phase 1a value cap and the graph copy is
  truncated by design.
- **Tier 1 — deterministic mini-evaluator** for the dominant BML idiom:
  `if (var == "X") { return "A|B|C" }` chains returning pipe-delimited
  allowed-value lists. Small grammar, evaluated against the session's `filled`
  state. Covers the hardware/frequency-restriction pattern from the report.
- **Tier 2 — LLM fallback:** for scripts Tier 1 cannot parse, pass the raw
  script plus current filled state to `llm_runtime.chat("menial", ...)` asking
  for the allowed-value list. Cache per `(function_id, inputs-hash)`.
- Rule loaders (`load_hiding_rules`, `load_recommendation_rules`,
  `load_constraint_rules`) stop filtering out `function_id != -1` rules and
  route them through this evaluator. Log per-workspace coverage: how many rules
  are declarative / Tier-1 / Tier-2 / unresolvable.

---

## 4. Phase 3 — State management & orchestration (Issues 5 + 6)

### 3a. Fix `build_payload` dropping confirmed values (Issue 5, site a)

A value the user confirmed against a real menu option is valid by definition.

- Add answer provenance to `CpqSession` (`src/aryx/cpq/state.py`):
  `filled_source: dict[var, "user" | "cascade" | "default"]`.
- `build_payload` (`engine.py:1373-1382`) drops a value only if it is none-like
  **and not user-confirmed**. `Region = "NA"` chosen from a menu survives;
  a genuinely empty auto-fill still gets pruned.

### 3b. Fix the visibility purge (Issue 5, site b)

In `evaluate_rules_loop` (`engine.py:830-836`), only pop filled keys hidden by an
*explicit* hiding-rule outcome — never keys merely absent from the loaded
attribute list. This also protects confirmed answers when `load_product_config`
returns a partial attr set.

### 3c. Fix MAX_TURNS forcing a fabricated payload (Issue 6)

At the turn cap (`ask_api.py:590`), emit an explicit *incomplete* response
instead of a full FORMAT B payload:

- Either a FORMAT A variant listing unresolved attributes, or FORMAT B flagged
  `"complete": false, "unresolved": [...]` — decided at implementation, but a
  payload presented as final must never contain guessed values.
- Gate: payload emission requires **no pending attrs AND all constraint rules
  (including BML-backed ones from Phase 2b) evaluated clean**.

---

## 5. Phase 4 — Generic test harness (sample: `SL3500e_Dummy_Config.xml`)

### Zero-hardcoding principle

Tests must work for **any** BigMachines `bm_config_zip_cache` export. The fixture
parses whatever XML it is given and derives all expectations from the file itself
(the same approach as `ground_truth_from_tabular` in
`src/aryx/pipeline/ingest_validation.py`). The sample path comes from a pytest
option / env var (e.g. `--cpq-sample`, `ARYX_CPQ_SAMPLE`), defaulting to
`SL3500e_Dummy_Config.xml`. No entity names, ids, counts, variable names, or menu
values from the sample may appear as literals in test code.

### Sample profile (for sizing only — derived at runtime by the fixture)

The default sample contains the full CPQ entity family: `bm_config_rule` (418),
`bm_config_rule_input` (626), `bm_config_rule_action` (247), `bm_function` (334),
`bm_menu_item` (353), `bm_config_attr` (15), `bm_config_layout_attr_prop`
(10 508), multilingual CDATA name wrappers, and `_children` containers — enough
to exercise all 6 issues.

### Test scenarios — `tests/test_cpq_e2e.py` + `tests/cpq_fixtures.py`

| # | Scenario | Ground truth derivation (from the XML, at runtime) | Assertions |
|---|---|---|---|
| S1 | Ingestion fidelity | Count entity elements per type using the same `_is_entity` heuristic as `doc_discovery` | Every discovered type lands; per-type graph node count == XML count; zero silent truncation (or logged caps only) |
| S2 | Native queryability | Randomly sample N entities per type; read their scalar attr keys/values from the XML | For each sampled (key, value): `MATCH (e {<key>: $value})` returns the node; oversized values truncated to the cap; nested values stringified per key; indexes exist for key-like properties |
| S3 | Schema truth | — | `describe_schema()` reports the real `Entity`/`REL {name}` pattern + lifted properties; reader round-trips every sampled entity with full attributes populated |
| S4 | ID mapping | Sample rule_input elements; resolve each `attribute_id` to its owning attr element inside the XML | The engine's ID bridge resolves the same `variable_name` for 100 % of sampled rules — via the indexed graph lookup path (Phase 1 lifted properties), with the RDB fallback also asserted; zero silent join misses |
| S5 | BML coverage | Enumerate rules in the XML whose condition/action references a `function_id != -1` | 0 rules silently dropped; each function entity is locatable in the graph by its lifted id property AND its full untruncated script text is retrieved from the RDB; Tier-1 evaluator parses its subset (coverage ratio logged and asserted > 0 when such rules exist) |
| S6 | Payload integrity | Drive a full simulated conversation; answer each pending question with an option sampled from that attribute's own menu items in the XML — deliberately preferring none-like codes (`NA`, `0`, …) when the menu contains them | Final payload keys == the user-confirmed set, exactly. Nothing dropped, nothing invented; provenance recorded per variable |
| S7 | No eager output | Same driven conversation, plus a forced turn-cap run | No `cpq_payload` / FORMAT B while pending attrs remain; at the cap, output is explicitly flagged incomplete and contains no guessed values |

Existing suite: pytest under `tests/` (see `tests/test_doc_discovery.py` for
ingestion-test conventions). S1–S3 need a FalkorDB instance (docker-compose
already provides one); S4–S7 run against the RDB + the deterministic engine and
can use an ephemeral workspace.

**Test backend scope (current):** the suite runs against the
**FalkorDB + Postgres** pair only. The scenarios are backend-agnostic by
construction (fixtures target the ports/dialect layer, never raw SQL), so
enabling the OCI graph + Oracle ADB pair later is a fixture parametrization —
no test-logic changes. Oracle-specific behavior (1e indexes, `JSON_VALUE`
dialect rendering) is design-complete in this plan but its test enablement is
deferred until an ADB test environment is provisioned.

---

## 6. Sequencing, dependencies, risks

```
Phase 1 (graph lift + indexes)  ──┐
Phase 4 fixture (XML parser)    ──┼──>  Phase 2 (ID bridge → BML)  ──>  full S1–S7 green
Phase 3 (state/orchestration)   ──┘
```

- **Parallel-safe:** Phase 1, Phase 3, and the Phase 4 fixture are independent.
- **Dependency:** Phase 2a's indexed graph lookups require Phase 1a (lifted
  properties) and 1b (indexes); Phase 2b depends on 2a and additionally reads
  full script text from the RDB because of the 1a value cap. Phase 2·0 (dialect
  layer) precedes all other Phase 2/3 query changes. S2–S5 assertions
  require Phase 1 to be landed first.
- **Biggest risk:** Tier-1 BML grammar coverage (2b). Mitigated by the Tier-2
  LLM fallback and the S5 coverage-ratio metric, which quantifies exactly how
  much rule logic each tier handles on real data.
- **Property bloat risk** (wide entities like `bm_config_layout_attr_prop`):
  mitigated by the value-length cap and the per-key skip flag; the RDB keeps
  full fidelity.
- **Reprojection cost:** full-graph rebuild per workspace; acceptable because
  projection is already a full rebuild (`graph.clear()` + re-add).

---

## 6a. Follow-up fix — `load_hiding_rules` misses marked-attribute-targeted rules

**Discovered:** post-implementation audit against workspace 12 (real ingested
data), while investigating why a production workspace (`CPQ_Quote_MSI`) was
still prompting for 85 individual attributes.

**Problem.** `load_hiding_rules` (§4, already shipped) assumes every
declarative hiding rule (`rule_type=11`, `condition_function_id=-1`) has a
matching `BmConfigRuleAction` row carrying the target `attribute_id`. On real
data this assumption is wrong for the large majority of hiding rules.

**Root cause — verified against workspace 12's real Postgres data, in two
passes (the first hypothesis was wrong; corrected below):**

- **0 of 35** declarative `rule_type=11` rows have a matching
  `BmConfigRuleAction` row, and each rule's own `attr_id` field is the unused
  sentinel `"-1"`.
- **First hypothesis (wrong, ruled out by direct query):** `bm_config_layout_attr_assoc`
  and `bm_config_rule_layout_assoc` were suspected as the real target
  linkage. Checked directly — **0 of the 35 rules match either table**. These
  tables exist and carry real data for *other* purposes (UI layout
  membership), but are not how hiding-rule targets are actually encoded here.
- **Real mechanism, confirmed by tracing one rule end-to-end and then
  validating across all 35:** a broad search for the rule's own id anywhere
  in the workspace's data surfaced **`bm_config_marked_attr`** — a table not
  read anywhere in the current CPQ engine. Each row carries `rule_id` /
  `bm_config_rule_id`, a target `attribute_id`, and a `mark_type` field. One
  rule can mark **multiple** attributes (the traced rule marked 2).
  - **32 of 35 (91%)** declarative hiding rules resolve a target via
    `bm_config_marked_attr`.
  - `bm_config_rule_assoc` (`rule_id → child_rule_id`, rule chaining) adds
    **zero rules beyond that 32** in this dataset — every chain-resolved rule
    was already resolved via `marked_attr` directly. Kept as a fallback path
    for robustness on other exports, not because it added coverage here.
  - **3 of 35 remain genuinely unresolved** by any mechanism found (no
    marked_attr row, no chain, `attr_id="-1"`) — e.g. `"Rule to hide Billing
    Option for EMEA"`, `"Hide OCC config attr"`. Not chased further with more
    guesses; flagged as a residual to log and count, not silently swallow.
    Plausibly incomplete rows in this dummy dataset specifically.
  - `mark_type` is `"3"` for all 145 rows in this dataset — no observed
    variability, so it cannot currently distinguish hide-vs-show. Every
    `rule_action_type` on these 35 rules is also `"1"` uniformly. **Working
    assumption, stated explicitly rather than silently baked in:** every
    `HidingRule` sourced from `bm_config_marked_attr` defaults to `hide=True`
    (matching the dataclass default) until an export is found where either
    field varies and a real hide/show signal can be derived from data.

**Impact.** Every hiding rule targeting via `bm_config_marked_attr` was
silently treated as having no target — `load_hiding_rules` was returning 0
usable rules where 32 genuinely exist. Any attribute whose visibility
depends on one of these rules never gets governed by D2's rule-outcome
eligibility test (`CPQ_CASCADE_CONVERSATION_PLAN.md` §2). This is very
likely the real reason `CPQ_Quote_MSI` (APX NEXT) still shows 85 unresolved
attributes even after the eager-payload fix (3c) landed.

**Fix.** Extend `load_hiding_rules` to resolve a rule's target(s) through, in
priority order: (1) existing `BmConfigRuleAction.attribute_id` (kept — still
the right path for exports that do use it), (2) `bm_config_marked_attr` by
`rule_id`/`bm_config_rule_id` — **may yield multiple targets per rule**, so
`load_hiding_rules` emits one `HidingRule` per (rule, marked attribute) pair
rather than changing `HidingRule`'s shape, (3) `bm_config_rule_assoc
.child_rule_id`, followed recursively (bounded depth, e.g. 3 hops) and
re-resolved through (1)–(2) at the terminal rule. Log rules that resolve via
none of these — visible residual, not silent data loss.

**Scope note — recommendation/constraint rules intentionally NOT touched.**
This workspace has zero `rule_type=10`/`rule_type=5` rows at all (verified —
not a join bug, a genuine data gap), so there is no real data to confirm
whether `bm_config_marked_attr` applies the same way to those rule types.
`mark_type`'s naming ("marked" as in UI-marked/hidden) suggests it may be
hiding-specific. Extending this fix to recommendation/constraint without
evidence would repeat the exact guessing mistake this whole investigation
exists to avoid — defer until an export with real type-10/5 data surfaces the
same gap, then re-run this same investigation method against it.

**Re-ingestion required? No.** `bm_config_marked_attr` and
`bm_config_rule_assoc` already exist in Postgres for workspace 12 with real
data, from the original ingestion — nothing new needs to be extracted from
the XML. This is a pure query/join change in `cpq/rdb.py` + `cpq/engine.py`;
it takes effect the next time the updated code runs, no pipeline re-run, no
reprojection.

**Test addition:** a scenario deriving, from the resolved sample, how many
declarative hiding rules resolve via each path (action / marked_attr / chain
/ unresolved) — regression guard against silently losing coverage again, and
a concrete "how many rules recovered" metric (32/35 here) to report
before/after on any export.

**Implemented and verified against workspace 12 (live, real data):**
`load_hiding_rules(12)` now returns **81 usable `HidingRule` objects, up from
0** before this fix — confirmed by direct execution against the running API
container. One important, honestly-reported caveat found during this
verification: **none of the 81 recovered rules target any of this dataset's
15 formal `BmConfigAttr` entities** (checked directly — zero id overlap).
They govern layout/property-level elements elsewhere in this bundled export,
not the conversational attributes `load_product_config` surfaces for the
"SL3500e" product specifically. So on *this* sample, Phase B of
`CPQ_CASCADE_CONVERSATION_PLAN.md` will correctly show 0 rule-governed attrs
for SL3500e — that is data reality, not a residual bug. The fix is proven
correct at the rule-loading level; whether it actually reduces
`CPQ_Quote_MSI`'s 85-attribute count can only be confirmed against that
workspace's own data, which remains inaccessible from this environment.

---

## 7. Out of scope

- Prompt-engineering changes to the Ask/side-Q&A LLM calls (the config payload
  is deterministic Python; the report's "state machine override" is the
  MAX_TURNS gate, fixed in 3c).
- Semantic edge types (replacing `[:REL {name}]` with typed edges) — deferred;
  `describe_schema()` (1d) removes the mismatch pain without a breaking graph
  rewrite.
- Oracle ADB **test execution** — the dialect layer (2·0) and graph parity (1e)
  are designed and implemented alongside, but automated tests run on
  FalkorDB + Postgres only until an ADB test environment exists.
