# CPQ Compound "Change + Question" Message — Clarify Mismatch Issue

**Status:** Root-caused, partial fix applied and live-verified. ONE
architectural gap remains, root-caused but not fixed (see §8).
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
