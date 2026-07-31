# CPQ Compound "Change + Question" Message — Clarify Mismatch Issue

**Status:** Root-caused, partial fix applied and live-verified. §9-§11 track
QA-reported issues #1/#2/#3 (BOM gate crash, decline detection, constrained
retry scope), all now fixed on this branch — see §9's cross-reference table
for the full 10-issue QA status. Issues #7/8, #9, #10 (QA numbering) remain
open.
**Date:** 2026-07-29
**Branch:** dev-rv (LLM-first intent gateway, `src/aryx/cpq/intent_gateway.py`)

---

## 1. Problem statement (live transcript)

Real interaction against `aSTRO25_bom` / APX NEXT (workspace 3):

```
i want to order APX Next radios for destination country United States
→ ... configuration proceeds normally ...

what are the available options for product
→ The available options for Product are:
  APX NEXT (4G LTE+5G)
  APX NEXT XE (4G LTE+5G)
  ✅ aSTRO25_bom is configured. Review your choices: ...

make product as APX NEXT XE (4G LTE+5G) and what is the carrier being selected
→ Which attribute did you mean? Reply with the name or the number:
  1. Is provisioning required in the Motorola Solutions Authorized
     Cloud environment? (isProvisioningRequiredInCloudEnv_astro)
  2. Is Quantity of 2-Wire Surveillance Kit for SVX Video RSM > 0
     (isQuantityOf2WireSurveillanceKitForSVXVideoRSMGreaterThan0_astro)
  3. Is Quantity of Receive Only Earpiece for SVX Video RSM > 0
     (isQuantityOfReceiveOnlyEarpieceForSVXVideoRSMGreaterThan0_astro)
  4. Is Quantity of SVX 12 Slot Battery Only Charger drives > 0
     (isQuantityOfSVX12SlotBatteryOnlyChargerDrivesGreaterThan0_astro)
  5. Is Item Type 2-Wire Surveillance Kit for SVX Video RSM
     (isItemType2WireSurveillanceKitForSVXVideoRSM_astro)
  6. Is Item Type Receive Only Earpiece for SVX Video RSM
     (isItemTypeReceiveOnlyEarpieceForSVXVideoRSM_astro)
  7. Is DMS Non promotional Duration Months less than 61
     (isDMSNonPromotionalDurationMonthsLessThan61_astro)
  8. Is DMS Non-promotional Duration (Months) < than 37
     (isDMSNonpromotionalDurationMonthsThan37_astro)
```

None of the 8 listed candidates are related to "Product" or "Carrier" at
all — a customer combining a change request with a question in one
message got a confusing, unrelated numbered list instead of either the
change being applied or the question being answered.

---

## 2. Root cause — traced with live log evidence, two layered mechanisms

### 2.1 The gateway itself understood the message correctly

The Gemini-backed intent gateway (`intent_gateway.py`) actually
recognised this as a compound request. Its own logged rationale:

```
cpq_divergence: rejected_output ... values=["quarantine:variable_name_not_in_candidates;
The user is issuing two commands in one message: a change request
('make product as APX NEXT XE (4G LTE+5G)') and an attribute query
('what is the carrier being selected'). The `change_requests_multi`
intent is used to capture this compound request. The flat JSON schema
does not support detailing multiple requests, so the specific variable
and value fields are set to null."]
```

It classified the message as `change_requests_multi`, but the
**quarantine guardrail rejected it** (`variable_name_not_in_candidates`)
because `variable_name`/`value_ref` were `null` — the gateway's schema
can only carry ONE resolved target per turn, and there genuinely are
two different things being asked for here (a change AND a question).
This downgraded the result to `AMBIGUOUS` and disagreed with the
deterministic side (`det=change_request`, a single-target match),
triggering a "clarify" action.

### 2.2 The clarify candidate-list builder then picked the wrong attributes

The function that builds the numbered disambiguation list
(`ask_api.py`, the un-named helper right before `_grounded_clarify_prompt`)
extracts meaningful words from the raw question, filtered through
`_CLARIFY_STOPWORDS`, then scores every catalog attribute by word
overlap against that set — already-filled attributes need only ONE
overlapping word to qualify (`if is_filled or ... or overlap >= 2`).

**`"is"` was missing from `_CLARIFY_STOPWORDS`.** The question — *"what
**is** the carrier being selected"* — let "is" survive the filter, and
it matched against **every** attribute whose `display_label` happens to
start with `"Is "` — a very common BM-catalog boolean-flag naming
convention (`Is provisioning required...`, `Is Quantity of X > 0`, `Is
Item Type Y`, `Is DMS...`). Since many of those were already
filled/defaulted, they passed the gate on that one generic word alone,
with no 2-word minimum applying to already-filled attributes. Sorted by
longest-label-first and truncated to 8, this produced exactly the
unrelated list observed.

---

## 3. Fix applied — live-verified

Added copula/auxiliary verbs to `_CLARIFY_STOPWORDS`
(`src/aryx/api/ask_api.py`) — exactly as generic as the words already
filtered there (`"and"`, `"or"`, `"of"`, `"the"`), just missed:

```python
_CLARIFY_STOPWORDS = frozenset({
    "change", "set", "update", "make", "switch", "modify", "edit", "alter",
    "please", "the", "a", "an", "to", "for", "my", "our", "me", "i", "want",
    "would", "like", "can", "you", "it", "this", "that", "and", "or", "of",
    "in", "on", "with", "from", "into", "value", "field", "attribute", "attr",
    "which", "what", "one", "option", "options",
    "is", "are", "was", "were", "be", "being", "been",
})
```

**Verified**: rebuilt and force-recreated `aryx-api-1` with the fix,
confirmed healthy. Not yet re-tested against the exact reported
transcript at the time of writing.

**What this fix does NOT change**: it only prevents false-positive
candidate matches caused by a single generic word. It does not change
how compound change+question messages are classified or handled — see
§4.

---

## 4. Remaining architectural gap — not fixed, documented for a future decision

Even with the stopword fix, a message combining a change request and a
separate question in one turn will still likely produce a "clarify"
response rather than both (a) applying the change and (b) answering the
question — because the root mechanism (§2.1) is untouched:

- `GatewayIntentResult` (the gateway's structured-output contract) has a
  single `variable_name` + `value_ref` pair — there is no way to
  represent "apply this change AND separately answer this question" in
  one classification result.
- The Gemini model itself already recognises the compound structure (its
  own logged rationale proves this) — the limitation is entirely in the
  **schema's expressiveness**, not the model's understanding.
- `change_requests_multi` (the category it fell back to) is designed for
  **multiple changes** in one message (e.g. "change X to A and Y to B"),
  not a change bundled with a question — using it here was the model's
  own best-effort fit into a category that doesn't quite match.

**Options for a future fix** (not decided, not implemented):
1. Extend the schema with a genuinely separate "and also answer this
   question" side-channel field, resolved independently from the
   primary change/query classification.
2. Detect compound change+question messages deterministically (a regex/
   keyword split on conjunctions) *before* the gateway call, and dispatch
   each clause as its own internal sub-turn.
3. Accept the current behavior (ask the customer to split compound
   requests into separate messages) and make the clarify response
   explicitly say so, rather than presenting an unrelated attribute list
   — a smaller, honest UX improvement without touching the classification
   architecture.

This needs an explicit product/architecture decision before further work
— flagged here rather than silently deferred.

---

## 5. Follow-up finding — the stale candidate list AND a real decline-handling gap

Live-reproduced immediately after §3's fix was applied and `aryx-api-1`
rebuilt: replying "no", then "I don't wanted to select the attribute" to
the same wrong 8-attribute clarify prompt produced the **identical**
list, verbatim, twice — before the turn-count guardrail finally offered
guided mode.

### 5.1 The stale list is expected behavior, not a new bug

`session.pending_clarify_vns` (`ask_api.py` line ~3743) is computed
**once**, on the turn that first triggers a clarify, and stored in
client-echoed session state. Every subsequent reply's handler (line
~3662) filters the catalog down to just those *already-stored*
variable_names — it never re-invokes the candidate-building logic (the
one fixed in §3) again for the same pending clarify. This means:

- The §3 stopword fix works correctly for any **freshly-triggered**
  clarify from this point forward.
- It cannot retroactively repair a `pending_clarify_vns` list that was
  already computed and stored **before** the fix existed — this
  transcript was a continuation of the same session thread from before
  the rebuild, not evidence the fix failed. A genuinely new compound
  message (fresh session, or after clearing pending state) would get the
  corrected candidate list.

### 5.2 Real gap, confirmed: no decline/negative-reply detection anywhere in this path

Read `_match_pending_clarify_reply()` (`ask_api.py` line 3550) in full.
It tries, in order: exact `variable_name`, exact display label, 1-based
index, label/variable_name containment, then an LLM fallback restricted
to the same fixed candidate list. **None of these paths recognize an
explicit decline.** "No" and "I don't want to select the attribute" are
treated identically to any other unmatched free-text guess —
incrementing `pending_clarify_misses` and re-showing the same stale
prompt, with no way for the customer to signal "none of these are right,
start over" other than accumulating enough misses to trigger the
turn-count guardrail (`should_offer_guided_mode`) into offering guided
mode as an escape hatch.

**Fix options, not yet decided or implemented:**
1. Add explicit decline-phrase detection (a small keyword/regex set:
   "no", "none of these", "I don't want to select", etc.) to
   `_match_pending_clarify_reply`'s caller — on decline, call
   `_clear_pending_clarify(session)` and re-interpret the reply as a
   fresh message rather than re-prompting with the same list.
2. Combine with §4's fix: if the underlying cause is a compound
   change+question message the schema can't represent, a decline should
   ideally re-surface *that* root ambiguity ("did you want to change
   Product, or ask about Carrier, or something else?") rather than just
   re-listing the same (now corrected, post-§3) candidates.
3. At minimum, make the miss-counter's own guided-mode offer trigger
   sooner on a *recognized* decline than on an ordinary unmatched guess —
   right now both count identically toward the same threshold.

This compounds with §4 — fixing §5 alone still leaves a customer stuck
re-picking from a list of attributes when what they actually wanted was
never expressible as a single attribute pick in the first place.

---

## 6. §5.2 fix revised — LLM-first classification instead of a regex

The first fix attempt (§5.2's option 1) used a keyword regex
(`_CLARIFY_DECLINE_RE`) — live-tested immediately and it missed the
exact reported phrase ("I don't **wanted** to select the attribute" —
grammatically loose, not "want"). Rather than keep patching an
ever-growing regex, replaced it with an LLM-first classification,
consistent with this codebase's own design direction:

- New `_llm_classify_pending_clarify_reply()` (`ask_api.py`) classifies a
  reply into exactly `"resolved"` / `"decline"` / `"unclear"` in one
  call — only reached after the cheap deterministic tiers (exact
  variable_name, exact label, 1-based index, containment) already found
  nothing, same gating discipline as the pre-existing
  `_llm_resolve_label_collision`.
- `_match_pending_clarify_reply()`'s return contract changed from
  `str | None` to `tuple[str, str | None]` (status, variable_name) to
  carry the 3-way result — its only caller was updated to match.
- **No new LLM round-trip added**: this replaces the *same* call site
  that already fell back to `_llm_resolve_label_collision` on a miss —
  the new classifier just returns a richer answer (resolved/decline/
  unclear) instead of a plain resolved-or-nothing one, at the same cost.
- `_llm_resolve_label_collision`'s other 5 call sites are untouched —
  this is a separate, purpose-built function, not a change to that
  function's existing contract.

Live-verified: `aryx-api-1` rebuilt and healthy on this version.

---

## 7. Gap 1 (§4) fixed — LLM-first split, both clauses handled in one turn

Per explicit direction: handle both the change and the question in the
same turn (change applied first, question answered against the
post-change state), using an LLM-first split rather than a deterministic
conjunction-split regex (which carries real misfire risk — see §4's
original risk note).

**New**: `_llm_split_compound_change_and_question()` (`ask_api.py`) — a
dedicated classification call: given the raw message, decide whether it
genuinely combines a change request AND a separate question, and if so
return both as self-contained strings. Returns `None` for anything that
isn't genuinely compound (a single change, a single question, or
multiple changes with no separate question — the existing
`CHANGE_REQUESTS_MULTI` category still owns that case unchanged).

**Wired in** at the gateway's existing `action == "clarify"` dispatch
point — exactly where compound messages were already landing (§2.1).
Gated behind a cheap pre-check (`"and"`/`";"` present in the raw message)
so this adds no extra call to the common, already-successful
single-intent path — only to messages that were *already* about to hit
the confusing clarify prompt.

**Dispatch, once split:**
1. `_cpq_engine.detect_change_request()` on the change-clause text — the
   *existing*, already-tested deterministic detector, unchanged.
2. If it resolves: `_handle_cascade()` applies the change first (mutates
   `session.filled` etc., the *existing* STEP 6 handler, unchanged).
3. `_handle_cpq_qa()` answers the question-clause text *second*, against
   the now-updated session — naturally sees the post-change state since
   it operates on the same mutated `session` object.
4. Responses concatenated; `session_data` in the final response reflects
   `_handle_cpq_qa`'s post-change `session.to_dict()`.
5. If the change-clause doesn't resolve deterministically (detector
   returns `None`), falls straight through to the existing clarify path,
   unchanged — no new failure mode, same behavior as before this fix
   whenever the split can't be usefully acted on.

**Live-verified**: `aryx-api-1` rebuilt and healthy on this version.
Not yet re-tested against the exact reported "make product as X and
what is the carrier being selected" transcript at time of writing.

---

## 8. New, distinct issue — "make it ATT/FirstNet" re-asks disambiguation instead of resolving

**Root-caused and fixed, live-verified.**

### 8.1 Problem statement (live transcript)

Radio already configured (Product = APX NEXT XE, Wireless Carrier already
set to "LTE CAPABILITY NO SERVICE"):

```
what are the other options for Wireless Carrier
→ ATT/FirstNet (provided by Motorola)
  Verizon Priority & Preemption (provided by Motorola)
  LTE CAPABILITY NO SERVICE (BYOS for Certified Carriers)
  Bell Canada (provided by Motorola)

make it ATT/FirstNet
→ Which attribute did you mean? Reply with the name or the number:
  Carrier Selection (carrierSelectionMultiSelect_astro)
  Wireless Carrier (wirelessCarrier_astro)
  Select (relatedServiceSelectAry_astro)
```

Repeated across 4 separate turns (same `run_id`, ~11 minutes) — every
attempt re-asked the identical 3-way disambiguation, never resolving.
Customer's complaint: they had just been discussing "Wireless Carrier"
by name one turn earlier — the reply should have resolved to it directly.

### 8.2 Root cause — two distinct findings, both confirmed with log/code evidence

**Finding A — the ambiguity itself is real, not a bug.** The gateway's
own logged rationale, repeated near-identically across attempts:

```
"The user's request is ambiguous as the value 'ATT/FirstNet' is a valid
option for both the 'Wireless Carrier' (wirelessCarrier_astro) and
'Carrier Selection' (carrierSelectionMultiSelect_astro) attributes."
```

Both attributes genuinely accept "ATT/FirstNet" as a valid catalog
option (consistent with earlier evidence this session that Wireless
Carrier / Carrier Selection / SIM Card Selection are a linked/mirrored
trio). Across 4 independent classification attempts, the deterministic
side and the LLM disagreed every time (`window_disagree_rate=1.00`) —
this is genuine catalog ambiguity, not a resolution-logic defect.
Auto-picking one of two genuinely-valid candidates on value-match alone
would be an unsafe guess.

**Finding B — the real, fixable gap: no signal carries "what the
customer just asked about" into the next turn's disambiguation.**

`_handle_cpq_qa`'s options fast path (`ask_api.py` line ~654) resolves
the exact queried attribute (`wirelessCarrier_astro`) every time — but
never persists it anywhere. `CpqSession` (`state.py` line ~278) only
tracks:
- `pending_variables` — attributes the *system* is still waiting on an
  answer for (cleared the moment an attribute is filled).
- `pending_label_collision_vns` — only set when a label collision itself
  fires.

Neither captures "the customer just asked a question about attribute
X." `build_candidate_bundles`'s existing recency boost (`intent_gateway.py`
line ~195) only reads `pending_variables`, so it has nothing to prefer
`wirelessCarrier_astro` with — the genuine catalog collision (Finding A)
wins by default every time.

**Why `pending_variables` can't simply carry this signal** (considered
and rejected — `wirelessCarrier_astro` was already *filled*, so it isn't
even in that list to begin with):
1. Every cascade/apply-change turn fully rebuilds `pending_variables`
   from currently-unfilled attrs only (8 call sites, e.g. `ask_api.py`
   line 1166) — an injected already-filled attribute would be silently
   wiped the very next turn that touches a cascade.
2. `ask_api.py` line ~6116 uses `not session.pending_variables` as a
   *config-complete* gate — injecting a filled attribute risks the
   system thinking there's still an open question.
3. `ask_api.py` line ~5744 dispatches the *initial-fill* Q&A path off
   `pending_variables[0]`, distinct from the *change-request/cascade*
   path (with its own cascade-log/dropped-note bookkeeping — see PR
   #130). Disguising "revisit an already-answered attribute" as "still
   pending" risks misrouting into the wrong handler.
4. `pending_variables[:20]` is sent straight into the gateway's prompt
   (`intent_gateway.py` line ~159) explicitly framed as *unanswered* —
   injecting an already-filled attribute feeds the model a false signal.

There *is* existing precedent for prepending a queried attribute into
`pending_variables` (`ask_api.py` line ~5695), but it lives entirely
inside the active-configuring flow, before the recompute sites above
would ever wipe it — it doesn't generalize to the post-fill,
already-configured case this bug occurs in.

### 8.3 Fix implemented — refined from the original sketch once the exact mechanism was traced

The original proposal (8.3 draft) named `_narrow_label_collision` as a fix
site — that turned out to be the wrong code path. Tracing the actual log
trail (`mutating_disagreement llm=change_request:wirelessCarrier_astro;
det=set()`) showed this bug lives entirely in `intent_gateway.py`'s own
LLM-first gateway (`classify_intent` / `_mutating_agrees`), not in
`ask_api.py`'s separate label-collision Q&A helper — `_narrow_label_collision`
handles a different bug class (shared `display_label` across attrs) and was
never in this code path. Implemented instead:

1. **`CpqSession.last_qa_variable: str = ""`** (`state.py`) — new field,
   deliberately separate from `pending_variables` per 8.2's four reasons.
2. **Set on resolution** — both attribute-options handlers now record it:
   `_handle_cpq_qa`'s fast path (`ask_api.py` line ~687) and the
   actively-configuring options-query handler (`ask_api.py` line ~5701).
3. **Fed into the gateway's own LLM prompt** (`intent_gateway.py`,
   `_llm_classify_once`, alongside the existing `pending_attr=`/
   `awaiting_clarify_pick=` context bits) as `customer_last_asked_about=`
   — lets the model itself use recency to answer confidently instead of
   reporting `ambiguous` in the first place.
4. **`_mutating_agrees`** (`intent_gateway.py`) gained a third parameter,
   `last_qa_variable` — when the LLM's named `variable_name` matches it,
   that now counts as agreement even when the deterministic detectors
   found nothing or found a different sibling attribute. This is the line
   that directly fixes the observed `mutating_disagreement` loop.
5. **`build_candidate_bundles`** also boosts `last_qa_variable` the same
   way it already boosts `pending_variables[0]`, for consistency in what
   gets surfaced to the LLM.
6. Three new regression tests in `test_cpq_intent_gateway.py`: dispatch
   when `last_qa_variable` corroborates a deterministic-empty
   disagreement; still clarifies when the LLM names a *different*
   attribute than the one last discussed (no blanket bypass); and
   `build_candidate_bundles` ranks the recently-discussed attribute first.

**Live-verified**: full existing CPQ regression suite + 3 new tests = 83/83
passing; `aryx-api-1` rebuilt, force-recreated, confirmed healthy, and the
new code confirmed present inside the running container.

**Risk:** low — additive field, empty-string default; `_mutating_agrees`
only gained an extra way to *agree* (never a new way to reject), so no
existing passing case can newly fail; the "still clarifies when it points
elsewhere" test guards against over-trusting recency.

---

## 9. `confirm` crash — constraint-recheck argument-order mismatch (QA issue #1). Fixed.

A separate QA pass (workspace 21, `aSTRO25_bom`) reported 10 issues against
`feature/msi_intent`. Re-verified each directly against actual code — on
both `feature/msi_intent` and this branch — before touching anything.
This section covers the one fixed here; the others are cross-referenced
below.

### 9.1 Problem

Every `confirm` with an active constraint rule (e.g. hit via Carrier
Selection / Wireless Carrier) failed the BOM gate with:

```
constraint recheck error: 'str' object has no attribute 'target_attr_id'
```

instead of emitting a payload.

### 9.2 Root cause — confirmed by reading both sides of the call

`bom_gate.py`'s `recheck_constraints` called:

```python
engine.apply_constraint_rules(attrs, session.filled, con_rules, bml_eval=bml_eval)
```

i.e. `(attrs, filled, rules)`. The real signature (`engine.py`) is:

```python
def apply_constraint_rules(self, attrs, rules, filled, bml_eval=None) -> dict[int, list[str]]
```

i.e. `(attrs, rules, filled)` — `session.filled` (a dict) landed in the
`rules` parameter; the real rule-object list landed in `filled`. Inside the
function, `for rule in rules:` iterated the dict's keys (plain strings),
and `rule.target_attr_id` threw exactly the observed error.

A second, latent bug: the function returns a single `dict`, but
`bom_gate.py` unpacked it as `_allowed, messages = ...` (expects a
2-tuple) — never reached since the AttributeError fired first, but would
have broken even with the argument order alone fixed, since
`apply_constraint_rules` has no `messages` output at all — it only returns
`{entity_id: [allowed_item_values]}`.

Checked all 7 other call sites of `apply_constraint_rules` (`ask_api.py`
×4, `engine.py` ×3) — every one of them already uses the correct order and
treats the return as a plain dict. `bom_gate.py` was the only outlier, so
the fix belongs entirely there, not in `apply_constraint_rules` itself.

### 9.3 Fix — live-verified

`recheck_constraints` now calls the engine with the correct argument order
and derives violation messages itself (since the engine never produced
them): for each `entity_id` in the returned dict, if the attribute's
current filled value isn't in that entity's freshly recomputed allowed
set, that's a real violation — "**{label}** is currently {value!r}, which
is no longer a valid option given your other selections."

Also fixed a test (`test_cpq_post_failure_guards.py`) whose mock modeled
the WRONG (buggy) contract — `apply_constraint_rules` mocked to return a
2-tuple, matching the bug rather than the real single-dict signature. That
specific test never actually exercised this path (`con_rules=[]` short-
circuits before the mock is called), so it wasn't masking the bug, but the
mock shape itself was misleading and is now corrected. Added 3 new
regression tests: correct-argument-order is asserted directly, a filled
value outside the recomputed allowed set is flagged, and a still-allowed
value passes cleanly.

**Live-verified**: 86/86 tests passing; `aryx-api-1` rebuilt, force-
recreated, confirmed healthy.

### 9.4 Cross-reference — status of all 10 QA-reported issues, verified against this branch

Re-checked every QA claim directly against this branch's code (not
`feature/msi_intent`, which this branch does not include) before recording
status:

| # | Issue | Status on this branch |
|---|---|---|
| 1 | `confirm` crash — constraint recheck arg-order mismatch | **Fixed** (§9, this section) |
| 2 | "I don't want to change X" mismatched as an invalid value | **Fixed** (§10) |
| 3 | Retry loses constrained option scope (false 328-option message) | **Fixed** (§10) |
| 4 | Turn-1 `pending_var` UnboundLocalError | Already fixed upstream (`dev-rv`, `aac7a67`) |
| 5 | Summary raw-dump fallback | Already fixed upstream (`dev-rv`, `6adc9fc` + `65a4d76`) |
| 6 | `isFedRampRequired_astro` Yes→No discrepancy | Inconclusive — needs a live-logged repro, not re-traced here |
| 7/8 | Dense-sentence trailing question disambiguates against unrelated attrs | Confirmed still open — `_relevant_intent_candidates` (`ask_api.py`) still falls back to the unfiltered candidate list when nothing scores. Distinct mechanism from §1-3/§8 above (`_ground_clarify_candidates`) — not touched by this branch's fixes |
| 9 | Naming both attrs explicitly doesn't resolve either | Not root-caused by QA; not re-traced here |
| 10 | "ATT/FirstNet" short answer fails to match its own just-shown option | Confirmed still open — and QA's own hypothesis (constraint-set inconsistency in `apply_answer`) is refined: the real attribute is multi-select, so the actual code path is `apply_multi_answer`, which has **no prefix-match tier at all** (only an exact, word-bounded full-display-name search) — a simpler, statically-confirmable mechanism, independent of `constrained_item_values` |

Issues #2/#3 share one fix location (`_handle_cascade`) and are the
recommended next pass.

---

## 10. QA issues #2 + #3 — decline detection + constrained-scope retry. Fixed.

Both share one call site: `pending_change_no_value_vn`'s resolution
(`ask_api.py`, right before it calls `_handle_cascade`).

**#2 fix**: new `_CHANGE_VALUE_DECLINE_RE` / `_is_change_value_decline()` —
checked before `_handle_cascade` is ever called, so a decline is always a
no-op (nothing in `session.filled` has been touched yet at that point).
Stemmed with `\w*` on verb forms (`want\w*`, `chang\w*`) rather than one
literal phrase — learned directly from §6's regex missing "wanted" vs
"want". Deliberately does **not** match bare "no" alone, since that's a
legitimate value for yes/no-shaped attrs. On a match, returns a friendly
"I'll leave **{label}** as it is" answer and clears
`pending_change_no_value_vn` without ever reaching `apply_answer`.

**#3 fix**: `_handle_cascade` gained an optional `constrained_item_values`
parameter (default `None` — every other one of its 9 call sites is
unaffected). The `pending_change_no_value_vn` call site now recomputes the
same `apply_constraint_rules(...)` set the *original* "which value?" ask
used and passes it through — both into `apply_answer` (so validation and
the prompt agree) and into the retry's `next_question_prompt`. A failed
match now re-shows the same scoped 8-option list instead of falling back
to `attr.options` unfiltered.

**Live-verified**: 5 new tests (2 full-turn integration tests via
`_run_cpq_turn`, 3 unit tests on the decline regex including the
"wanted"-class stemming check) — 131/132 in the full combined suite (the
1 failure is pre-existing, unrelated: a DNS resolution error hitting a
docker-only hostname from outside the container, identical before and
after this change). `aryx-api-1` rebuilt, force-recreated, confirmed
healthy.

---

## 11. Live bug from §9's own fix — stale constraint values now correctly hard-blocked confirm, but that contradicts an existing product decision. Redesigned.

Once §9 made `recheck_constraints` actually reachable (instead of crash-
and-swallowed), a real confirm hit two genuine violations: `Carry Type`
and `Frequency Bands`, both auto-filled earlier in the session with
values that a later Product/model selection's constraint rules no longer
allow.

**Not a bug in §9's fix** — cross-checked against a completely separate,
pre-existing mechanism (`find_rule_inconsistencies`, logged as `"cpq:
rule-consistency check found N issue(s)"`) that runs independently every
turn. It found the *same two* violations (plus 5 more recommendation-rule
mismatches it also doesn't act on). Both mechanisms agree these are real.

**The actual problem**: `docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md
§4.1` already made an explicit decision about this exact issue class —
*"NOT auto-fixed... the engine can't be certain what the correct value
should have been... logged only, for now... surfacing it to the user
directly is a separate, not-yet-built follow-up."* §9's fix, by finally
working, started hard-blocking confirm on precisely the class of issue
this codebase had already decided not to hard-block on anywhere else.

**Decision (asked directly): auto-clear the stale value and re-ask**,
rather than hard-block or silently warn-and-proceed.

**Fix**:
- `bom_gate.py`: `recheck_constraints` now returns structured
  `StaleConstraintViolation` objects (`attr`, `current_value`, `allowed`)
  instead of hard-fail message strings. `BomGateResult` gained a
  `stale_violations` field, separate from `errors` — provenance failures
  (invented/hallucinated values) still hard-fail exactly as before; that's
  a different, more serious integrity problem this decision doesn't touch.
- `ask_api.py`'s confirm handler: when `gate.stale_violations` is non-
  empty (and there are no hard provenance errors), it pops each stale
  attr from `filled`/`display_filled`/`filled_source`, queues them in
  `pending_variables`, flips `session.status` back to `"configuring"`,
  and re-asks the first one using the *corrected* constrained option list
  (same `next_question_prompt(..., constrained_item_values=...)` pattern
  as §10) — no payload emitted, but framed as a fresh question rather
  than a block the customer has to self-diagnose.

**Live-verified**: 3 new tests (structured-violation shape at the
`bom_gate.py` level, `validate_before_payload` confirmed to return
`ok=False` + `stale_violations` with an empty `catch_message` rather than
hard-failing, and a full `_run_cpq_turn` reproduction of the live Carry
Type/Frequency Bands scenario proving auto-clear + re-ask end to end).
131/132 in the full combined suite (same pre-existing unrelated DNS
failure as §10). `aryx-api-1` rebuilt, force-recreated, confirmed
healthy, new code confirmed present in the running container.

---

## 12. External review of §11 — 4 findings, all confirmed and fixed

A code review of the §11 changes (before merge) raised 4 issues. Each was
independently verified against the actual code before being accepted —
all 4 were real.

### 12.1 P1 — Constraint validation fails open on an unexpected exception

**Finding**: `recheck_constraints`'s `except Exception: return []` meant
an unexpected engine error looked identical to "no violations found" —
silently letting a possibly constraint-invalid BOM through.

**Confirmed**: yes — this was a deliberate design choice in §11
("fail OPEN here (not a hard block)"), but on reflection it contradicts
the "never guess" discipline every other integrity check in this file
follows (`check_provenance` hard-fails; §11 itself hard-fails on
provenance for the same reason).

**Fix**: `recheck_constraints` no longer catches its own exceptions — it
propagates. `validate_before_payload` catches it and returns a hard fail
(`ok=False`, populated `errors`, real `catch_message`), the same
fail-closed treatment as a provenance failure. `stale_violations` stays
empty in this case, so the caller's auto-clear branch is never reached —
an unexpected error and a real known violation are now handled
differently, on purpose.

### 12.2 P1 — Constrained multi-selects bypassed validation entirely

**Finding**: `apply_multi_answer()` never received the constrained set,
and the final recheck only read `session.filled` — a multi-select
attribute's stale value(s) were invisible to both the retry-scope fix
(§10) and the confirm-time recheck (§11).

**Confirmed**: yes, two separate gaps in the same class of bug:
- `_handle_cascade`'s multi-select branch called
  `apply_multi_answer(changed_attr, new_value_hint)` with no third
  argument at all.
- `recheck_constraints` only ever did
  `session.filled.get(attr.variable_name)` — a multi-select's values live
  in `session.filled_multi`, so `current` was always `None` and the
  `if current is not None` guard silently skipped every multi-select attr.

**Fix**: `apply_multi_answer` now receives `constrained_item_values` at
the `_handle_cascade` call site. `recheck_constraints` now branches on
`attr.select_type == "multi"` and checks `session.filled_multi` for that
case, flagging any selected value(s) outside the recomputed allowed set.
The confirm-handler's auto-clear loop now pops from `filled_multi` (not
`filled`) for multi-select violations.

### 12.3 P2 — Auto-clear mutation not undoable

**Finding**: the §11 auto-clear block mutates `filled`/`display_filled`/
`filled_source` directly with no `push_snapshot()` call first, unlike
every other mutation site in this file (`_handle_cascade` pushes one at
its very start).

**Confirmed**: yes — a customer saying "undo" right after this re-ask
would jump back further than just this turn's clear, to whatever the
last actually-snapshotted state was.

**Fix**: added `push_snapshot(session, reason="stale_constraint_reask")`
immediately before the mutation loop, matching the established pattern.

### 12.4 P2 — Decline check discarded a stated replacement value

**Finding**: `"I don't want Standard; use Premium"` would be classified
as a pure decline (cancel, keep current value) rather than resolving to
Premium, because the decline-phrase regex fired on "don't want" without
checking whether a real replacement was also named.

**Confirmed — and worse than reported.** Testing directly against the
live engine:

```python
>>> engine.apply_answer(price_tier_attr, "I don't want Standard, use Premium", None)
('Standard', 'Standard')
```

`apply_answer`'s substring matching has no concept of negation — both
"Standard" and "Premium" appear in the text, and it matched the
**rejected** value, not the intended one. The original planned fix
("try a real value match before checking decline") would have silently
applied the *wrong* value here — worse than misreading it as a decline.

**Fix**: new `_extract_replacement_clause()` — when a correction cue
("use X" / "instead X" / "prefer X" / "rather X") is present, only the
text *after* the cue is matched against the catalog. For "I don't want
Standard, use Premium", this narrows matching to just "Premium" — the
rejected value never appears in the substring being searched at all, so
it can't be matched by mistake. Falls back to the full message when no
cue is present (the common, non-compound case is unaffected). This
extracted clause is what actually gets matched *and* what's passed as
`new_value_hint` into `_handle_cascade`, so its own internal matching
stays consistent with the decision made at the call site.

**Live-verified**: 8 new tests across `bom_gate.py`-level unit tests and
full `_run_cpq_turn` integration tests — exception hard-fail, multi-select
stale-value detection (both violating and passing), `push_snapshot`
called before mutation, multi-select auto-clear from the correct dict,
and the compound decline+replacement case resolving to the *stated*
value rather than the rejected one or a false cancellation.

---

## 13. Second QA report cross-check — 2 staleness corrections, everything else confirmed accurate

A second, independent QA report (synthesizing `CPQ_SESSION_2026_07_29_ISSUES_PLAN.md`
and `CPQ_LLM_INTENT_FIRST_TRANSCRIPT_ANALYSIS_AND_RISK_PLAN.md`) tracked
the same 9 numbered issues plus 3 more (a downstream "provisioning"
hijack, "what is the error" wrongly refused, and an `llm_normalize`
envelope crash) against `origin/dev-rv`. Verified every claim directly
(`git merge-base --is-ancestor`, and grepping each cited function against
`origin/dev-rv`'s actual tree) before accepting any of it.

**Confirmed accurate, no corrections needed:**
- #2, #4, #5, #7/8, #9, and the transitive "provisioning hijack" fix — all
  genuinely merged into `dev-rv` via `da7246c`/`aac7a67`/`6adc9fc`/`65a4d76`.
  Line numbers the report cited had drifted slightly from the actual
  current file, but every named function/fix is genuinely present.
- #6 (FedRAMP) and "what is the error wrongly refused" — confirmed still
  unfixed anywhere, on any branch. No code touches either.

**2 corrections to the report's own claims:**

1. **#1 and #3/10** ("confirm crash", "retry loses constrained scope") —
   the report says *"not on `dev-rv` — fix exists only as my own
   uncommitted local edit."* That was true when written; it's stale now.
   Both are committed (`5b84bd1`) and pushed, with PR #134 open against
   `dev-rv` — not yet merged, but no longer uncommitted. Separately: the
   report's cited symbols for the fix (`_hc_constrained`/`_hc_allowed`,
   `bom_gate.py:77`) don't match this repo's actual implementation
   (`constrained_item_values`, `StaleConstraintViolation` — see §9-§10) —
   same bug, independently identified and described, not a description of
   this branch's own diff.

2. **`llm_normalize` envelope crash** — the report says *"not on `dev-rv`
   — only on `feature/msi_intent` (`eaaecc3`)."* This is simply wrong:
   `git merge-base --is-ancestor eaaecc3 origin/dev-rv` returns **true** —
   `eaaecc3` merged into `dev-rv` via PR #132 ("Merge pull request #132
   from Giggso-Inc/feature/msi_intent"), which landed *before* `da7246c`.
   It has been on `dev-rv` the whole time.

**Also not tracked by this QA report at all**: §11 (the stale-constraint
auto-clear redesign) and §12 (its own follow-up review — fail-open
exception, multi-select bypass, undo safety, decline-regex over-match) —
both newer findings from work after this report was written.

---

## 14. "what is the error" wrongly refused as out-of-scope. Fixed.

Of the 2 issues §13 confirmed genuinely unfixed anywhere (FedRAMP and
this one), this one had a clear, scoped fix — implemented.

### 14.1 Root cause, confirmed

`_llm_classify_is_cpq_question` has exactly **2** call sites — its own
docstring claimed "one call site in `run_ask`", which was already stale:

1. `run_ask`'s fresh-turn router (`ask_api.py` ~6891) — decides whether
   to enter CPQ mode at all, before any session/CPQ context exists. Must
   stay context-free.
2. `_synthesise` (`ask_api.py` ~325) — the mid-session Q&A scope check,
   deciding whether an in-flight follow-up is still in scope.

Call site 2 already computes `conv` (the last-6-turn conversation, via
`_recent(history, limit=6)`) one line before the classify call — for the
answer-synthesis prompt right below it — but was never passing that same
`conv` into the classify call itself. Classified alone, "what is the
error" reasonably reads as an unrelated tech-support question; the one
fact that would make it recognizable (the prior turn was the engine's own
gate error) was never shown to the classifier.

### 14.2 Fix — live-verified

`_llm_classify_is_cpq_question` gained an optional `prior_context: str = ""`
parameter, folded into the prompt only when non-empty (`RECENT
CONVERSATION` block). Call site 2 (`_synthesise`) now passes the
already-computed `conv`. Call site 1 (`run_ask`'s router) passes nothing —
default empty string, prompt byte-identical to before.

**Impact confirmed additive/backward-compatible**: no test anywhere
references this function directly (none to update); the only 2 callers of
`_synthesise` both already pass `history`, so both benefit identically; no
new LLM call — same call, richer prompt, same cost.

**Live-verified**: 2 new tests proving `prior_context` reaches the prompt
when given and is fully absent when not (pinning call site 1's
behavior as byte-identical to before). 66/66 in the targeted suite;
full combined suite run pending at time of writing.

### 14.3 FedRAMP (§13's other open item) — investigation finding, not yet a fix

Checked whether `CpqSession.cascade_log` already captures this class of
discrepancy before proposing any new logging: confirmed it does, in
principle — `ask_api.py` ~6494-6504 appends `{var, old, new, rule, turn}`
to `cascade_log` for **every** value that changes during the rule-loop
rerun, on every turn, not just explicit cascades. This should already
record an `isFedRampRequired_astro` flip if one occurs — the `rule` field
is a source tag ("auto"/"cascade"/"rule"/"user"), not the specific
condition, so it wouldn't explain *why*, but it would confirm *when* and
*whether* it happens at all.

**Not yet fixable further from static reading alone** — needs a live
repro of the exact reported sequence (Single Band / Houston / US / Police
Protection) with `session_data.cascade_log` inspected afterward. If an
entry for this attr is present, that's the "when" already answered
without any new logging. If absent despite the value genuinely changing,
that would itself be a second, real finding (a code path that changes
`filled` without going through this cascade-log block at all) — worth
its own investigation. No code changed for this item this round.

---

## 15. Third review round on §11/§12 — 3 more findings, all confirmed and fixed

A third review of the stale-constraint auto-clear and pending-change
flows caught 3 more real gaps (1 P1, 2 P2). Same discipline: verified
every claim directly before planning any fix.

### 15.1 P1 — Empty constraint intersections created an unanswerable loop

**Finding**: multiple active constraints can legitimately intersect to
`[]` — the auto-clear handler cleared the stale value and prompted with
that empty set anyway; every subsequent reply was rejected since no
option was ever allowed.

**Confirmed**: traced `next_question_prompt`/`apply_answer` directly with
`constrained_item_values=[]` — `effective_opts`/`options` both filter to
empty regardless of input, producing "Please provide a value" with no
option able to ever match. A genuine dead end, not a wording problem.

**Fix**: the confirm handler now checks `gate.stale_violations` for any
entry with an empty `allowed` set *before* doing any clearing. If found,
it reports a rule conflict explicitly (which attribute(s), and that
active rules conflict) and suggests changing an earlier selection or
saying **undo** — nothing is mutated, since there's no productive value to
ask for. Only when no conflict is present does the existing auto-clear +
re-ask flow (§11/§12) run, unchanged.

### 15.2 P2 — "Prefer X over Y" / "rather X than Y" could still select the rejected Y

**Finding**: `_extract_replacement_clause()` only strips text *before* the
correction cue — "prefer Premium over Standard" extracts "Premium over
Standard", which still contains the rejected value.

**Confirmed — live-tested directly**:
```python
>>> engine.apply_answer(attr, "Premium over Standard", None)
('Standard', 'Standard')
```
Reproduced for both "prefer X over Y" and "rather X than Y", exactly as
reported.

**Fix**: added a second cut at the first contrastive word (`over` /
`than` / `instead of` / `rather than` / `not`) found *within* the
extracted clause — "Premium over Standard" → "Premium". Verified against
all phrasings including the original §12 case ("I don't want Standard,
use Premium"), which is unaffected since it has no contrastive word to
cut at.

### 15.3 P2 — A pure cancellation depended on constraint evaluation succeeding

**Finding**: `apply_constraint_rules()` runs unconditionally *before* the
decline check — if it raises, a pure "I don't want to change it" (which
should always be a harmless no-op) crashes instead.

**Confirmed**: yes, by inspection — no try/except existed around that
call at this specific site.

**Fix**: wrapped the call in try/except, falling back to `None`
(unconstrained) on failure. Safe here specifically because this value
only *scopes* matching/prompting at this call site — it is not a final
integrity gate the way `bom_gate.py`'s recheck is (where fail-closed was
the correct call in §12). A pure decline, or a real value match, now both
proceed regardless of the rule engine's health.

**Live-verified**: 6 new tests — empty-intersection reports a conflict
without mutating state, "prefer/rather...over/than" resolves to the
wanted value, and decline survives a forced constraint-engine exception.
Full combined suite run pending at time of writing.

---

## 16. FedRAMP (#6) — no longer inconclusive. Real mechanism found; fix not yet implemented.

**Update: fixed.** See `docs/config_consistency_issues_2026-07-30.md` §6
for the implemented fix — a new `CpqEngine.resync_stale_recommendations()`,
wired into `evaluate_rules_loop`, that generically re-syncs any
recommendation-governed attribute the engine (not the customer) filled
once its driving attribute's value later disagrees with the
recommendation. Scoped to `filled_source != user/hint/cascade`, the exact
boundary `find_rule_inconsistencies` already used for detection-only.

The earlier investigation concluded "no rule sets this attribute's Yes/No
value via script — only hide/show." That conclusion was **wrong** —
apparently because it only checked script-backed rules. A live query
against the real ingested catalog (workspace 3, `aSTRO25_bom`, via
`GraphReader('redis://falkordb:6379', graph='aryx_ws_3')` +
`CpqEngine.load_product_config`/`load_recommendation_and_constraint_rules`
run directly inside the running container) found plain declarative
recommendation rules that DO set this value:

- **"Set NO for Is FedRAMP High Baseline required?"** — condition
  `isProvisioningRequiredInCloudEnv_astro == "YES"` → recommends `NO`.
- **"Default No Is fedramp high baseline required"** — unconditional
  (`condition_attr_id=0`) → recommends `NO`.
- **"Associated Rec Rule: Hide FedRamp Required for US FED customer Only
  (Molokai)"** — condition `systemEnhancementFeatureType_astro ==
  "RADIO FED TA FCC TRIGGER"` → recommends `NO`.

### 16.1 Root-cause hypothesis, evidence-backed but not turn-traced

`isFedRampRequired_astro`'s own options list has `YES` at `order=1`, `NO`
at `order=2`. `CpqEngine.auto_fill`'s own docstring
(`engine.py:3974-3987`) documents an **already-known bug class**: if a
recommendation's driving attribute isn't filled yet at the moment THIS
attribute is auto-filled, the guard meant to catch "condition already
satisfied" can't fire, so first-by-order picks the first option instead —
and since neither `auto_fill` nor `apply_recommendation_rules` ever
revisits an attribute already in `filled`, that choice is permanent. The
docstring cites a near-identical historical case already fixed for a
DIFFERENT attribute (`hWVersion_astro`'s region=NA recommendation losing
this exact race). The working hypothesis: `isProvisioningRequiredInCloudEnv_astro`
(or `systemEnhancementFeatureType_astro`) isn't filled yet when
`isFedRampRequired_astro` is first auto-filled → first-by-order locks in
`YES` → a later turn's driving-attribute resolution can't undo it via the
normal recommendation path, but something (unconfirmed which mechanism)
still produced the later "No" observation.

### 16.2 Not yet fixed — needs one more confirmation step

Before changing any code: confirm whether `isFedRampRequired_astro` is a
member of the `governed_ids`/`rule_governed_ids` sets `auto_fill`'s
step-3/step-5 guard checks, and trace the actual turn-by-turn fill order
of `isProvisioningRequiredInCloudEnv_astro` relative to this attribute in
a live session. This is now a scoped, evidence-backed investigation
rather than a dead end — the previous "inconclusive" status is retired.

---

## 17. Multi-select stale-value clear discarded valid selections alongside the invalid one. Fixed.

**Finding**: the auto-clear handler popped the ENTIRE `filled_multi` entry
for a stale multi-select attribute, even though `bom_gate.py`'s recheck
already isolates only the invalid item(s) (`invalid = [v for v in
current_multi if v not in allowed]`). A customer with 5 valid carrier
selections and 1 now-invalid one lost all 5 and had to re-pick everything.

**Confirmed**: `ask_api.py`'s auto-clear loop called
`session.filled_multi.pop(_vn, None)` unconditionally for any multi-select
violation — no filtering.

**Fix**: filter `session.filled_multi.get(_vn, [])` down to the values
still in `_v.allowed`, keep them (rebuilding `display_filled` from the
survivors' display names), and only clear the key entirely when nothing
in the selection remains valid.

**Live-verified**: 2 tests — 5 valid + 1 invalid selection now keeps the
5 and only the invalid one triggers the re-ask (naming it specifically in
the message); a fully-invalid selection still clears the whole key as
before.

---

## 18. `_extract_replacement_clause`'s cue detection was position-based, not semantic — a reversed phrasing still leaked the rejected value. Fixed.

**Finding**: the cue regex matches on the FIRST occurring cue word
(`use`/`instead`/`prefer`/`rather`) and takes everything after it, then
trims at the first contrastive word found *within that captured text*.
"Instead of Standard, prefer Premium" matches on "instead" (the earliest
cue), capturing "of Standard, prefer Premium" — that captured clause has
no contrastive word of its own (the word "instead" that would normally
trigger a cut was already consumed by the outer match), so nothing gets
trimmed and "Standard" stays in the text handed to `apply_answer`.

**Confirmed — live-tested directly**:
```python
>>> _extract_replacement_clause("instead of Standard, prefer Premium")
'of Standard, prefer Premium'
>>> engine.apply_answer(attr, 'of Standard, prefer Premium', None)
('Standard', 'Standard')
```

**Root cause**: "instead" plays two different grammatical roles
depending on what follows it. Alone, it introduces the WANTED value
("use Premium instead"). As "instead of X", X is the REJECTED value and
the real replacement is stated elsewhere in the sentence — but the cue
regex treated both forms identically.

**Fix**: excluded "instead of" from the cue match via a negative
lookahead (`instead(?!\s+of)`). When "instead of X" appears, that
alternative simply doesn't match there, and `re.search` naturally
continues scanning forward to find the real cue word ("prefer") later in
the sentence — no special-casing needed, the existing scan-forward
behavior does the right thing once the false match is excluded.

**Live-verified**: 2 new tests — the reversed phrasing now resolves to
Premium, and bare "instead" (not followed by "of") still works as a
direct cue exactly as before.
