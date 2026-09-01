# CPQ Ambiguous-Clarify Discards Already-Resolved Evidence — Fix Plan

**Date:** 2026-08-21
**Status:** Fix 1 and Fix 2b implemented and verified; Fix 2 implemented,
then reverted after discovering a real conflict with an existing safety
checkpoint (branch `fix/cpq-ambiguous-clarify-discards-resolved-evidence-
2026-08-21`)
**Severity:** High — customer-visible dead end, distinct from the already-fixed
value-candidate-truncation bug (`docs/CPQ_VALUE_CANDIDATE_TRUNCATION_PLAN_
2026_08_21.md`). Two different mechanisms, same symptom shape: the system
already has the right answer internally and throws it away before asking
the customer anything.

## Problem (live-reproduced, two cases)

**Case 1** — `"set the Primary Frequency band to UHF band"`:
```
Which attribute did you mean? Reply with the name or the number:
1. Primary Frequency (modelSelectionPrimaryFrequency_astro)
2. Frequency Band (modelSelectionFrequencyBandMsl_astro)
3. Additional Frequency Bands (modelSelectionFrequencyBandPlus_astro)
4. Secondary Frequency (modelSelectionSecondaryFrequency_astro)
5. Frequency Bands (modelSelectionFrequencyBands_astro)
```
The customer named the attribute unambiguously ("Primary Frequency"). Five
attributes get offered anyway.

**Case 2** — `"Set SmartProgramming to 2Yrs"`:
```
Which value would you like for SmartProgramming?
SmartProgramming — choose one:
1. 1 Year
2. 2 Year
Currently set to: 1 Year
```
The customer stated both the attribute AND a value. The value gets silently
discarded and the menu re-shown as if nothing had been said.

## Root cause (verified against real code + live gateway logs)

Two distinct mechanisms; the pattern connecting them is the actual fix
target.

### Case 1 — the gateway's own attribute resolution is thrown away

Live log for the exact reproduced turn:
```
cpq_intent_gateway: ambiguous run_id=... reason="The user requested to set
'Primary Frequency' to 'UHF band'. The attribute 'modelSelectionPrimary
Frequency_astro' (Primary Frequency) is the clear target. However, its
value candidates do not include a generic 'UHF' option. The available
options are 'UHF R1' and 'UHF R2', making the user's request ambiguous..."
```
The LLM gateway is unambiguous about the **attribute** (its own words: "the
clear target") — the real ambiguity is entirely about the **value** (UHF R1
vs UHF R2, both genuinely plausible matches for "UHF band"). The gateway's
structured result carries this: `vn='modelSelectionPrimaryFrequency_astro'`
is populated even though `category=ambiguous`.

But `IntentCategory.AMBIGUOUS`'s handler (`ask_api.py:5634`) never reads
`result.variable_name` at all:
```python
if result.category == IntentCategory.AMBIGUOUS:
    if not result.clarifying_question:
        return None
    ...
    return _set_pending_clarify_and_answer(
        req, session, attrs,
        original_question=req.question,
        clarifying_question=result.clarifying_question,
        ...
    )
```
`_set_pending_clarify_and_answer` re-derives candidate **attributes** from
scratch via `_ground_clarify_candidates`, scoring by raw word-overlap
against the raw question text and the LLM's own free-text
`clarifying_question`. "Primary Frequency," "Frequency Band," "Secondary
Frequency," "Frequency Bands," and "Additional Frequency Bands" all share
the generic word "frequency," so all five score into the candidate list —
even though the gateway had already, correctly, narrowed this to exactly
one attribute. The already-resolved `vn` is never consulted; the correct
answer is computed, then discarded.

### Case 2 — a resolved attribute never gets a chance to match the stated value

Live log for the exact reproduced turn:
```
cpq_intent_gateway: mutating_disagreement run_id=... llm=change_request
vn='anywhereProgramming_astro' → clarify
cpq_intent_gateway_turn: action=clarify reason='mutating_disagreement'
category=ambiguous vn=None value_ref=None ...
cpq_shadow_intent_actual: tools_called=['cpq_intent_gateway_clarify()
->single_candidate(anywhereProgramming_astro)']
```
Confirmed directly against the live catalog: `anywhereProgramming_astro`'s
real `display_label` **is** "SmartProgramming" (options: "1 Year", "2
Year") — a legacy vn/label mismatch already baked into the catalog data,
not a bug. The gateway's attribute resolution here is correct; a real
mutating-action safety gate (LLM + deterministic detector must agree before
a mutating change dispatches) downgraded this to a clarify, and the clarify
path correctly narrowed to exactly one real candidate attribute.

The bug is what happens next: reaching a single resolved candidate routes
straight to asking `"Which value would you like for X?"` — this path was
built for the genuine "attribute named, no value given" case
(`detect_change_target_without_value`'s own contract) and **never
re-attempts matching the customer's already-stated value** ("2Yrs") against
that attribute's real options before asking. The customer's own answer is
sitting right there in `req.question`; nothing downstream of "single
candidate resolved" ever looks at it again.

A related, secondary gap makes this worse even if a match were attempted:
`CpqEngine.apply_answer`'s matching tiers (exact item_value, exact
display-name, substring-of-display-name) would **still** fail "2Yrs"
against "2 Year" — no tier normalizes common unit abbreviations ("Yrs"/"Yr"
→ "Year"). Tokenizing "2yrs" as one alphanumeric run (no space) also means
it shares zero words with "2 Year" for any word-overlap-based matcher.

## Fix

**Design refined during implementation planning**: this codebase already has
the exact building block both fixes need —
`_apply_pending_clarify_resolution` (`ask_api.py:7754`), used today only for
the anchor-based bare-value-reply case. It already does precisely "prefer
applying a value if the ORIGINAL utterance had one for this attr
(`detect_change_request`, which internally requires the attr to already be
in `session.filled` — a real change, not a first-time fill), falling back to
`_build_no_value_response` only when none parses." Reusing it directly for
both fixes needs zero new dispatch logic, and its existing
`session.filled`-membership requirement naturally scopes both fixes to the
"already filled, genuine change" shape both reported cases share — an
attribute that was never filled correctly keeps today's behavior
(`_build_no_value_response`'s original, still-appropriate contract for a
genuine first-time "no value given" case).

### Fix 1 — trust the gateway's own resolved attribute for AMBIGUOUS results

In the `IntentCategory.AMBIGUOUS` handler (`ask_api.py:5634`), before
falling through to `_set_pending_clarify_and_answer`'s raw-text attribute
re-derivation: if `result.variable_name` is populated, resolves to a real
attribute in `attrs`, and rule context (`hiding_rules`/`rec_rules`/
`con_rules`) is available, replay the original message against that ONE
attribute via `_apply_pending_clarify_resolution` instead of re-opening
attribute selection from scratch.

```python
if result.category == IntentCategory.AMBIGUOUS:
    if not result.clarifying_question:
        return None
    if (
        result.variable_name
        and any(a.variable_name == result.variable_name for a in attrs)
        and hiding_rules is not None and rec_rules is not None and con_rules is not None
    ):
        return _with_classify_usage(
            _apply_pending_clarify_resolution(
                req, session, attrs, result.variable_name, req.question,
                hiding_rules, rec_rules, con_rules, bml_eval,
            ),
            classify_prompt_tokens, classify_completion_tokens,
        )
    # ... existing fallback for genuinely attribute-level ambiguity ...
```
`result.variable_name` is re-validated against `attrs` here rather than
trusted blindly — the same defensive pattern this codebase already uses
everywhere else an LLM-supplied identifier crosses into real dispatch logic.

### Fix 2 — attempt to resolve the already-stated value before asking for one

`_set_pending_clarify_and_answer`'s two `len(candidates) == 1` branches
(`ask_api.py:8023` and `:8040`) currently jump straight to asking for a
value. Replace the `con_rules is not None` branch's direct
`_build_no_value_response` call with `_apply_pending_clarify_resolution`
(same call shape as Fix 1) whenever `hiding_rules`/`rec_rules` are also
available — it internally re-attempts matching `original_question` against
`candidates[0]`'s real options, applying directly on a match and falling
back to the exact same `_build_no_value_response` otherwise. The other
`elif len(candidates) == 1:` branch (no rule context at all) is left
unchanged — there is nothing to apply a change against yet.

### Fix 2b — normalize common duration/unit abbreviations in `apply_answer`

Add a small, targeted normalization step to `apply_answer` (or a wrapper
used by Fix 2's call site) recognizing "Yrs"/"Yr"/"Y" as equivalent to
"Year(s)", and similar common abbreviations, before the exact/substring
match tiers run — scoped narrowly to duration-shaped values (a token
matching `^\d+\s*(?:yrs?|y)$` normalized to `"<n> Year"`), not a general
NLP rewrite. Without this, Fix 2 alone still fails case 2's exact repro:
"2Yrs" would not match "2 Year" through any of `apply_answer`'s existing
tiers even once given the chance to try.

## Why this direction, not an alternative

- **Rejected: make `_ground_clarify_candidates` rarity-weighted (mirroring
  the value-candidate-truncation fix's approach) instead of trusting
  `result.variable_name`.** Would reduce, but not eliminate, Case 1's
  false candidates (Frequency Band would still plausibly out-score on "band"
  overlap) — and does nothing for Case 2 at all, since the LLM legitimately
  never disagreed on the correct attribute there. Fix 1 uses a stronger
  signal already computed for free: the gateway's own resolved `vn`.
- **Rejected: skip Fix 2b (abbreviation normalization) and call it a
  separate NLP problem.** Unlike the value-candidate-truncation plan's
  "zero overlap → correctly ask" carve-out, this case has **real,
  unambiguous lexical intent** ("2Yrs" plainly means "2 Year(s)" to any
  human reader) — this is a normalization gap, not genuine ambiguity, so
  falling through to a clarifying question here is the wrong outcome, not
  the correct fallback.

## Risk assessment

- **Fix 1 blast radius**: only changes behavior when `result.category ==
  AMBIGUOUS` AND `result.variable_name` is both populated and resolves to a
  real attribute — every other AMBIGUOUS shape (no vn at all, e.g. a
  genuinely unclear message naming no attribute) keeps today's behavior
  unchanged.
- **Fix 2 blast radius**: only fires at the specific single-candidate
  "about to ask which value" moment — never affects the main, already-
  working change-request dispatch path.
- **Fix 2b needs verification**: confirm the abbreviation normalization
  doesn't false-positive against any real catalog option whose display
  name coincidentally matches the narrowed pattern (e.g. an option
  literally displayed as "2Y" for an unrelated concept) — audit real
  catalog option text for the pattern before enabling broadly.
- **What could still go wrong**: Fix 1 assumes the gateway's per-turn
  `vn` is trustworthy whenever present on an AMBIGUOUS result — confirmed
  true for both live-reproduced cases, but worth a broader audit of how
  often AMBIGUOUS carries a populated `vn` vs. `None` before assuming this
  covers the majority of real ambiguous-clarify traffic.

## Verification plan

1. Unit tests: AMBIGUOUS result with a populated, real `variable_name`
   routes to `_build_no_value_response` for that attribute, not the
   generic multi-attribute clarify; AMBIGUOUS with no `variable_name` (or
   one that doesn't resolve to a real attr) keeps today's fallback
   behavior unchanged.
2. Unit tests: single-candidate clarify resolution with a genuinely
   matchable stated value (e.g. "2 Year" exactly) dispatches directly
   instead of asking; with a non-matchable value, still falls through to
   asking (no regression to the "value not given" case's real UX).
3. Unit tests for the abbreviation normalization: "2Yrs"/"2yr"/"2 Yrs" all
   resolve to the real "2 Year" option; an unrelated value untouched.
4. Full CPQ regression suite — confirm no new failures against the
   established pre-existing baseline (worktree-comparison discipline for
   any ambiguous failure, per this session's established convention).
5. Live replay: rebuild + redeploy `api`, replay both exact reported
   transcripts (Primary Frequency → UHF band; SmartProgramming → 2Yrs) and
   confirm each produces the correct, narrower outcome — a value-level
   clarify scoped to Primary Frequency alone for case 1 (UHF R1 vs UHF R2,
   not 5 unrelated attributes), and a direct dispatch for case 2 instead of
   a re-ask.

## Implementation summary (2026-08-21)

**Fix 1 — implemented, at both real AMBIGUOUS call sites.** Applied at
`ask_api.py`'s `_gw.action == "clarify"` branch and the sibling
`_mapped.category == IntentCategory.AMBIGUOUS` branch under `_gw.action ==
"dispatch"` (the `IntentCategory.AMBIGUOUS` branch inside
`_dispatch_intent_result`, which uses a structurally different
`IntentResult` type with no `variable_name` field for this category at all,
was investigated and confirmed NOT the real call site — the live bug's own
log evidence traced to the `_gw.result`-based path instead). Both edits
check `_gw.result.variable_name` (populated and real) plus rule-context
availability before routing through `_apply_pending_clarify_resolution`
scoped to that one attribute.

**Real safety-checkpoint interaction, verified rather than assumed.**
Investigated whether `mutating_disagreement`-triggered clarifies (a
DIFFERENT reason a clarify can be reached, distinct from case 1's genuine
value-level ambiguity) could also populate `variable_name` and
accidentally trigger Fix 1's new branch. Confirmed by reading
`intent_gateway.py`'s `mutating_disagreement` handling directly: the
`GatewayIntentResult` constructed there never sets `variable_name`,
defaulting it to `None` — so Fix 1's guard naturally and correctly never
fires for that case. Fix 1 is safe.

**Fix 2 — implemented, then reverted.** Applying the identical
`_apply_pending_clarify_resolution` pattern to `_set_pending_clarify_and_
answer`'s single-candidate branch broke
`test_cpq_llm_verdict_checkpoint_2026_08_13.py::test_change_request_
rejected_by_gateway_never_executes` — a real, deliberate safety mechanism
("blanket LLM-as-final-verdict") that exists specifically to stop a
confident deterministic pattern-match from dispatching when the gateway
disagreed. Unlike Fix 1's call sites, this branch is reached precisely
BECAUSE of ambiguity/disagreement, with no reliable way (at this call
site) to distinguish "reached here via genuine multi-attribute word-
overlap ambiguity" (safe to auto-apply) from "reached here via mutating_
disagreement" (unsafe — the gateway already said don't trust a
deterministic-only match). Confirmed this isn't merely a test artifact:
the same deterministic `apply_answer` match would also fire for real,
unmocked "change battery type to extended"-shaped messages. Reverted per
explicit user decision after presenting the tradeoff. SmartProgramming's
"stated value discarded" bug (case 2) remains open, needing a narrower
fix that can make this distinction before it's safe to implement.

**Fix 2b — implemented and unit-tested independently of Fix 2's revert.**
`CpqEngine.apply_answer` now normalizes `\d+\s*yrs?\b` to `"<n> year"`
before its existing matching tiers run. Still valuable on its own merits:
`apply_answer` is called from many other real dispatch paths (the main
change-request cascade, the anchor-based bare-reply case) where this
normalization applies with no safety-checkpoint conflict at all — it just
no longer helps close case 2 specifically, since that code path was
reverted.

**Tests**: `tests/test_cpq_ambiguous_clarify_resolved_evidence_2026_08_21.py`
(4 tests: 2 for Fix 1's apply/ask-scoped-narrowly behavior, 1 confirming
genuinely attribute-level ambiguity is unaffected, 1 pinning down Fix 2's
reverted-but-deliberate current behavior) and `tests/test_cpq_apply_
answer_duration_abbreviation_2026_08_21.py` (7 tests for Fix 2b) — all
passing, plus the full pre-existing `test_cpq_llm_verdict_checkpoint_
2026_08_13.py` suite (16 tests) re-confirmed passing after the revert.

**Full CPQ regression suite**: 1324 passed, 13 pre-existing failures
(byte-identical to the established baseline), zero new — confirmed both
before Fix 2's revert (which showed a genuine 14th, new failure, correctly
attributed and then fixed by reverting) and after.

**Live verification**: rebuilt + redeployed `api` against `dev-rv-msi`
with Fix 1 + Fix 2b in place (Fix 2 reverted). Confirmed via real gateway
logs that Fix 1's trigger condition (`AMBIGUOUS` category with a populated,
resolved `variable_name`) is a genuine, observed live response shape — the
original bug report's own transcript is direct evidence of it. Could not
force this EXACT trigger to reproduce deterministically on repeated retries
of the identical borderline phrasing ("Primary Frequency band") — the live
LLM gateway is genuinely non-deterministic for this specific wording,
sometimes classifying it as fully attribute-ambiguous (`vn=None`, correctly
untouched by this fix) and sometimes as attribute-resolved-value-ambiguous
(`vn` populated, the case this fix targets) — both confirmed via direct log
inspection across repeated live calls. A less ambiguous rephrasing
("Please set Primary Frequency to UHF R2") correctly dispatched directly
with no clarify needed at all, confirming no regression to the underlying
apply/dispatch mechanism. Fix 1's own logic is proven deterministically via
its unit tests (a controlled, mocked `GatewayDecision` removes the LLM's
live non-determinism from the test), which is the appropriate level to
verify code whose live trigger condition depends on an inherently
non-deterministic upstream classification.
