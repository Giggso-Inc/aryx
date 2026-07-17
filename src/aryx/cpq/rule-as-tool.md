# CPQ Rule-as-Tool Flow — Consolidated Plan

Consolidates four design/analysis rounds into one plan: rule extraction (see
`CPQ_APX_NEXT_RULE_CATALOG.md`), the rule-tool unification design, multi-catalog
scoping, and the (separate, already-diagnosed) payload-serialization bug.

## 1. Where rule-tools already fire today (no new orchestration needed)

The per-turn flow in `ask_api.py` already has exactly one firing point for
rule evaluation, and this plan upgrades what happens INSIDE it — it does not
add a new step to the turn loop:

- **STEP 3** (`ask_api.py:864-880`, first turn and every configuring turn):
  `evaluate_rules_loop()` runs hiding → recommendation → constraint rules
  against `session.filled`, then `auto_fill()` picks the next `pending`
  attribute to ask about. Rules fire **before** the next question is
  formulated — this is the actual "fire the rule before answering/asking"
  point the plan targets.
- **STEP 6** (cascade, `ask_api.py:357`): any answer change re-runs the same
  `evaluate_rules_loop()` so dependents re-resolve.
- **STEP 7** (Q&A interrupt): does NOT re-run the rule loop — a side question
  is answered from the graph without touching `filled`, so rule state is
  undisturbed. Rule-tools stay scoped to configuration turns, not Q&A turns.
- **Activation on ingestion**: rules load lazily per-turn straight from the
  RDB/graph (`load_hiding_rules`, `load_recommendation_and_constraint_rules`,
  `build_bml_evaluator`), scoped by `catalog_prefix`. A newly-ingested XML's
  rules become usable the moment `resolve_product_hint()` matches a
  conversation to its `catalog_prefix` — **no separate activation step**.

**Implication for the rule_tool unification (items 1-2 below)**: it must stay
a pure, stateless function of `(attrs, filled, rules)` — same contract
`evaluate_rules_loop`/`apply_*` already have — because it will be called
fresh on every turn AND every cascade, not once per session.

## 2. Action plan

| # | Action | Owner | File |
|---|---|---|---|
| 1 | Generalize `bml._parse_condition`/`_first_matching_branch` to accept condition tuples sourced from `bm_config_rule_input` (not just parsed script text) — one AND/OR evaluator for both declarative multi-input and script conditions | Kelsey | [bml.py](../src/aryx/cpq/bml.py) |
| 2 | Add `RecommendationRule.script` + a `apply_recommendation_rules` BML hookup mirroring `apply_constraint_rules`, gated "unknown → no fill" | Kelsey | [state.py](../src/aryx/cpq/state.py), [engine.py](../src/aryx/cpq/engine.py) |
| 3 | Change `inputs_by_rule` from dict-overwrite to list; wire `rule_input_index`/operator into the AND/OR chain | Ravi | [engine.py:1198](../src/aryx/cpq/engine.py#L1198), [rdb.py](../src/aryx/cpq/rdb.py) |
| 4 | Fold `bm_config_rule_input_action` rows in as extra declared dependency edges (widen `referenced_variables`) | Ravi | rdb.py, bml.py |
| 5 | Every new script-recommendation auto-fill logs to `cascade_log`, never overwrites an existing value | Kelsey | engine.py |
| 6 | Shadow-mode diff of the fixed loader against real historical APX Next quotes before flipping live — prioritize model-selection, country/FEDERAL, and package/promotion paths (where dropped conditions cluster) | Meera | — |
| 7 | Thread `catalog_prefix` through the new unified evaluator (item 1) and recommendation hookup (item 2) — key any shared cache by `(workspace_id, catalog_prefix, ...)`, matching `BmlEvaluator`'s existing convention | Kelsey | bml.py |
| 8 | Replace fuzzy substring family-name matching with an explicit `catalog_prefix → canonical product name` manifest once 3+ XML files share a workspace | Ravi | engine.py (`_match_family_name`) |
| 9 | Ingestion-time assertion: reject/flag an XML whose derived `catalog_prefix` already exists in that workspace under a different source file | Ravi | ingestion pipeline (`rest_ingest_api.py`/`doc_router.py`) |
| 10 | Keep the unified evaluator (item 1) a pure function of `(attrs, filled, rules)` — no session mutation inside it — since STEP 3/6 call it fresh every turn and every cascade | Kelsey | engine.py |

## 3. Gaps if this is implemented as-is

- **Shadow-mode risk (item 6) is not optional.** Fixing item 1/3 changes 220
  of 348 declarative rules' firing behavior (63%) — see catalog addendum.
  This is a behavior change on a live, tuned configurator, not a pure bug fix.
- **444 script-backed recommendations (item 2) are only ~1.4% directly
  portable.** ~438/444 use loops/`dict()`/`recordset()`/`util.` calls the
  Tier-1 evaluator cannot parse. Item 2 closes the mechanism (the hookup);
  it does NOT by itself make all 444 fire — that needs either Tier-2 LLM
  (cost/latency/non-determinism, off by default) or hand-porting the
  highest-frequency targets (see catalog addendum's top-15 table).
- **Fuzzy catalog matching (item 8) degrades, not fails, as N grows** —
  more ingested XML files raise the odds of a substring collision pushing
  `_scope_to_catalog` into its "ambiguous → load all" fallback, which is
  the exact cross-catalog mixing this whole mechanism prevents. Needs the
  explicit manifest before scaling past a handful of catalogs.
- **No event-driven/reactive dispatch** — deliberately rejected (cycle
  detection cost not justified given the bounded per-turn loop already
  terminates). Rule-tools stay indexed by declared input set but still
  evaluated inside the existing STEP 3/6 loop, not on an independent trigger.

## 4. Multi-select / payload-serialization issue — separate track, NOT fixed by this plan

Diagnosed separately (andie-jr pass, this session): 17 CPQ API rejection
errors split into:
- 4 already fixed by the **uncommitted** `build_payload` diff (`hide_in_trans`
  exclusion + `select_type=="boolean"` serialization) — needs committing.
- 13 (`itemTypeVX650_astro` + 12 generic "invalid payload" attrs) — all
  `select_type=="multi"` per `classify_select_type`, but their answers were
  written to `session.filled` (string) instead of `session.filled_multi`
  (array) upstream of `build_payload`. Fix: gate every answer-write site in
  `engine.py` on `select_type=="multi"`.

**This is orthogonal to the rule_tool plan.** Rule-tools decide *which value*
an attribute may take; `build_payload`/answer-application decide *how an
already-chosen value is serialized*. Closing items 1-10 above will not fix
the 13 multi-select payload errors, and fixing the multi-select bug will not
change rule-firing behavior. Track and ship independently.

## 5. Multi-XML confirmation — one correction to the "compile rules per file" framing

The request to validate: "extract all rules per file, prefixed by file,
compiled into one per file/product, checked against on every query/quote."

**Mostly already true, one correction:** rules are NOT merged/compiled into
a single blob per file today, and should not be — they are loaded fresh,
scoped by `catalog_prefix`, straight from the RDB/graph on every turn
(`load_hiding_rules`/`load_recommendation_and_constraint_rules`/
`build_bml_evaluator`, all catalog_prefix-scoped). "Compiling per file" as a
*batch pre-merge step* isn't needed — the scoping IS the compilation
boundary; a query for product A never sees product B's rules regardless of
how many XML files share the workspace (items 7-9 harden this further).

**Where a real "compile once" optimization DOES fit** (proposed, not yet
planned): the codebase already has the pattern (`_FLAG_KEYWORD_INDEX_CACHE`,
`_SHARED_SCRIPT_CACHE`) — a process-wide cache keyed by
`(workspace_id, catalog_prefix)`. Today it's warmed lazily on first query.
If ingestion-to-first-query latency matters, the SAME cache could instead be
warmed once at ingestion completion (a "compile this catalog's rule set"
step run right after ingestion, not per-turn) — a performance optimization,
not a correctness requirement. Add as item 11 if latency is a real concern;
skip if current lazy-load performance is acceptable.

**Confirmed already covered — both quote-generation paths:**
- **Single-query** ("quote me an APX Next 5G radio for a US federal
  customer"): STEP 1/2 (anchor resolution) → STEP 3 (rule eval + auto_fill)
  all run in the SAME turn against every hint extracted from the one
  message. If everything resolves, the turn goes straight to the review
  summary — no multi-turn requirement, same code path as conversational.
- **Conversational** (multi-turn): STEP 3 re-runs every turn (`ask_api.py:864`)
  and again on any cascade (STEP 6, `ask_api.py:357`).
- **Change before final payload**: a change requested WHILE in
  `awaiting_approval` review (`ask_api.py:707-714`) routes through the SAME
  `_handle_cascade` used mid-configuration — the full rule loop re-runs and
  re-verifies before the user sees the review again. Nothing reaches
  `build_payload` without having passed through rule evaluation on its most
  recent change. This is already correct; item 1-3 fixes improve WHAT that
  evaluation catches, not whether it runs.

## 6. Conversational Chat UI Enhancement — separate track, not rule_tool scope

Requested: structured/scannable output (Product Name · Service Plan ·
Quantity & Duration · Associated Options · quote-creation confirmation)
instead of the current paragraph.

**Current state**: `_cpq_summary_text` (`ask_api.py:200`) explicitly
instructs the LLM to "Write ONE flowing paragraph... No lists, no markdown,
no headings" — this is a deliberate, existing design choice, not an
accident. A deterministic bullet renderer already exists
(`CpqEngine.render_filled_summary`, `engine.py:3095`) but is used ONLY as a
fallback when the LLM call fails.

**Proposal**: make the structured format the primary path instead of the
fallback — either (a) drop the LLM narration for the summary step and use
`render_filled_summary`-style output directly, grouped under the requested
headings, or (b) rewrite `_cpq_summary_text`'s prompt to require the same
grouped-bullet structure instead of flowing prose. Both are prompt/rendering
changes confined to `ask_api.py`/`engine.py`'s summary layer.

**This is orthogonal to the rule_tool plan and to the payload bug** — same
reasoning as §4: this changes how an already-resolved configuration is
*displayed*, not which values are valid or how they're serialized to the
API. Track and ship independently; no shared code path with items 1-10.