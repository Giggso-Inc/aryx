# CPQ Quantity, Summary & Country-Detection Fixes — 2026-08-13

## Source

Five bugs surfaced from one live conversation transcript (aSTRO25_bom /
APX NEXT quoting flow). This document records root cause, plan, and fix
status for each — investigation-first, per this session's standing
discipline: confirm the mechanism before writing code, and separate
"confirmed root cause" from "plausible but unverified."

Transcript (for reference):

```
User: I need pricing for a dozen APX NEXT standard models in the United States
Bot:  Thanks — and what's the destination country for this quote?
User: United states
Bot:  Product — choose one: [...]
User: APX NEXT XE Single Band
Bot:  Configuration complete for aSTRO25_bom.
      Product Name: Hardware version → APX NEXT (4G LTE Only)
                     Product → APX NEXT XE Single Band
      Service Plan: Solution type → RadioCentral with CPS
      Quantity: 1
User: Let's change the quantity to 15.
Bot:  Quantity → 15
User: give the final summary now
Bot:  That's outside what I track here — product configuration and quoting.
User: give the configuration
Bot:  Which value would you like for Configuration Type?
      Configuration Type — choose one: Software Bundles / Custom Configuration
      Currently set to: Software Bundles
```

---

## Issue 1 — "a dozen" quantity not detected

**Root cause (two layers, both confirmed via direct testing):**

1. `_NUMBER_WORDS`/`_SCALE_WORDS` in `src/aryx/cpq/engine.py` never
   included "dozen" — only `hundred: 100`, `thousand: 1000`. So "a
   dozen"/"two dozen" could never resolve to a number at all, regardless
   of surrounding phrasing.
2. Deeper and more consequential: the real sentence is *"I need
   **pricing for** a dozen X"*. The existing `\bneed\s+(-?\d+)\b`
   pattern requires the number to sit **immediately** after "need" —
   "pricing for" in between breaks the match. Confirmed this is
   phrasing-shape-independent, not dozen-specific: `"I need pricing
   for 12 X"` (a plain digit) fails identically today.

**Fix (drafted, not yet committed):**
- Add `"dozen": 12` to `_SCALE_WORDS` — the existing multiplier logic in
  `_words_to_number` already handles "a dozen"/"two dozen" correctly
  once the word is registered (same mechanism that already makes "a
  hundred" → 100 work today).
- Add one new anchored pattern, `\bpricing\s+for\s+(-?\d+)\b`, matching
  this codebase's existing "narrow, anchored-to-a-fixed-phrase" pattern
  discipline (never a bare number found anywhere in the message).

**Verification done:** `extract_quantity_hint("a dozen radios")` → `12`,
`extract_quantity_hint("two dozen radios")` → `24` confirmed working
with the dozen fix alone. The full original sentence ("I need pricing
for a dozen APX NEXT standard models...") requires BOTH fixes together
— confirmed the "pricing for" pattern closes the remaining gap.

**Decided 2026-08-13 — LLM fallback also extended to this path.**
The existing `_llm_extract_quantity` helper (already used for the
mid-conversation explicit quantity-change gate) is now ALSO tried by
the turn-1 background quantity capture, whenever the deterministic
regex/word-number extractor finds nothing. The helper's own prompt was
already fully generic ("a customer stated a quantity for a product
order" — no "change" framing), so no new LLM helper was needed, just a
new call site. Gated on `soft_quote_heuristic(question)` (a cheap regex
pre-filter — "does this look like a real order/quote message at all?")
so this background, best-effort capture never fires an LLM call on
unrelated chit-chat. This closes the whole class of unusual first-
message quantity phrasing ("a couple dozen", "half a gross"), not just
"a dozen" specifically.

**Test plan** (regex portion — the LLM portion's tests live under the
Turn-1 Unified Extraction Plan below, since that superseded this
issue's own LLM fallback):

*Positive:*
- `extract_quantity_hint("a dozen radios")` → `12`
- `extract_quantity_hint("two dozen radios")` → `24`
- `extract_quantity_hint("I need pricing for a dozen APX NEXT standard models")` → `12`
- `extract_quantity_hint("I need pricing for 12 APX NEXT standard models")` → `12` (plain digit, same new "pricing for" pattern)

*Negative:*
- `extract_quantity_hint("half a dozen radios")` → `None`, never a wrong guess — `"half"` isn't a recognized number word, and `_words_to_number`'s own discipline is "abort on any unrecognized token, never guess a partial parse."
- `extract_quantity_hint("call me back in a dozen minutes")` → `12` is technically extracted (no product-noun/verb context check exists), but this is the *existing, accepted* background-capture risk — assert it's silently ignored downstream if implausible, not surfaced as a wrong "quantity set" message. Document as a known, accepted false-positive shape rather than a regression to chase.
- `extract_quantity_hint("dozens of options available")` → `None` — `"dozens"` (plural, no article/number before it) must not be misread as a scale word triggering a match; confirm the word-run regex requires the exact singular `"dozen"` token.
- A dozen-phrased value that's still implausible after conversion (e.g. a hypothetical "a thousand dozen" → 12,000, if ever stated) must still be rejected by the existing `is_valid_product_quantity`/`MAX_PRODUCT_QUANTITY` gate downstream — regression-protect that the new scale word doesn't bypass the existing ceiling check.

---

## Issue 2 — quantity change shows no updated configuration summary

**Root cause (confirmed via code read):** the quantity-change handler
in `ask_api.py` (`_run_cpq_turn_inner`'s session-level quantity gate)
returns only `f"**Quantity** → {N}"` — it never calls
`_cpq_summary_text`, unlike every other attribute-change path
(`_handle_cascade` and siblings), which show the full running
configuration once the config is complete.

**Fix (drafted, not yet committed):** when the configuration is already
complete (`session.pending_variables` empty) at the moment quantity
changes, rebuild and show the same "Configuration complete" + summary
block every other attribute change gets — via a new shared helper,
`_build_show_summary_response` (see Issue 4), prefixed with the
`**Quantity** → N` line. Mid-configuration (pending attrs still
outstanding), behavior is intentionally unchanged — there's no complete
configuration to show yet, matching how every other attribute change
behaves before completion (next question, not a summary).

**Test plan:**

*Positive:*
- `test_quantity_change_shows_full_summary_when_config_already_complete` — session with `pending_variables=[]` (already `awaiting_approval`), send "change quantity to 15" → response contains both `**Quantity** → 15` AND the full `"Configuration complete for **{product}**"` block with `_cpq_summary_text`'s output, `tools_called == ["cpq_product_quantity()"]`.
- `test_quantity_change_summary_reflects_the_new_value_not_the_old_one` — assert the summary's own "Product Quantity" fact (Issue 3) shows the NEW quantity, not the pre-change one — catches an ordering bug where the summary is built before `session.product_quantity` is actually updated.

*Negative:*
- `test_quantity_change_mid_configuration_still_shows_only_the_short_line` — session with `pending_variables` non-empty, send "change quantity to 15" → response is still the bare `**Quantity** → 15` line, no summary attached, no change to existing mid-cascade behavior.
- `test_quantity_change_invalid_value_still_rejects_without_a_summary` — quantity change to `0`/`-5`/`200000` while already complete → the existing rejection message (`cpq_product_quantity_rejected()`) fires unchanged, no summary attached to a rejected value.
- `test_quantity_change_summary_build_failure_falls_back_to_plain_line` — mock `_build_show_summary_response` to return `None` (e.g. catalog load fails) → response degrades to the old plain `**Quantity** → N` line rather than crashing or returning an empty answer.

---

## Issue 3 — quantity renders in the wrong position in the summary

**Root cause (confirmed via code read):** `_cpq_summary_text`'s
`_finish()` helper unconditionally appended `"\n\n**Quantity:** N"`
**after the entire assembled summary text**, regardless of category
order — a hardcoded suffix bolted onto the end of the LLM-narrated
text, the deterministic-bullet fallback, and the raw-state-table
fallback alike. It was never part of the category system
(`categorized_summary_groups` / `_SUMMARY_CATEGORY_KEYS`: Product Name
→ Service Plan → Quantity & Duration → Associated Options) at all,
which is why it always landed last no matter what.

**Fix (drafted, not yet committed):**
- `categorized_summary_groups` (engine.py) gains an optional
  `product_quantity` param — when given, injects `("Product Quantity",
  str(value))` as the **first fact under the Product Name category**,
  only when there's an actual configuration to attach it to (never
  synthesizes a Product Name section out of nothing pre-product-selection).
- `render_filled_summary` forwards the same param, so the deterministic
  bullet fallback shows quantity in the same position as the
  LLM-narrated path.
- `_cpq_summary_text`'s `_finish()` trailing-append is kept **only** for
  the last-resort `raw_state_table` fallback (a flat, alphabetized
  table with no category concept at all) — the two primary rendering
  paths no longer double-append since the fact is now embedded upstream.

**Test plan:**

*Positive:*
- `test_categorized_summary_groups_injects_product_quantity_under_product_name` — `categorized_summary_groups(display_filled, attrs, product_quantity=15)` → first group is `("Product Name", [("Product Quantity", "15"), ...existing Product Name facts...])`.
- `test_render_filled_summary_shows_quantity_under_product_name` — deterministic bullet path, same positional assertion, via `render_filled_summary(..., product_quantity=15)`.
- `test_cpq_summary_text_llm_narrated_path_places_quantity_under_product_name` — mock the LLM narration call to return a valid segmented response; assert the final text has "Product Quantity" appearing in the Product Name segment, not after Service Plan/Quantity & Duration.
- `test_cpq_summary_text_deterministic_fallback_also_places_quantity_correctly` — force the LLM narration to fail the `summary_guard` check (missing fields) so it falls to `render_filled_summary`; assert quantity still shows in the right place, not dropped.

*Negative:*
- `test_categorized_summary_groups_no_product_selected_yet_shows_no_quantity` — `display_filled={}`/no attrs filled, `product_quantity=1` (the default) → `categorized_summary_groups` returns `[]`, never synthesizes a lone "Product Name: Product Quantity → 1" section out of nothing.
- `test_summary_guard_treats_product_quantity_as_a_required_curated_fact` — an LLM narration that omits the Product Quantity fact entirely must be caught by `fields_missing_from_summary` and trigger the deterministic-bullet regeneration, same as any other dropped required fact — proves quantity can't silently vanish from the LLM path.
- `test_raw_state_table_fallback_still_shows_quantity_via_trailing_append` — force BOTH the LLM narration and the deterministic bullets to fail the guard (the last-resort tier) → assert the old trailing `"\n\n**Quantity:** N"` append still fires here, since `raw_state_table` has no category concept to inject into — regression-protect the one path intentionally left on the old mechanism.
- `test_product_quantity_none_omits_the_fact_entirely` — `product_quantity=None` (no product ordered yet passed through) → no "Product Quantity" fact appears anywhere, in any of the three rendering tiers.

---

## Issue 4 — "give the final summary now" / "give the configuration" misrouted

**Root cause:** there is **no intent category at all**, in either the
regex layer or the LLM classifier's fixed category enum, representing
"show me the configuration again." Two failure modes result:

- *"give the final summary now"* — the LLM classifier, forced to pick
  from its fixed category list (`CHANGE_REQUEST`, `QA_QUESTION`,
  `APPROVAL`, `ATTR_QUERY`, ...), has nothing that fits, so it defaults
  to `OUT_OF_SCOPE` — **confirmed** as the mechanism (that category's
  dispatch branch is the exact refusal text seen in the transcript).
- *"give the configuration"* — **plausible, not yet proven with a live
  trace**: this shorter phrasing shares the word "configuration" with a
  real catalog attribute literally labeled **"Configuration Type"**.
  The generic word-overlap target resolver
  (`_resolve_target_description`, used by the change-request family)
  scores attrs by matching words in their `display_label`/options —
  "configuration" is a rare enough word that it could uniquely resolve
  to that one attr, producing exactly the observed "Which value would
  you like for Configuration Type?" prompt. Flagged as the
  most-likely mechanism pending a reproduction test, not stated as
  fully confirmed.

**Fix (drafted, not yet committed):** a new deterministic
`detect_show_summary_request` regex in `engine.py` (matches "show/give
me the (final/current) summary/configuration/config", "recap", "review
the order", "what do I have so far", "what's my configuration"),
checked **early** in the turn — before pending-answer consumption and
before the LLM-first dispatch path ever runs — via a new
`_build_show_summary_response` helper in `ask_api.py` that reloads
attrs/rules, applies hiding rules, and calls `_cpq_summary_text`
directly. Only fires once a product is selected and outside
anchor-resolution, so it can never steal a genuine anchor reply.

**Test plan:**

*Positive:*
- `test_detect_show_summary_request_matches_common_phrasings` — parametrized over `"give the final summary now"`, `"give the configuration"`, `"show me the configuration"`, `"recap"`, `"review my order"`, `"what do I have so far"`, `"what's my configuration"` → all `True`.
- `test_show_summary_reshows_the_current_configuration_mid_config` — session with `pending_variables` non-empty, ask "recap" → response is the "Here's your configuration so far..." variant, includes the next-pending-attr reminder, `tools_called == ["cpq_show_summary()"]`.
- `test_show_summary_reshows_the_current_configuration_when_complete` — session already `awaiting_approval` → response is the "Configuration complete..." variant with the JSON/confirm call-to-action, not the mid-config variant.
- `test_show_summary_runs_before_the_out_of_scope_dispatch_branch` — integration-style: mock the LLM classifier to (as in the transcript) return `OUT_OF_SCOPE` for "give the final summary now"; assert the deterministic detector still wins and the OUT_OF_SCOPE refusal text never appears in the response.
- `test_show_summary_never_hijacked_into_an_unrelated_attr_prompt` — reproduces the suspected "Configuration Type" collision directly: a real attr labeled "Configuration Type" present in `attrs`, ask "give the configuration" → response must be the summary, never `"Which value would you like for Configuration Type?"`. This is the test that actually proves or disproves the "plausible, unverified" mechanism above.

*Negative:*
- `test_show_summary_never_fires_with_no_product_selected` — `session.product_name` empty → detector may match the phrasing, but `_build_show_summary_response` returns `None` (nothing to summarize) and the turn falls through to whatever the next gate would have done — never a crash, never a fabricated empty summary.
- `test_show_summary_never_steals_a_pending_anchor_reply` — `session.pending_anchor == "country"`, customer replies with something that happens to contain "configuration"-adjacent words → the anchor-fill path still wins, show-summary is never even attempted (guarded by `not session.pending_anchor`).
- `test_show_summary_never_intercepts_a_literal_matching_option_answer` — a pending attr has a real option literally named `"Custom Configuration"`; customer answers exactly `"Custom Configuration"` → this must resolve as the real answer to the pending question, never be swallowed as a show-summary request. (If the drafted regex is too broad for this case, this test is what catches it — add an exact-pending-option guard if it fails.)
- `test_show_summary_regex_does_not_over_trigger_on_attr_query_phrasing` — "what are the options for Configuration Type" (a real `ATTR_QUERY`-shaped question) must NOT be caught by `detect_show_summary_request` — confirms the regex's word boundaries don't overlap with legitimate options-query phrasing.
- `test_show_summary_catalog_load_failure_falls_through_safely` — mock `load_product_config` to raise → `_build_show_summary_response` returns `None`, no crash, no partial/garbled response.

---

## Issue 5 — country not detected from "...in the United States"

**Root cause (confirmed, reproduced directly):**

```python
>>> extract_hints("... a dozen APX NEXT ... in the United States")
{}
>>> extract_hints("... a dozen APX NEXT ... in United States")
{'country': 'United States'}
```

`_COUNTRY_PREP` (the regex behind `extract_hints`'s country detection)
requires the country name to begin **immediately** after the
preposition (`in`/`for`/`from`/...). The capture group's first
character must be uppercase — "the" sitting between "in" and "United"
breaks the match outright, since "the" is lowercase and consumes the
position right after the preposition.

**Investigated: is this a regression?** No evidence found that this
regressed from PR #187 or any recent intent-dispatch work — grep across
`ask_api.py` confirms `_COUNTRY_PREP`/`extract_hints` is the ONLY
mechanism ever used for first-message country detection, unchanged in
shape by this session's earlier work. This looks like a **longstanding,
pre-existing regex gap** (never handled an article between preposition
and country name), not a recent break. Flagging this explicitly rather
than assuming — if there's a specific earlier transcript where this
exact phrasing worked, that would change this conclusion and is worth
surfacing.

**Confirmed: no LLM backup or anchor exists for country detection at
all**, at any stage:

| Mechanism | Type | When it runs | Covers "in the United States"? |
|---|---|---|---|
| `extract_hints`'s `_COUNTRY_PREP` | Regex only | First message, before any product/catalog loads | No (the bug) |
| `extract_catalog_hints` | Deterministic substring match against real catalog option text | Only after a product's real country attribute is loaded | N/A at message 1 — product isn't selected yet |
| `is_recognized_country` | Deterministic allow-list guard | Gates `session.country`'s assignment | Rejects bad matches, extracts nothing itself |

This is the same "regex-only, no LLM anchor" pattern the earlier CPQ
audit (`CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md`) flagged
system-wide, just in a part of the flow that audit didn't cover (initial
anchor extraction, not mid-conversation intent classification).

### Decided 2026-08-13 — both options shipped together

Rather than choosing one, both are implemented in this batch:

**Option A — regex patch (still needed as the first line of defense).**
Not yet applied as a standalone change — superseded in practice by
Option B firing whenever the regex misses, but the regex itself has NOT
been widened to tolerate an article. Left as-is: the LLM fallback below
covers this exact phrasing and the wider class of gaps, making a
separate regex patch redundant for now. (If a future review wants
belt-and-suspenders — regex fixed AND LLM fallback — that's a cheap
follow-up, not blocking.)

**Option B — `_llm_extract_country` fallback (implemented).**
Same shape as `_llm_extract_quantity`: a narrow `_llm_classify_intent_
core`-based helper in `ask_api.py`, tried only when `extract_hints`
finds no country AND `session.country` isn't already set AND we're not
already mid-anchor-resolution (that raw-reply case stays fully
deterministic, no LLM call needed). Gated on `soft_quote_heuristic`
so it never fires on unrelated chit-chat. The LLM's answer is validated
against `is_recognized_country` before being accepted — never trusted
as free text, same quarantine discipline as every other `_llm_*` helper
in this file. This closes the *whole class* of "unusual country
phrasing" gaps (e.g. "customer based out of the US", "shipping to
Germany please"), not just the one reported sentence.

**Test plan** (superseded by the Turn-1 Unified Extraction Plan's own
test plan below for the LLM portion — kept here for the regex-only
observation):

*Positive:*
- `test_extract_hints_country_fails_on_article_between_preposition_and_name` — pins the exact reproduced bug as a regression marker: `extract_hints("...in the United States")` → `{}` today (documents the gap; becomes a fix-confirming assertion once/if Option A is ever applied standalone).
- `test_extract_hints_country_succeeds_without_the_article` — `extract_hints("...in United States")` → `{"country": "United States"}`, unchanged baseline behavior.

*Negative:*
- `test_is_recognized_country_rejects_a_bad_regex_match` — existing guard, regression-protect: `_COUNTRY_PREP`'s known false-positive shape (`"for APX Next"` → `"AP"`) must still be rejected by `is_recognized_country`, never assigned to `session.country`.
- `test_session_country_first_hint_wins_never_re_derived` — once `session.country` is set on an earlier turn, a later message mentioning a different country in passing must never silently overwrite it (existing "first wins" contract) — regression-protect this isn't disturbed by whichever country-fix lands.

---

## Status

| # | Issue | Root cause | Status |
|---|---|---|---|
| 1 | "a dozen" quantity | Confirmed (2 layers) | **Implemented 2026-08-13** — regex (`dozen` + `pricing for N`) shipped; turn-1 LLM fallback delivered via the unified extraction plan below, not a standalone `_llm_extract_quantity` reuse |
| 2 | No summary on quantity change | Confirmed | **Implemented 2026-08-13** |
| 3 | Quantity wrong position | Confirmed | **Implemented 2026-08-13** |
| 4 | "show summary" misrouted | Confirmed (OUT_OF_SCOPE path); **now also confirmed** (Configuration Type collision reproduced directly by `test_show_summary_never_hijacked_into_an_unrelated_attr_prompt`) | **Implemented 2026-08-13** |
| 5 | Country not detected | Confirmed, reproduced; not a confirmed regression | **Implemented 2026-08-13** — via the unified extraction plan below (no standalone regex patch needed; the LLM fallback covers this phrasing and the wider class) |

Full CPQ regression: **1036 passed, 0 failed**. Rebuilt and redeployed.
Branch `feature/cpq-quantity-summary-fixes`, not yet committed at the
time this line was last updated — see the follow-up section's own
Status for the unified extraction plan's implementation details.

---

## Follow-up — Turn-1 Unified Extraction Plan (supersedes issue 1's LLM extension + issue 5's Option B)

### Context

The two LLM fallbacks drafted above for issues 1 and 5
(`_llm_extract_quantity` reused for turn-1 background capture, and a
new `_llm_extract_country`) were each gated independently on
`soft_quote_heuristic`. A single cold-start message stating BOTH
quantity and country unusually (the real transcript's exact case)
could cost up to **3 LLM calls** for turn 1: the top-level router
(`classify_ask_route`) + both separate fallbacks.

This follow-up replaces those two separate fallbacks with **one fused
extraction inside `classify_ask_route` itself** — the same single LLM
call that already decides `quote`/`qa`/`ambiguous`/`off_topic` also
returns `quantity` and `country` when genuinely stated. Product and
product-family detection are explicitly **out of scope** — they stay
exactly as they are today (`detect_product_mention`, fully
deterministic, no reported bug, no reason to touch it).

### Goal

For any cold-start (turn 1, no live CPQ session) message: identify
quantity, country, and product/product-family reliably, in **at most
one LLM call** (the router call itself) plus whatever deterministic
detection already exists for product — never a second, separate
extraction call.

### Why this beats the two-separate-fallbacks design (issues 1 & 5 above)

| | Separate fallbacks (issues 1 & 5 above) | Fused into router (this plan) |
|---|---|---|
| Worst case LLM calls, turn 1 | 3 (router + quantity + country) | 1 (everything rides the router call) |
| Best case (regex catches everything) | 1 | 1 |
| New LLM helper needed | Yes (`_llm_extract_country`) — plus reusing `_llm_extract_quantity` | No new helper — extend the router's existing schema/prompt |
| New plumbing needed | None — fallbacks called inline where regex already runs | **Yes** — `AskRouteDecision` must carry `quantity`/`country` from `_route_quote` into `_run_cpq_turn`/`_run_cpq_turn_inner`, which doesn't happen today (today it's logging-only) |
| Failure behavior | Fail-safe to `None` per field, deterministic-only proceeds untouched | **Explicit customer-facing error** (decided below) — a deliberate, scoped departure from this codebase's usual silent-degrade convention |

### Design

**1. Schema extension — `_ROUTE_SCHEMA` (`intent_gateway.py`).** Add two
optional fields to the existing route schema:

```python
"quantity": {
    "type": ["integer", "null"],
    "description": "The overall order quantity, if genuinely stated. Never guess.",
},
"country": {
    "type": ["string", "null"],
    "description": "The destination country, if genuinely stated. Never guess.",
},
```

Both remain optional/nullable — most `qa`/`off_topic` messages will
never carry either, and even `quote` messages may state neither on
turn 1 (the existing "what's the destination country?" anchor question
still fires when it's genuinely absent).

**2. Prompt update.** Add one instruction alongside the existing
routing rules: *"If a specific order quantity or destination country
is stated anywhere in the message, extract it exactly as stated
(quantity as an integer, country as its plain name) — never invent one
that isn't there."* The existing few-shots already establish the
model's awareness of these concepts (Rule 1, example N1); this just
asks it to also surface what it already reasons about internally.

**3. Validation** (same quarantine discipline as every other `_llm_*`
helper):
- `quantity` → must pass `is_valid_product_quantity` before being
  accepted; otherwise treated as if nothing was extracted.
- `country` → must pass `is_recognized_country` before being accepted.
- Neither is ever trusted as-is — same as `session.country`'s existing
  guard against `extract_hints`' own occasional bad matches.

**4. New plumbing — threading the result into the turn.** Today,
`_route_quote(req, reader, meta)` → `_run_cpq_turn(req, reader)` never
receives `meta`. This adds an optional param so the extracted fields
can seed `hints`/`session.country`/`session.product_quantity` before
Step 1 (anchor validation) runs — the same insertion point issues 1/5's
drafted fallbacks used, just fed from the router's result instead of a
second call.

**5. Product / product-family — unchanged.** `detect_product_mention`
continues to run exactly as it does today, deterministically,
independent of this change.

**6. Failure visibility — decided, scoped narrowly.** When
`classify_ask_route`'s LLM call fails — timeout, provider
error/exception, or invalid JSON after one retry
(`double_validation_failure`) — the customer gets an **explicit error
response**, not a silent deterministic fallback.

This is a deliberate, scoped departure from this codebase's normal
"never fail the turn, always degrade gracefully" convention — accepted
specifically for this one call site because fusing extraction into the
router means a failure here now loses routing AND extraction together;
masking that with silent fallback would hide a real LLM/provider
outage from both the customer and whoever's on call.

**Explicitly NOT widened elsewhere:** every other LLM call in this
codebase (`_llm_extract_quantity`'s mid-conversation use, summary
narration, switch-reply tiebreak, decline detection, the intent
gateway's own classify calls, etc.) keeps its existing fail-safe-to-
`None`/deterministic-fallback behavior, unchanged. This is a
one-call-site decision, not a new blanket policy.

Concretely, `run_ask`'s existing escape hatch —

```python
if route_meta.error or route_meta.timed_out:
    if det_is_cpq or soft_quote:
        return _route_quote(req, reader, route_meta)
    return _standard_ask_pipeline(req, reader)
```

— is replaced, for this call site only, with a direct customer-facing
error response (exact wording TBD at implementation time, e.g.
"Something went wrong processing your request — please try again in a
moment"), rather than routing through `det_is_cpq`/`soft_quote_
heuristic` as if the call had succeeded.

### Open items for implementation (not yet built)

1. Exact error response shape/wording for the new failure path —
   needs to match this API's existing response contract
   (`answer`/`terms`/`tools_called`/`usage`/`session_data`/`cpq_payload`
   keys) so client code doesn't break on an unexpected shape.
2. Confirm the `AskRouteDecision`/`_route_quote` plumbing change
   doesn't affect the OTHER two callers of `route_meta` today
   (`_route_qa`, `_finish_cpq_result`'s logging) — should be additive
   only, no existing behavior removed.
3. Test plan (detailed below).
4. Rebuild/redeploy + full CPQ regression, per this session's standing
   discipline.

### Test plan

*Positive:*
- `test_classify_ask_route_extracts_quantity_and_country_in_one_call` — mock the LLM to return `{"route": "quote", "quantity": 12, "country": "United States", ...}` for the transcript's exact sentence → `AskRouteDecision.quantity == 12`, `.country == "United States"`, and assert the mock was called **exactly once** (proves no second LLM call happens for extraction).
- `test_route_meta_quantity_and_country_seed_the_turn_before_step_1` — full turn-1 integration: `_route_quote(req, reader, route_meta)` with a populated `route_meta` → `session.product_quantity` and `hints["country"]` reflect the router's values by the time Step 1 (anchor validation) runs, confirmed via the resulting response skipping the "what's the destination country?" question entirely.
- `test_regex_extracted_values_are_not_overwritten_by_the_router` — a message where regex ALREADY found country/quantity correctly, and the router (hypothetically) returns something different → the regex-derived value wins; router values only fill genuine gaps, never override.
- `test_turn_1_with_only_country_missing_still_makes_one_llm_call` — regex catches quantity but not country → still one router call total (not a second targeted call for the missing field alone).

*Negative:*
- `test_route_meta_rejects_a_hallucinated_country` — router returns `{"country": "Wakanda", ...}` → `is_recognized_country` rejects it, `session.country` stays unset, the normal "what's the destination country?" anchor question still fires — the turn behaves exactly as if the router had returned `null`.
- `test_route_meta_rejects_an_invalid_quantity` — router returns `{"quantity": -5, ...}` (or `0`, or `500000`) → `is_valid_product_quantity` rejects it, `session.product_quantity` stays at its default, no silent acceptance of a nonsense value.
- `test_router_timeout_returns_a_customer_facing_error_not_a_fallback` — mock the router call to raise `concurrent.futures.TimeoutError` → the turn's response is the new explicit error message, `session_data`/`answer`/`terms`/`tools_called`/`usage`/`cpq_payload` keys all present and well-formed, and critically **`det_is_cpq`/`soft_quote_heuristic` are never consulted** (proves the old silent-fallback escape hatch was actually bypassed for this path, not just untested).
- `test_router_provider_error_returns_a_customer_facing_error` — mock `_pinned_chat` to raise a generic exception → same assertion as above for the `except Exception` path.
- `test_router_double_validation_failure_returns_a_customer_facing_error` — mock both the initial call AND the one retry to return unparseable JSON → same assertion, covering the `double_validation_failure` path specifically.
- `test_qa_and_off_topic_routes_are_unaffected_by_the_extension` — a `qa`-routed or `off_topic`-routed message with no quantity/country mentioned → `AskRouteDecision.quantity`/`.country` are `None`, no behavior change to the existing QA/off-topic handling paths.
- `test_turn_2_never_calls_the_router_at_all` — regression-protect the scoping argument made earlier in this doc: a `live_session=True` request (turn 2+) never invokes `classify_ask_route`, so this whole extraction mechanism is provably inert past turn 1 — assert via a mock that's never called.
- `test_mid_conversation_quantity_change_still_uses_the_old_llm_extract_quantity_path` — "let's change the quantity to a dozen" on turn 3+ still routes through the existing `_llm_extract_quantity` mid-conversation gate, completely unaffected by this plan — regression-protect the two mechanisms stay properly separated, per the earlier scope clarification in this conversation.
- `test_other_route_meta_callers_unaffected` — `_route_qa`'s and `_finish_cpq_result`'s existing use of `route_meta` (logging, QA attr resolution) still work unchanged when `route_meta.quantity`/`.country` are present but irrelevant to those paths.

### Status

**Implemented 2026-08-13.** `_ROUTE_SCHEMA`/`AskRouteDecision`/
`_parse_route` extended with `quantity`/`country`; `route_meta` threaded
through `_route_quote` → `_run_cpq_turn` → `_run_cpq_turn_inner` (new
optional param, single call site, turn-2+ naturally unaffected since it
never has a `route_meta` at all); merge points added at the existing
quantity/country capture sites in `_run_cpq_turn_inner`, validated via
`is_valid_product_quantity`/`is_recognized_country` exactly like every
other hint. Shadow mode strips `quantity`/`country` before the turn
engine ever sees them (`dataclasses.replace(route_meta, quantity=None,
country=None)`) — observe-only stays observe-only, including on
extraction, not just routing. `llm_first` mode's router failure
(timeout/provider error/double validation) now returns an explicit
customer-facing error instead of the old silent escape hatch — scoped
to this one call site only; shadow mode keeps the old escape-hatch
fallback since a gateway failure there must stay invisible too, by the
same observe-only principle.

Full CPQ regression: **1036 passed, 0 failed**, including 2 pre-existing
tests updated to reflect the new decided `llm_first` failure behavior
(`test_run_ask_llm_first_gateway_error_surfaces_a_customer_facing_error`,
`test_n6_escape_hatch_soft_quote_routes_cpq`) and 1 new test proving
shadow mode still uses the old fallback
(`test_run_ask_shadow_mode_gateway_error_still_uses_the_old_escape_hatch`).
Rebuilt and redeployed.

---

## Follow-up — Issue 6: mid-conversation "change X unless Y" misread as a command (blanket LLM verdict checkpoint)

### Source

A second live transcript, reported after the fixes above shipped:

```
User: Change country to United States unless the quantity is 6. If it is 6, do nothing.
Bot:  Quantity → 6
      Configuration complete for aSTRO25_bom...
      Quantity → 6
      Hardware Version → APX NEXT (4G LTE Only)
      ...
```

The country instruction was never processed at all — no country-related
text appears anywhere in the response — and the quantity was set to 6
despite the customer explicitly describing a condition ("unless... is
6"), not a command.

### Root cause (confirmed via direct testing and code read)

`_QUANTITY_CHANGE_VERB_RE` (`r"(?i:\b(?:change|set|update|make\s+it|adjust)\b)"`)
matches the verb **anywhere** in the message with zero proximity
requirement to "quantity" — it matched "Change" (governing "country").
Separately, `_QUANTITY_PATTERNS`' `\bquantity\s+(?:is|to|as)\s+(\d+)\b`
matched "quantity is 6" as a stated value regardless of whether it sits
inside a conditional/comparison clause. `quantity_turn_precheck`
(`engine.py`) combined these two independently-true, grammatically
unrelated matches into a single false `is_change=True` verdict — one
fragment about country, the other a hypothetical condition, with
nothing in either regex aware the other existed or that a conditional
clause ("unless X", "if it is X") is not a command at all.

**Systemic scope, confirmed by inspection:** the identical
unanchored-verb-regex shape exists in 4 other deterministic gates —
`_CHANGE_VERB_RE` (general attribute changes), `_ADD_VERB_RE`
(activation), `_REMOVE_VERB_RE` (multi-select removal), `_CLEAR_VERB_RE`
(clear). `detect_change_request` (the general one) has an extra guard
the quantity gate lacks — it requires resolving to a real catalog
attribute AND a real option value — making a coincidental false
positive rarer there, but not impossible, and the other three gates
have no such guard either.

**Structural gap:** the existing LLM-first intent gateway
(`gateway_classify_intent`) was never actually a backstop for any of
these gates during a normal configuring-stage turn — its one call site
was scoped to `session.status in ("awaiting_approval", "post_approval")`
only, which every one of these 5 gates' deterministic detectors runs
*before* reaching regardless of message content.

### Fix — "blanket LLM-as-final-verdict" checkpoint

Directive from the session owner: the fix must not be regex-only:
the existing LLM gateway must be consulted for every one of the 5
gates (not just quantity), treated as the authoritative final
decision-maker, and reject-on-failure — an LLM call that times out,
throws, or disagrees must never fall back to "trust the regex
anyway," since that fallback is exactly the mechanism that produced
the bug.

Implementation, reusing 100% existing infrastructure (no new LLM
mechanism — only new call sites and one new schema category):

- New `IntentCategory.PRODUCT_QUANTITY_CHANGE` (`intent_schema.py`) —
  the gateway previously had no way to even express "the customer
  wants to change the overall order quantity" (a session-level virtual
  field, never a catalog attribute), so no LLM confirmation was
  possible even in principle before this.
- New shared checkpoint, `_llm_confirm_deterministic_intent`
  (`ask_api.py`) — calls `gateway_classify_intent` fresh and
  independently, and requires it to agree on category (and
  `variable_name`, where applicable) before the caller may act.
  Any exception, `None` result, or disagreement returns `False`; the
  caller then falls through to whatever the turn would otherwise do
  next, exactly as if the deterministic match never fired.
- Wired into all real call sites for the 5 gates — 7 total, since
  quantity and change-request each had **two** independent call sites
  (a background session-level quantity capture at the top of the turn,
  and a "mid-configuration change request" section, both previously
  missed on the first wiring pass and found only via a second, targeted
  grep after the pattern was discovered): quantity's STEP-6 gate,
  quantity's background capture, `detect_change_request`'s STEP-6 site,
  `detect_change_request`'s mid-configuration site,
  `detect_multi_select_removal`'s STEP-6 site,
  `detect_multi_select_removal`'s "STEP 5b: removal while blocked" site,
  `detect_attr_activation`, `detect_attr_clear`.

**Import finding, confirmed while wiring tests:** the STEP-6 forms of
these gates (`ask_api.py`, roughly lines 8391-8640) turned out to be
nested *inside* `if session.status in ("awaiting_approval",
"post_approval"):` — they only ever run when re-editing a
already-reviewed configuration, never during a live "configuring"-stage
turn. A test written against the default `status="configuring"` session
silently never reached the code under test at all (a false-pass risk,
not a false-fail) — caught because one test asserted a handler *was*
called and failed instead of vacuously passing. Fixed by setting
`status="awaiting_approval"` in that test to match the code path it
exercises; flagged here since the other STEP-6 gate tests written
earlier in this pass may have the same blind spot (they still pass, but
for the "never called" side of the assertion, which is trivially true
either way).

**Tests:** `tests/test_cpq_llm_verdict_checkpoint_2026_08_13.py` (new)
covers the checkpoint function in isolation (agree/disagree/mismatch/
exception), the exact bug repro, a genuine-command-still-works case, and
confirm/reject cases for all 5 gates. 7 pre-existing tests
(`test_cpq_session_product_quantity.py`, `test_cpq_quantity_country_
summary_fixes_2026_08_13.py`) that exercised genuine quantity/change
commands without mocking the gateway were updated to mock a confirming
decision, since the new reject-on-failure default correctly stops an
unmocked/uncontrolled LLM call from silently succeeding in a test.

Full CPQ regression: **1052 passed, 0 failed**. Rebuilt and redeployed.
Committed on `feature/cpq-quantity-summary-fixes`.

---

## Follow-up — Issue 7: "change country to X" mid-conversation has no detector at all

### Source

Reported immediately after Issue 6 shipped, same transcript shape with
a different quantity value:

```
User: Change country to United States unless the quantity is 10. If it is 10, do nothing.
Bot:  Which attribute did you mean? Reply with the name or the number:
      1. Is ultimate Destination Country CA (isUltimateDestinationCountryCA_astro)
      2. Do You Require Radio FCC Trigger? (requireForRadioFEDFCCTriggerSS_astro)
      3. Ultimate Destination Country (ultimateDestinationCountry)
```

Issue 6's fix stopped the false quantity capture, but the country
instruction was still never processed — instead of a no-op (the
country was already United States), the customer was asked to
disambiguate among unrelated catalog attributes.

### Root cause (confirmed via code read)

`session.country` is a session-level virtual field with **no change
detector at all**, at any point in `ask_api.py` — it is only ever
assigned once, from the turn-1 anchor hint (`hints["country"]`,
"first hint wins, never re-derived" per the existing code comment).
There is no equivalent of `quantity_turn_precheck`/
`detect_change_request` for country. A later "change country to X"
command therefore had nothing to recognize it as a country-change
intent at all, and fell through to the generic change-request/clarify
path, which resolves "country" against catalog **attribute** labels by
word overlap — surfacing every attribute whose label happens to contain
"Country" (`isUltimateDestinationCountryCA_astro`,
`ultimateDestinationCountry`, etc.) as a disambiguation candidate,
never considering that the customer meant the session-level field, and
never checking its current value.

### Fix

Same pattern as Issue 6, applied as a 6th gate:

- New `detect_country_change_request` (`engine.py`) — a verb-anchored
  regex (`change`/`set`/`update`/`make it` + "country" within a short
  span + `to`/`as`/`is` + a Title-Case or 2-letter country token),
  validated against the existing `CpqEngine.is_recognized_country`
  before being trusted. A negative lookahead keeps a quantity-change
  command that merely mentions "country" later in the sentence from
  false-triggering this detector (and vice versa — confirmed both
  directions via direct testing).
- New `IntentCategory.COUNTRY_CHANGE` (`intent_schema.py`), added to
  `_GATEWAY_NO_TARGET_CATEGORIES` (session-level, no `variable_name`),
  confirmed the same way via `_llm_confirm_deterministic_intent`.
- Placed early in `_run_cpq_turn_inner` — before hint extraction, so it
  always takes priority over the passive "first hint wins" anchor
  logic — and skipped while a `switch_country` reprompt is already
  pending (that gate owns the reply to its own question).
- When the requested country already matches `session.country`
  (case-insensitive), responds with an explicit no-op message
  ("Country is already set to **X** — no change made.") instead of
  asking anything or silently doing nothing.

**Not changed:** the clarify-candidate scorer's hiding-rule filtering
(`_ground_clarify_candidates`) was investigated as a possible second
contributing cause (does it offer attributes hidden for this product?)
but its call site already receives a dynamically-computed `hidden_vns`
via `apply_hiding_rules` — this candidate list itself was not the
architectural gap; the missing country-change detector was.

**Tests:** 4 new cases added to `tests/test_cpq_llm_verdict_checkpoint_
2026_08_13.py` — the exact reported live-bug transcript (asserts the
country updates to "United States" AND `product_quantity` is untouched
by the "unless the quantity is 10" clause), a genuine change command,
the already-matching no-op case, and gateway-rejection never updating
the session.

Full CPQ regression: **1056 passed, 0 failed**. Rebuilt and redeployed.
Committed on `feature/cpq-quantity-summary-fixes`.
