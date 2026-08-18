# CPQ Gateway pending_attr Conflation — Fix Plan

**Date:** 2026-08-17 / **implemented and verified 2026-08-18**
**Status:** Implemented (2 related rules — see "Second finding" below) on
`fix/cpq-gateway-pending-attr-conflation`. Verified: curated-scenario diff (6/8 clean, 2
confounded by an unrelated pre-existing mechanism — see scenario notes), 4 new unit tests +
27 pre-existing `test_cpq_intent_gateway.py` tests all passing (31/31), full CPQ regression
suite re-run with every failure/timeout individually confirmed pre-existing via `git
worktree` comparison against `dev-rv-msi` base, and the original reported live transcript
replayed end-to-end 2/2 successfully (previously failed 3/3 before this fix).
**Severity:** Medium-High (silent misroute to a generic re-ask; not data-corrupting, but
directly blocks a genuine request with no path forward except rephrasing)
**Discovered via:** live end-to-end replay while verifying `fix/cpq-quantity-target-misroute`
(PR #208) — confirmed unrelated to that PR's own code (see "Why this is separate" below).
**Scope note:** the concrete bug found and reproduced is quantity-specific, but the
underlying mechanism (a bare, unlabeled `pending_attr` variable name inviting the model to
hallucinate relevance) is generic — it can plausibly misfire for any message/category
pairing, not just quantity. This plan's fix is written at that general level rather than
patching only the one instance found; see "Fix design" and "Verify before implementing".

## Problem

While a genuinely unrelated attribute is pending (e.g. Hardware Version, mid-configuration),
sending an ordinary quantity-change message —

> "can you change that quantity to 5"

— sometimes gets rejected with a generic, wrong re-ask:

> "I didn't get **that reply** for **Hardware Version** — did you mean **APX NEXT (4G
> LTE+5G)**, **APX NEXT (4G LTE Only)**, or something else from the same list?"

instead of updating the overall product quantity. Reproduced consistently (3/3 live runs)
against the exact same turn-1 setup ("quote for APX NEXT in Canada" → Hardware Version
pending → "can you change that quantity to 5").

## Root cause

Confirmed via live container logs (`aryx-api-1`), not inferred:

```
cpq_intent_gateway: ambiguous run_id=2fc02670... reason="quarantine:variable_name_not_in_candidates;
The user is explicitly requesting to change a quantity to a specific number ('5'). The session
state 'pending_attr=hWVersion_astro' indicates that 'that quantity' refers to the quantity of
the recently discussed or modified line item, making this a bulk_quantity_change rather than a
change to the overall product quantity."
```

1. `src/aryx/cpq/intent_gateway.py:364` builds the gateway's session-state context as a bare
   variable name:
   ```python
   pending_bits.append(f"pending_attr={session.pending_variables[0]}")
   ```
   No display label, no concept, no signal about what that attribute actually represents.
2. Given `pending_attr=hWVersion_astro` (Hardware Version — nothing to do with quantity)
   alongside a message containing "quantity," the model hallucinates a connection purely
   from co-occurrence: it infers "the recently discussed line item" must be quantity-related,
   and misclassifies the message as `BULK_QUANTITY_CHANGE`.
3. That category fails quarantine (`variable_name_not_in_candidates` — there's no real
   quantity-shaped target to point at), downgrades to `ambiguous`.
4. `_llm_confirm_and_extract_quantity` (`ask_api.py:4509`, this session's own PR #208 code)
   correctly rejects on `intent_category != PRODUCT_QUANTITY_CHANGE` per its existing
   reject-on-disagreement discipline — falls through to normal hint/attribute processing.
5. Normal processing tries to match the message against the actually-pending Hardware
   Version answer slot, fails, and produces the generic "invalid answer" re-ask.

**Why this is separate from PR #208:** step 4 is PR #208's own gate behaving exactly as
designed (reject-on-disagreement, never guess) — the actual defect is one level up, in the
*general* intent gateway's classification, which PR #208's code never controls or touches.

## Fix design

**Rejected approach:** don't special-case `hWVersion_astro` or any specific attribute name —
this must be catalog-agnostic (this session's standing "don't hardcode" constraint), since
the same conflation can happen with any pending attribute paired with any quantity-mentioning
message.

**Chosen approach — give the model real context instead of a bare variable name, plus an
explicit instruction, matching this session's established design principle (reinforce the
LLM, don't route judgment through pattern-matching):**

1. In `_llm_classify_once` (`intent_gateway.py:320`), resolve `session.pending_variables[0]`
   against `bundles` (already passed in — each `AttrCandidateBundle.attr` has
   `display_label`) to get its real label, and include it:
   ```python
   pending_bits.append(f"pending_attr={vn} (label: {label!r})")
   ```
   No new parameter needed — `bundles` is already in scope.
2. Add a new HARD RULE to the system prompt (alongside the existing 6, e.g. as rule 7) —
   **written generally, not scoped to quantity**, since the underlying mechanism (a bare
   pending_attr name inviting a hallucinated connection) isn't quantity-specific:
   *"A pending attribute is relevant to classifying THIS message only if the message's own
   content actually relates to that attribute's real concept (its label, or its value
   candidates) — never infer relevance just because something is pending and the message
   happens to mention a related-sounding word. In particular: a pending attribute must never
   be treated as 'what the customer means' for a category (quantity change, country change,
   approval, or anything else) unless the pending attribute's own label genuinely matches
   that category's concept. When the message's real subject doesn't match the pending
   attribute at all, classify based on the message's actual content, not the fact that
   something else happens to be pending."*
3. No change to quarantine/validation logic, no change to PR #208's code — this fix lives
   entirely in the general gateway's own prompt, one level upstream of anything PR #208
   touches.

## Second finding, folded into this same fix (discovered during implementation, 2026-08-18)

Rule 7 alone was implemented and verified via the curated scenario table — it demonstrably
fixed the model's REASONING (scenario 1's rationale now explicitly says "The pending
attribute 'Hardware Version' is irrelevant to a quantity change"), but the outcome CATEGORY
for scenario 1 stayed `ambiguous` both before and after rule 7 alone. Since
`_llm_confirm_and_extract_quantity` (PR #208's own gate) rejects on ANY
`intent_category != PRODUCT_QUANTITY_CHANGE` — including a correctly-reasoned `ambiguous` —
rule 7 alone would NOT have fixed the user-visible symptom.

**Root cause of this second gap:** `IntentCategory.PRODUCT_QUANTITY_CHANGE` is a real,
schema-supported category (added 2026-08-13), but unlike `approval`/`decline` — which got an
explicit, dedicated disambiguation rule (rule 6, added after ISSUE-002) — it never got an
equivalent rule telling the model when to confidently choose it over defaulting to
`ambiguous` per rules 4/5's built-in caution ("prefer ambiguous when unsure"). This is
independent of the pending-attr conflation rule 7 addresses.

**Fix — rule 8, added to the same system prompt:**
*"PRODUCT_QUANTITY_CHANGE vs ambiguous: a bare/generic quantity reference ('that quantity',
'the quantity') with a clearly stated new number, and no specific catalog item named in the
message, should be classified as PRODUCT_QUANTITY_CHANGE with high confidence — do not
default to ambiguous just because no candidate attribute in CANDIDATE ATTRIBUTES matches;
PRODUCT_QUANTITY_CHANGE deliberately has no attribute target (variable_name=null is correct
for it)."*

**Confirmed via the same curated scenario 1, rule 8 added:**
```
scenario 1: 'can you change that quantity to 5'
    action=dispatch category=product_quantity_change confidence=high   (was: ambiguous)
```
Scenarios 2/3/4/6 unaffected (still correct) — rule 8 did not destabilize the categories it
doesn't concern.

Both rules 7 and 8 are needed together for the actual reported symptom to be fixed — rule 7
alone demonstrably was not sufficient. Kept in the same fix/PR since they were discovered
together, in the same investigation, targeting the same reported symptom.

## Why this direction over alternatives

- **Suppress/skip `pending_attr` entirely when the message mentions quantity:** rejected —
  too broad; `pending_attr` context is genuinely useful for many other classifications
  (e.g. resolving a short reply against the pending attribute's own options), and removing
  it unconditionally would regress those cases.
- **Special-case "if message mentions quantity, ignore pending_attr":** rejected — a
  pattern-matching special case exactly of the kind this session has repeatedly moved away
  from; also wrong when the pending attribute genuinely IS quantity-shaped (a real
  per-item quantity question could legitimately be pending).
- **Chosen fix generalizes correctly:** giving the model the label plus an explicit,
  category-agnostic rule lets it correctly handle every pairing — pending attribute
  genuinely matches the message's category (rule doesn't block it) vs. pending attribute is
  unrelated to whatever the message is actually about (rule forbids the conflation,
  regardless of which category would otherwise have been hallucinated) — without any
  catalog-specific or category-specific logic.
- **Scoping the rule to quantity only (the narrower alternative considered):** rejected once
  the user asked directly whether "any other random question" would be handled — a
  quantity-only rule only patches the one instance we happened to reproduce live; the
  general version closes the actual mechanism instead of one symptom of it.

## Risk assessment

This fix carries more risk than the quantity-target-misroute fix (PR #208), for structural
reasons worth stating plainly before implementing:

- **Blast radius is much larger.** `_llm_classify_once` is the *general-purpose* intent
  classifier used across nearly every conversational turn in this system — not a small,
  dedicated resolver like `_llm_resolve_quantity_target`. A prompt change here can shift
  classification behavior for scenarios that have nothing to do with quantity or
  pending-attr conflation at all.
- **Real overcorrection risk, not hypothetical.** The pending-attr context this fix
  restricts is *already* legitimately used elsewhere in this exact prompt — e.g.
  `customer_last_asked_about` and the existing guidance that "their immediately preceding
  message was a question about this attribute — a short follow-up like 'make it X' most
  likely refers to it." If the new anti-conflation rule is worded even slightly too
  strongly, it could suppress those genuinely correct inferences too. The fix must
  distinguish "don't hallucinate an unrelated *category*" from "don't use pending context at
  all," and that's a narrow line for prompt wording to hold reliably.
- **Thin evidence base.** Only one live-reproduced failure exists (the quantity case). The
  "general case" coverage below is spot-checks, not regression tests against confirmed prior
  failures — confidence in the generalized rule is lower than in the quantity fix, which had
  a known-bad baseline to prove against.
- **No deterministic backstop available.** Unlike PR #208 (which got a code-level backstop
  for the one case that's provably safe), this fix is prompt-only — the space of "message +
  pending attribute" pairings is too broad to enumerate a safe-default rule for.

Given this, verification must explicitly include a regression check against the *existing*
legitimate pending-context behaviors, not just new anti-conflation cases — that's the
overcorrection risk most likely to slip through unnoticed. Added below.

## No-regression guarantee — honest limits, and the strongest mitigation available

Stated plainly: **a prompt-only change to a shared, general-purpose classifier cannot be
proven to have zero impact the way PR #208's code-level backstop could.** No amount of
testing makes an LLM's behavior provably unchanged for every input — only "checked against
everything we can reasonably enumerate, with a cheap way back out if something slips
through." That's the honest ceiling here, and the plan below is built to reach it, not to
overclaim past it.

**Cost reassessment (revised after review — mining all 50 live cases was overkill):**
Mining real transcripts from all 50 E2E cases was the first idea, but it doesn't hold up
under its own cost: it requires at least one full live run of all 50 cases just to build
the extraction dataset, and per-turn latency in this system runs tens of seconds real time
(confirmed repeatedly this session), making that a genuinely expensive one-time cost for
what the overcorrection guard actually needs. The guard doesn't require *real* transcripts —
it needs realistic `(pending attribute, message)` pairings, which can be directly
constructed the same way this session already verified the quantity fix's own Critical
finding (a synthetic `ConfigAttr` + a crafted message, no live case run at all). Replaced
with a small, curated, directly-constructed scenario set below — no live case replay, no
transcript mining, no 50-case run.

**Curated scenario set — call `classify_intent` directly on each, before and after
implementing, diff the decisions:**

| # | Pending attribute (label) | Message | Covers | Expected classification behavior |
|---|---|---|---|---|
| 1 | `hWVersion_astro` ("Hardware Version") | "can you change that quantity to 5" | The confirmed live bug | Must NOT be `bulk_quantity_change`/`ambiguous` due to the pending attr — should resolve toward `product_quantity_change` |
| 2 | `hWVersion_astro` ("Hardware Version") | "change country to Germany" | Different category, same conflation shape | Must classify as a country-change intent, not conflated with Hardware Version |
| 3 | `serviceDuration_astro` ("Service Duration") | "yes, that's correct, submit it" | Approval conflation | Must classify as `approval`, not conflated with Service Duration |
| 4 | `serviceDuration_astro` ("Service Duration") | "no, don't submit yet" | Decline conflation | Must classify as `decline`, not conflated with Service Duration |
| 5 | `hWVersion_astro` ("Hardware Version") | "make it the 4G LTE Only one" | **Must keep working** — legitimate pending-context resolution | Must still resolve as an answer to `hWVersion_astro` (unaffected by the new rule) |
| 6 | none pending; `last_qa_variables=["batteryType_astro"]` | "make it standard" | **Must keep working** — `customer_last_asked_about` mechanism | Must still resolve against `batteryType_astro` (unaffected — this is a different, pre-existing pending-context mechanism) |
| 7 | A real quantity-shaped attr (e.g. `quantityVX650ItemType_astro`, "Quantity (VX650 Item Type)") | "change the quantity to 3" | Non-overcorrection check | The new rule must NOT block this category outright just because it's the same shape as case 1 — a genuinely quantity-shaped pending attribute may still legitimately compete |
| 8 | `modelSelectionHousing_astro` ("Housing") | "how many should I order" | Edge case — unrelated attr, no digit at all | Must resolve toward the overall product quantity, not conflated with Housing |

Any scenario whose before/after classification changes gets root-caused the same way this
session has treated every other finding: confirmed via direct evidence (the actual
prompt/reply), not assumed safe.

**This scenario table is also being added to the `docs/CPQ_E2E_TEST_SUITE_2026_08_14.xlsx`
tracking workbook** (a new sheet, mirroring this table) so it's tracked the same way every
other test scenario in this project is — not left as doc-only.

**Overcorrection guard (the specific failure mode most likely to hide in that diff):**
- A pending attribute + a short, valid-looking reply to it ("make it X", a bare option name)
  must still resolve against that pending attribute exactly as today — the new rule must
  only block an unrelated CATEGORY inference, never suppress legitimate value-resolution
  against the pending attribute itself.
- `customer_last_asked_about`-driven resolution (a short follow-up naming a value right
  after a QA question about that same attribute) must be unaffected — this is a different,
  pre-existing pending-context mechanism in the same prompt that must not be collaterally
  weakened.
- Run the full existing `tests/test_cpq_intent_gateway.py` suite (27 tests) — must stay
  100% green; any failure here is treated as a real regression, not noise.

**Cheap way back out, if the diff surfaces something real:** this fix is scoped to one
function's prompt construction in one file — a single, easily-revertible commit, not a
structural change spread across the codebase. If the golden-baseline diff shows an
unacceptable behavior shift anywhere, reverting this one commit fully restores prior
behavior with no cleanup needed elsewhere.

**Quantity case (the one we can directly regression-test against a known-bad baseline):**
- Live-reproduce the exact failing scenario against the current code first (confirm still
  reproducible on top of the latest `dev-rv-msi`, not just PR #208's branch, since this bug
  is independent of that PR).
- After the fix, replay the same 3 turns that reproduced the bug 3/3 times; confirm all 3
  resolve correctly to `cpq_product_quantity()`.
- Confirm a genuinely quantity-shaped pending attribute (e.g. a per-item quantity question
  actually pending) still classifies correctly as `BULK_QUANTITY_CHANGE` when appropriate —
  the new rule must not overcorrect into never allowing that category.

**General case (no known-bad baseline exists yet — these are spot-checks, not regression
tests against a confirmed prior failure):**
- Construct 2-3 other pending-attr + unrelated-message pairings by the same shape as the
  quantity bug (e.g. Hardware Version pending + a country-change message; a color attribute
  pending + an approval/decline message) and confirm the classification is driven by the
  message's real content, not the pending attribute's bare presence.
- Confirm a pending attribute that DOES genuinely relate to the message's category still
  classifies correctly — same non-overcorrection check as the quantity case, generalized.

**Both:**
- Confirm no regression in existing `intent_gateway` test coverage
  (`tests/test_cpq_intent_gateway.py`, 27 tests) — the prompt change is additive (one more
  context field, one more rule) but must not shift unrelated classifications.
- Run the full CPQ regression suite after implementing.

## Test cases (specified, not yet written)

All target `tests/test_cpq_intent_gateway.py`, mocking `aryx.cpq.intent_gateway._pinned_chat`
— the same mock point every existing test in that file already uses (e.g.
`test_gateway_classify_intent_timeout_returns_fast`). Two are prompt-content tests (the only
part of this fix that's meaningfully unit-testable — a mocked reply can prove the plumbing
works but can't prove a live model resists the hallucination); the third is the existing
non-overcorrection outcome check, kept as an outcome test since it only needs the *category*
in the mocked reply to still parse/dispatch correctly, not real judgment.

1. **`test_pending_attr_prompt_includes_display_label`**
   Setup: `session.pending_variables = ["hWVersion_astro"]`; build bundles via
   `build_candidate_bundles` from an attrs list containing
   `_attr("hWVersion_astro", "Hardware Version", [...])`. Call `_llm_classify_once` (mock
   `_pinned_chat` to capture its `user` arg and return a trivial valid JSON reply so the call
   completes).
   Assert: the captured `user` prompt contains `"Hardware Version"` — not just the bare
   `pending_attr=hWVersion_astro` token. **Currently fails** (today's code only ever emits the
   bare variable name at `intent_gateway.py:364`) — this is the test that goes green once
   fix step 1 (label lookup) lands.

2. **`test_pending_attr_conflation_rule_present_in_system_prompt`**
   Same setup as (1), but assert against the captured `sys` prompt instead: contains language
   requiring the pending attribute's own concept/label to genuinely match the message before
   it's treated as relevant (exact wording TBD at implementation time — assert on a
   distinctive substring of whatever the final rule text is, not the full sentence, so minor
   copy edits later don't break the test). **Currently fails** (no such rule exists yet) —
   goes green once fix step 2 (new HARD RULE) lands.

3. **`test_unrelated_pending_attr_does_not_block_correct_classification`**
   Setup: `session.pending_variables = ["hWVersion_astro"]` (unrelated to quantity); mock
   `_pinned_chat` to return a reply correctly classifying a quantity message as
   `product_quantity_change` (simulating what we want the reinforced prompt to make MORE
   likely in production, not proving it does). Call the full `classify_intent(...)` (not just
   `_llm_classify_once`) and assert `decision.action == "dispatch"` and
   `decision.result.intent_category == IntentCategory.PRODUCT_QUANTITY_CHANGE` — i.e. the
   quarantine/dispatch pipeline correctly accepts and forwards this category once the model
   gets it right, with nothing downstream still fighting it. This test should already PASS
   today (it isn't testing the prompt fix itself, just that the rest of the pipeline doesn't
   independently block a correct classification) — kept as a guard so a future change to
   quarantine logic can't silently reintroduce a block here.

Explicitly out of scope for unit tests (per "Verify before implementing" above): whether a
*live* model actually stops hallucinating the conflation — that can only be checked by live
replay against the running container, the same way the quantity-target fix's Critical finding
was verified end-to-end, not asserted in a mocked test.

## Files expected to change

- `src/aryx/cpq/intent_gateway.py` — `_llm_classify_once`'s `pending_bits` construction
  (~line 362-364) and its system prompt's HARD RULES list (~line 336-358).
- `tests/test_cpq_intent_gateway.py` — new tests covering the general rule, not just the
  quantity instance: (1) pending attr unrelated to quantity + quantity-mentioning message →
  must NOT classify as `bulk_quantity_change` (the confirmed live bug); (2) pending attr
  that IS quantity-shaped + quantity message → classification behavior unchanged; (3) at
  least one non-quantity pairing (e.g. an unrelated pending attr + a country-change or
  approval message) → classification driven by the message's real content, not the pending
  attribute's mere presence.
- Possibly `docs/CPQ_QUANTITY_TARGET_MISROUTE_FIX_PLAN_2026_08_17.md` — cross-reference once
  this is implemented, closing the "separate, out-of-scope finding" section there.
