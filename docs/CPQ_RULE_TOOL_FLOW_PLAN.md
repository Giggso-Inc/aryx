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

## 7. Traced example: "Quote APX Next Enhanced radios for a US customer"

Walked against the REAL extracted catalog (not hypothetical) to sanity-check
the plan. Found a concrete, live inconsistency plus one new gap.

- `"APX Next Enhanced"` direct-matches a real `productSelectionProduct_all`
  option (`item_value='APX NEXT ENHANCED'`) via `extract_catalog_hints` — sets
  cleanly on turn 1.
- `"US customer"` → `ultimateDestinationCountry='US'` → region `NA` (confirmed
  real option, confirmed `_COUNTRY_TO_REGION` mapping).
- Hiding rules ("Hide Product if Country is Blank", "Hide HW Version unless
  NA or fed portables") both pass — `hWVersion_astro` stays visible.
- **But** the recommendation rule "Default hardware version for APX Next"
  fires on `region==NA` and auto-fills `hWVersion_astro` = `NEXT STANDARD LTE
  ONLY` (the 4G-only option) — NOT the 5G/Enhanced one. Nothing in the
  catalog sets `hWVersion` FROM the product-name hint in the other direction.
  **Net: today this produces product="APX NEXT ENHANCED" + hardware="4G LTE
  Only" in the same quote — an internally inconsistent result the current
  rules never catch.**
- The one rule that looks like it should catch this cross-check
  ("Constrain Product LOVs for APX NEXT BOM model", condition
  `hWVersion_astro`, operator `3`, value `""`) is confirmed **dead today** —
  same pattern as the 101 dead rules in §Gap Deep-Dive: an empty condition
  value can never match under the live equality-only evaluator, so this
  never fires and catches nothing.
- The reverse-direction script ("Default APX Next Enhanced based on HW
  version") IS Tier-1-simple (`if(hWVersion_astro=="NEXT ENHANCED LTE PLUS
  5G"){returnVal="APX NEXT ENHANCED";}`) — a genuine quick win for item 2,
  but wiring it alone is not sufficient: it only fires once `hWVersion` is
  already the 5G option, which nothing currently sets from the product-name
  hint.

**New item 12** (adds to §2): NL hint extraction has no "stated product
variant implies its driving attribute" reconciliation. When a customer names
a variant that is the documented OUTPUT of a (possibly currently-skipped)
recommendation script, the engine should bias/ask the INPUT attribute toward
the value that produces it, or at minimum flag the conflict instead of
silently defaulting past it. Owner: Meera (confirm intended UX) + Kelsey
(implement once confirmed).

**Q2 answer** ("what values are available for the hardware versions for APX
NEXT?") — routes through the `detect_attr_query` fast path (no rule
evaluation, just real menu options), unaffected by any of the above:
`hWVersion_astro` → `APX NEXT (4G LTE+5G)` (`NEXT ENHANCED LTE PLUS 5G`) and
`APX NEXT (4G LTE Only)` (`NEXT STANDARD LTE ONLY`). Not required, not
hidden, no default — correct today and after the plan, no gap here.

## 8. Q1 final payload — validated by RUNNING the real engine, not reimplementing it

Rather than hand-simulate the rule cascade, the actual `CpqEngine` classes
(`state.py`/`engine.py`/`bml.py`) were imported and executed directly against
`ConfigAttr`/`HidingRule`/`RecommendationRule`/`ConstraintRule` objects built
straight from `APX_Next_config.xml` (`evaluate_rules_loop` → `auto_fill` →
`build_payload`, the exact production call chain, `bml_use_llm=False`
matching the real default). Only dependency installed: `pydantic`/
`pydantic-settings` (no DB/graph — those methods were bypassed by
constructing the rule objects directly from the parsed XML instead of via
`get_cpq_rdb()`). One known simulation gap: `load_product_config`'s
`_NOISE_VAR_FRAGMENTS`/`_NOISE_ITEM_FRAGMENTS` filtering was replicated by
hand (confirmed correct — dropped `testPager`/`testPager2` as the real
loader would).

**Result: 0 pending questions — this resolves in a single turn.** And it
**empirically confirms** the §7 finding: `productSelectionProduct_all` =
`APX NEXT ENHANCED` (hint) while `hWVersion_astro` = `NEXT STANDARD LTE ONLY`
(rule) — the exact "Enhanced" product paired with the non-Enhanced hardware,
now proven by running the real code, not predicted.

```json
{
  "configAttributes": {
    "productSelectionProduct_all": {"value": "APX NEXT ENHANCED"},
    "hWVersion_astro": {"value": "NEXT STANDARD LTE ONLY"},
    "ultimateDestinationCountry": {"value": "US"},
    "modelSelectionRegion_astro": {"value": "NA (not in payload - country_derived, cascade-only)"},
    "batteryType_astro": {"value": "STANDARD"},
    "antennasType_astro": {"value": "WHIP APX NEXT"},
    "modelSelectionHousing_astro": {"value": "BLACK"},
    "beltClipType_astro": {"value": "2.0 INCH / 5.08 CM (STANDARD)"},
    "multikeyType_astro": {"value": "MULTIKEY"},
    "checkProvAgencises_astro": {"value": true},
    "packageTypeBundles_astro": {"value": ["CORE BUNDLE"]},
    "provisioningAssistance_astro": {"value": ["INCLUDE ASSISTANCE"]},
    "...": "full 84-attribute payload in q1_final_payload.json (scratchpad)"
  }
}
```

Confirms correct handling of the payload bug fixes too: `hide_in_trans=1`
attrs (`productInformationText_astro`, `productSelectionHelptext_astro`)
are correctly EXCLUDED; `checkProvAgencises_astro` (boolean) is correctly a
native JSON `true`, not the string `"true"`; `packageTypeBundles_astro`/
`provisioningAssistance_astro` (multi-select) are correctly arrays.

## 9. No product/no country in the question — confirmed correct, not a gap

`ask_api.py` STEP 1 is a sequential, blocking anchor gate: no product →
asks for the product family (lists real ingested families via
`list_ingested_families`, never guesses); product given but no country →
asks for destination country next. Only once BOTH are set does STEP 2
(`load_product_config`) and the rule loop even run. This is deliberate
(D1/D2 "never guess" doctrine) and confirmed working as designed — no fix
needed here.

## 10. Five different products in one session — CONFIRMED GAP (5 Whys)

**Symptom**: asked whether quoting 5 different products (from 5 different
ingested XML files) inside ONE ongoing session produces 5 quotes, or the
first product sticks and the rest cross-reference into it.

- **Why 1** — the quote only ever configures the first product mentioned →
  Because STEP 1's product-detection gate is `if not session.product_name:`
  — it only runs while that field is empty.
- **Why 2** — why does `session.product_name` never go back to empty? →
  Because nothing in `ask_api.py` or `engine.py` ever resets it; confirmed
  by grep — the only `CpqSession()` (fresh, empty) construction in the
  entire file is the initial no-session-data fallback (`ask_api.py:529`).
- **Why 3** — why is there no reset trigger? → Because `detect_change_request`
  (STEP 6, the only "modify something" intent detector) is scoped to
  attributes already in the CURRENT product's `filled` dict — it has no
  concept of "this is now a different product," only "change this
  attribute's value."
- **Why 4** — why wasn't a product-switch case handled? → `CpqSession` was
  designed as one-session-one-product from the start (`product_name`/
  `product_entity_id` are singular fields, not a list) — multi-product
  quoting was never in scope for the session model.
- **ROOT CAUSE**: the session schema itself has no concept of more than one
  product. A later product mention in the same session is not detected,
  not routed, and not configured — it is silently ignored, and any of its
  option-text could in principle stray-match an attribute in the FIRST
  product's own catalog if the text happens to coincide (low-probability
  but real, given `extract_catalog_hints` runs against whatever `attrs`
  STEP 2 already loaded for the original product).

**Countermeasure (proposed)**:
1. Add explicit "new quote" / "different product" intent detection
   (parallel to `detect_change_request`) that, when a DIFFERENT product
   family is named mid-session, prompts for confirmation ("Start a new
   quote for {new product} instead of continuing {current product}?") —
   never guesses whether the user meant to switch or misspoke.
2. On confirmed switch: reset `product_name`, `product_entity_id`,
   `filled`, `filled_multi`, `display_filled`, `filled_source`,
   `pending_variables`, `status`, `negated_vns`, `cascade_log` — everything
   product-scoped — while keeping `country` (a customer-level fact, not
   product-level, per D1).
3. **For running 5 quotes truly in parallel** (not sequential switches):
   recommend the CLIENT hold 5 separate `session_data` objects (5
   conversations) rather than extending `CpqSession` to hold a list of
   products — confirmed via §7-8's catalog_prefix scoping that this already
   works cleanly today with zero cross-contamination; multiplexing
   products inside one session schema is a bigger, riskier change for a
   need the client can already meet.

**Verification signal**: shadow-test a scripted 2-product conversation
(mention product A, complete it, mention product B) against today's code —
confirm product B is currently silently dropped, then confirm the fix
prompts for the switch instead.
**Rollback trigger**: if the new-product-detection heuristic false-positives
on a legitimate same-product attribute answer (e.g., an option value that
coincidentally names another ingested product), revert to requiring an
explicit "new quote" phrase rather than inferring it from a bare product
mention.

## 11. Logging design — RUN ID, for the rule-tool + Ask/CPQ flow

**Current state** (confirmed by inspection): `engine.py`/`bml.py`/`ask_api.py`
all use plain `logging.getLogger(__name__)` with ad-hoc `"cpq: ..."`-prefixed
messages (e.g. `"cpq: loaded %d hiding rules (...)"`) — no correlation id of
any kind. A `run_id` concept DOES exist elsewhere in the codebase (the ETL
pipeline's `insert_run.sql`/`finish_run.sql`/`resolution/run.py`), but that's
a separate ingestion-run tracking table — unrelated to, and not reusable
for, a conversational Ask/CPQ turn.

**Proposed scheme**:
- **One `run_id` per CpqSession, not per turn.** Minted once (`uuid4` hex)
  the moment a fresh `CpqSession()` is created (`ask_api.py:529`), stored as
  a new `CpqSession.run_id` field, echoed back in `session_data` every turn
  like every other session field — so it survives across the whole
  conversation and traces one quote's entire lifecycle (anchor gate →
  rule cascade → cascades → approval → payload), not just one request.
- **Thread it via `contextvars`, not function-parameter drilling.** A
  `run_id_var: ContextVar[str]` set once at the top of the `ask_api` request
  handler; a `logging.Filter` injects `record.run_id` from it. Every
  existing `logger.info("cpq: ...")` call needs zero signature changes —
  only the log FORMAT gains `%(run_id)s`. Avoids the invasive alternative
  of passing `run_id` through every `CpqEngine` method (`evaluate_rules_loop`,
  `apply_hiding_rules`, `auto_fill`, ...), which are also called from tests
  without a request context.
- **Format**: structured (`extra={"run_id": ..., "turn": session.turn,
  "catalog_prefix": ..., "workspace_id": ...}`), JSON-renderable — matches
  the "traceable, leveled, no secrets" bar implied by "proper logging."
  Never log full `filled`/`session.to_dict()` at INFO (PII/commerce data);
  DEBUG only, and only field names changed, not full customer values, at
  INFO (mirrors the existing `"cpq: recommendation rules auto-filled %s"`
  style — logs which KEYS changed already, not raw values).
- **Rule-tool-specific spans**: each rule bucket already logs a summary
  line (`"cpq: loaded %d hiding rules (...)"`, `"cpq: loaded %d
  recommendation rules, %d constraint rules (...)"`) — add `run_id` to
  those plus one NEW line per `evaluate_rules_loop` pass: which rule NAMES
  fired this turn (already partially present as `rule_messages` for hiding
  rules; extend the same pattern to recommendation/constraint fires) — this
  is the audit trail item 5 (recommendation cascade_log) already commits to
  in §2, now unified with `run_id` so a support engineer can grep one id
  and see the whole quote's rule-firing history.

## 12. Test scenarios — extends the EXISTING suite, not a new framework

`tests/test_cpq_e2e.py` already has 38 tests (`test_s1_...` through
`test_s37_...`, using the `truth`/`fake_rdb`/`apx_truth`/`apx_fake_rdb`
fixtures). New tests below follow the SAME `test_sNN_description` naming and
fixture convention — no new test framework needed.

| # | Scenario (from the request) | Test name (proposed) | Asserts |
|---|---|---|---|
| 1 | Single-query full quote — all necessary details in one message (e.g. "Quote APX Next Enhanced radios for a US customer") | `test_s38_single_query_full_quote_zero_pending` | `pending_variables == []` after turn 1; `cpq_payload` present; `run_id` set and stable |
| 2 | Missing necessary details — flow drops into conversational Q&A, offering available values | `test_s39_missing_details_falls_to_conversation_with_options` | product/country anchor gate fires (STEP 1) when absent; `next_question_prompt` lists real menu options, never an empty/guessed prompt |
| 3a | Quote generation via single query, straight to payload on the same turn | `test_s40_single_query_generates_payload_without_extra_turns` | same as #1, explicitly checks 0 intermediate `awaiting_approval` round-trips needed when nothing is ambiguous |
| 3b | Quote generation via multi-turn conversation, payload only after explicit confirm | `test_s41_conversational_quote_only_payload_after_confirm` | `cpq_payload is None` on every turn until `detect_approval()` fires; payload appears only on the confirm turn |
| 4 | RUN ID present and STABLE across an entire conversation | `test_s42_run_id_stable_across_turns_and_present_in_logs` | `session.run_id` unchanged turn 1→N; `caplog` (existing pattern, see `test_s5_script_rules_not_silently_dropped`) shows every `"cpq: ..."` line for that conversation carrying the same `run_id` |
| 5 | Change after confirm re-fires rule tools before final payload (ties to §7 cascade finding) | `test_s43_change_during_approval_reruns_rule_loop_before_payload` | `_handle_cascade` invoked from the `awaiting_approval` branch; payload reflects post-change constrained values, not stale ones |
| 6 | Gap regression guard (ties to §7/§8): Enhanced-hint vs region-default mismatch stays VISIBLE, not silently shipped | `test_s44_product_hint_hardware_version_conflict_flagged` | until item 12 (hint reconciliation) ships, this test documents current (inconsistent) behavior as an intentional xfail/known-gap marker, flips to a real assertion once fixed |

**Fixtures**: reuse `apx_truth`/`apx_fake_rdb` (already built against THIS
catalog per `test_s15_fk_compound_column_detection` etc.) rather than
authoring new fixture data — the real APX Next rule/attr shapes are already
wired in.

**Handoff**: this is now concrete enough to implement directly — either
ask me to write these tests into `tests/test_cpq_e2e.py` next, or route
through the `raven-test` skill (test-first discipline) if implementing
alongside the item 1-13 code changes rather than before them.

## 13. Generic/deterministic audit — what's ALREADY generic vs genuinely hardcoded

Checked every stage of ingestion→retrieval→rule-tool against "does this only
work for the 2 already-ingested catalogs, or any Nth ingested XML." Result:
mostly already generic, with two confirmed, self-documented exceptions.

**Category: Method (rule classification/retrieval logic) — GENERIC, confirmed**
- `catalog_prefix` derivation (`_catalog_prefix`) is a pure regex off
  `ontology_type` (`^(.*?)Bm[A-Z]`) — works for any PascalCase-prefixed type
  name a new ingestion produces, not tied to "ApxNextConfig"/"Sl3500EConfig"
  literally.
- Rule classification (hiding vs constraint vs recommendation) is by each
  action's `set_type`, NOT `rule_type` strings — this was DELIBERATELY
  built this way (`engine.py:1464-1483`) after confirming `rule_type` codes
  differ per catalog and can't be trusted generically.
- `resolve_product_hint`'s PRIMARY pass (family/catalog entity-name
  matching) is fully generic DB-driven matching — confirmed live working
  for products outside any hardcoded list (`"DGM 8500e"`, per its own
  docstring).

**Category: Measurement (LLM/token cost) — ALREADY MITIGATED, confirmed**
- `bml_use_llm` defaults to **False** — the Tier-2 LLM fallback for
  unparseable BML scripts is opt-in, not the default path. Token cost from
  "hardcoded retrieval forcing LLM guesses" is not currently happening —
  rule retrieval and product resolution are 100% deterministic (regex +
  DB lookups), never an LLM call. The only LLM calls in the CPQ path are
  the summary-narration prose (§6, display-only) and the opt-in BML Tier-2.

**Category: Material (data/field-name assumptions) — CONFIRMED HARDCODED**
- `_fetch_product_option_list` (`engine.py:843`) hardcodes the literal
  field name `"productSelectionProduct_all"` — **self-documented in its own
  docstring**: "Confirmed live: both currently-ingested catalogs... name
  this field `productSelectionProduct_all` — a different catalog using
  another convention would need this extended." A 3rd ingested XML naming
  its product-selection field differently gets ZERO options from this
  fallback pass (pass 1, family/catalog-name matching, is unaffected and
  still generic).

**Category: Machine (intent detection) — PARTIALLY HARDCODED, confirmed**
- `_CPQ_TRIGGER` (the regex that decides a question IS a CPQ request)
  bakes in family keywords (`apx|mototrbo|sl3500|dpx|xpr`) alongside
  generic verbs (`quote|configure|radio|bom|...`). A genuinely new product
  family whose name matches none of those AND whose question omits every
  generic verb would not trigger CPQ handling. Low real-world risk (generic
  verbs are almost always present) but not fully generic as written.

**Category: Machine (fast-path optimization) — INTENTIONAL, not a bug**
- `_PRODUCT_PATTERNS`/`_HINT_PATTERNS`' fixed regex list is a deliberate
  Priority-1 fast path (no DB round-trip) for the two known catalogs;
  `resolve_product_hint` is the generic Priority-2 fallback that covers
  everything else. This is a valid speed/genericity tradeoff already in
  place, not something to remove — flagged only for transparency.

**Category: Measurement (ingestion-time rule count) — MISSING, confirmed**
- No code anywhere (`rest_ingest_api.py`, `doc_router.py`, `rdb.py`)
  currently extracts or stores "N rules found for catalog X" at ingestion
  time — this is a genuinely new capability, not a hardcoding fix.

## 14. Fix plan for the confirmed gaps

| # | Gap | Fix | Impact |
|---|---|---|---|
| 14a | `productSelectionProduct_all` hardcoded field name | Resolve the product-selection field GENERICALLY: pick the config attr most likely to hold product-line variants by structural signal (e.g. highest-cardinality single-select attr among top-level, non-hidden attrs — same "structural, not name-list" principle already used by `_is_noise_var`), falling back to the literal name only if no better candidate is found | `engine.py` — touches only `_fetch_product_option_list`, isolated, no callers change |
| 14b | `_CPQ_TRIGGER` bakes in family keywords | Widen the generic-verb set OR (better) make CPQ-intent detection ALSO fire whenever `resolve_product_hint` finds ANY match across ingested catalogs — i.e., let real ingested data extend intent detection instead of a fixed keyword list | `engine.py` (`is_cpq_question`) — needs a DB round-trip only when the fast keyword check misses, so no added cost on the common path |
| 14c | No ingestion-time rule count | Add a summary step at the end of XML ingestion: count `bmconfigrule`/`bmconfigattr`/`bmfunction` rows just ingested for that `catalog_prefix`, log it (`run_id`-tagged per §11) and store as ingestion metadata (new small table or reuse the existing ETL `run` tracking pattern found in `resolution/run.py`) | `rest_ingest_api.py`/`doc_router.py` — additive only, no existing behavior changes |

## 15b. Payload type-shape audit — checked against the real CPQ API contract

The user supplied the real per-type CPQ payload contract (Boolean/Text/
Float/Integer/Date/Currency/Single-Select/Multi-Select/Array). Checked it
field-by-field against `build_payload()` and `classify_select_type()`.

**Confirmed: `classify_select_type` only has 3 buckets (single/multi/
boolean) — real data in THIS catalog needs at least 4 more.** Sampled real
attrs by `data_type` directly from the XML:

| data_type | Real example in this catalog | True type | Handled today? |
|---|---|---|---|
| 5 | `subscriptionStartDate`, `subscriptionEndDate` | **Date** | No — falls into "single", wrapped like a menu value |
| 7 | `solutionCategoryListPrice_astro` | **Currency/Price** | No — no currency-code companion field exists anywhere in the payload builder |
| 3 | `_configuration_id`, `promotionArrayController`, counters/IDs | **Integer** | No — same generic "single" fallback |
| 2 | `_BM_USER_EXCHANGE_RATE` | **Float** | No — same generic "single" fallback |

**Confirmed shape mismatches vs the real contract, even for the 3 types
that ARE distinguished today:**

| Type | Real contract | `build_payload` today | Verdict |
|---|---|---|---|
| Boolean | bare `"attr": true` (no wrapper) | `{"value": true}` | **Mismatch** — extra wrapper object |
| Text/Float/Integer/Date | bare `"Attr": "ABCD"` / `0.19` / `1` / `"01/18/2019"` (no wrapper) | `{"value": v}` | **Mismatch** for all four — currently uses the SAME wrapped shape as menu attrs |
| Currency | `{"value": 3.33, "currency": "USD"}` | `{"value": v}` (single string, no currency field at all) | **Mismatch** — currency code is never attached (likely sourced from `_BM_USER_CURRENCY`, already present in the payload as its own noise-filtered var, per §8's simulation output) |
| Single-Select Menu | `{"value": "5", "displayValue": "5 GHz"}` | `{"value": v}` (no `displayValue`) | **Mismatch** — not yet empirically confirmed as a rejection (no error seen for single-selects in the 17-error sample), but not spec-conformant |
| Multi-Select Menu | `{"items": [{"value":..,"displayValue":..}, ...]}` | `{"value": [...]}` (bare list of value strings) | **Confirmed mismatch, compounds the earlier multi-select bug**: even AFTER fixing the filled-vs-filled_multi routing bug (prior andie-jr session), the SERIALIZATION shape itself is still wrong — two stacked bugs, not one |
| Array / composite table (e.g. `_setCountryArray`) | `{"items": [{"_index":0, "Country": {value,displayValue}, "startDate":.., "endDate":..}, ...]}` | No handling at all | **Likely gap** — this catalog has `bm_config_attr_set`/`bm_config_attr_set_assoc` entities (37+31, confirmed present in the raw XML) that neither `engine.py` nor `rdb.py` reference anywhere; these are the probable source of composite/repeating-row attributes like the Country-array example. Needs confirming against a real attr_set sample before scoping the fix. |

**Rule-extraction genericity is UNAFFECTED by any of this** — confirmed:
hiding/constraint/recommendation/script rule loading (§13) never inspects
an attribute's value TYPE, only its `variable_name`/`attribute_id` and the
rule's own condition/action rows. A constraint or recommendation targeting
a Date or Currency attribute is extracted and classified exactly the same
as one targeting a menu attribute — the gap is entirely in `build_payload`'s
final serialization step, not in rule retrieval.

**Proposed fix**: extend `classify_select_type` to return the full type
set (`single`/`multi`/`boolean`/`date`/`currency`/`integer`/`float`/`array`)
keyed off `data_type` (confirmed codes: 2=float, 3=integer, 4=boolean,
5=date, 7=currency) rather than the current binary multi/boolean/single
split, then give `build_payload` one serialization branch per type
matching the real contract exactly. Isolated to `classify_select_type` +
`build_payload` — same low-blast-radius shape as the original hide_in_trans/
boolean fix, extended to cover the types that fix didn't anticipate.

## 15c. Array-set hypothesis — CONFIRMED against raw XML + a real production error

Parsed `bm_config_attr_set` (37 rows) + `bm_config_attr_set_assoc` (31 rows)
directly. Most `bm_config_attr_set` rows are trivial 1-attribute self-wraps
(`size_attr=-1`, no real members) — NOT arrays. But **6 are genuine
multi-column composite arrays**, each with a driving "size" attribute and
real member columns, matching the user's `_setCountryArray` shape exactly:

| Array set | Size/driver attr | Member columns |
|---|---|---|
| `promotions` | `promotionArrayController` | `promotionId`, `promotionMessage`, `promotionPricingInstructions`, `promotionOptOut` |
| `provAgenciesArraySet` | (own control attr) | `provAgencyId_astro`, `provAgencyName_astro` |
| `commandCentralArraySet_astro` | `ccArrayControl_astro` | `commandCentral_ato_atsro`, `commandCentral_Id_atsro` |
| `solutionCategoryArraySet_astro` | `solutionCategoryArrayControl_astro` | 7 columns incl. `solutionCategoryListPrice_astro` (the Currency-type attr from §15b — this one array ROW carries a Currency column, compounding both gaps) |
| `relatedSoftwareAndServicesArraySet_astro` | `relatedSoftwareAndServiceArrayControl_astro` | 6 columns |
| `vX650EnergySolutions_astro` | `vX650ItemTypeArrayControl_astro` | `itemTypeVX650_astro`, `quantityVX650ItemType_astro`, `isQuantityVX650ItemTypeThan0_astro`, `vx650PartsArray` |

**Cross-validated against a real production error, not just structure**:
the earlier 17-error session's exact message — *"itemTypeVX650_astro is an
array attribute. Please use array set payload to modify it's value"* — uses
BigMachines' own term **"array set payload"**, and `itemTypeVX650_astro` is
confirmed here as a real member of the `vX650EnergySolutions_astro` array
set. The earlier diagnosis (attr_type==1 → `select_type=="multi"`) was
directionally right but underspecified: this isn't a flat multi-select
checkbox list, it's a **composite array-set row** with 3 sibling columns —
a DIFFERENT payload shape than simple multi-select (`{"items":[{value,
displayValue}]}`) and closer to the user's full `_setCountryArray` example
(`{"items":[{"_index":0, col1:{...}, col2:.., ...}]}`).

**Confirmed: `engine.py`/`rdb.py` have zero references to `attr_set` or
`attr_set_assoc` anywhere** — this mechanism is entirely unread by the
current ingestion/retrieval pipeline. Fixing it requires: (1) ingest
`bm_config_attr_set`/`bm_config_attr_set_assoc` as a new relationship type
(set→member-columns, ordered), (2) classify a `ConfigAttr` as `"array"`
type when it's a set's driver/member rather than only checking
`data_type`/`display_type`, (3) `build_payload` groups sibling columns by
their shared `set_id` into one `{"items":[...]}` row per array index rather
than emitting each column as its own top-level key.

## 16a. Full BML-script coverage plan — staying deterministic, zero runtime LLM

Extends item 2 — closes the "444 script recommendations" gap toward full
coverage WITHOUT a live LLM call in the retrieval path, addressing the
tension between "cover everything" and "no LLM token cost at query time."

**Reframed the effort by clustering, not counting scripts 1-by-1**:
- 438 non-Tier-1 entries collapse to **only 115 distinct rule NAMES** — the
  same underlying script logic is reused across many target attributes
  (e.g. `"Set Default Attribute Values for Packages(Pricing Admin)"` alone
  feeds 74 different attres).
- Normalizing script text confirms the same thing at the text level: 438
  entries → **163 distinct script openings**.
- **The top 20 rule names alone cover 329 of 438 instances (75%)** — this
  is not a 438-script marathon, it's closer to a 20-150 distinct-pattern
  effort depending on how aggressively patterns are shared.

**Three-tier coverage plan (all deterministic at runtime)**:
1. **Tier 1 (existing)**: simple `if/else returnVal=` idiom — already
   covers ~6 entries, zero new work.
2. **Tier 1.5 (new, proposed)**: most "complex" scripts aren't actually
   bespoke business logic — they're a handful of REPEATED structural
   idioms (build a delimited string via `dict()`/`put()`/`get()`, iterate
   a small `recordset()`, look up `util.constants()`, `split()`/join
   patterns). Write ONE small deterministic parser per idiom (same
   philosophy as `_parse_branches`/`_parse_condition` already used for the
   if/else idiom) — this is pattern-matching against a KNOWN grammar, not
   general BML interpretation, so it stays 100% deterministic and
   auditable. Target the top ~20 rule names first (75% of instances).
3. **Tier 2 (long tail, explicit non-goal)**: genuinely bespoke,
   low-frequency scripts that fit no repeatable idiom. **Do not fall back
   to a live LLM call for these** — leave them un-evaluated, same safe
   "never guess" behavior already governing ambiguous/unresolved rules
   (§Gap-Deep-Dive). This keeps the RUNTIME 100% deterministic and
   LLM-free, at the honest cost of not reaching 100% script coverage —
   an explicit, bounded tradeoff instead of a hidden gap.

**Where an LLM CAN still help — offline, dev-time only, never at query
time**: an engineer building a Tier-1.5 parser or hand-porting a long-tail
script may use an LLM as a drafting aid to produce a first-pass Python
translation for human review before it's committed as code. This is a
one-time authoring tool, not a runtime dependency — it never runs during
`ask` retrieval, so it doesn't reintroduce the token-cost concern that
started this whole thread.

**Net commitment**: with Tier 1.5 covering the top ~20 patterns, realistic
coverage rises from ~1% (6/444) to an estimated ~75%+ of script-recommendation
INSTANCES, entirely deterministically, with the remaining long tail
explicitly and safely left unfilled rather than guessed — never a runtime
LLM call anywhere in the `ask`/retrieval path.

## 16b. Actual idiom shapes — read the real scripts behind the top 8 rule names

Pulled the FULL script body (not just the 150-char preview) for one
representative rule per top name. The picture is even better than §16a's
estimate — most of this isn't bespoke business logic at all.

| Idiom | Example rule names | Instances | Shape |
|---|---|---|---|
| **A — shared BM utility passthrough** | `Set Default Attribute Values for Packages(Pricing Admin)` (74), `Default Values for Base Model` (45), `Default Values For Attributes Based on Package Type FIXED` (36) | **155 (35% of all 444)** | Literally `return util.getDefaultAttributeFromPackage(packageChoiceString, "<literal attr name>");` or an equivalent one/two-line call into a SHARED BM built-in (`util.getDefaultValues`, `util.packageConfig`) — the entire rule body is one function call with a literal parameter. Implement the handful of underlying `util.*` functions ONCE in Python; every rule using them becomes free. |
| **B — constant/static return** | `Set HelpTtext info` (9), `Populate Solution Set Array` (11) | **20** | `retVal = "<fixed literal string>"; return retVal;` — no variables checked at all. Trivially portable, simpler than even the existing Tier-1 if/else idiom. |
| **C — delimited string/array builder** | `Populate Related Services And Software Array` (14), `...SEMI-FIXED` (41) | **~55** | Self-contained split/loop/dict logic with no external `util.*` dependency — fully expressible in Python directly, moderate one-time translation effort per idiom, not per instance. |
| **D — genuinely bespoke, longest scripts** | `Default Values If only one value is available` (+Portable/Mobile variants) | **46, across only 3 real script variants** | Real conditional filter-building logic (region/country-based) — the hardest bucket, but still 3 scripts to port, not 46. |

**Revised effort estimate**: idioms A+B+C+D above account for **276 of 444
entries (62%)** from just the top 8 rule names, reducible to roughly
**4 idiom-classes + 3 bespoke script variants** — not 20+ separate efforts
as §16a's first-pass estimate assumed. Idiom A alone (implement 2-3 shared
`util.*` functions once) closes 35% of the total gap for near-zero marginal
cost per rule. This makes "deterministic, ~75%+ coverage, zero runtime LLM"
a materially smaller, well-bounded engineering effort than it looked before
this read.

## 16c. New idiom found while investigating native-UI visibility (cross-linked)

`docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md` §6 found a fifth real hiding-rule
idiom while explaining why specific screenshot fields show/hide: a script
that `SPLIT()`s a per-selected-base-model "enabled attributes" string
(`hiddenUISequenceForModelSelection_astro` /
`hiddenMasterStringForAstroPortable_astro`, delimited by
`hidddenRecordSeparator_allFamilly`) and checks `findinarray()` for
whether the target attribute's name appears in it. Confirmed live-relevant,
not hypothetical — it's the actual mechanism gating
`modelSelectionFrequencyBands_astro`/`modelSelectionFrequencyBandPlus_astro`/
`productSelectionHelptext_astro`/`softwareBundlesBundleType_astro` in the
real screenshot. Doesn't fit Tier 1's if/else grammar (the condition checks
a LOCAL script variable — `findinarray()`'s result — not a direct attribute
comparison), so it falls to "unknown → stay visible" today even with items
1-9 implemented. Add as a candidate Tier 1.5 idiom alongside §16a/§16b's
util-passthrough and constant-return idioms — same "one small deterministic
parser per repeated pattern" approach, not general BML interpretation.

## 16. Rule-capture coverage ledger — does the deterministic flow actually use everything it extracts?

Verified against the full 688-rule extraction (not a sample): every rule
bucket, whether it's actually captured AND used by the current retrieval
pipeline, or extracted-but-inert, and why.

| Bucket | Entries extracted | Captured & used today? | Mechanism |
|---|---|---|---|
| Hiding — declarative | (of 456 total) | **Yes, 100%** | `load_hiding_rules` + `apply_hiding_rules` — equality check |
| Hiding — script-backed | (of 456 total) | **Yes, 100%** | `BmlEvaluator.hide_for_script` — confirmed by `test_s5_script_rules_not_silently_dropped` |
| Constraint — declarative | (of 208 total) | **Yes, 100%** | `apply_constraint_rules` — equality + intersection |
| Constraint — script-backed | (of 208 total) | **Yes, 100%** | `BmlEvaluator.allowed_values_for_script` |
| Recommendation — declarative | 157 | **Yes, 100%** | `apply_recommendation_rules` |
| Recommendation — script-backed | 444 | **No, 0%** (Gap B, §2/§7) | Extracted, logged, no BML hookup — `RecommendationRule` has no `script` field yet |
| Ambiguous multi-value recommendation | 21 | No — **by design**, not a gap | Never-guess principle (D2); correctly excluded |
| Unresolvable target | 1 | No — **by design**, not a gap | No target found via action/marked-attr/chain; correctly excluded rather than guessed |

**Net: of 1,287 total rule-entries extracted, 821 (64%) are captured and
used today; 466 (36%) are not** — but only 444 of that 36% (34.5% of the
total) is an actual GAP (Gap B); the remaining 22 are correct, intentional
safety exclusions, not something to "fix."

**Caveat carried over from §Gap-Deep-Dive**: "captured and used" for
declarative rules does not mean "used CORRECTLY" — 220 of the 348
declarative rules with any condition input (63%) are affected by the
last-input-only truncation (Gap A, items 1/3). Coverage and correctness are
two different axes; this ledger answers coverage, §Gap-Deep-Dive answers
correctness.

**Determinism/genericity of the RETRIEVAL mechanism itself**: confirmed
unaffected by any of the above — every bucket above is captured via
`set_type` inspection (not `rule_type` strings) and BML script parsing (not
hardcoded per-attribute logic), so this coverage ledger holds for ANY
newly-ingested catalog, not just APX Next — the 36%/34.5% figures are
specific to this file's data, but the MECHANISM producing them is generic.

## 15. Net assessment

The end-to-end flow is **already deterministic and generic for rule
classification, rule retrieval, and LLM-avoidance** — the two real hardcoded
spots (14a, 14b) are narrow, already self-documented in the code's own
comments, and fixable without touching the rule_tool unification work
(items 1-10) at all — fully independent tracks, same as the payload bug and
UI work. 14c is additive, no risk to existing behavior.

## 17. Native UI layout visibility — moved to its own plan

Split out into a dedicated document: **[docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md](CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md)**
— covers the `rule_type=6` "Configuration Flow" mechanism, why the native
UI shows only a subset of attributes, and the 3-tier fallback for catalogs
without it. Kept separate from this plan since it's a different question
(which attrs are DISPLAYED) from what this plan covers (rule
extraction/evaluation and payload correctness).
