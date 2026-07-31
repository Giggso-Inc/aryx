# APX NEXT Single Band — Configuration Consistency Review

Source: `config_consistency_issues_2026-07-30.pdf` (aSTRO25_bom, US quote,
post-cascade attribute audit). Each of the 3 reported issues was verified
directly against the real ingested catalog and current code before any fix
was designed — two of the PDF's own root-cause guesses needed correcting.

---

## Issue 1 — Cascade-invalidated attributes survive into the final "complete" state

**Status: root-caused and fixed at its confirmed mechanism, live-verified.**

Changing Frequency Bands to VHF wrote the value to
`modelSelectionFrequencyBandMsl_astro` — an attribute the catalog's own
hiding rule (`hideFrequencyBandModelSelectionAttributeForAPXNEXTXEMULTIModel`)
gates OFF for Single-Band products — instead of the correct
`modelSelectionFrequencyBands_astro`. The engine announced the OLD values
as "removed," but the final state table and payload still showed them
unchanged, because the write never actually landed on the attribute the
product-family logic reads.

### 1.1 Root cause, confirmed against the exact reported transcript

The PDF's own screenshot shows the actual mechanism: "add VHF (136-174
MHz) as frequency bands" triggered a 7-item "Which attribute did you
mean?" disambiguation — a numbered list mixing genuinely unrelated
attrs ("Add SVX Video Wireless Remote Speaker Microphone", "Extend Range
to 762-764 MHz") alongside **both** the correct
`modelSelectionFrequencyBands_astro` (#6) **and** the hidden-for-this-
product `modelSelectionFrequencyBandMsl_astro` (#7) — offered side by
side as equally valid choices.

That prompt format ("Which attribute did you mean? Reply with the name
or the number:") is built by `_ground_clarify_candidates` /
`_grounded_clarify_prompt` (`ask_api.py`), reached from the LLM-first
gateway's `clarify`/`AMBIGUOUS` paths via `_set_pending_clarify_and_answer`
(3 call sites: `_dispatch_intent_result`, and twice in
`_run_cpq_turn_inner`'s gateway-dispatch block). This candidate builder
scores every attr in the catalog by word-overlap against the utterance —
it never checks whether a matched attribute is currently **hidden** for
this product under active hiding rules. A hidden, lexically-similar
attribute remains a fully valid, indistinguishable candidate.

### 1.2 Fix — deterministic, live-verified

`_ground_clarify_candidates` gained an optional `hidden_vns: set[str] |
None = None` parameter — any attribute in that set is skipped entirely
before any overlap scoring runs, never offered as a candidate regardless
of how well it matches. `_set_pending_clarify_and_answer` threads this
through. All 3 call sites now compute `hidden_vns` via the same
`apply_hiding_rules(attrs, session.filled, hiding_rules, bml_eval)[2]`
already used everywhere else in the engine for this exact purpose — no
new hiding-evaluation logic, just reusing it one step earlier in the
pipeline than before.

This is a pure candidate-filtering fix — deterministic, not an LLM
concern, since "is this attribute hidden right now" is a hard rule-engine
fact, not a language-understanding question. Where genuine ambiguity
remains *after* this filtering (2+ still-visible attrs both plausible),
the existing LLM-first disambiguation (`_llm_classify_pending_clarify_reply`,
already covering this) is unchanged and continues to own that decision.

**Live-verified**: new test proves a hidden attribute is excluded from
`session.pending_clarify_vns` while genuinely visible candidates survive
correctly — confirmed against the exact reported scenario (Single-Band
product, VHF change, Msl variant hidden by a real `HidingRule`).

The snapshot-mismatch half of this issue (narration says "removed," final
state disagrees) was a downstream symptom of the write landing on the
wrong attribute — the correct attribute's dependents were never actually
invalidated because the "change" never touched it. No separate fix is
needed for the mismatch itself once the write lands on the right attribute.

---

## Issue 2 — Software Bundles: only 1 of ~24 real options surfaced

**Status: closed via live repro — confirmed catalog-correct, not a bug.**

The PDF's own root-cause guess ("the Q&A handler returns the customer's
current answer instead of the options list") does not hold up against the
actual code: `_handle_cpq_qa`'s options-query fast path correctly calls
the same `apply_constraint_rules` used everywhere else in the engine — it
is not substituting the current value for the option list.

### Live repro (`evaluate_rules_loop` run against the real catalog, workspace 3)

Ran the exact reported order (`productSelectionProduct_all = "APX NEXT
SINGLE BAND"`) through the real rule loop with real hiding/recommendation/
constraint rules and a real BML evaluator:

```
Bundle Type final value: STANDARD BUNDLE   (source: "rule" — a real recommendation rule fired)
Software Bundles constrained allowed set: ['CORE BUNDLE']
```

**Confirmed, definitively: 1 option is correct catalog behavior for this
exact order.** A real recommendation rule (not first-by-order guessing)
sets Bundle Type to STANDARD BUNDLE for this product/base-model
combination, and the separate declarative *"Validate Config Scenario for
APX Next"* rule then correctly narrows Software Bundles to exactly
`["CORE BUNDLE"]` when Bundle Type is STANDARD. Both steps are
deterministic, catalog-authored, and fired exactly as designed.

The PDF's own comparison evidence (the "5 real options" the native UI
supposedly shows) carries its own caveat: *"Recreated... not a captured
screenshot for this specific transcript, since none was supplied with
it."* That comparison is from a **different session's** configuration
state (a different Bundle Type value), not this order — so there was
never actual positive evidence of a discrepancy, just two non-equivalent
screenshots being compared as if they were the same order.

**No code fix needed or made for this issue.**

### A real, separate, minor gap this repro surfaced — see §Issue 2b below

The live repro's own logs showed a genuine (but unrelated to this
symptom) Tier-1 BML parsing gap on adjacent bundle-constraint scripts —
fixed below.

---

## Issue 2b — BML Tier-1 parser rejected a fully-literal `|^|`-delimited concatenation as "unparseable"

**Status: fixed, live-verified.**

While reproducing Issue 2, the live run logged repeated warnings for
several *other* script-backed constraint rules on adjacent bundle
attributes:

```
cpq: Tier-1 _branch_values found a returnVal assignment whose right-hand
side continues past the pipe-delimited literal list (string
concatenation) — treating as unparseable rather than returning a
truncated value. matched='retVal = "CORE BUNDLE" '
body='retVal = "CORE BUNDLE" + "|^|" + "SECURITY BUNDLE" + "|^|" + ...'
```

### Root cause

These real APX Next scripts build a `|^|`-delimited allowed-value list
via **string concatenation** — `"CORE BUNDLE" + "|^|" + "SECURITY
BUNDLE" + "|^|" + ...` — a different authoring style than
`_split_pipe_caret_values`'s existing single-literal case
(`"A|^|B|^|C"`, one packed string). `_branch_values`'s existing
concatenation guard (`bml.py`) correctly bails as "unparseable" whenever
anything continues past the first matched literal with a `+` — a
deliberate, correct safety net for a **genuinely dynamic** chain (its
own docstring's motivating case: a real variable like `link` mixed into
an HTML-building script, which truly can't be resolved statically). But
this `|^|`-concatenation shape isn't dynamic at all — **every single
term in the chain is a quoted string literal**, nothing else. It's fully
statically resolvable; it was just authored with `+` instead of one big
string, and the existing guard couldn't tell the two cases apart.

### Fix

New `_literal_concat_values()` helper (`bml.py`): before giving up as
unparseable, checks whether the ENTIRE right-hand-side (captured via a
new full-chain regex, not just the first fragment) consists *only* of
quoted-string literals joined by `+` — no variables, no function calls,
nothing else. If so, extracts every literal and filters out pure
delimiter tokens (`|^|`, `|`), returning the real values. If the chain
contains anything else at all (a variable, a function call), it still
falls straight through to the original warning/unparseable path,
unchanged — the safety net this guard exists for is fully preserved.

Wired into both places `_branch_values` already had this exact
concatenation-tail check: the `retVal = ...` assignment idiom and the
direct `return "...";` idiom.

**Live-verified**: re-ran the exact live repro — the warnings are gone,
and the final Issue 2 outcome (`['CORE BUNDLE']`) is unchanged, confirmed
via `docker exec` against the running container. 4 new tests
(`tests/test_cpq_bml_bool_literal_and_return_string.py`): the real
`|^|`-concatenated `retVal`/`return` shapes now resolve correctly; a
genuine variable or function call mixed into the chain still correctly
returns `None` (the original SVX HTML-building safety case, unchanged).
17/17 in that test file, 42/42 across the broader BML/recommendation/
label-collision sweep.

---

## Issue 3 — Wireless Carrier wrongly pulled into a "Frequency Bands" label-collision prompt

**Status: fixed, live-verified.**

### 3.1 Root cause, confirmed

"What are the Frequency Bands and Wireless Carrier available?" triggered
a 3-way disambiguation ("There are 3 different attributes labeled
'Frequency Bands'...") that wrongly included `wirelessCarrier_astro` —
whose real label, "Wireless Carrier," shares zero tokens with "Frequency
Bands" and is not ambiguous at all.

`CpqEngine.detect_label_collision` (`engine.py`) computed:

```python
label_matches = [attr for attr in attrs if attr.display_label.lower() in q_lower]
distinct_vns = {a.variable_name for a in label_matches}
if len(distinct_vns) >= 2:
    return label_matches
```

This counts **all** attrs whose own (individually unambiguous) label
happens to appear anywhere in the question, then treats "2+ different
variable_names matched" as proof of a shared-label collision. It never
checks whether those matches actually **share one label** — a compound
question correctly and unambiguously naming 2+ *different* attributes
("Frequency Bands" **and** "Wireless Carrier") was indistinguishable, by
this check, from a genuine collision (one label, 2+ attrs). The
prompt's own claim — "3 different attributes labeled 'Frequency Bands'"
— was itself inaccurate: only 1 of the 3 actually had that exact label
text (the other two were "Frequency Band" [singular, a different
attribute] and "Wireless Carrier").

### 3.2 Fix — deterministic (no LLM needed for the collision check itself)

`detect_label_collision` now groups `label_matches` by **exact label
text** first, and only reports a collision when **one label** maps to 2+
distinct variable_names:

```python
by_label: dict[str, list[ConfigAttr]] = {}
for a in label_matches:
    by_label.setdefault(a.display_label.lower(), []).append(a)
for group in by_label.values():
    if len({a.variable_name for a in group}) >= 2:
        return group
return None
```

This is a pure grouping-key bug — genuine label collisions are a hard
catalog fact (does this label string literally repeat across attrs?),
not a language-understanding problem, so a deterministic fix is both
correct and cheaper than an LLM call here. Every existing collision test
(shared "Mounting Type" across 2 attrs, etc.) still passes unchanged.

### 3.3 Fix — LLM-first compound-attribute answer (the "more robust" half)

Fixing the grouping bug alone stops the wrong 3-way prompt, but
`detect_attr_query` (the single-attribute fast path reached next) only
ever returns **one** best match — so the response would still silently
answer just "Frequency Bands" and drop "Wireless Carrier" entirely.

New `_llm_split_multi_attr_options_query()` (`ask_api.py`): gated behind
a cheap options-keyword + conjunction pre-check (so the overwhelming
majority of ordinary single-attribute questions never pay this call),
scoped to `_relevant_intent_candidates`' own word-overlap narrowing
(`fallback_to_full=False` — nothing plausibly relevant means nothing to
split), asks the LLM whether the message names 2+ genuinely different
attributes and, if so, splits it into that many self-contained
per-attribute questions. LLM-first rather than pure label-substring
matching so this also generalizes to paraphrased/synonym attribute
mentions a literal check would miss — same reasoning that moved the
earlier change+question compound-detection work
(`_llm_split_compound_change_and_question`) off deterministic splitting.

Each split sub-question is resolved through the **same**
`detect_attr_query` + constrained-options logic as the single-attribute
path (factored into a new shared helper, `_build_attr_options_text`, so
there's exactly one place that computes "options for X, constrained to
what's currently active" — not two copies that could drift). Answers are
concatenated into one response. Falls through to the unchanged
single-attribute fast path whenever fewer than 2 sub-questions actually
resolve to a real attribute.

**Projected response after this fix**, for the exact reported question:

> *"The available options for **Frequency Bands** are: [8 items]*
> *The available options for **Wireless Carrier** are: [4 items]"*

— both halves of the compound question answered in one turn, instead of
either the wrong 3-way disambiguation or a silently incomplete
single-attribute answer.

**Live-verified**: 7 new tests — 2 at the `detect_label_collision` level
(a compound question naming 2 different unambiguous attrs no longer
false-collides; a genuine shared-label collision still fires correctly
even inside a compound question), 3 unit tests on the LLM splitter
(splits a genuine 2-attribute question, returns None for a single
attribute, fails closed on malformed LLM output), and 1 full
`_handle_cpq_qa` end-to-end test proving both attributes get answered in
one turn. 125/125 in the targeted suite (label-collision, replacement-
clause, intent-gateway, negative-harden, ask-route-fewshots test files).

---

## Issue 6 (FedRAMP Yes→No, carried over from `docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md` §16) — fixed generically.

Originally tracked in the other doc as inconclusive, then narrowed to a
strong, evidence-backed hypothesis (§16: real recommendation rules exist
that set `isFedRampRequired_astro` to "NO", and `auto_fill`'s own
docstring documents a known "first-by-order claimed it first" race that
could plausibly explain the Yes→No flip). This section closes it with a
generic fix, not a one-off patch for this single attribute.

### 6.1 The design tension, resolved

`CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1` deliberately chose to only
**detect**, never **correct**, a recommendation-governed value that drifts
out of sync with its own rule — *"the engine can't be certain what the
correct value should have been [for a customer's choice], so silently
changing it risks overwriting a real customer decision."*

That reasoning protects customer choices. It does not apply to a value
the **engine itself** auto-filled before its own driving attribute had a
value to check against — re-running the *same deterministic rule* with
fresher inputs isn't a guess, it's finishing a computation that fired too
early. The existing detection code (`find_rule_inconsistencies`) already
draws exactly this line — it skips `filled_source == "user"` — the fix
below reuses that identical boundary, just to correct instead of only log.

### 6.2 Fix — a general resync, not a FedRAMP-specific patch

New `CpqEngine.resync_stale_recommendations()` (`engine.py`): re-applies
every recommendation rule to attrs already in `filled`, using the exact
same condition-evaluation logic `apply_recommendation_rules` uses for
*unfilled* attrs. Corrects the value only when:
- the attr is already filled (unfilled attrs stay `apply_recommendation_
  rules`' job, never this one's), **and**
- `filled_source` is NOT `"user"`, `"hint"`, or `"cascade"` — anything
  that traces back to the customer is untouched, **and**
- the rule's condition now holds and its recommended value differs from
  what's currently filled.

Wired into `evaluate_rules_loop`'s existing fixed-point iteration
(hide → recommend → **resync** → constrain → auto-fill, until stable) —
not a separate one-off pass, so a correction here can itself cascade
through further iterations exactly like any other rule effect already
does. The loop's own stability check was extended so a resync correction
always forces at least one more pass, even when the filled key-set itself
didn't change (a resync only ever changes a *value*, never adds/removes a
key).

This generalizes the fix: **any** recommendation-governed attribute that
was engine-derived and gets stranded stale by fill-order will now
self-correct on the next full rule-loop pass — not just FedRAMP.

**Live-verified**: 6 new tests (`tests/test_cpq_recommendation_resync.py`)
— the exact FedRAMP shape corrects properly; `user`/`hint`/`cascade`
sources are all confirmed untouched even when stale; already-in-sync and
not-yet-filled attrs are correctly no-ops; and a full `evaluate_rules_loop`
integration test proves the correction happens within the real rule loop,
not just the standalone method.

---

## Issue 4 — Repeated re-ask loop: the same Frequency Bands question asked three times

**Status: primary loop cause fixed and live-verified. Two narrower,
independent bugs found as side effects — one retracted (not a real bug),
one confirmed and fixed. See "Follow-up investigation" below.**

### What the PDF got right and wrong

The PDF's own root-cause guess (a recommendation rule re-deriving
Frequency Bands from a stale `packageChoiceString`) does **not** hold up
against the code: every write path that lands a customer's disambiguation
reply (`ask_api.py`'s STEP 5 answer-lock, `_handle_cascade`) tags it
`filled_source="user"`, and both `apply_recommendation_rules` and this
doc's own Issue 6 fix (`resync_stale_recommendations`) explicitly refuse
to touch `user`/`hint`/`cascade`-sourced values. That mechanism cannot
revert a confirmed customer answer — confirmed by direct code trace, not
just inspection.

### Real root cause (live-reproduced against the running container)

Direct catalog dump, workspace 3: **"VHF" is a legal option value on all
four** of `modelSelectionFrequencyBands_astro` (Frequency Bands),
`modelSelectionFrequencyBandMsl_astro` (Frequency Band), `modelSelection
PrimaryFrequency_astro`, and `modelSelectionSecondaryFrequency_astro`. Msl
isn't hidden for "APX NEXT SINGLE BAND" specifically — the catalog's own
hiding rule ("Hide Frequency Band for Single Band") matches the exact
string `"APX NEXT SINGLE"`, not `"...SINGLE BAND"` — a real catalog-data
quirk, not a bug in this doc's Issue 1 fix.

Once the customer explicitly resolves an ambiguous "which attribute did
you mean?" clarify to one of these (e.g. "Frequency Bands"), that
resolution was never remembered. A later bare-value reply ("VHF"/"UHF"),
or even "confirm" itself, re-triggers a **fresh** 4-way clarify every
time — live-reproduced exactly: the same prompt repeats turn after turn,
"confirm" gets swallowed as a failed disambiguation attempt, and the
LLM fallback (`_llm_classify_pending_clarify_reply`) has no visibility
into each candidate's own option domain, so it can't break the tie either
and returns "unclear" forever.

### Fix — remember the resolved attribute, use it as a tie-breaker

`CpqSession` gained `last_clarified_attr_vn` / `last_clarified_turn`,
set in `_apply_pending_clarify_resolution` every time a clarify actually
resolves. Two call sites now consult it:

- `_match_pending_clarify_reply` (an **active** pending clarify's reply):
  after the existing name/label/index/containment tiers, a new
  anchor-aware value tier resolves directly to the remembered attribute
  if it's among the candidates and the reply is one of *its* real option
  values; otherwise falls back to a plain unique-value match (only when
  exactly one candidate accepts the value — never guess across a shared
  value with no anchor).
- `_set_pending_clarify_and_answer` (building a **fresh** clarify): the
  same anchor check runs before a new clarify is even created, so a bare
  value reply that would otherwise re-derive the identical 4-way ambiguity
  resolves immediately instead.

`_set_pending_clarify_and_answer` needed `hiding_rules`/`rec_rules` added
to its signature (all 3 call sites already had them in scope, used for
Issue 1's `hidden_vns` computation) to actually replay the resolved
attribute via `_apply_pending_clarify_resolution`.

**Live-verified**: re-running the exact transcript against the container
with the anchor seeded, Turn 3's reply now correctly narrows straight to
"Which value would you like for Frequency Bands? 1. VHF 2. UHF" instead
of the 4-way clarify. 3 new unit tests
(`tests/test_cpq_2026_07_28_fixes.py`): anchor breaks a 4-way tie end to
end via `_dispatch_intent_result`; without an anchor, a value shared by
2+ candidates still correctly stays ambiguous (never guesses); without an
anchor, a value unique to one candidate still resolves normally.

### Follow-up investigation (2026-07-30, second pass)

1. **"Raw, unvalidated literal write" — RETRACTED, not a bug.** Direct
   catalog dump confirms `"VHF (136-174 MHz)"` is a real, distinct,
   literal `item_value` on `modelSelectionFrequencyBands_astro` — a
   separate, more specific catalog option from plain `"VHF"` (the
   catalog also carries `"UHF (403-470 MHz)"`, `"900 (896-940 MHz)"`,
   etc. as their own distinct codes alongside the bare bands). Direct
   test against the real attribute confirms `apply_answer` correctly
   matches the customer's exact phrase to this real option — it is not
   bypassing validation, it's validly picking the more specific of two
   real choices. The same-turn "Updated → VHF (136-174 MHz)" then
   "Removed VHF (136-174 MHz) — no longer valid" sequence is therefore a
   real, subsequent cascade/constraint narrowing (same class as Issue 1's
   already-documented, correctly-behaving narrowing), not a validation
   bypass — the exact rule that narrows it away wasn't pinned down this
   pass, but the earlier "bypasses `apply_answer`" framing was wrong and
   is withdrawn. Matches this session's Issue 2 precedent: a PDF/earlier
   theory that doesn't survive direct verification gets retracted, not
   patched around.

2. **Wrong-sibling write despite a correctly-pending attribute — CONFIRMED, now FIXED.** After
   the Issue 4 fix correctly narrows to "Frequency Bands — choose one:
   VHF/UHF" with `session.pending_variables = ["modelSelectionFrequency
   Bands_astro"]`, the next turn's plain "UHF" reply was live-observed
   landing in `filled_multi["modelSelectionFrequencyBandMsl_astro"]`
   instead — the wrong, sibling multi-select attribute — even though
   Bands was correctly the sole pending variable and Bands' own option
   list contains a matching value. Root cause not yet isolated; likely
   the LLM-first gateway classifying the bare reply as a fresh,
   context-free message before STEP 5 ever consults
   `session.pending_variables`. Needs its own live-repro-then-fix pass.

   **Root cause, confirmed by code trace:** `_run_cpq_turn_inner`'s
   LLM-first mid-session gateway block (`ask_api.py` ~line 6098) runs
   *before* "STEP 5: Lock user's answer from previous turn" (~line
   6681), and its guard condition
   (`cpq_llm_first_enabled and not guided_mode and not
   top_level_route_used()`) has **no check for
   `session.pending_variables`** at all. So even when a single-select
   question is actively pending (Bands, in this case), a bare reply like
   "UHF" is still classified by the gateway first — context-free, with no
   awareness that a specific attribute is already waiting on exactly this
   reply — and if the gateway confidently dispatches it as a fresh
   `CHANGE_REQUEST`/`CHANGE_REQUESTS_MULTI` naming a *different but
   plausible* attribute (Frequency Band/Msl also legally accepts "UHF"),
   it writes there and STEP 5 never even sees the turn. This is the same
   *shape* of bug STEP 5's own `_looks_like_new_request` guard already
   defends against for its own domain (a bare reply must not be
   reinterpreted as a fresh request without a clear change-verb/arrow
   signal) — the gateway has no equivalent guard.

   **The gateway hypothesis above was only half the picture.** A gate on
   `session.pending_variables` was added to the gateway (`ask_api.py`,
   via a new shared `_pending_reply_looks_like_new_request()` helper also
   used by STEP 5's own pre-existing answer-lock, removing the prior
   duplicated logic) — but re-running the exact live transcript afterward
   showed the **identical** misrouting persisted unchanged. Tracing the
   actual call stack (a live `traceback.format_stack()` dump on
   `_handle_cascade`, not further static reading) showed the write wasn't
   coming from the gateway at all — it came from a *separate*,
   unconditional deterministic "mid-config change request" block further
   down in `_run_cpq_turn_inner`, which the gateway's own gate never
   touched.

   **Actual root cause, confirmed live:** `CpqEngine._change_request_matches`
   (`engine.py`) — the shared scan behind `detect_change_request`/
   `detect_change_requests_multi` — decides whether an attribute is
   "already filled" (and therefore an eligible implicit target) using
   `attr.variable_name in filled_multi` — **dict KEY presence**, not
   whether the multi-select actually holds a selection. `auto_fill`/
   hiding-rule evaluation seeds nearly every multi-select attribute in a
   real catalog with an empty `[]` entry whether the customer ever
   touched it or not — confirmed live by dumping the session state:
   `modelSelectionFrequencyBandMsl_astro` sat in `filled_multi` as `[]`,
   never selected by the customer at any point. Because `"VHF"`/`"UHF"`
   are also real option values on that untouched multi-select, a bare
   reply meant to answer the correctly-pending single-select
   `modelSelectionFrequencyBands_astro` matched Msl instead, through this
   generic scan — a completely different code path from either the
   gateway or STEP 5, running unconditionally before both.

   **Fix:** an empty (never-selected) multi-select now only stays
   eligible for an implicit change-request match when explicitly named by
   its own label/variable_name — a bare, unnamed value-only mention now
   requires the multi-select to already hold a real selection. A first
   attempt at this fix was too broad (excluded ANY empty multi-select
   unconditionally) and broke a real, pre-existing, correctly-tested case
   — `tests/test_cpq_grid_decline.py`'s "I wanted to include the mounting
   type: X" after an explicit decline — caught by the existing regression
   suite (`test_change_request_detected_on_declined_multi` failed) before
   this reached anyone; corrected to the label/name-explicit exception
   above.

   **Live-verified, end-to-end, twice** (once per fix iteration) against
   the real running container and catalog: the exact reported transcript
   (order APX NEXT Single Band for United States, confirm, answer the
   Carry Type + Frequency Bands stale-constraint reasks) now completes
   cleanly to `status=post_approval, complete=True`, with no repeated
   questions and the real `modelSelectionFrequencyBands_astro` attribute
   correctly holding `"VHF"` — not the sibling Msl multi-select.
   150/150 tests pass across the affected CPQ test files (excluding the
   one pre-existing, unrelated DNS-resolution failure confirmed
   throughout this whole session:
   `test_llm_first_gate_calls_the_llm_and_dispatches_when_enabled`).
   Shipped on `fix/cpq-frequency-band-multiselect-collision`.

---

## Issue 7 — A brand-new, completely default order fails its own BOM-gate on the first confirm

**Status: root-caused and fixed, live-verified.**

### Problem statement

After the Issue 4 fix above, a customer reported *still* hitting a
stale-constraint reask on the very first `confirm` of a totally vanilla
order — no explicit frequency-band request, no mid-config edits, just
"i want to order APX Next radios for destination country United States" →
pick "APX NEXT Single Band" → `confirm`:

> **Frequency Bands** is currently *700/800 MHz*, which isn't valid
> anymore given your other choices...

This is a different symptom from Issue 4: there's no repeated question
and no wrong-attribute write here — the config only ever asks about
Frequency Bands *once* per order — but it shouldn't need to ask about it
**at all**, since nothing about Frequency Bands was ever touched. Every
single default APX NEXT Single Band order hit this same extra,
unnecessary correction round-trip.

### Root cause, confirmed live — a real catalog data typo, not a logic bug

Dumping the full `filled` state right before the failing `confirm` and
calling `apply_constraint_rules` directly against it isolated the exact
rule responsible: **"Constrain for APXNEXTSINGLE & APXNEXTXNSINGLE"** — a
plain declarative constraint rule (no BML script involved) whose allowed-
value list is pulled straight from the raw catalog data. Its authored
list is:

```
['UHF', 'VHF', '700/800 MHz']
```

— note the lowercase `z`. Every real menu item for
`modelSelectionFrequencyBands_astro` elsewhere in the catalog spells this
value `"700/800 MHZ"` (uppercase Z). `bom_gate.py`'s stale-constraint
check (`recheck_constraints`) does a plain, case-sensitive
`current not in allowed` comparison, so the correctly-defaulted
`"700/800 MHZ"` value never matched the rule's own `"700/800 MHz"` entry
and was flagged as stale on every order, unconditionally — regardless of
anything the customer did.

This is a genuine authoring inconsistency in the source BigMachines/
Oracle CPQ catalog data itself (confirmed by direct comparison against
the attribute's real menu items) — not something fixable at the source
from this codebase, and not a "cascading defaults don't converge" issue
as first suspected.

### Fix

`CpqEngine.apply_constraint_rules` (`engine.py`) now normalizes every
rule's allowed-value list back to the attribute's real, canonically-cased
catalog `item_value` (case-insensitive lookup against `target.options`)
before intersecting — for both script-derived and declarative allowed
lists. A value with no matching real catalog option (a genuinely unknown
value, not just a casing variant) passes through unchanged rather than
being silently dropped or invented.

**Live-verified**: re-running the exact reported transcript, Frequency
Bands is no longer flagged at all — the vanilla order needed only the
one remaining Carry Type correction after this fix (see Issue 8 below
for why that one *also* turned out to be fixable, and the resulting
zero-correction outcome). 4 new unit tests in
`tests/test_cpq_constraint_value_casing.py` (mismatched-casing value
still matches; correctly-cased rules unaffected; multi-rule intersection
still works after normalization; a genuinely unknown value is never
invented or silently accepted). Shipped alongside Issue 4's fix on
`fix/cpq-frequency-band-multiselect-collision`.

---

## Issue 8 — The catalog's own generic default_value can be invalid for the selected product, and nothing corrected it before asking

**Status: root-caused and fixed, live-verified.**

### Problem statement

After Issue 7's fix removed the false Frequency Bands flag, the customer
asked a sharper follow-up question: since the product is already known
by the time defaults get filled, why does the engine ever lock in a
default value that isn't even valid for that product in the first place
— shouldn't it pick a real, valid option automatically instead of
forcing a correction round-trip?

### Root cause, confirmed by direct code trace

`CpqEngine.auto_fill`'s default-value step (`engine.py`, "3. Default
value") applies the catalog's raw XML `default_value` **unconditionally**
— it never checks the attribute's currently-active constrained allowed
set at all:

```python
if not value and _valid(attr.default_value) and not _is_pointer_default(attr):
    value = attr.default_value
```

A later step in the *same* function (a few lines down) already does the
right thing for rule-governed attributes: filter the option list by the
active constraint, then pick the first remaining option by menu order —
exactly the "auto-select a real, valid default" behavior the customer
was asking for. But that step is gated on `if not value`, and by the
time execution reaches it, `value` is already set from the unconditional
default step above — **the correct, constraint-aware logic never gets a
chance to run**, because the invalid default already won.

For Carry Type specifically: the catalog's generic default
(`"2.0 INCH / 5.08 CM (STANDARD)"`) is locked in immediately, even though
it's excluded by "Constrain for APXNEXTSINGLE & APXNEXTXNSINGLE" (Issue
7's own finding) for this exact product.

### Fix

Added a check to the default-value step: if `constrained_opts` has an
entry for this attribute and the raw `default_value` isn't in it, skip
locking in the default and fall through — letting the existing,
already-correct constraint-aware fallback pick the first valid option by
catalog menu order instead. No new selection logic was written; this
only stops a known-bad value from winning the race before the correct
logic runs.

Scoped deliberately narrow: this fallback only auto-picks for
**rule-governed** attributes (`is_governed`) — an excluded default on an
*ungoverned* attribute still falls through to asking the customer,
unchanged (verified by `test_ungoverned_attr_with_excluded_default_asks_
instead_of_guessing`), preserving this engine's "never silently guess"
discipline everywhere it already applies.

**Live-verified**: re-running the exact reported transcript end to end —
"order APX NEXT radios for United States" → pick "APX NEXT Single Band"
→ `confirm` — now goes straight from product selection to
`status=post_approval, complete=True` with **zero** correction
round-trips. Carry Table now shows `PLASTIC HOLSTER WITH 2.5 INCH BELT
CLIP (STANDARD)` — auto-selected as the first catalog-order option
within the constrained allowed set — exactly the value the customer
previously had to pick manually every time. 4 new unit tests in
`tests/test_cpq_default_value_ignores_active_constraint.py` (excluded
default falls through to the first valid option; an allowed default
still wins outright with no unnecessary fall-through; no active
constraint at all is fully unaffected; an ungoverned attr still asks
instead of guessing). Shipped alongside Issues 4 and 7 on
`fix/cpq-frequency-band-multiselect-collision`.

---

## Issue 9 — Regression sweep for Issues 7/8 hung indefinitely on a bare host (pre-existing test-fixture bug, not a product bug)

**Status: root-caused, confirmed pre-existing and unrelated to Issues 7/8. Fixed, live-verified.**

### Problem statement

While running the broader regression sweep to sign off on the Issue 7
and Issue 8 fixes, `tests/test_cpq_product_switch.py` hung indefinitely
instead of completing in the usual sub-second range — no output, no
crash, no timeout, just stuck. This blocked getting a clean pass/fail
signal for that file on a bare host (i.e. `pytest` run directly, not
inside the `aryx-api-1` container).

### Root cause, confirmed live

Process inspection showed the hung `pytest` process burning almost no
CPU (2s of CPU time over 20+ minutes) with all threads parked on
`futex_wait_queue` — a lock/IO wait, not a slow computation. Bisecting
file-by-file, then test-by-test, isolated it to two tests:

- `test_detect_product_mention_prefers_specific_variant_over_generic_name`
- `test_detect_product_mention_recognises_a_brand_new_product_with_no_code_change`

Both instantiate their own local engine —
```python
reader = _fake_reader_with_batch_fetch(monkeypatch, {...})
engine = CpqEngine()          # <-- a NEW instance
engine.detect_product_mention(..., reader=reader, workspace_id=1)
```
but `_fake_reader_with_batch_fetch`'s monkeypatch targets the wrong
object:
```python
monkeypatch.setattr(api._cpq_engine, "_batch_fetch", lambda ids, ws: {...})
```
`api._cpq_engine` is the module-level singleton instance used by
`_run_cpq_turn`/`ask_api.py` — patching an attribute directly on *that*
instance never affects a separate, locally-constructed `CpqEngine()`.
So the local `engine.detect_product_mention(...)` call falls through to
the **real** `CpqEngine._batch_fetch`, which calls
`get_cpq_rdb().fetch_entity_attributes(...)` — a genuine attempt to
reach the Postgres RDB. On a bare host with no route to the `postgres`
compose service, the connection attempt never resolves and never times
out on its own, hanging the test (and the whole file, and the whole
sweep) forever.

A third test further down the same file,
`test_switch_preserves_valid_country_without_reasking`, hangs for the
same underlying reason (an incompletely-mocked path that falls through
to a real network call) via a different code route
(`_run_cpq_turn`'s product-switch confirmation flow).

**Confirmed unrelated to Issues 7/8**: `git stash`-ing every uncommitted
change (the `apply_constraint_rules` and `auto_fill` fixes, both new
test files) and re-running these exact tests against clean `dev-rv`
reproduced the identical hang — this is a latent bug in
`test_cpq_product_switch.py`'s own fixtures, not a regression introduced
by this session's work. `git diff` also confirms neither fix touches
`detect_product_mention`, `ingested_product_alias_map`, or
`_batch_fetch` at all.

### Fix

Two parts:

1. `_fake_reader_with_batch_fetch` now patches `_batch_fetch` on
   **`type(api._cpq_engine)`** (the class) instead of the `api._cpq_engine`
   singleton instance, so a test that constructs its own local
   `CpqEngine()` (the two `detect_product_mention` tests) still picks up
   the mock.

2. The third hang (`test_switch_preserves_valid_country_without_reasking`)
   turned out to be a **different** real RDB call than `_batch_fetch` —
   traced live via `faulthandler` (all-thread stack dump on a running
   hung process) through THREE distinct call chains in turn, each fixed
   individually before the next one surfaced:
   `extract_flag_hints` → `_build_flag_keyword_index` →
   `PostgresCpqRdb.fetch_function_scripts`; then `load_validation_rules`
   → `_load_value_rules` → `IngestQuestionStore.list`; then
   `payload_flow_exclusions` → `_detect_layout_tier` →
   `fetch_layout_attr_assoc`. Mocking each `CpqEngine` method one at a
   time is a moving target — a fourth call site surfaced every time the
   previous one was patched, and the same gap was found independently
   affecting 3 more tests elsewhere in the same file
   (`test_confirmed_switch_seeds_product_identifier_without_reasking`,
   its `..._when_family_name_wont_match` sibling, and
   `_pending_menu_setup`'s consumers) that duplicate this same
   fake-catalog-config setup inline rather than sharing a helper.

   Rather than continuing to enumerate call sites, the fix targets the
   actual **choke point**: every `PostgresCpqRdb`/`OracleCpqRdb` method
   routes through its own `self._connection()`, and `IngestQuestionStore`
   calls `get_pool(dsn)` in `__init__` — both ultimately resolve
   `aryx.store.pool.get_pool`. A new `_block_real_rdb_access(monkeypatch)`
   helper patches `get_pool` at its two import sites
   (`aryx.store.pool.get_pool` for `rdb.py`'s lazy per-call import,
   `aryx.store.ingest_question_store.get_pool` for its module-level
   binding) to raise immediately instead of hanging on connection. This
   is safe because every `PostgresCpqRdb` method already wraps its query
   in `try/except Exception: ... return {}/[]` (the module's own
   documented contract — "Failures are logged and surface as empty
   results, never a hard error") and `_load_value_rules` wraps its
   `IngestQuestionStore` call the same way — so a fast-failing
   `get_pool` degrades exactly the way a genuinely unreachable
   production DB would, it just doesn't hang getting there. Applied at
   all 4 sites in `test_cpq_product_switch.py` that build this kind of
   fake catalog config.

**Live-verified**: full file now runs in **0.81s, 47 passed, 0 hangs**
on a bare host (previously hung indefinitely at 3+ different tests).
Broader sweep (`test_cpq_product_switch.py` + `test_cpq_pending_clarify.py`
+ the Issue 7/8 test files + 2 more thematically-related files): 77
passed, 4 pre-existing failures confirmed unrelated (the same stale
`_match_pending_clarify_reply` tuple-vs-string contract mismatch noted
below Issue 11).

### How the Issue 7/8 sign-off was actually completed (at the time, before this fix)

Re-ran the full 9-file sweep (81 tests) inside the running `aryx-api-1`
container instead, where the docker-compose network makes `postgres`
genuinely reachable — **81 passed**, including
`test_cpq_product_switch.py` in full, no hang. This is the same
container-based workaround already established earlier in this session
for the host/container Python-version mismatch — no longer necessary
for this file now that the actual fix above is in place, but still a
valid general fallback for any future, not-yet-discovered case of this
same class of gap.

---

## Issue 10 — Five attributes never get their catalog-recommended value on a vanilla APX NEXT Single Band order

**Status: root-caused (two distinct causes), not yet fixed — fix approach for the second cause deliberately deferred pending a blast-radius decision.**

### Problem statement

A vanilla APX NEXT Single Band order never picks up the catalog's own
recommended values for five attributes, even though the values are
valid, real catalog options:

| Attribute | Catalog would recommend |
|---|---|
| `operationModeType_astro` | DIGITAL TRUNKING (SMARTNET/SMARTZONE AND P25 PHASE I INTEROPERABILITY) |
| `solutionTypeDuration_astro` | 7 YEARS |
| `multikeyType_astro` | NO MULTIKEY |
| `modelSelectionHousing_astro` | BLACK |
| `secureEncryptionType_astro` | AES |

Live tracing showed these split into two unrelated root causes.

### Cause A (3 attrs: operationModeType, secureEncryptionType, multikeyType) — genuine catalog-authoring gap, not an aryx bug

All three are governed by the declarative rule **"Set Default for APX
Next"**, whose condition is:

```
productSelectionProduct_all == "APX NEXT MULTI" OR "APX NEXT XE MULTI"
```

(an 18-attribute rule also covering `beltClipType_astro`,
`antennasType_astro`, `batteryType_astro`, and others — all with the
identical condition.) This condition was authored to cover only the
**MULTI-band** product variants and was never extended to
`"APX NEXT SINGLE BAND"`. For a Single Band order the rule simply never
fires — confirmed by reading the condition's raw text directly, not a
parsing or matching bug on our side (unlike Issue 7's casing bug, the
strings here are exact and the tilde-OR list is just incomplete).

### Cause B (2 attrs: modelSelectionHousing_astro, solutionTypeDuration_astro) — a real aryx engine ordering bug

Unlike Cause A, these two attributes' governing BML **does** fire
correctly:

- Housing's paired rule **"Associated rec rule for Hide Housing
  attribute if not XE model"** — condition script explicitly lists
  `"APX NEXT SINGLE BAND"` and evaluates to `True`; recommends `BLACK`.
- Duration's script evaluates to `'7 YEARS'` given
  `solutionTypeDevices_astro == 'CLOUD RC'`.

Live-tracing `evaluate_rules_loop`'s internals confirmed both attrs get
correctly filled (`BLACK`, `7 YEARS`) in the turn's early passes. But a
**separate hiding rule** later legitimately hides each attribute for
this exact state — `"Hide Housing attribute if not XE model"` (Housing
is genuinely not customer-choosable for non-XE models) and `"Hide
Solution Type Duration if Solution Type<>Radio Management (MSI Hosted)
(Molokai)"` (a module-specific condition). Once hidden, the attribute is
correctly popped from `filled` (matching this doc's own established
"hidden attrs must not carry stale values" principle) — but
`evaluate_rules_loop` runs `apply_hiding_rules` before
`apply_recommendation_rules` on every pass, and a hidden attr is dropped
from the `attrs` list passed to recommendations. The "associated"
recommendation rule — whose entire purpose, per its own name, is to
silently backfill a BOM-payload value for an attribute the customer will
never be shown — never gets a chance to run again, because by the time
its condition would evaluate `True`, its target attribute is no longer
in the list recommendations consider at all.

This `"Associated rec rule for Hide X..."` pairing pattern (hide the
question from the customer, but still silently default the backend
value) is used **repeatedly** throughout this catalog — also seen for
Encryption Bundle LACR, Essential Core Bundle, and Essential Security
Bundle (Molokai) — so this ordering bug likely silently drops backend
defaults for other hidden attributes too, not just these 2.

### Fix — deliberately not yet applied

Three candidate approaches were discussed:
1. Run `apply_recommendation_rules` against the pre-hide attr list each
   pass, so any rule can still backfill a hidden attr's backend value.
2. Narrower: only exempt rules matching the `"Associated...Hide..."`
   naming convention from the hidden-attr exclusion.
3. Document only, decide the fix separately.

Option 3 was chosen — this is a catalog-wide behavioral change (given
how pervasive the "hide but still recommend" pattern is, a fix could
surface many previously-silent backend defaults across many attributes
and products at once), so the blast radius needs assessment before
committing to an approach.

### Verified directly against the raw source XML (`APX Next.xml`)

Both causes were cross-checked against the actual BigMachines/Oracle CPQ
export, not just the engine's parsed/ingested view of it — ruling out an
ingestion or parsing bug as the explanation for either.

**Cause A.** Rule `"Set Default for APX Next"` (`bm_config_rule id=
19435387773`) carries a single `bm_config_rule_input` condition on
`productSelectionProduct_all` (`attribute_id=39427019`):

```
value1 = "APX NEXT MULTI~APX NEXT XE MULTI"
```

— byte-for-byte the same tilde-OR list the engine parsed. Its
`bm_config_rule_action` children confirm the per-attribute recommended
values match exactly: `operationModeType_astro` (`attribute_id=
19435386979`) → `"DIGITAL TRUNKING (SMARTNET/SMARTZONE AND P25 PHASE I
INTEROPERABILITY)"`, `secureEncryptionType_astro` (`19435386991`) →
`"AES"`, `multikeyType_astro` (`19435386993`) → `"NO MULTIKEY"`. The
source data itself simply never lists `"APX NEXT SINGLE BAND"` in this
condition — confirms Cause A is a genuine catalog-authoring gap, not
anything introduced by our XML ingestion.

**Cause B.** The hiding rule `"Hide Housing attribute if not XE model"`
and `"Associated rec rule for Hide Housing attribute if not XE model"`
reference two *different* condition functions (`19435386508` and
`19435386509` respectively) — but pulling both `script_text` bodies from
the XML shows they are **byte-for-byte identical** (`script_size=168`
each, same 8-way product OR-list, both explicitly including
`"APX NEXT SINGLE BAND"`):

```
if( ((productSelectionProduct_all=="APX NEXT INTL FED") OR
     (productSelectionProduct_all=="APX NEXT XN SINGLE BAND") OR
     (productSelectionProduct_all=="APX NEXT ENHANCED") OR
     (productSelectionProduct_all=="APX NEXT MULTI") OR
     (productSelectionProduct_all=="APX NEXT SINGLE BAND") OR
     (productSelectionProduct_all=="APX NEXT INTL") OR
     (productSelectionProduct_all=="APX NEXT SINGLE INTL") OR
     (productSelectionProduct_all=="APX NEXT XN ALL"))){
    return true;
}
return false;
```

The catalog authors cloned the exact same condition into both rules so
they are guaranteed to fire together — there is no catalog-side scenario
where Housing is hidden but the `BLACK` recommendation doesn't also
apply. Separately, Duration's recommendation action (`attribute_id=
19435387025`, its own function `id=22194395116`) matches the engine's
live-evaluated script exactly:

```
if (solutionTypeDevices_astro=="RADIOCENTRAL PLUS CPS PROGRAMMING" OR
    solutionTypeDevices_astro=="CLOUD RC") { retVal = "7 YEARS"; }
```

Since the hide-condition and its paired recommend-condition are
literally identical source scripts (not just similarly-named or
similarly-scoped), this rules out any alternate reading of the rules —
Cause B is conclusively an aryx-side ordering bug in `evaluate_rules_loop`
(hidden attrs excluded from `attrs` before recommendations get a chance
to run against them), not a misconfigured or ambiguous catalog rule.

---

## Issue 11 — Compound "Frequency Bands + Wireless Carrier" change silently mis-bound to the wrong attribute

**Status: root-caused (two chained bugs), fixed, live-verified.**

### Problem statement

Live transcript: after asking "what are the Frequency Bands and Wireless
Carrier available?" (worked correctly), the customer tried to set both
in one message:

> Frequency Bands -700/800 MHz Wireless Carrier- ATT/FirstNet (provided
> by Motorola)

The gateway classified this as ambiguous and responded:

> Which attribute did you mean? Reply with the name or the number:
> Is provisioning required in the Motorola Solutions Authorized Cloud
> environment? / Add SVX Video Wireless Remote Speaker Microphone /
> Agency has Motorola evidence solution / Extend Range to 762-764 MHz /
> Additional Frequency Bands / Secondary Frequency / Carrier Selection /
> Primary Frequency

— a candidate list containing **neither** of the two attributes the
customer actually named. The customer then rephrased explicitly:

> change Frequency Bands to 700/800 MHz and Wireless Carrier to
> ATT/FirstNet (provided by Motorola)

This time the system accepted it — but the response said **"Updated
Carrier Selection → ATT/FirstNet"**, a completely different attribute
(`carrierSelectionMultiSelect_astro`) than the one requested
(`wirelessCarrier_astro`, "Wireless Carrier"). Frequency Bands was never
confirmed either. Configuration then completed without either value
having been correctly set — a silent wrong-attribute write plus a
silently-dropped request, the customer only discovering it by inspecting
the final JSON.

### Root cause 1 — `_ground_clarify_candidates` ranks by label length, not relevance

`_ground_clarify_candidates` (`ask_api.py`) scores every attr by
word-overlap against the message, then — before this fix — sorted the
survivors by `-len(display_label)` (longest label first) and truncated
to the top 8. Reproduced live with the exact message: both real targets
("Frequency Bands", "Wireless Carrier" — each a clean 2-word overlap)
scored *more* relevant than every attr that actually made the cut, but
lost the sort because their labels are short. The winners were all
long-labeled, already-filled attrs matching on a single incidental word
("Motorola" appears in the display label of three unrelated Yes/No
attributes; "MHz" and "wireless" appear once each in two more) — a
data shape that is common throughout this catalog's verbose,
boilerplate-heavy attribute labels.

### Root cause 2 — a stale candidate pool force-matches any follow-up reply

Once root cause 1 seeded `session.pending_clarify_vns` with that wrong
8-item list, `_handle_pending_clarify_turn` had no way to recognize that
the customer's next, perfectly well-formed message was a **fresh**
request rather than a reply to the earlier (wrong) clarify question — it
unconditionally matched against the stale pool. `carrierSelectionMultiSelect_
astro` ("Carrier Selection") happened to be in that pool *and* shares
`ATT/FIRSTNET` as a real option value with the correct `wirelessCarrier_
astro`, so it won the match — while the correct attribute was never even
a candidate at that point (confirmed separately: `_resolve_target_
description("Wireless Carrier", attrs)` resolves correctly to
`wirelessCarrier_astro` in isolation — this is not a scoring bug in that
function, purely a consequence of being trapped in the wrong pool).

### Fix

1. `_ground_clarify_candidates` now tracks each attr's overlap score
   (with a large bonus for a label/variable_name explicitly grounded in
   the LLM's own clarifying-question text) and sorts by **that score
   first**; label length is only a tiebreaker among equally-relevant
   candidates.
2. `_handle_pending_clarify_turn` now runs a cheap escape-hatch check
   before matching against the stale pool: if the message has an
   explicit change-verb/arrow AND `_resolve_target_description` (run
   unscoped, against every attr — not just the stale pool) confidently
   resolves to a real attribute **outside** `pending_clarify_vns`, the
   stale clarify is cleared and the turn falls through to normal
   dispatch instead of force-matching. This mirrors the existing
   `_pending_reply_looks_like_new_request` escape hatch STEP 5 already
   has for the sibling `pending_variables` mechanism (Issue 4) — this
   was the missing analog for `pending_clarify_vns`.

### Live-verified, end-to-end, including the negative case

Re-ran the exact transcript against the fixed code. The candidate list
now correctly includes both real targets. The compound message no
longer touches `carrierSelectionMultiSelect_astro` at all
(`filled_multi["carrierSelectionMultiSelect_astro"] == []` throughout).
It takes a few follow-up turns to fully apply both values (the pending-
clarify resolution path binds to one attribute as a topic before
re-confirming its value, rather than applying an inline value from the
same message in one shot — a narrower, separate gap not in scope here),
but each attribute is correctly asked in turn and set to the right
value: `modelSelectionFrequencyBands_astro == "700/800 MHZ"`,
`wirelessCarrier_astro == "ATT/FIRSTNET"`.

Per explicit request, the negative case was also verified: when a
cascade-triggered follow-up ("Additional Frequency Bands") was declined
("no thanks, leave it"), the system accepted the decline gracefully
("No problem — I'll leave Additional Frequency Bands as it is...")
rather than re-forcing the question — matching the "ask the second
value in the next turn; a decline is fine" behavior explicitly
requested.

2 new tests added to `tests/test_cpq_pending_clarify.py`:
`test_relevance_beats_label_length_in_ground_candidates` and
`test_stale_clarify_pool_does_not_misbind_a_fresh_named_request`. Full
file run: 29 passed, 4 pre-existing failures confirmed unrelated (a
stale contract mismatch in `test_match_reply_by_label`/`test_match_
reply_by_index`/`test_match_reply_by_variable_name`/`test_unrelated_
reply_does_not_misbind` — these assert `_match_pending_clarify_reply`
returns a bare string, but it has returned a `(status, variable_name)`
tuple since this session's LLM-first clarify-decline work; not touched
by this fix, flagged for a separate cleanup).

---

## Issue 12 — Session only remembers ONE of the two attributes from a compound options query

**Status: root-caused, fixed, live-verified. LLM classification consistency for this exact phrasing remains a separate, open, non-deterministic gap — see "What this fix does NOT guarantee" below.**

### Problem statement

Live transcript: after correctly answering "what are the Frequency Bands
and Wireless Carrier available?" (both attributes' options listed
correctly), the customer tried to set both at once:

> Add Frequency Bands as VHF and Wireless Carrier as ATT/FirstNet

Instead of setting both, the response was:

> Added Frequency Band to your quote — what value would you like?

— followed by the configuration completing without either value applied.
The customer's question: *why can't the LLM tell this belongs to the
question it just answered?*

### Root cause, confirmed by reading the code

`CpqSession.last_qa_variable` (`state.py`) was a single `str` field whose
entire purpose is telling the LLM classifier "the customer just asked
about attribute X, so a short follow-up naming a value most likely
refers to X" — exactly the signal needed here. But the compound
options-query handler (`ask_api.py`, the `_multi_qs` loop) processes
**multiple** attributes in one turn and did:

```python
for _sub_q in _multi_qs:
    _sub_attr = _cpq_engine.detect_attr_query(_sub_q, attrs)
    ...
    session.last_qa_variable = _sub_attr.variable_name   # overwritten every iteration!
```

Each loop iteration **overwrites** the field — so after asking about
both Frequency Bands and Wireless Carrier, the session only remembers
whichever one was processed **last** ("Wireless Carrier"). "Frequency
Bands" was silently forgotten as a follow-up-resolution hint. When the
customer's next message named both attributes, the LLM's classification
prompt carried a strong contextual anchor for only one of them — the
other had no memory hint at all, leaving its resolution to depend purely
on the LLM's own judgment for that one attribute, with nothing to
stabilize it turn-to-turn.

Live-verified before the fix: driving the exact transcript through
`_run_cpq_turn` directly and inspecting `session_data["last_qa_variable"]`
after the compound options-query turn showed only `"wirelessCarrier_
astro"` — `"modelSelectionFrequencyBands_astro"` was already gone by the
time the next turn needed it.

### Fix

`last_qa_variable: str` → `last_qa_variables: list[str]` throughout
(`state.py`, `ask_api.py`'s three assignment sites, `intent_gateway.py`'s
three read sites: the candidate-scoring boost in `build_candidate_
bundles`, the LLM prompt's `customer_last_asked_about=` context line, and
`_mutating_agrees`' corroboration check). The compound-query loop now
collects every resolved attribute into one list and assigns it once
after the loop, instead of overwriting a scalar on each pass. The LLM
prompt's context line was also reworded to explicitly say "asked about
ALL of these attributes at once" when there's more than one, rather than
implying a single topic.

**Live-verified**: re-running the exact transcript and inspecting
`session_data["last_qa_variables"]` after the compound options-query
turn now shows `["modelSelectionFrequencyBands_astro",
"wirelessCarrier_astro"]` — both attributes correctly retained. 2 new
tests: `tests/test_cpq_2026_07_28_fixes.py::test_compound_options_query_
remembers_every_attribute_not_just_the_last` (pins the exact bug —
asserts both survive, not just the last one) and the existing
`test_cpq_intent_gateway.py` suite updated for the new list-typed field
(3 assignments changed from a bare string to a single-item list; all 18
tests in that file still pass unmodified otherwise). Broader sweep across
`test_cpq_intent_gateway.py` + `test_cpq_pending_clarify.py` +
`test_cpq_product_switch.py` + `test_cpq_llm_first_cutover_regression.py`:
92 passed, only the same 4 pre-existing failures already flagged under
Issue 11 (unrelated stale test contract).

### Follow-up: the initial state fix alone didn't guarantee single-turn resolution

The `last_qa_variables` fix above corrects a real, confirmed
state-tracking bug — the session no longer silently forgets one of two
just-discussed attributes. On its own, though, it did **not** make the
"Add X as Y and Z as W" message resolve reliably in one turn: re-running
it post-fix still sometimes landed on `ambiguous` rather than directly
dispatching. The user asked directly why the LLM couldn't tie the
follow-up back to the question it had just answered — that question led
to the real structural root cause below.

### Root cause 2 — `classify_intent`'s schema cannot represent two targets, and no splitter existed for change+change compounds

`classify_intent`'s `GatewayIntentResult` (`intent_schema.py`) has
**exactly one** `variable_name`/`value_ref` slot. It structurally cannot
report "set Frequency Bands to VHF AND set Wireless Carrier to
ATT/FirstNet" — a genuine two-target compound collapses to `ambiguous`
(or an inconsistent single-target guess) no matter how well-formed the
message is, *before* `last_qa_variables`/`_mutating_agrees`
corroboration is ever consulted (that corroboration only fires once the
LLM has already committed to a mutating category).

A splitter already exists for the sibling case — **change + question**
("change X and what is Y", `_llm_split_compound_change_and_question`) —
and one already exists for **options + options**
("what are the Frequency Bands and Wireless Carrier available?",
`_llm_split_multi_attr_options_query`). Neither covers **change +
change**. The change+question splitter's own docstring claimed that case
was "already handled by CHANGE_REQUESTS_MULTI" — live-confirmed false:
that category only ever corroborates a single already-resolved
`variable_name`; it never applies a second one.

Also confirmed live: the codebase's two generic full-catalog resolvers
are not reliable enough to resolve a split fragment on their own once
one exists — `detect_change_request("change Frequency Bands to VHF", ...)`
resolved to the **wrong sibling** ("Primary Frequency", which also has a
VHF option), and `_resolve_target_description` resolved the same text to
an unrelated attribute entirely (the added word "change" itself picked
up incidental vocabulary overlap elsewhere in the catalog).

### Fix

1. New `_llm_split_multi_attr_change_request` (`ask_api.py`), mirroring
   `_llm_split_multi_attr_options_query`'s already-working pattern:
   detects a genuine 2+-attribute change compound and splits it into
   self-contained "change X to Y" strings. `last_qa_variables` is passed
   into its prompt as explicit context ("the customer's immediately
   preceding message already discussed: Frequency Bands, Wireless
   Carrier — a follow-up naming these same attributes... is very likely
   setting both of them, not a fresh ambiguous request") — directly
   addressing the user's own diagnosis that this "Add" message should be
   treated as continuing the prior topic, not a separate call.
2. New `_resolve_split_change_text`, since the generic detectors proved
   unreliable per the collisions above: resolves each split fragment
   directly against the small, already-known `last_qa_variables` set
   first (exact label containment, then a real option value of that same
   attribute named in the text) — a strictly narrower and more precise
   search than either generic catalog-wide detector — before falling
   back to `detect_change_request` only when `last_qa_variables` doesn't
   cover the fragment at all.
3. Wired into the same gateway "clarify" branch the change+question
   splitter already occupies: tried whenever that splitter reports "not
   a change+question compound," resolving and applying every split
   fragment via `_handle_cascade` in sequence — but only when **every**
   fragment resolves (same never-half-apply-and-guess discipline as the
   sibling splitter); otherwise falls through to the existing clarify
   path completely unchanged.

**Live-verified end-to-end**: re-running the exact reported transcript,
"Add Frequency Bands as VHF and Wireless Carrier as ATT/FirstNet" now
resolves in a **single turn** — `tools_called: ['cpq_cascade()',
'cpq_cascade()']`, `Frequency Bands: VHF`, `Wireless Carrier:
ATT/FIRSTNET`, no clarify prompt at all. 7 new tests across
`tests/test_cpq_llm_first_cutover_regression.py` (the new splitter's
split/gate/fail-closed behavior, and the resolver's collision-avoidance
pinning the exact wrong-sibling-match and wrong-attribute-match failures
found live). Broader sweep across `test_cpq_llm_first_cutover_regression.py`
+ `test_cpq_intent_gateway.py` + `test_cpq_pending_clarify.py` +
`test_cpq_product_switch.py` + `test_cpq_change_request_multi.py` +
`test_cpq_grid_decline.py`: 112 passed, only the same 4 pre-existing
failures already flagged (unrelated stale test contract). Full
`test_cpq_2026_07_28_fixes.py` sweep: 54 passed, only the same
pre-existing DNS-environment failure seen throughout this entire session.

Root cause note, still accurate and still open: `_CHANGE_VERB_RE` (the
shared deterministic change-verb gate used throughout this codebase)
does not recognize "add" at all — confirmed via direct regex test. The
LLM-first splitter above is what makes "Add X as Y" reliable now, not a
deterministic detector; `detect_change_request`/`detect_change_requests_
multi` still can't see this phrasing directly. A proposed complementary
fix — recognizing the specific "`<name> as <value>`" construction as an
additional unambiguous signal (mirroring how `→` is already treated
alongside verbs), without touching the word "add" itself so genuine "add
this accessory" requests are unaffected — remains undiscussed further;
flagged here only if full deterministic (non-LLM-dependent) coverage for
this phrasing is wanted later.

### Follow-up 2 — a THIRD phrasing the "and"/";" pre-check gate still missed entirely

After the fix above shipped, the customer hit the same symptom again
with yet another compound phrasing that predates both "change...to..."
and "Add...as...": the very first transcript that opened this whole
investigation —

> Frequency Bands -700/800 MHz Wireless Carrier- ATT/FirstNet (provided
> by Motorola)

— uses `-` as its separator, with **no** "and" and **no** `;` anywhere
in the message. Both compound splitters (`_llm_split_compound_change_
and_question` and the new `_llm_split_multi_attr_change_request`) are
only ever *attempted* behind a shared pre-check:

```python
if " and " in _cq_lower or ";" in req.question:
```

Since this message matches neither keyword, **neither splitter was ever
called at all** — straight through to the generic clarify prompt, no
matter how much better that prompt's own candidate ranking had already
gotten from Issue 11's fix. A keyword-only gate can never anticipate
every way a customer might separate two requests (dashes, commas,
newlines, bullet-style pastes from a spreadsheet, ...).

**Fix**: the gate now also fires whenever `session.last_qa_variables`
already holds 2+ entries — a cheap, keyword-free, context-driven signal
that's exactly as strong as (and complements) the surface-level "and"/
";" check, and directly uses the same `last_qa_variables` signal the
customer had already pointed at as the right fix earlier in this
investigation:

```python
_looks_compound = " and " in _cq_lower or ";" in req.question
_recent_multi_topic = len(session.last_qa_variables or []) >= 2
if _looks_compound or _recent_multi_topic:
```

**Live-verified**: re-running the exact original dash-separated
transcript now resolves in a single turn —
`tools_called: ['cpq_cascade()', 'cpq_cascade()']`, `Frequency Bands:
700/800 MHZ`, `Wireless Carrier: ATT/FIRSTNET`, `Carrier Selection`
confirmed untouched (`[]`). Regression sweep across the same 6 files as
the previous fix: 112 passed, only the same 4 pre-existing failures
already flagged. Full `test_cpq_2026_07_28_fixes.py` sweep re-run
afterward for final sign-off.
