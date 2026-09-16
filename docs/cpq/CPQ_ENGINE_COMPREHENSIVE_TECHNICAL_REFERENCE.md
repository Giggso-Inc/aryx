# Aryx CPQ Engine — Comprehensive Technical Reference

**Scope:** everything from raw BigMachines/Oracle CPQ catalog ingestion through to a
served `/ask` conversational turn and final BOM payload. Every file that participates,
what it's responsible for, and the exact sequence execution follows — including where
the system is deterministic vs. where an LLM is involved, and how each is validated.

**Source checkout:** `aryx_rv_branch/aryx` (branch `fix_issues_main`, includes PR #134's
merged fixes). Line numbers are accurate as of this checkout and will drift; treat them
as pointers, not permanent anchors.

---

## 1. The two halves of the system

The CPQ engine is not a standalone application — it's a domain built entirely on top of
Aryx's generic knowledge-graph ingestion pipeline. There is **no dedicated CPQ database
schema**. Every BigMachines/Oracle CPQ concept (attribute, rule, function/script,
option list) is ingested as a generic Aryx entity, distinguished only by an
`ontology_type` string prefix tied to the source catalog.

```
┌─────────────────────────────┐        ┌──────────────────────────────────┐
│   INGESTION (offline)        │        │   ASK-TIME (online, per request)  │
│   BM/Oracle CPQ XML export   │  --->  │   CpqEngine + intent gateway +    │
│   → generic entity graph     │        │   rule loop → BOM payload         │
└─────────────────────────────┘        └──────────────────────────────────┘
```

---

## 2. Ingestion: catalog XML → queryable entity graph

### 2.1 Pipeline stages (generic — not CPQ-specific code)

Entry point: **`src/aryx/pipeline/orchestrate.py`** → `run_pipeline()`. Chains, in order:

| Stage | Function / module | What happens |
|---|---|---|
| **Discover** (extract + clean + profile + land) | `aryx.discover.discover()` | Pulls raw records from the source connector (for CPQ: an XML file connector reading the BM export, e.g. `APX_Next_config.xml`) and lands them as raw records in Postgres. |
| **Tag** (optional, cheap-tier) | pipeline tag stage | Cheap-LLM field tagging, opt-in. |
| **Resolve / cluster** | `aryx.resolve_entities.resolve_run()` → `EntityStore` | Groups landed records into canonical entities and writes them to `aryx_entity`. |
| **Seed ontology** | `OntologyStore.seed_types()` | Registers the resolved `ontology_type` so the schema UI/diagram picks it up. Idempotent. |
| **Relate** (optional) | `aryx.pipeline.enrich._relate()` | Frontier-tier relationship inference between entities. |
| **Schema FK inference** (optional) | `_infer_schema_fk_links()` + `link_by_attribute()` | One LLM call across all type schemas to find shared-value joins with no naming-convention hint. |
| **Cooccurrence link** | `aryx.pipeline.cooccurrence_link` | Statistical co-occurrence-based linking. |
| **Relate isolated** | `_relate_isolated()` | Safety net for entities left with no edges. |
| **Dimension link** | `aryx.pipeline.dimension_link` | Links dimension-style reference entities. |
| **Project** | `aryx.project.project_graph()` | Projects the final entity/edge set into FalkorDB. |

### 2.2 Where CPQ-specific logic enters ingestion

Ingestion itself has **no dedicated CPQ module** — but one file has CPQ-aware heuristics
baked into the generic schema-inference logic:

- **`src/aryx/pipeline/doc_discovery.py`** — infers entity types/fields from XML
  structure. Contains explicit, additive BigMachines/CPQ heuristics: recognizing
  `bm_config_rule_id`-style bare 2-letter codes, `bm_function`/`bm_config_attr` naming
  patterns, and a size cap (`ARYX_XML_MAX_ENTITY_TYPES`, default 20) for large CPQ/ERP
  exports. These are "degrade gracefully on non-BM data" heuristics, not a hard
  dependency — a non-BM XML source still ingests through the same code path.
- **Cross-dependency, ingestion → CPQ engine code**: `doc_discovery.py` (around the FK
  detection pass) **imports and reuses `aryx.cpq.bml.parse_array_iteration`** — the same
  BML array-iteration parser the live engine uses — to recognize `bm_function` /
  `bm_config_attr` array-iteration patterns as FK link candidates during ingestion. This
  is the one place ingestion and the live CPQ engine share code (see
  `docs/CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md`).

### 2.3 Storage after ingestion

No `cpq_*` tables exist. Everything rides on:

- **`aryx_entity`** (`src/aryx/store/migrations/0009_workspaces.sql`) — `id`,
  `workspace_id`, `ontology_type` (e.g. `ApxNextConfigBmConfigAttr`,
  `...BmConfigRule`, `...BmFunction` — prefixed per source catalog), `attributes JSONB`,
  `confidence`, `created_at`. LIST-partitioned by `workspace_id`.
- **`aryx_entity_member`** — links each entity back to the landed raw record(s) it was
  resolved from (provenance chain back to the source XML).
- **FalkorDB** (`src/aryx/graph/falkor_store.py`, Oracle variant
  `oracle_graph_store.py`) — the rebuildable graph *projection* of the same entities;
  relationships (rule → target attribute, attribute → option list, etc.) are graph
  edges here, not foreign-key columns in Postgres. Postgres remains the source of
  truth; FalkorDB can always be rebuilt via `project_graph()`.

### 2.4 How the CPQ engine reads this generic data as if it were a real schema

**`src/aryx/cpq/rdb.py`** is the abstraction layer that makes the generic
`ontology_type`/JSONB storage look like a real relational CPQ schema to the rest of the
engine:

- `PostgresCpqRdb` (lines ~58–492) and `OracleCpqRdb` (subclass, ~493–756) — same
  interface, different SQL dialect (`JSONB` operators vs. Oracle `JSON_VALUE`).
- Key methods, each pattern-matching on `ontology_type LIKE '<catalog_prefix>%<suffix>'`:
  `fetch_entity_attributes`, `fetch_entities_by_type`, `fetch_rules`,
  `fetch_value_rules`, `fetch_rule_inputs`, `fetch_rule_actions`, `fetch_marked_attrs`,
  `fetch_rule_chain_links`, `fetch_function_scripts` (BML script bodies),
  `fetch_attr_set_assoc` (array/grid groupings), `fetch_layout_attr_assoc`,
  `fetch_layout_model_nodes`.
- `get_cpq_rdb()` (line 756) — factory returning the Postgres or Oracle implementation
  based on config.
- The `_catalog_prefix()` scheme (in `engine.py`) is what disambiguates multiple
  ingested catalogs living in the same `aryx_entity` table — e.g. `APX_Next_config.xml`
  vs. `SL3500e_Dummy_Config.xml` both produce `BmConfigAttr` entities, distinguished by
  a catalog-specific `ontology_type` prefix.

---

## 3. Ask-time: the request/response lifecycle

### 3.1 Top-level entry: `run_ask()` — `src/aryx/api/ask_api.py:6680`

Every `/ask` HTTP call (`ask_router()` → `POST /ask`, line 6789/6792) enters here.
`run_ask` decides, per request, whether this is a CPQ turn at all — governed by
`ARYX_CPQ_INTENT_MODE`:

| Mode | Behavior |
|---|---|
| `llm_first` | The intent gateway (§4) routes every cold-start turn — its route decision is authoritative. |
| `deterministic_first` | Legacy path — only the regex/alias gate (`is_cpq_question`) plus one narrow LLM fallback (`_llm_classify_is_cpq_question`) decide. No gateway call. |
| `shadow` (**default**) | Deterministic gate still decides routing; the gateway runs anyway and only *logs* agreement/disagreement (`cpq_router_shadow` log line) — a live A/B measurement with zero behavior risk. |

Routing logic, in order:
1. **Live session check** — if `session_data.mode == "cpq"`, always re-enter
   `_run_cpq_turn` directly (line 6699) — an in-progress CPQ session owns its own
   switch/undo/cascade logic and skips top-level routing entirely.
2. **Hard off-topic veto** (`hard_off_topic()`, line 6708) — a fixed regex
   (astrology/weather/jokes/etc.) short-circuits straight to the standard (non-CPQ) Ask
   pipeline, no LLM call at all.
3. **Deterministic CPQ gate** (`_deterministic_cpq_gate`) + **soft-quote heuristic**
   (`soft_quote_heuristic`, regex for order/config/quote-shaped language) computed
   regardless of mode — used as the escape hatch and shadow auditor.
4. Mode-specific dispatch as above, ultimately landing on one of: `_route_quote`
   (→ `_run_cpq_turn`), `_route_qa`, `_route_ambiguous`, or `_standard_ask_pipeline`
   (the generic, non-CPQ Ask/RAG path — out of scope for this doc).

### 3.2 The CPQ turn: `_run_cpq_turn` → `_run_cpq_turn_inner` (line 3939/3961)

This is the actual conversational state machine. It executes as a numbered STEP
sequence (comments in the code literally say `STEP N`):

| Step | What it does | Deterministic or LLM? |
|---|---|---|
| **STEP 1** — Sequential anchor prompting (line ~4383) | Product, then country, asked one at a time before any config question. | Deterministic (string/regex hint extraction). |
| **STEP 2** — Resolve product name → item_value (line ~4474) | Maps a free-text product mention to the catalog's real item_value. | Deterministic, with fuzzy/word-overlap matching. |
| **STEP 3** — Rule evaluation loop (line ~6154) | hide → auto-fill → recommend → constrain, to a fixed point. | Deterministic core; BML Tier-2 fallback *can* be LLM (off by default, §5). |
| **STEP 4** — Format A: next question (line ~6415) | Builds the next pending question with context sentence + numbered options. | Deterministic templating. |
| **STEP 5** — Lock user's answer from previous turn (line ~5870) | Applies the prior turn's answer into `session.filled`/`filled_multi`. | Deterministic matching (`apply_answer`/`apply_multi_answer`), scoped by any active constraint (`constrained_item_values`). |
| **STEP 6** — Change request → cascade (line ~5415; cascade logic itself at line 1021) | Detects "change X to Y" mid-session, invalidates dependents, re-runs the rule loop. | Deterministic regex detectors first; the intent gateway (§4) or narrow `_llm_classify_*` fallbacks only on regex-miss, and only when they *agree* with a deterministic detector for mutating intents. |
| **STEP 7** — Contextual Q&A (line 612, active-config variant at line ~5745, review variant at line 5203) | Answers a graph/catalog question ("what carriers are available?") without losing config state, then resumes. | Deterministic dispatch; the answer content for a graph question goes through the generic Ask/RAG path, not the CPQ rule engine. |
| **STEP 8** — Explicit approval → BOM payload (line ~5087) | On "confirm", runs `bom_gate.validate_before_payload` and either emits the payload or blocks with a specific reason. | Deterministic gate (§6). |

### 3.3 What `CpqEngine` (the workhorse) actually does per step

**`src/aryx/cpq/engine.py`** (~7,000 lines) implements the mechanics STEP 1–8 call into.
Key methods (this is the same rule engine documented in depth earlier this session —
summarized here for completeness):

- **Hint/intent extraction**: `extract_hints`, `extract_catalog_hints`,
  `detect_product_mention`, `detect_change_request(s)`, `detect_attr_query`,
  `detect_approval`, `detect_qa_question`, etc. — all regex/string-matching, zero LLM
  calls inside `engine.py` itself.
- **Catalog loading**: `load_product_config`, `_scope_to_catalog` (prevents attribute
  bleed across multiple ingested catalogs in one workspace).
- **Rule loading**: `load_hiding_rules`, `load_recommendation_and_constraint_rules`.
- **Rule engine**: `apply_hiding_rules`, `apply_recommendation_rules`,
  `apply_constraint_rules`, `evaluate_rules_loop` (the fixed-point driver, capped at 8
  passes), `build_bml_evaluator` (constructs the `BmlEvaluator` for script-backed
  rules).
- **Auto-fill**: `auto_fill` — strict priority chain (user hint → explicit default →
  single-remaining-option → otherwise ask); never silently guesses.
- **Answer application**: `apply_answer` (single-select), `apply_multi_answer`
  (multi-select) — both accept an optional `constrained_item_values` to scope matching
  to only the currently-allowed options.
- **Payload synthesis**: `build_payload` — assembles the final `{variable_name:
  item_value}` BOM structure from `filled`/`filled_multi`.
- **Narration support**: `render_filled_summary` (deterministic bullet fallback),
  `categorized_summary_groups`.

---

## 4. The intent layer — how natural language becomes a structured decision

This is the newest and most substantial architectural layer, and it sits **around**
`CpqEngine`, never inside it — `CpqEngine`'s own methods never call an LLM directly.

### 4.1 `src/aryx/cpq/intent_gateway.py` (966 lines) — the LLM-first gateway

Module docstring, verbatim intent: *"One structured Gemini Pro call per turn... The
model only SELECTS from candidate lists... never emits free-text catalog identifiers or
values."*

- **`classify_ask_route()`** — the top-level router call from `run_ask` (§3.1). Decides
  `quote` / `qa` / `off_topic` / `ambiguous` for a cold-start turn.
- **`classify_intent()`** (exposed to `ask_api.py` as `gateway_classify_intent`) — the
  mid-session STEP 6 equivalent, used when a live CPQ session needs to classify a
  change/removal/clarification intent.
- **Candidate scoping** (`build_candidate_bundles`, `AttrCandidateBundle`,
  `ValueCandidate`) — the model is given an **indexed candidate list** built from the
  live `CpqSession` + `CpqEngine.load_product_config`, and can only refer to a
  candidate by index. It never sees or emits a raw catalog identifier.
- **Quarantine validation** (`validate_gateway_quarantine`, in `intent_schema.py`) —
  fails closed to `AMBIGUOUS` unless: the returned `variable_name` is in the injected
  candidate set, the `value_ref` is in-range for that attribute's candidates, AND the
  `evidence_span` appears verbatim in the user's actual question. Any violation is
  treated as "the model made this up" and discarded.
- **Mutating-intent agreement gate** (`MUTATING_CATEGORIES`, `_mutating_agrees`) — for
  anything that would *change* session state (change request, attribute clear/
  activation, bulk quantity change, multi-select removal), the LLM's classification
  must **agree** with an existing deterministic `detect_*` function. Disagreement means
  the LLM's mutating decision is not trusted alone.
- **One-call-per-turn discipline** (`mark_top_level_route_used`/`top_level_route_used`,
  a `contextvars.ContextVar`) — if `classify_ask_route` already ran this turn at the top
  level, the mid-session STEP 6 gateway call is skipped, so a turn never pays for two
  LLM classification calls.
- **Hard off-topic veto** (`_OFF_TOPIC_HARD`) and **soft-quote heuristic**
  (`_SOFT_QUOTE`) — both deterministic regexes that bound what the LLM is even allowed
  to override.
- **Caching**: module-level dict (`_CACHE`, `_CACHE_MAX = 256`), keyed by
  `(model_id, pid, normalized_question, session_state_hash)` — `session_state_hash()`
  fingerprints exactly the parts of session state the candidate list depends on
  (product, filled/filled_multi, pending variables, status).

### 4.2 `src/aryx/cpq/intent_schema.py` (398 lines) — typed contracts

- `IntentCategory` (enum) — the fixed vocabulary of intents (`CHANGE_REQUEST`,
  `MULTI_SELECT_REMOVAL`, `ATTR_CLEAR`, `BULK_QUANTITY_CHANGE`, etc.).
- `Confidence` (enum), `ChangeTarget`, `IntentResult`, `GatewayIntentResult` — typed,
  validated dataclasses the LLM's raw JSON is parsed into (`parse_intent_result`,
  `parse_gateway_intent`) before any code touches it.
- `validate_gateway_quarantine()` — the quarantine check described above, factored out
  so both the gateway and its tests exercise the identical rule.

### 4.3 `src/aryx/cpq/intent_queue.py` (237 lines) — multi-target change requests

Handles "change A, B, and C" in one utterance:

- `enqueue_intent_targets` — when a user names multiple attributes to change in one
  message, only the first is handled this turn; the rest go on
  `session.pending_intent_queue`.
- `drain_intent_queue_into_pending` — moves queued targets into the active pending-
  question list once ready.
- `audit_intent_conservation` (`IntentAuditResult`) — a correctness check ensuring no
  named target is silently dropped between turns.
- `format_dropped_intent_notice` / `format_queue_overflow_notice` — user-facing
  messaging for the (rare, capped) failure modes.

### 4.4 `src/aryx/cpq/telemetry.py` (102 lines) — shadow-mode measurement

- `DivergenceRecord` + `log_divergence()` — records every case where the LLM gateway's
  route/intent disagreed with the deterministic path (this is what powers the
  `cpq_router_shadow` WARNING-level log line in `run_ask`).
- `log_rejection()`, `disagreement_rate()` — aggregate telemetry for evaluating whether
  `ARYX_CPQ_INTENT_MODE` could safely move from `shadow` toward `llm_first`.

### 4.5 Compound "reject + replace" reply parsing — `ask_api.py` (STEP 6 pending-change-value flow)

This is a small, self-contained, **regex-only** (no LLM) piece of STEP 6's cascade
handling, at the point where the customer is answering a pending "which value?" prompt
that was raised because they said "change X" without naming a new value. It has its own
history of live-found bugs and is a good example of the "narrow, independently
bisectable" fallback design described in §4 — worth documenting in full because it's
easy to lose track of the exact bug shape across sessions.

**Location** (PR #134 branch, `fix/cpq-carrier-disambiguation-and-decline`,
`src/aryx/api/ask_api.py`, ~line 1020–1090; exact line numbers drift — search for
`_REPLACEMENT_CUE_RE` if the anchors below are stale):

```python
_CHANGE_VALUE_DECLINE_RE = re.compile(
    r"don'?t\s+want\w*|do\s+not\s+want\w*"
    r"|no\s+chang\w*|not\s+chang\w*"
    r"|leave\s+it|keep\s+it"
    r"|never\s*mind"
    r"|cancel\s+(this|that|it)"
    r"|skip\s+(this|that)",
    re.IGNORECASE,
)

def _is_change_value_decline(reply: str) -> bool:
    return bool(_CHANGE_VALUE_DECLINE_RE.search(reply or ""))

_REPLACEMENT_CUE_RE = re.compile(
    r"\b(?:use|instead(?!\s+of)|prefer|rather)\b\s*[:,]?\s*(.+)$", re.IGNORECASE,
)
_CONTRAST_CUT_RE = re.compile(
    r"\b(?:over|than|instead\s+of|rather\s+than|not)\b", re.IGNORECASE,
)

def _extract_replacement_clause(text: str) -> str | None:
    m = _REPLACEMENT_CUE_RE.search(text or "")
    if not m or not m.group(1).strip():
        return None
    clause = m.group(1).strip()
    cut = _CONTRAST_CUT_RE.search(clause)
    if cut:
        clause = clause[:cut.start()].strip()
    return clause or None
```

**Problem these solve**: a customer's reply to a "which value?" prompt has three
possible shapes, which must be told apart *before* any value-matching happens —
conflating them was the original bug:

1. **A plain declined change** — `"never mind"`, `"leave it as is"`, `"I don't want to
   change it"`. Must leave the current value untouched.
2. **A plain new value** — `"H45"`. Goes straight to `apply_answer`/`apply_multi_answer`.
3. **A compound reject-and-replace** — `"I don't want Standard, use Premium"`,
   `"prefer Premium over Standard"`. States a real replacement, but *also* names the
   rejected value in the same sentence.

**Why case 3 needed its own function** — `apply_answer`'s substring/fragment matching
has no concept of negation. Fed the raw sentence `"I don't want Standard, use
Premium"`, it can resolve to `"Standard"` (the rejected value) just as readily as
`"Premium"` (the wanted one), because both are real catalog option names present in
the text — confirmed live. `_extract_replacement_clause` exists purely to strip the
rejected value out of the text *before* it ever reaches `apply_answer`.

**How `_extract_replacement_clause` works**, step by step:
1. `_REPLACEMENT_CUE_RE` searches for the first occurrence of a cue word
   (`use`/`instead`/`prefer`/`rather`) and captures everything after it as group 1 —
   the assumption being the wanted value is stated *after* the cue.
2. `_CONTRAST_CUT_RE` then searches that captured clause for a trailing contrastive
   word (`over`/`than`/`instead of`/`rather than`/`not`) and truncates the clause right
   before it — so `"Premium over Standard"` → `"Premium"`.
3. Returns `None` if no cue is found at all (caller falls back to matching the raw
   sentence — i.e. case 2's plain-value path).

**Call site** (STEP 6, pending-change-value branch, `ask_api.py`, inside the
`_pcnv_attr` handling block):
```python
_pcnv_match_text = _extract_replacement_clause(req.question) or req.question
# ... apply_answer / apply_multi_answer against _pcnv_match_text, constrained by
# _pcnv_constrained (re-derived active constraint set, wrapped in try/except so a
# pure decline never crashes on an unrelated constraint-engine failure) ...
if not _pcnv_matched and _is_change_value_decline(req.question):
    # only treated as a decline if NO real value could be extracted/matched first —
    # a stated replacement always wins over decline phrasing.
    ...
```
Order matters: the code tries to resolve a real value **first**; only if that fails
does it check `_is_change_value_decline`. This is what lets `"I don't want Standard,
use Premium"` resolve to `"Premium"` instead of being misread as a cancellation.

**Bug history on this exact function (chronological — all confirmed live, all in
`docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md`)**:

| § | Bug | Fix | Status |
|---|---|---|---|
| §10 | No decline detector existed at all — "I don't want to change product" fell straight into `apply_answer` as an attempted (failing) value. | Added `_is_change_value_decline`. | ✅ Fixed |
| §10 | Retry after a failed match fell back to the full unfiltered catalog (e.g. 328 cross-family options), not the originally-scoped list. | Added `constrained_item_values` threading through `_handle_cascade`. | ✅ Fixed |
| §12 | `apply_answer("I don't want Standard, use Premium")` resolved to `"Standard"` (the rejected value). | Added `_extract_replacement_clause` — match only the clause after a correction cue. | ✅ Fixed |
| §15 | `"prefer Premium over Standard"` / `"rather Premium than Standard"` still resolved to `"Standard"` — the cue clause captured `"Premium over Standard"`, which still contained the rejected value. | Added `_CONTRAST_CUT_RE` to trim at a trailing contrastive word. | ✅ Fixed |
| §15 | A pure decline crashed if constraint re-evaluation itself raised for an unrelated reason. | Wrapped `_pcnv_constrained` computation in try/except, falls back to unconstrained. | ✅ Fixed |
| §18 | **Reversed phrasing** — `"instead of Standard, prefer Premium"` matched on the leftmost cue word (`"instead"`), capturing `"of Standard, prefer Premium"` — no trailing contrastive word in *that* clause, so nothing got trimmed and `"Standard"` leaked through. | Author's fix (commit `6118c72`): excluded `"instead of"` from the cue match via `instead(?!\s+of)` — lets the regex continue scanning forward to the real cue (`"prefer"`). | ✅ Fixed, shipped |
| — | **Still open, reported, not yet fixed**: `"rather than X"` is the exact same construction as `"instead of X"` (X rejected, real replacement stated elsewhere) but has no matching exclusion — `rather` still matches unconditionally. `"rather than Standard, prefer Premium"` returns `None` (not a leak, but a failed extraction — `_CONTRAST_CUT_RE` cuts the captured `"than Standard, prefer Premium"` clause down to an empty string), which sends the caller back to matching the **raw sentence**, reintroducing the original leak risk via the fallback path. | Proposed, posted as a PR comment, not yet applied: add `rather(?!\s+than)` symmetric to the shipped `instead(?!\s+of)` — i.e. `r"\b(?:use|instead(?!\s+of)|prefer|rather(?!\s+than))\b\s*[:,]?\s*(.+)$"`. Verified standalone against all known cases (both reversed forms, both bare forms, both trailing-contrast forms) — no regressions. | ❌ **Open** |

**Verification note**: this whole area could not be run against the full test suite in
this checkout — `tests/test_cpq_llm_first_cutover_regression.py` and friends fail to
even collect (`ModuleNotFoundError: No module named 'falkordb'` / `psycopg` native
driver missing on this machine). Every claim above about specific input→output behavior
was verified by extracting the regex definitions and running them standalone in a bare
Python interpreter, not via the project's pytest suite. Re-verify with the real suite
before relying on this table if the environment gets fixed.

---

## 5. Script-backed rules: the BML tier system (deterministic-first)

**`src/aryx/cpq/bml.py`** (1,595 lines) — interprets "BigMachines Markup Language" rule
scripts pulled via `rdb.fetch_function_scripts`.

- **Tier 1** (default, always tried first): `_parse_branches` — a strict structural
  parser for flat if/else-if/else chains of literal-equality comparisons.
  `_TIER1_BLOCKERS` regex rejects anything with loops, `util.` calls, or nested `if`s —
  those scripts are punted, not guessed at.
- **Tier 1.5**: `evaluate_constant_return` — for scripts with no branching at all,
  whose return value is provably a literal-only concatenation.
- **Tier 2** (LLM fallback): only reached if Tier 1/1.5 genuinely can't resolve the
  script **and** the feature flag `bml_use_llm` is enabled (config default: **False**).
  Even when enabled, Tier 2 is deliberately skipped if the blocker is a missing
  variable value rather than script complexity ("the LLM has no more information than
  we do").
- **`parse_array_iteration`** — the array/grid-iteration parser reused by the ingestion
  pipeline's FK-detection pass (§2.2) — the one piece of code shared between ingestion
  and live serving.
- **Caching**: process-wide `_SHARED_SCRIPT_CACHE` module dict, capped at 20,000
  entries (full clear on overflow, not LRU), keyed by
  `(kind, workspace_id, catalog_prefix, script_hash, relevant_variable_frozenset)` — not
  persisted across process restarts.

**Determinism implication**: with the default config (`bml_use_llm=False`), every rule
evaluation is 100% deterministic Python. Enabling Tier 2 introduces LLM variance (no
temperature=0, no seed pinning) bounded to exactly the scripts Tier 1/1.5 can't parse.

---

## 6. Deterministic validation — how rules and the final BOM are checked

Two distinct validation layers exist: one that gates a **live** `confirm`, and one
**offline oracle** used only in tests.

### 6.1 Live gate: `src/aryx/cpq/bom_gate.py` (161 lines)

Called at STEP 8 as `validate_before_payload(engine, attrs, session, con_rules,
bml_eval)`. Three distinct outcomes, deliberately handled differently:

1. **Provenance failure** (`check_provenance`) — an invented/hallucinated value with no
   catalog or utterance backing. Hard-fails; no payload emitted.
2. **Stale constraint violation** (`recheck_constraints` →
   `StaleConstraintViolation`) — a value that was valid when set but a *later*
   selection has since narrowed its allowed set. **Not** hard-failed — the caller
   auto-clears just the invalid item(s) (multi-select: filters down to the still-valid
   subset, per PR #134's fix) and re-asks, since the engine knows the value is wrong
   but can't guess the replacement.
3. **Rule conflict** — two active constraints intersect to a genuinely empty allowed
   set. Reported as an explicit conflict message; nothing is mutated (there's no
   productive value to ask for).
4. **Unexpected exception during recheck** — hard-fails (fail-closed), never silently
   treated as "no violations found."

`recheck_constraints` checks **both** `session.filled` (single-select) and
`session.filled_multi` (multi-select) against the freshly recomputed
`apply_constraint_rules` result — a gap that PR #134 specifically closed.

### 6.2 Offline oracle: `src/aryx/cpq/validation/` (test-only, not wired into serving)

A parallel, pure-function reimplementation of rule semantics, used to prove the live
engine's rule loop converges correctly against real ingested catalogs — **never called
from `ask_api.py` or `engine.py`**, only from the test suite.

| File | Role |
|---|---|
| `models.py` | `ValidationIssue`, `Scenario`, `RuleEvaluation`, `EvaluationResult` — typed result shapes. |
| `oracle.py` | `DeterministicRuleOracle` — the reference implementation. |
| `transitions.py` | `apply_constraints`, `apply_recommendations`, `auto_fill` — oracle-side reimplementations mirroring the live engine's own logic, for cross-checking. |
| `runner.py` | `evaluate_to_fixed_point` — fixed-point iterator with cycle detection. |
| `conditions.py`, `constraint_phase.py` | Declarative-condition and constraint-phase evaluation helpers. |
| `compare.py` | Diffs oracle output against live-engine output. |
| `production.py` | Runs the oracle against production-shaped scenario data. |
| `scenarios.py`, `scenario_support.py` | Generates test scenarios from real catalog data. |
| `script_oracle.py` | Oracle-side BML script evaluation (mirrors `bml.py`'s Tier 1). |
| `trace.py`, `report.py` | Execution tracing and human-readable reporting for test output. |

---

## 7. Supporting/cross-cutting modules

| File | Role |
|---|---|
| **`state.py`** (538 lines) | `CpqSession` — the entire per-conversation state (filled values, multi-select values, display labels, per-value provenance, pending anchors/queues, product-switch snapshots, `last_qa_variable` recency signal). Fully JSON round-tripped through the client every turn — **no server-side session store**. Also defines `ConfigAttr`, `HidingRule`, `RecommendationRule`, `ConstraintRule`, `MenuOption`. |
| **`session_guard.py`** (325 lines) | Conversational-invariant enforcement: `push_snapshot`/`restore_last_snapshot` (the undo stack — every mutating action must snapshot first), `detect_undo`, `detect_guided_mode_accept`, `assert_conversational_invariant`/`enforce_conversational_invariant` (structural sanity checks on the response before it's returned), clarify-streak tracking (`note_clarify`/`clear_clarify`/`should_force_numbered_options`). |
| **`summary_guard.py`** (110 lines) | `fields_missing_from_summary` — validates the LLM-narrated customer-facing summary against the **curated** field set the narration prompt was actually built from (not the raw superset of ~170 internal BM fields) — this exact mismatch was PR #134's-era Issue #5 (the "raw-dump fallback" bug). `validate_or_fallback` orchestrates narration → validate → deterministic-bullet fallback → raw-table last resort. |
| **`logging_context.py`** (69 lines) | `set_run_id`/`get_run_id`, `RunIdLogFilter` — stamps every log line for a turn with a `run_id` (UUID per quote) for lifecycle tracing across the whole rule-evaluation loop. |
| **`rdb.py`** (760 lines) | See §2.4 — the generic-storage-to-relational-shape abstraction. |
| **`__init__.py`** | Public exports: `CpqEngine`, `CpqSession`, `ConfigAttr`, `HidingRule`, `MenuOption`. |

---

## 8. Consumers outside `src/aryx/cpq/` and `ask_api.py`

| File | Role |
|---|---|
| `src/aryx/api/share_config_api.py` | Serializes/deserializes a CPQ session for the "share this config" link feature — payload-shape-agnostic per `fix/share-config-payload-shape-agnostic`. |
| `src/aryx/api/ssrf_guard.py` | General SSRF protection; CPQ-relevant only insofar as it guards any outbound URL CPQ flows might touch. |
| `src/aryx/config.py` | `get_settings()` — the single source for every CPQ feature flag mentioned in this doc: `bml_use_llm`, `cpq_intent_mode`, `cpq_intent_gemini_model`, `cpq_intent_timeout_s`. |
| `src/aryx/graph/falkor_store.py`, `oracle_graph_store.py`, `reader.py`, `retrieve.py` | Graph projection/read layer — CPQ's rule/attribute relationships are graph edges here; also used by the generic Ask/RAG path for STEP 7's contextual Q&A. |
| `src/aryx/llm_normalize.py` | Shared JSON-envelope normalization for any LLM JSON response (BML Tier 2, gateway responses, summary narration) — absorbs provider quirks like a single-item-list wrapper around a flat object. |
| `src/aryx/pipeline/doc_discovery.py` | See §2.2 — ingestion-side CPQ/BM heuristics. |
| `src/aryx/project.py` | `project_graph()` — the FalkorDB projection step ingestion ends on. |
| `src/aryx/store/ask_thread_store.py` | Persists Ask conversation history (including CPQ turns) for thread continuity, distinct from `CpqSession`'s own client-round-tripped state. |
| `src/aryx/ui/api.py`, `src/aryx/ui/ask_panel.py` | The Streamlit desktop UI's own thin wrapper around `/ask` for manual CPQ testing. |

---

## 9. End-to-end sequence, condensed

```
1. Offline: BM/Oracle CPQ XML export
      → discover() (extract/clean/land)
      → resolve_run() → aryx_entity rows (ontology_type = catalog-prefixed BM concept)
      → project_graph() → FalkorDB projection
   (doc_discovery.py applies BM-aware schema heuristics + reuses bml.parse_array_iteration for FK detection)

2. Online, per POST /ask:
   run_ask()
     ├─ live session? → _run_cpq_turn() directly
     ├─ hard_off_topic? → standard Ask pipeline (no LLM)
     └─ else: classify_ask_route() [intent_gateway] (mode-gated: llm_first / shadow / deterministic_first)
             → _route_quote / _route_qa / _route_ambiguous / standard Ask pipeline

3. Inside a CPQ turn (_run_cpq_turn_inner, STEP 1-8):
   STEP1 anchor (product/country) → STEP2 resolve product
     → STEP3 rule loop (CpqEngine.evaluate_rules_loop: hide→auto_fill→recommend→constrain,
             BmlEvaluator Tier1/1.5 deterministic, Tier2 LLM only if bml_use_llm=True)
     → STEP4 render next question OR STEP5 lock prior answer OR STEP6 cascade (change request,
             intent_gateway.classify_intent / narrow _llm_classify_* fallbacks only on regex-miss,
             mutating intents require deterministic agreement)
     → STEP7 contextual Q&A (resumes config state after) 
     → STEP8 on "confirm": bom_gate.validate_before_payload()
             (provenance hard-fail | stale-constraint auto-clear+reask | rule-conflict report | pass)
     → build_payload() → BOM payload returned to client

4. Narration: summary_guard validates the LLM-narrated summary against the curated
   field set; falls back to a deterministic bullet render, then a raw table, if the
   LLM output can't be validated.
```

---

## 10. Where non-determinism can enter (and how it's bounded)

| Source | Default state | Bound |
|---|---|---|
| BML Tier 2 (script fallback) | **Off** (`bml_use_llm=False`) | Only reached if Tier 1/1.5 structurally fail; JSON-shape validated, not semantically re-verified; no temperature/seed pinning when on. |
| Intent gateway (`classify_ask_route`/`classify_intent`) | **`shadow`** mode — observes only, doesn't decide | Candidate-indexed selection only (never free text); quarantine validation (candidate-membership + verbatim evidence span); mutating intents require deterministic agreement. |
| Narrow `_llm_classify_*` fallbacks in `ask_api.py` (decline detection, compound-question split, is-CPQ-question gate) | Fallback tier only, after regex miss | Same never-guess/validate-against-real-options discipline. |
| Summary narration (`_cpq_summary_text`) | Always LLM | Cosmetic only — never affects `filled`/`filled_multi`/payload; validated against curated fields, falls back deterministically. |

Everything else — rule loading, the rule loop's fixed-point convergence, auto-fill
priority, answer matching, payload assembly, the BOM gate — is plain, reproducible
Python and SQL.
