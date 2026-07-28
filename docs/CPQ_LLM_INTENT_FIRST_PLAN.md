# CPQ LLM-Intent-First Plan

Status: implemented and live-verified. 257/257 tests pass (255 baseline +
2 new regression tests in `tests/test_cpq_intent_first_gate.py`).

## Implementation note: the gate had to run BEFORE detect_product_mention, not just in its failure branch

The first implementation attempt gated the intent check on `not detected`
(i.e. only fires when `detect_product_mention` found nothing) — this
still failed live. Root cause: `detect_product_mention` itself matched
"Svx Video Remote Speaker Microphone" (quoted back from the assistant's
own prior answer) inside "You said something about Svx Video RSM, how is
it connected to astra?" and confidently resolved it to `videoSolutions_BOM`
— a fuzzy, incidental mention inside a genuine question, not the user's
real intent. Fixed by moving the Q&A check to run unconditionally before
`detect_product_mention` is even called (still gated on `session.
pending_anchor == "product"`), not merely in its `None` branch.

**Live-verified, both fixes**:
- "You said something about Svx Video Remote Speaker Microphone, how is it
  connected to astra?" → now answers from real graph facts about the SVX
  RSM's relationship to ASTRO 25 (`cpq-qa`, real tokens spent), instead of
  being swallowed into "what's the destination country?" (`cpq-engine`, 0
  tokens).
- "what does astra mean in an astrological sense?" → *"I don't have any
  information in my data about what 'astra' means in astrology. My
  knowledge is strictly limited to the specific product, configuration,
  and enterprise data provided to me."* — honest, no fabricated SVX/
  currency details.

## Context

Live-traced this session: asking "how do i configure an astra radio" then
"You said something about Svx Video Remote Speaker Microphone, how is it
connected to astra?" produced two `cpq-engine`-tagged, zero-token
responses — confirming **no LLM intent classification ran at all** for
either turn. The second message (a genuine question, containing `?`) got
silently swallowed as a raw product-family answer and the system moved
straight to the next deterministic prompt ("what's the destination
country?").

Separately, a related but distinct bug: when a question DOES reach the
LLM-answer path (`_synthesise`), its own prompt instructs it to never admit
"not stored" and instead fabricate a plausible answer from the OVERVIEW —
confirmed live to hallucinate details about the SVX Video RSM when asked an
unrelated astrology question.

## Revised architecture (per explicit direction): a fixed 3-call pipeline for every user question

Whenever a message could be a question (not just at STEP 1's anchor edge
case — everywhere in the turn), it goes through exactly three stages, in
this order, never skipped or reordered:

```
1. LLM INTENT CALL       — classify: is this a question? what is it about?
2. GRAPH-GROUNDED DECISION — check the graph for real facts matching that
                             intent; DECIDE, from those facts, whether the
                             deterministic CPQ engine (attrs/rules/auto_fill)
                             needs to be invoked as a tool, or whether the
                             graph facts alone are enough to answer.
3. LLM FINAL RESPONSE    — synthesize the actual answer to the user from
                             whatever came out of step 2 (graph facts
                             and/or CPQ-tool output) — never from step 1's
                             raw intent alone.
```

This is NOT the full agentic rewrite (Option A from the prior draft,
rejected for cost/risk) — it's a fixed, always-three-stage pipeline wrapped
around the CURRENT deterministic code, reused at every point a message
might be a question, rather than a free-form "LLM decides everything, in
any order" loop. The CPQ engine (attrs, hiding/recommendation/constraint
rules, auto_fill) stays exactly as it is — it becomes a well-defined TOOL
this pipeline calls in stage 2 when the facts warrant it, not something
rebuilt.

## Stage 1: LLM intent call

**Reuses** `_llm_classify_is_cpq_question` (already built, Amendment 16
Layer 1) as the base — extend its output from a bare bool to a small
structured classification: `{is_question: bool, topic/entities mentioned:
[...], is_cpq_relevant: bool}`. This is the FIRST thing that runs for any
message that could plausibly be a question — including at STEP 1's anchor
point, where nothing like this runs today at all (confirmed: the "astra"
question got zero LLM calls, tagged `cpq-engine`, 0 tokens).

**Cheap pre-filter still applies**: the existing deterministic check
(`"?" in question or _QA_INTENT_RE`) runs first as a free gate — only
messages that pass it invoke stage 1's LLM call at all. A plain one-word
answer to "what product family?" never reaches this pipeline; it can't
match either signal.

## Stage 2: graph-grounded decision — call the CPQ tool or not

Given stage 1's classified intent, query the graph for real matching
facts (reusing `_handle_cpq_qa`'s existing term-extraction + `gather()`
search — no new graph-access code). The DECISION this stage makes:

- **Graph facts alone answer it** (e.g. "what values are available for
  Product?") → no need to invoke deeper CPQ engine logic beyond what's
  already loaded; pass facts straight to stage 3.
- **Graph facts imply this needs the CPQ engine's live rule evaluation**
  (e.g. a question whose honest answer depends on currently-selected
  constraints/hiding rules, not just static graph structure) → invoke the
  CPQ engine as a tool: call the existing `apply_constraint_rules`/
  `apply_hiding_rules`/`auto_fill` functions with the current session
  state, exactly as they run today, and pass THEIR output to stage 3
  alongside the raw graph facts.
- **Nothing relevant in the graph at all AND not CPQ-relevant** (e.g. the
  astrology question) → skip the CPQ tool entirely; stage 3 must be told
  explicitly "no facts, not in scope" so it doesn't fabricate (Fix 2
  below).

This stage is where "decides whether to call the cpq engine tool or not"
literally happens — it's a decision node, not new engine logic.

## Stage 3: LLM final response

This is the EXISTING `_synthesise` call — but it now always runs LAST,
after stages 1-2 have already gathered whatever facts/tool-output exist,
never as a first-and-only pass over raw context like today. Its prompt
(`ask_api.py:184-214`) needs the Fix 2 change below so it can honestly
report "stage 2 found nothing, this is out of scope" instead of being
instructed to always fabricate a follow-up.

## Fix 2: stop the hallucination-inducing instruction (unchanged from prior draft)

**Problem, confirmed**: `_synthesise`'s prompt instructs the LLM: *"GRAPH
FACTS empty → ... suggest a concrete follow-up question. Do NOT say 'no
matching entities' or 'not stored'."* — no carve-out for a question
genuinely unrelated to CPQ at all.

**Scoped fix**: add an explicit branch — distinguish "no graph facts, but
CPQ-relevant" (keep suggesting a follow-up) from "not CPQ-relevant at all"
(stage 1/2 already determined this — say so plainly, no fabrication). This
is now driven directly by stage 2's decision, not guessed independently by
stage 3 itself.

## Insertion points in current code

- **STEP 1** (`ask_api.py:2782-2783`, the exact bug found live): before
  the blind `detected = req.question.strip()` fallback, run the 3-stage
  pipeline whenever the cheap pre-filter matches. `attrs=[]` is safe for
  stage 2's graph search at this point (no product chosen yet); the CPQ
  tool call in stage 2 simply never fires here since there's no
  configuration state yet to evaluate against.
- **STEP 7** (existing Q&A gate, `_handle_cpq_qa`): already the closest
  thing to this pipeline today — needs restructuring so its own fast
  paths (options-listing, label collision) and its `_synthesise` call
  become stage 2 / stage 3 of the SAME pipeline, rather than a separate,
  parallel implementation (this is also why the Product-options-list bug
  from earlier existed as two independently-patched copies — unifying
  into one pipeline removes that duplication risk going forward).

## Risks

1. Extra LLM round-trip (stage 1) on every question-shaped message, even
   ones the old code answered in a single `_synthesise` call — latency/cost
   tradeoff to confirm is acceptable.
2. `_handle_cpq_qa`/STEP 7 unification is a real refactor, not just an
   insertion — needs care to avoid regressing the two duplicate-path bugs
   already fixed this session (Product options constraint filtering, the
   no-value change-request fallback) which existed precisely because two
   separate implementations of "the same thing" existed.
3. Full regression (`pytest tests/ -k "cpq or bml"`, currently 255/255)
   must stay green — STEP 1 and STEP 7 are both heavily exercised.

## Test plan (once implemented)

1. Unit-level: a message containing `?` sent while `session.pending_anchor
   == "product"` runs the 3-stage pipeline, not the blind anchor accept.
2. Unit-level: a plain, non-question reply to "what product family?" is
   completely unaffected — cheap pre-filter keeps it out of the pipeline
   entirely.
3. Live: re-run the exact "astra radio" / "SVX... how is it connected to
   astra?" transcript — confirm the second message gets a real answer (or
   an honest "no data for that, out of scope") instead of being swallowed.
4. Live: a genuinely out-of-scope question (astrology, weather) gets an
   honest answer, no fabricated catalog details, via stage 2's "not
   CPQ-relevant" decision reaching stage 3.
5. Live: a real in-scope constraint-dependent question (e.g. "what values
   are available for Product" with Hardware Version already selected)
   correctly triggers stage 2's CPQ-tool invocation and reflects the
   narrowed, constrained list — this is the unification test for STEP 7's
   refactor.
6. Full regression stays at 255/255.

## Related finding (context for Fix 3 below): internal rule names leaking into Q&A answers

Separately found live: "what is the frequency band being set" answered
with raw internal rule names verbatim — *"the system applies several
rules... 'Hide Model selection frequency band attribute'... 'Associated
Recommendation Rule'..."* Root cause traced to `render_context()`
(`src/aryx/graph/retrieve.py:98-138`): it lists every graph neighbor of a
matched entity with zero type filtering — `_SKIP_ATTR_KEYS` only filters
an entity's own bookkeeping attributes, never its neighbor entities'
types. When a ConfigAttr's neighbors include `BmConfigRule` nodes
(BigMachines' own hiding/recommendation/constraint/validation rule
construct, ingested per-catalog with a type prefix e.g.
`ApxNextConfigBmConfigRule`), their raw `rule_name` values get dumped
straight into the GRAPH FACTS block the LLM reads, and `_synthesise`'s own
system prompt ("name the specific things you're talking about... relationships
shown") makes it faithfully repeat them.

A scoped fix here (not yet re-implemented — reverted along with this
plan's own draft pending further verification) would filter neighbor
entities whose `type` ends with `bmconfigrule` (case-insensitive suffix
match, same catalog-prefix-agnostic convention `CpqEngine._attr_index`
already uses) out of `render_context`'s neighbor listing entirely — a
one-function, low-risk change with 12 existing `test_render_context.py`
tests to guard it.

## Fix 3 (scoped, not implemented): the graph-search Q&A path can't see session.filled at all

Found live while first verifying the rule-leak fix above: once raw
`BmConfigRule` neighbor names were filtered out (in an earlier, since-
reverted attempt), "what is the frequency band being set" started
answering *"The data doesn't show a specific frequency value being
set..."* — even though `modelSelectionFrequencyBands_astro` was genuinely
filled with "700/800 MHz" in the session at that exact moment. The rule-
leak fix removed the distraction and exposed the real, deeper gap
underneath: the answer was never wrong about "no rule names," it was
wrong about not knowing the actual value.

**Root cause, confirmed by direct code read**: `_handle_cpq_qa`'s generic
fallback (`ask_api.py`, the `else` branch after the fast-path options
check) resolves entities purely from the **static catalog graph** —
`all_types(reader)` → `_extract_terms` → `gather(reader, terms)` →
`render_context(entities)` → `_synthesise(...)`. None of these touch
`session.filled` (the per-turn answered values) at any point. The function
receives `session` as a parameter and uses it elsewhere in this same file
(resume prompts, pending-question logic) — it's simply never
cross-referenced against the entities the graph search found.

**Scoped fix**: after `entities` is resolved and catalog-scoped, match
each entity's `id` against the already-loaded `attrs` list's `entity_id`
(both come from the same `bm_config_attr` source — a ConfigAttr entity's
graph `id` IS its `entity_id`, no new lookup needed), restricted to
entities whose `type` actually corresponds to a `ConfigAttr` (not a menu
item, product node, or anything else the search might also return). For
any match present in `session.filled`, build a small labeled block:

```
CURRENT SESSION VALUES (this customer's actual configuration, not just
the catalog's static definition):
- Frequency Bands (modelSelectionFrequencyBands_astro): 700/800 MHz
```

Extend `_synthesise`'s signature with a new optional `session_values: str
= ""` param, inserted into the user prompt ABOVE the GRAPH FACTS block,
with an explicit instruction: *"If the question asks what something is
currently SET TO, answer from SESSION VALUES when present — it reflects
this customer's real selection, which the static GRAPH FACTS alone cannot
show."* Pass the built block from `_handle_cpq_qa`'s call site into this
new parameter.

**Why this is scoped narrowly, not a general session-awareness rewrite**:
only inject values for entities the graph search ALREADY found relevant
to this specific question — never dump the whole `session.filled` dict
(that would bloat the prompt and risk surfacing irrelevant/confusing
state for unrelated questions). The existing entity-matching work
(`gather`, catalog-prefix filtering) already does the relevance
filtering; this reuses it rather than adding new logic.

**Risks**:
1. An entity the graph search returns might not correspond 1:1 to a
   single `ConfigAttr` (e.g. it could be a `bm_menu_item`, a product/
   family node, or something else entirely) — the entity-to-attr match
   needs an explicit type check (`entity.type` ends with the catalog's
   `BmConfigAttr` suffix) before trusting `entity.id == attr.entity_id`,
   not a bare id lookup.
2. `_synthesise` may be called from other, non-`_handle_cpq_qa` contexts
   — confirm the new optional param defaults safely to no-op (empty
   string) everywhere it isn't explicitly passed.
3. Needs a live re-test of the exact frequency-band scenario, plus a
   negative test (a question about an attr that's genuinely unfilled,
   e.g. a not-yet-reached pending field) to confirm it correctly stays
   silent rather than fabricating a "current value" that doesn't exist.
4. Full regression (`pytest tests/ -k "cpq or bml"`, plus the 12
   `test_render_context.py` tests) must stay green.
5. This fix depends on (or should land together with) the rule-leak fix
   above — implementing session-value injection without also filtering
   `BmConfigRule` neighbors would leave both problems compounding in the
   same answer.
