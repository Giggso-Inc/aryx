# Session-Level Product Quantity — Root Cause & Fix Plan

## Problem Statement

When a customer mentions how many units of a product they want ("50 in qty", "i want 10 APX
NEXT"), Aryx today either:

- **Silently drops it** — nothing anywhere in the backend extracts a quantity mention from free
  text, so a quantity stated in the customer's very first message is discarded and never
  resurfaces anywhere (summary or payload).
- **Or, when Aryx tries to resolve quantity via the catalog's own quantity attribute** (a real,
  array-set-linked field like `quantityVX650ItemType_astro`), it gets stuck in a repeating
  validation loop: any natural-language answer containing a number and other words ("i want 10
  APX NEXT") fails to match, and the customer is re-asked the identical question indefinitely,
  with no explanation of what went wrong.

The customer has no reliable way to state a quantity, see it confirmed anywhere, change it, or
have it reflected in the quote summary — a basic, expected capability of any quoting conversation
is effectively broken. **This is the issue to fix first**, and this document plans that fix only.
(The separate default-suggestion-chip issue reported alongside this one lives in the web chat
client's own codebase, confirmed not present anywhere in this backend — tracked separately, out
of scope here.)

## Root Cause

`CpqEngine.apply_answer` (`src/aryx/cpq/engine.py:9097`) has no step anywhere that extracts a
number from a sentence, and nothing in the backend extracts a quantity mention from free text at
all — confirmed by `grep`, there is no existing "50 in qty"-style parser anywhere in this
codebase. The one place quantity is currently expected to resolve is by conversationally
slot-filling the catalog's own quantity attribute, which:

- Has no menu options (a genuine free-text/numeric field), so `apply_answer`'s only viable path is
  its final free-text fallback — which only fires when **no active constraint** is narrowing the
  field (`allowed is None`). The real attribute is constrained (an array-set quantity member gated
  by a rule on its sibling selector), so that fallback never runs.
- Has no numeric-extraction step anywhere else in `apply_answer` — every other matching pass
  (exact item-value, exact display-name, prefix, word-boundary) is built for **menu-backed**
  attributes and has nothing to match against on a menu-less field.

Result: every phrasing of a quantity answer fails identically, and the caller (`ask_api.py:1811`)
falls into its generic "couldn't match" re-ask branch forever.

## Decision: a session-level quantity, not a catalog-attribute fix

Rather than patching `apply_answer` to parse answers to the catalog's own quantity attribute, the
fix is a **dedicated, product-level quantity concept tracked directly in the session** —
decoupled entirely from any catalog attribute's own options/constraints:

1. Quantity is tracked **once per product, in the session** — not as an answer to any specific
   catalog attribute.
2. It **defaults to 1** if the customer never mentions one.
3. It **appears in the quote summary** shown before confirm.
4. It **must NOT appear in the final JSON payload** (`configData`).
5. Any quantity-related question or statement from the customer ("what's my quantity", "change
   quantity to 20", "how many did I order") is answered from **this session-level value first** —
   never routed through the generic catalog-attribute slot-filling pipeline.

This also removes Issue 1's failure surface at the root: with no catalog quantity question ever
asked conversationally, there is nothing for a composite "i want 10 APX NEXT"-style answer to fail
to match against.

## Implementation Plan

### 1. New session field

`CpqSession.product_quantity: int = 1` (`src/aryx/cpq/state.py`) — a plain session field,
deliberately kept OUTSIDE `session.filled`/`filled_multi`. This is what makes requirement #4
(never in JSON) hold structurally, not by convention: `CpqEngine.build_payload` only ever iterates
`session.filled` and `session.filled_multi` — a value that never enters either dict can never
reach `configData`, with no special-case exclusion code needed anywhere.

### 2. Free-text quantity extraction

A new extraction step, run on every turn's free text the same place `extract_hints`/
`extract_catalog_hints` already mine country/product mentions from the opening message. Pattern
set to cover the real phrasings seen so far: "50 in qty", "qty of 50", "50 units", "quantity 50",
"i want 50", "50 radios", etc. — a number adjacent to a quantity-indicating word or the product
noun, not just any bare number in the message (to avoid misreading an unrelated number, e.g. a
model code or a year, as the quantity). Sets `session.product_quantity` when a confident match is
found; never overwrites an already-set, user-confirmed quantity with a lower-confidence match on a
later turn.

### 3. Early routing for quantity-related turns — with disambiguation

A new, early check in `ask_api.py`'s per-turn handler — before the generic pending-attribute-answer
or Q&A paths — detects a quantity-related question or change request. "Quantity" is ambiguous in
this catalog: it can mean the overall **product quantity** (`session.product_quantity` — "how many
radios") or a specific **catalog quantity attribute** on an accessory/component (e.g. "Quantity
(VX650 Item Type)" — how many of a particular add-on). Resolution order:

1. **The message itself already disambiguates** — it names a specific item/accessory (e.g. "how
   many VX650 mics", "set the battery quantity to 3") or, conversely, clearly means the overall
   order (e.g. "how many radios total", "what's my quantity"). Resolve directly against the
   matching target — `session.product_quantity` for the overall case, or the specific real catalog
   attribute (if one is currently visible/governed) for the named-item case — no clarifying
   question needed.
2. **Genuinely ambiguous** — the customer says only "quantity" or "qty" with no distinguishing
   detail, AND there is at least one real, currently-relevant catalog quantity attribute in play
   (visible/governed for the current configuration) besides the overall product quantity. Ask:
   *"Are you asking about the overall product quantity ({current value}), or the quantity for a
   specific item like {catalog attribute's display label}?"* Do not guess.
3. **No competing catalog quantity attribute exists** for the current configuration — resolve
   directly against `session.product_quantity`, since there's nothing to disambiguate against.

Once the customer's turn (or their answer to the disambiguation question) identifies which one,
route to that target: `session.product_quantity` directly, or the real catalog attribute via the
existing `apply_answer`/cascade machinery (unaffected by this plan — only reached here when the
customer explicitly means that specific item, never guessed).

### 4. Summary line

`_cpq_summary_text` (`ask_api.py:485`) gets one new line (e.g. "**Quantity** →
{session.product_quantity}"), sourced from the session field directly, shown once a product is
selected — independent of whether any catalog quantity attribute exists or resolves.

### 5. Catalog quantity attributes are never proactively asked, but remain answerable

Aryx no longer asks about a catalog quantity attribute (e.g. `quantityVX650ItemType_astro`) as a
pending variable on its own initiative — `session.product_quantity` is the default, proactive
source of truth for "how many." But a catalog quantity attribute is a real, options/constraint-
backed field a specific accessory may genuinely need — it isn't deleted or made unreachable. It's
only ever touched when the customer's own message clearly names that specific item (step 3, case
1) or explicitly picks it via the disambiguation question (step 3, case 2) — never asked
unprompted, never guessed.

## Critical Files

- `src/aryx/cpq/state.py` — new `CpqSession.product_quantity` field.
- `src/aryx/cpq/engine.py` — new quantity-extraction helper (free text → int).
- `src/aryx/api/ask_api.py` — early quantity-question/change routing; summary line addition;
  exclusion of the catalog quantity attribute from the conversational pending-question path.
- `tests/test_cpq_session_product_quantity.py` (new) — unit tests per the plan below.

## Testing Plan

1. **Extraction**: each supported phrasing ("50 in qty", "qty of 50", "50 units", "i want 50",
   "50 radios") sets `session.product_quantity` to the correct integer; an unrelated number in the
   message (e.g. a model number) does not get mistaken for quantity.
2. **Default**: a fresh session with no quantity ever mentioned reports `product_quantity == 1`.
3. **Routing**: a quantity question ("what's my quantity") answers directly from
   `session.product_quantity` without touching `session.pending_variables` or the catalog
   attribute pipeline at all, when no competing catalog quantity attribute is in play.
3a. **Disambiguation — named item**: "how many VX650 mics" or "set the battery quantity to 3"
    routes directly to the matching real catalog attribute, no clarifying question, even when a
    catalog quantity attribute also exists.
3b. **Disambiguation — ambiguous**: a bare "what's the quantity" WITH a real catalog quantity
    attribute currently visible/governed triggers the clarifying question naming both options
    (overall product quantity vs. the specific catalog attribute's display label) instead of
    guessing either way.
3c. **Disambiguation — no competing attribute**: a bare "what's the quantity" with no catalog
    quantity attribute currently in play resolves directly against `session.product_quantity`,
    no clarifying question (nothing to disambiguate against).
4. **Change**: "change quantity to 20" updates `session.product_quantity` in place, the same
   session field, not a new/duplicate entry.
5. **Summary inclusion**: `_cpq_summary_text` output contains the quantity line once a product is
   selected, at any value including the default 1.
6. **JSON exclusion**: `build_payload`'s output never contains `product_quantity` or any key
   derived from it, regardless of value — regression-locked so a future change can't accidentally
   reintroduce it into `configData`.
7. **Regression**: full `-k cpq` suite — confirm no existing attribute-answering test's behavior
   changes; only the catalog quantity attribute's own conversational path is affected.

## Verification

1. Unit tests above, all passing.
2. Full regression suite — same pre-existing failures only, no new ones.
3. Live verification: replay the real conversation that surfaced this bug (order request
   containing "50 in qty" → confirm `product_quantity` is set from turn 1 without being asked;
   ask "what's my quantity" mid-conversation → confirm it answers from the session value; ask to
   change it → confirm it updates; reach "Configuration complete" → confirm the summary shows
   quantity and the JSON payload does not).
4. Rebuild, redeploy, live-verify — same discipline as every other fix this session.

## Verification results (implemented and live-verified, 2026-08-11)

Implemented as planned, with one deliberate deviation from the original design: the
product-vs-catalog-attribute disambiguation judgment call (plan step 3) is NOT keyword-matched.
Discussed live with the user — this codebase already has an established "small, single-purpose
LLM helper" pattern for exactly this kind of judgment call (`_llm_resolve_label_collision`,
`_llm_split_compound_change_and_question`), used instead of either a fragile regex heuristic or
the big generic intent gateway (whose schema structurally can't represent "the overall product
quantity" at all — it only ever names real `ConfigAttr` variable_names). New helper:
`_llm_resolve_quantity_target` (`ask_api.py`), called only when a real competing catalog quantity
attribute exists; with none, resolution is fully deterministic and free.

**Bonus fix, same investigation:** while wiring this in, found and fixed a stale test —
`test_llm_first_gate_calls_the_llm_and_dispatches_when_enabled` (one of the 3 pre-existing
failures tracked all session) was patching `aryx.api.ask_api.llm_runtime.chat`, but the real
LLM-first gateway (`intent_gateway.classify_intent`) calls `aryx.llm.complete_text` directly and
never touches `llm_runtime` at all — the mock silently intercepted nothing, and a real unmocked
LLM call resolved the turn underneath the test. Also fixed a second, compounding issue in the same
test: its fake JSON reply used an outdated schema shape (`category`/`target`) instead of the real
current one (`intent_category`/`variable_name`/`value_ref`/`evidence_span`), which failed schema
validation and silently fell through to the deterministic detector on retry. Both fixed; all 3
tests in that group pass now.

**Further pre-existing test debt cleaned up in the same pass** (both were stale test fixtures, not
real bugs — confirmed by tracing each to its exact failure point):
- `test_run_cpq_turn_mines_history_before_country_gate` — mocked `load_product_config` to return
  an empty attrs list, which correctly triggers `_run_cpq_turn_inner`'s own deliberate
  `if not attrs: return {}` bailout ("no CPQ data in graph, fall through to standard Ask"),
  making the test's own assertions about session state unreachable regardless of whether history
  mining worked. Fixed by giving the mock one real minimal attr.
- `test_plain_family_reply_still_anchors_normally` — never mocked `list_ingested_families` or
  `_persist_cpq_history`, so it hit a real graph/DB call against a bare `object()` reader and an
  unreachable Postgres pool (this sandbox has no network). Fixed by adding the same mocks the rest
  of that test file already uses.

**Unit tests**: 17 new tests in `tests/test_cpq_session_product_quantity.py` covering extraction,
the cheap pre-filter, the LLM disambiguation helper (including a never-guess rejection test for an
invented variable name), session defaults/round-tripping, and 8 end-to-end `_run_cpq_turn`
scenarios (opening-message capture, direct read, change, named-attribute fall-through, ambiguous
disambiguation, and the structural JSON-exclusion guarantee).

Two hangs were hit and fixed during test development — both pure test-setup gaps (missing the same
`_persist_cpq_history`/DB-loader mocks every other test in this codebase already applies), not
bugs in the feature; diagnosed via `faulthandler.dump_traceback_later` against a real Postgres-pool
connection attempt.

**Full `-k cpq` regression**: 906 passed, 0 failed (up from 887 passed / 2 pre-existing failures at
the start of this fix) — both previously-known pre-existing failures are now fixed as part of this
same pass, and the LLM-first-gate test fix separately confirmed the third of the session's original
3 known failures. 13 unrelated collection errors remain (`datetime.UTC` Python-version import issue
in ingestion modules, nothing to do with CPQ).

**Live verification** (real conversation, workspace 39005, exact reproduction of the original bug):
1. Opening message "...radios 50 in qty..." → `session_data.product_quantity == 50` from turn 1,
   never asked.
2. Configuration completed normally through product selection; quantity survived unchanged.
3. Confirmed `product_quantity` and no `"50"` value anywhere in the real JSON payload
   (`configData`) — structural guarantee held.
4. "what is my quantity" mid-conversation → answered directly (`**Quantity** → 50`,
   `tools_called: ["cpq_product_quantity()"]`), no LLM call (no competing catalog attribute for
   this product).
5. "change quantity to 75" → `session_data.product_quantity` updated to `75`.

Rebuilt and redeployed (`docker compose build api` / `up -d --force-recreate --no-deps api`),
confirmed healthy, all live checks above run against the redeployed container.

Still uncommitted, pending explicit go-ahead to commit and push.
