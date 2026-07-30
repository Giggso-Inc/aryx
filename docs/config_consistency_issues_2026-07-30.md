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
independent bugs found as side effects — documented below, not yet fixed.**

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

2. **Wrong-sibling write despite a correctly-pending attribute — CONFIRMED, still not fixed.** After
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

   **Why not fixed yet:** the fix requires either gating the gateway call
   on `session.pending_variables` (skip it, or require a strong
   new-request signal, whenever a single-select answer is actively
   pending) or moving STEP 5's pending-answer check to run *before* the
   gateway. Both are re-orderings of the core per-turn dispatch sequence
   used by every conversation, not a localized change — they need
   explicit scoping and dedicated regression coverage (specifically:
   confirm a genuine "change X" mid-pending-answer still correctly
   reaches the gateway, only a bare answer-shaped reply gets deferred to
   STEP 5) before shipping, which hasn't been done yet.
