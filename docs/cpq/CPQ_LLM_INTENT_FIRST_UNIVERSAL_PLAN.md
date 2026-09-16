# CPQ LLM-First Universal Intent Plan

Status: **investigation / proposal — not implemented, not approved for code changes**
Owner request: make the LLM the *first* decision-maker for every user turn,
replacing the deterministic regex/keyword layer as the primary router.
Explicitly stated: speed and cost are not constraints for this decision.

---

## 1. Current architecture (baseline)

`_run_cpq_turn` (`ask_api.py`) is a fixed sequence of **deterministic
detectors**, each a regex/keyword function in `engine.py`, checked in a
fixed order, top to bottom, per turn:

| # | Detector | Purpose |
|---|---|---|
| 1 | `detect_product_mention` | resolve a product/catalog family from free text |
| 2 | `detect_response_mode_request` | "show json" / "show all pending" |
| 3 | `detect_multi_select_removal` | "remove Jacket Magnetic Mount" |
| 4 | `detect_attr_activation` | re-add an excluded optional attr |
| 5 | `detect_attr_clear` | clear a filled attr back to empty |
| 6 | `detect_bulk_quantity_change` | "change both mounting quantities to 67" |
| 7 | `detect_approval` | "confirm" |
| 8 | `detect_qa_question` | is this a question, not a config instruction |
| 9 | `detect_change_request` | single "change X to Y" |
| 10 | `detect_change_target_without_value` | "change X" with no value |
| 11 | `detect_change_requests_multi` | "change X to A and Y to B" |
| 12 | `detect_label_collision` | a QUESTION naming an ambiguous shared label |
| 13 | `detect_change_request_collision` | a CHANGE naming an ambiguous shared label |
| 14 | `detect_attr_query` | "what are the options for X" |

Plus **pending-state re-entry checks** (not detectors, but also deterministic):
`session.pending_change_no_value_vn`, `pending_change_collision_vns`,
`pending_label_collision_vns`, `pending_multi_intent_vn`.

Plus fragment-matching value appliers: `apply_answer`, `apply_multi_answer`
(match a free-text reply against an attr's own option list).

**Existing LLM fallback layer** (already present, only invoked when the
above finds nothing or is ambiguous):

- `_llm_classify_is_cpq_question` — is an out-of-scope-looking question
  actually CPQ-relevant?
- `_llm_extract_multi_attr_hints` — dense multi-fact sentences
- `_llm_classify_change_intent` — change/remove intent when regex found nothing
- `_llm_resolve_pending_answer` — fragment match failed, try semantic match
- `_llm_resolve_label_collision` — resolve "the second one" phrasing
- `_compose_disambiguation_question` — phrase a clarifying question

So today's architecture is already "LLM-assisted," just **LLM-last**, not
LLM-first. Every regex detector was added in response to a **specific,
live-reproduced bug** — each one encodes a real customer phrasing this
system got wrong before the detector existed.

---

## 2. Proposed change

Replace step-by-step regex triage with: **one LLM call per turn, first,
that classifies the user's intent** (which of the ~14 categories above,
or "none/ambiguous") and extracts whatever structured fields that intent
needs (target attr, new value, collision resolution index, etc.) — then
dispatch directly to the same handler functions (`_handle_cascade`,
`_handle_multi_select_removal`, etc.) using the LLM's structured output
instead of a regex match object.

If the LLM itself is uncertain or the question is ambiguous about the
graph, the system asks the user a clarifying question *before* doing
anything else — even for a single ambiguous word — rather than guessing.

---

## 3. Risks (the actual investigation)

### 3.1 Determinism loss on state-mutating operations — highest severity

Every detector above doesn't just "understand" the message — it directly
produces the **exact string keys** the rest of the system depends on:
`variable_name`, `item_value` (not `display_name`), `entity_id`. These are
catalog-specific, machine-generated identifiers
(`serviceTypeRSM_astro`, `H45TGU9PW8AN`) that never appear in natural
language. An LLM asked "which attribute and value does this refer to"
has to be handed the candidate list and asked to pick/copy an ID
verbatim — the same constraint `_llm_resolve_pending_answer` and
`_llm_classify_change_intent` already work under. This is solvable (it's
what the existing fallback functions already do) but it means the LLM is
never truly "freeform" — every call still needs the full candidate-attr
list in its prompt, which reintroduces per-catalog context assembly cost
this proposal was meant to simplify away.

### 3.2 Loss of test reproducibility

The current 257 CPQ/BML tests assert exact deterministic outcomes for exact
inputs. An LLM classifier is not guaranteed to return the same
classification for the same input across model versions/temperature —
today's regex detectors are pinned, versioned, and diffable in code
review; an LLM-first router's *behavior* lives partly in a prompt string,
which is far more prone to silent drift. Every one of today's detectors
exists because of a **live-reproduced regression** — replacing them
removes the thing that made each of those regressions provably fixed
forever, in favor of "probably still handled by the model."

### 3.3 Compounding hallucination risk on ambiguous-but-plausible input

Several detectors exist specifically to prevent a *plausible-sounding
wrong answer* (`detect_label_collision`, `detect_change_request_collision`,
the D1 "user value overridden" revert logic) — these are cases where a
wrong-but-confident guess is worse than an explicit disambiguation
question. An LLM intent classifier, unless very carefully prompted and
gated, tends toward confident single answers rather than admitting
uncertainty — this is the exact failure mode already observed live in
this session (the "astra" hallucination) at the Q&A layer; making the
LLM the intent gate for **every** action (including ones that mutate a
real customer quote) raises the stakes of that same failure mode.

### 3.4 Catalog scale and prompt cost per turn

The user's own stated context — "multiple XML files," large catalogs
(APX Next, SVX, CommandCentral Aware all seen in this session with
hundreds of attrs) — means the LLM would need either (a) the full
candidate attr list in every prompt (large, catalog-dependent context) or
(b) a pre-filtering step to narrow candidates first, which reintroduces a
deterministic/heuristic step ahead of the LLM anyway. Cost/speed are
stated as non-concerns, but context-window correctness (the LLM must not
silently omit a real candidate attr due to truncation) is a correctness
risk independent of cost.

### 3.5 Error handling / malformed output

Every existing `_llm_*` function already has to defensively parse JSON,
handle empty/garbled replies, and fail closed (`return None`/`False`) —
this pattern multiplies by however many action types now route through
one universal classifier. A malformed or empty LLM response for a
config-mutating action (not just a Q&A answer) has a larger blast radius:
a misfired removal, an incorrectly-applied value, or a wrong attribute
targeted for change.

### 3.6 Regression risk to this session's own recent fixes

Several bugs fixed this session exist specifically because of *detector
ordering* (`detect_change_request_collision` running before
`detect_change_requests_multi`; the pending-state checks running before
their surrounding STEP) and because `_handle_cascade` is the single
convergence point every path reaches. An LLM-first router would need to
reproduce this exact convergence discipline itself (one classification →
one handler call, no double-dispatch) or these same classes of bug
reappear in a new form.

---

## 4. What genuinely gets better

- **Phrasing coverage**: today's regex misses *specific* phrasings until
  someone hits them live and a new detector/pattern is added (this
  session added several this way). An LLM-first classifier could
  generalize across phrasing variance the fixed pattern list can't
  anticipate.
- **Single dispatch point**: one classification call, one result object,
  one handler call — potentially *simpler* control flow than today's
  14-detector waterfall, if the schema is designed well.
- **Ambiguity handling as a first-class output**: the classifier can be
  required to emit `"ambiguous": true` + a clarifying question whenever
  confidence is low, which is exactly the "ask before guessing, even for
  one word" behavior requested — this is a real, buildable improvement,
  and is the strongest part of this proposal on its own merits,
  independent of whether it's LLM-*first* or LLM-*augmented*.

---

## 5. Reconciled target architecture — LLM-first for understanding, deterministic-underneath for exactness

Owner follow-up (2026-07-28): a per-category evidence-gated flip (the
original §5) under-serves the actual problem — a genuinely novel
phrasing the regex layer has never seen will never accumulate the
shadow-mode evidence needed to flip its category in the first place.
The fix isn't choosing which layer runs first per category; it's
changing *what each layer is responsible for*, on every turn, no
per-category gating needed:

1. **LLM runs first, always, for every turn.** It classifies intent
   (one of the 14 categories, or "ambiguous") and names its target(s) in
   **plain language** — "the Solution Type field," "the shirt-mount
   quantity," "Extended Warranty" — not catalog IDs. This is exactly what
   generalizes to phrasing the regex layer has never seen, because the
   LLM isn't pattern-matching against fixed strings.
2. **The deterministic layer runs second, underneath, as the exactness
   step, not the router.** It resolves whatever the LLM named against
   the real catalog — `variable_name`, `item_value`, `entity_id` — using
   the same fragment/fuzzy-matching (`apply_answer`, `apply_multi_answer`)
   and collision-detection (`detect_label_collision` et al.) logic that
   exists today. This is where §3.1's exactness requirement is satisfied
   — the LLM never has to output a machine ID verbatim, only point at
   what it means well enough for the deterministic layer to resolve it.
3. **Ambiguity is a required, explicit LLM output, not a side effect.**
   Every classification either resolves cleanly through step 2, or one of
   two things happens and the turn stops to ask instead of guessing:
   - the LLM itself couldn't confidently name a target (low confidence),
   - the deterministic layer couldn't resolve what the LLM named to a
     real catalog entry (e.g. the LLM said "the coverage field" and 2+
     attrs plausibly match).
   Either case surfaces `_compose_disambiguation_question` — this
   directly satisfies "ask before guessing, even for a single word,"
   because it's now the REQUIRED fallback of every classification, not
   an occasional side path.
4. **Existing handler functions are unchanged.** `_handle_cascade`,
   `_handle_multi_select_removal`, etc. still receive a resolved attr +
   value — same contract as today, just fed by (LLM name → deterministic
   ID resolution) instead of (regex match → ID directly). This preserves
   §3.6's convergence discipline: one classification, one resolution,
   one handler call, no double-dispatch.

This still needs implementation discipline to be safe, so the phased
rollout below is unchanged in spirit — shadow mode first — but the
*shape* being validated is this two-layer design, not "which detector
wins," which is what actually addresses "a question we haven't seen":

1. **Phase 0 — schema design — ✅ DONE (2026-07-28)**: `src/aryx/cpq/
   intent_schema.py` — `IntentCategory` (12 detector-mirror categories +
   `AMBIGUOUS` + `OUT_OF_SCOPE`, deliberately excluding `label_collision`/
   `change_request_collision` per the §5 refinement — those emerge from
   resolution-layer failure, not upfront LLM classification),
   `Confidence` (high/medium/low, low always routes to ambiguous
   handling), `ChangeTarget`/`IntentResult` dataclasses, the
   `INTENT_RESULT_JSON_SCHEMA` structured-output contract, and
   `parse_intent_result` — the single fail-closed parse/validate
   chokepoint (mitigation #7). Covered by `tests/
   test_cpq_intent_schema.py` (11 tests, all passing; full CPQ/BML suite
   257→268 passing, zero regressions — this module is NOT wired into
   `_run_cpq_turn` yet, purely additive). Every field is a plain-language
   description, never a raw `variable_name`/`item_value` — see the
   module's own docstring for the full rationale.
2. **Phase 1 — shadow mode — ✅ DONE (2026-07-28)**: `_llm_classify_
   intent_universal` + `_resolve_target_description` (ask_api.py) — one
   classification call per turn using the Phase 0 schema, resolved via
   the SAME `_relevant_intent_candidates` word-overlap matching every
   other `_llm_*` fallback already uses (never a new heuristic). Wired
   read-only via `_shadow_classify_cpq_turn`, called right after `attrs`
   loads in `_run_cpq_turn`; the real turn's outcome is logged separately
   in `run_ask` right after `_run_cpq_turn` returns — both lines carry the
   same `run_id` (existing contextvar logging), so "agreement/
   disagreement" is a grep-by-run_id analysis, not an in-process diff
   against a function with dozens of early-return call sites. Gated on
   new setting `cpq_shadow_intent_enabled` (default **off**) — live-
   confirmed the unconditional version added a real LLM call to every
   test invoking `_run_cpq_turn`, taking the CPQ/BML suite from ~10s to
   ~128s with zero behavioral change; this is a genuine test-speed/CI-cost
   concern, distinct from the "not a concern in production" decision, and
   is guarded the same way `bml_use_llm` already guards an analogous
   always-on-cost risk. Direct functional check (bypassing the flag):
   fed the exact "change solution type and primary service type"
   scenario that took 3 rounds of deterministic patching earlier this
   session — the shadow classifier correctly returned `category=
   ambiguous` with a genuinely useful clarifying question on the FIRST
   call, no iteration needed. Full CPQ/BML suite: 268/268 passing with
   the flag off (default).
3. **Phase 2 — cutover — ⚠️ PARTIAL (2026-07-28), NOT recommended for
   production yet**: `_dispatch_intent_result` + `_resolve_target_
   description` (ask_api.py), wired at the top of STEP 6 behind new
   setting `cpq_llm_first_enabled` (default **off**). Covers
   `CHANGE_REQUEST`, `CHANGE_REQUESTS_MULTI`, `AMBIGUOUS`, `OUT_OF_SCOPE`
   only — every other category (`MULTI_SELECT_REMOVAL`, `ATTR_ACTIVATION`,
   `ATTR_CLEAR`, `BULK_QUANTITY_CHANGE`, `RESPONSE_MODE_REQUEST`,
   `APPROVAL`, `ATTR_QUERY`, `QA_QUESTION`, `CHANGE_TARGET_WITHOUT_VALUE`,
   `PRODUCT_MENTION`) still returns `None` from the dispatcher and falls
   through to the unchanged deterministic path — deliberately deferred,
   not rushed. **This landing is the CAPABILITY, not evidence the cutover
   is safe** — the plan's own Phase 2 criterion ("once shadow mode shows
   the deterministic resolution step reliably resolves what the LLM
   names") has not actually been measured against real traffic yet, since
   Phase 1 was only just wired. Enabling `cpq_llm_first_enabled` in
   production ahead of that data is skipping the evidence-gathering step
   the phased design exists for.

   A real bug was caught building this: `_resolve_target_description`
   originally reused `_relevant_intent_candidates` (Phase 1's own
   resolver), but live-verified that function returns its top-K (K=10)
   candidates by score, not just tied-best ones — its actual job is
   narrowing an LLM prompt's candidate list, not declaring a single
   winner — so reusing it made resolution look "ambiguous" for almost
   every target, even a genuinely uniquely-labeled attr. Replaced with
   direct single-winner scoring (resolves only when there's a strictly-
   highest, nonzero-overlap match; a tie or zero overlap both mean
   unresolved). Live-confirmed against `quickStartGuide_astro` (a
   uniquely-labeled attr): `_dispatch_intent_result` correctly resolved
   the plain-language description, called `_handle_cascade`, and the
   value applied exactly as it would through the regex path
   (`tools_called: ["cpq_cascade()"]`).

   Regex detectors remain the fallback for every un-dispatched case —
   never removed, same "fail closed" discipline every `_llm_*` function
   already follows.
4. **Phase 3 — ambiguity-first Q&A — ✅ DONE (2026-07-28)**: wired into
   `_handle_cpq_qa`'s generic fallback, right before the `_synthesise`
   call, behind new setting `cpq_qa_ambiguity_check_enabled` (default
   off). Reuses the SAME universal classifier as Phase 1/2 — this is its
   first REAL (non-shadow) consumer: when the classifier returns
   `AMBIGUOUS` with non-low confidence and a `clarifying_question`, that
   question is returned directly instead of calling `_synthesise` on
   whatever `gather()` found. Lower risk than Phase 2's cutover because
   Q&A answers are informational, never config-mutating — a wrong call
   here costs one extra clarifying question, not a misapplied change.
   Directly satisfies the original "ask before guessing, even a single
   word" request for the generic graph Q&A path specifically (config-turn
   ambiguity was already handled by existing label-collision detectors).
5. **Never remove the regex detectors** — they remain the deterministic
   resolution layer (Phase 2's `_resolve_target_description`) AND the
   fallback path for every category Phase 2 doesn't cover — this design
   needs them forever, just repurposed/supplemented, never replaced.

**Test/verification summary across all four phases**: full CPQ/BML suite
268/268 passing throughout, ~13-14s (all new settings default off — zero
test-speed impact). Each phase's new code path was also directly,
functionally exercised (bypassing its settings flag) against the live
ASTRO catalog: Phase 1's shadow classifier against the exact multi-intent
scenario that needed 3 rounds of deterministic patching earlier this
session (correctly flagged ambiguous, first try); Phase 2's dispatcher
against a uniquely-labeled attr (correctly resolved and applied); Phase 3
reuses Phase 1's already-verified classifier output with a straightforward
conditional, not independently re-verified end-to-end via a live turn.

---

## 6. Risk register and mitigations (excluding speed/cost — explicitly ruled out)

Each risk from §3, paired with a concrete mitigation. Every mitigation
reuses a discipline already proven in this codebase this session (fail-
closed defaults, shared resolution helpers, shadow-mode measurement
before cutover) rather than inventing a new safety mechanism — the
lowest-risk path to the same design.

| # | Risk (§3 ref) | Mitigation |
|---|---|---|
| 1 | Determinism loss on state-mutating IDs (§3.1) | LLM never outputs a `variable_name`/`item_value` — only a plain-language target description + a confidence score. The deterministic layer (existing `apply_answer`/`detect_label_collision` fuzzy-match) is the ONLY thing allowed to produce a real catalog ID. If it can't match with confidence, that's an automatic ambiguity, not a guess. |
| 2 | Test reproducibility (§3.2) | Keep all 257 existing tests as a permanent regression gate against the deterministic resolution layer (unchanged by this plan). Add a SEPARATE, versioned suite of frozen classification transcripts (input → expected category) re-run on every prompt change — catches prompt drift the way snapshot tests catch code drift. |
| 3 | Hallucination on config-mutating actions (§3.3) | Because of mitigation #1, hallucination risk is structurally contained to "picked the wrong category" (cheap to catch via #9's ambiguity threshold), never "picked the wrong catalog attribute to edit" — the resolution step can't silently accept a wrong ID it invented itself. |
| 4 | Resolution-failure blast radius | Make "ask, don't guess" the literal default return value of the resolution step (`None`/ambiguous) rather than an opt-in check each call site has to remember — same bail-to-`None` pattern this session already used in `describe_free_text_constraint`/`evaluate_constant_return`. One shared function, not per-caller discipline. |
| 5 | Convergence-discipline regression (§3.6) | Route every resolved classification through the EXISTING single handler set (`_handle_cascade`, etc.) unchanged — the classifier's job ends at "which handler, with what resolved attr/value," never calling handlers directly itself. Reuses the exact convergence fix already proven this session (moving the multi-intent follow-up logic into `_handle_cascade` itself). |
| 6 | Context-window truncation on large catalogs (§3.4) | Never send the full attr list blind — pre-filter candidates deterministically first (cheap keyword/embedding narrowing to top-N) before the LLM sees them, and log() when narrowing drops candidates, so silent omission is visible, not just silently wrong. |
| 7 | Malformed/empty LLM output handling (§3.5) | One shared parse-and-validate wrapper (schema-validated JSON) used by every classification call site, not each one hand-rolling its own `try/except` — consolidates today's per-`_llm_*`-function defensive parsing into a single, testable chokepoint. |
| 8 | Prompt maintainability/reviewability | Version the prompt as a tracked file (not an inline string), require the same PR review as code, and gate every prompt change on the golden-transcript suite from #2 passing — makes prompt changes diffable and testable, not silent. |
| 9 | Ambiguity threshold calibration | Start conservative (ask more than feels strictly necessary) and tune down ONLY against measured shadow-mode data (real disagreement/resolution-failure rates from Phase 1), never by feel. |

## 7. Explicit go/no-go questions for the user before Phase 0 starts

- Is a full, all-at-once cutover acceptable, or is the phased/shadow-mode
  approach (safer, slower to fully land) preferred?
- Should the 257 existing deterministic tests be treated as a *regression
  gate* the LLM-first path must also satisfy (recommended), or superseded?
- Who reviews/owns the classification prompt as it evolves — prompts are
  harder to code-review than regex diffs.

---

## 8. Phase 4 — Universal cutover: LLM-first on every turn, not just post-approval (2026-08-13)

### Context

Two live bugs this same day (docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md,
Issues 6/7) both had the same shape: a deterministic regex either
misfired or was simply missing for a real customer request, during a
normal **configuring-stage** turn. The fix applied there
(`_llm_confirm_deterministic_intent`) is a *confirm-after* checkpoint —
the regex still runs first, the LLM only vetoes. Owner directive
following that fix: the LLM should identify intent **first**, on every
turn, everywhere — not just as a post-hoc veto, and not just on the
narrow slice of turns this plan's Phase 2 already covers.

**The gap, confirmed by code read:** `_dispatch_intent_result` — the
Phase 2 LLM-first dispatcher — already resolves **10 of the 16
`IntentCategory` values** directly to real handlers (`CHANGE_REQUEST`,
`CHANGE_REQUESTS_MULTI`, `CHANGE_TARGET_WITHOUT_VALUE`, `AMBIGUOUS`,
`OUT_OF_SCOPE`, `ATTR_QUERY`, `QA_QUESTION`, `MULTI_SELECT_REMOVAL`,
`ATTR_ACTIVATION`, `ATTR_CLEAR`). It is far more built-out than this
doc's own §5 status table suggests. But its **only call site**
(`ask_api.py:8418`) sits inside `if session.status in
("awaiting_approval", "post_approval"):` — a block that only runs
*after* the customer has already seen a complete configuration summary.
During the entire configuring-stage conversation (every turn before
that point — the majority of real traffic), this dispatcher never
executes at all; only the narrower, confirm-after checkpoint from
Issues 6/7 runs there today.

Two more gaps found alongside this:
- `classify_intent`/`gateway_classify_intent` has **no timeout
  wrapper** — unlike `classify_ask_route`'s `cpq_intent_timeout_s`
  (10s, `ThreadPoolExecutor`-based). Calling it far more often makes an
  unbounded hang a bigger exposure than it is today.
- `PRODUCT_QUANTITY_CHANGE` and `COUNTRY_CHANGE` (new categories added
  for Issues 6/7) are not wired into `_dispatch_intent_result` at all
  yet — they exist only as confirm-after checkpoints.
- `BULK_QUANTITY_CHANGE`, `RESPONSE_MODE_REQUEST`, `APPROVAL`,
  `PRODUCT_MENTION` remain unwired from this plan's original Phase 2
  landing, deferred deliberately at the time.

### Goal

The LLM classifies intent first, for every turn, regardless of
`session.status` — configuring, awaiting_approval, and post_approval
alike — for every `IntentCategory`, with the deterministic layer
staying in place underneath as the exactness/resolution step (§5's
already-agreed design), never removed.

### Design

**1. Timeout wrapper on `classify_intent` (`intent_gateway.py`).**
Wrap the `_pinned_chat` call the same way `classify_ask_route` already
wraps its own call — `ThreadPoolExecutor` + a new setting
`cpq_intent_classify_timeout_s` (default 10.0s, mirroring
`cpq_intent_timeout_s`). On timeout, return a `GatewayDecision` with
`action="fallback"` (not `"dispatch"` or `"clarify"`) — callers already
treat `fallback` as "proceed to the deterministic path," so no new
caller-side branch is needed, only the new failure mode feeding an
existing one.

**2. Move the dispatch call site out of the status-gated block.**
Relocate the "LLM-first mid-session gateway" section (`ask_api.py`,
currently ~8177-8210, nested inside the `awaiting_approval`/
`post_approval` `if`) to run unconditionally, immediately after
`hiding_rules`/`rec_rules`/`con_rules`/`bml_eval` load (~line 7793) —
the same insertion point Issues 6/7's confirm-after checkpoints already
use for their own early gates, so both mechanisms sit at a consistent
place in the turn. Existing guards (`cpq_llm_first_enabled`,
`not session.guided_mode`, `not top_level_route_used()`, `not
_defer_gateway_to_pending_answer`) are kept as-is — they already exist
to prevent double-classification and to respect an actively-pending
reply, and apply equally well regardless of status.

The existing status-scoped call site is then redundant and removed —
one call site, one dispatch point, for every stage of the
conversation, matching this plan's own §5 convergence-discipline
mitigation (#5 in the risk register).

**3. Wire the 6 remaining categories into `_dispatch_intent_result`.**
Two groups, same pattern each existing branch already follows
(resolve target via `_resolve_target_description`, re-verify the
action is *currently valid* the same way the regex counterpart would,
call the same existing handler):

- `PRODUCT_QUANTITY_CHANGE` → the existing STEP-6 quantity-gate body
  (`ask_api.py`, `_qty_target == "product"` branch) refactored into a
  small callable both the regex path and this dispatch branch invoke,
  taking the already-parsed quantity value directly (no
  `_resolve_target_description` needed — this category has no
  `variable_name`, mirroring how `PRODUCT_QUANTITY_CHANGE` is already
  in `_GATEWAY_NO_TARGET_CATEGORIES`).
- `COUNTRY_CHANGE` → same shape, reusing the country-change response
  logic (no-op-if-already-matching included) added for Issue 7.
- `BULK_QUANTITY_CHANGE` → resolve the named grid/selector via
  `_resolve_target_description`, re-verify real quantity-linked rows
  exist for it, call `_handle_bulk_quantity_change`.
- `RESPONSE_MODE_REQUEST` → no target needed; dispatch straight to
  `_build_json_preview_response`/existing batch-mode handling, mirroring
  `detect_response_mode_request`'s own return value via the
  already-defined `response_mode` schema field.
- `APPROVAL` → dispatch to `_handle_approval`, `Confidence.HIGH`
  required (mutating + terminal — same discipline `ATTR_QUERY`/
  `QA_QUESTION` already use for their own high-stakes-but-unprobed
  categories).
- `PRODUCT_MENTION` → deferred again, explicitly, in this phase too —
  this doc's own §5 already flags it needs a different resolution
  shape (product/family name, not an attribute), which is a separate,
  smaller follow-up, not blocking the other 5.

**4. Reject-on-failure stays a fallback, not a hard error.**
Unlike `classify_ask_route`'s turn-1 behavior (explicit customer-facing
error on failure, per §5/Follow-up in the sibling doc), a mid-session
classification failure here falls through to the unchanged
deterministic-detector-plus-confirm-checkpoint path from Issues 6/7 —
never a raw error to the customer. This is a deliberate difference from
the turn-1 router: turn-1 has no deterministic fallback with any
real chance of being right (the whole point of that call was
extraction), whereas here the full deterministic layer is right there,
already hardened, and already gets its own independent LLM
confirmation. Two failed LLM calls in a row (dispatch-attempt +
confirm-checkpoint) is the actual worst case, and only then does the
turn fall through to old, pre-Issue-6 behavior for that one gate.

**5. Rollout — shadow-mode first, matching this plan's own §6/#9 discipline.**
1. Ship behind the existing `cpq_llm_first_enabled` flag, default
   unchanged (already `True` in dev/test per `config.py`) — but add a
   NEW, separate flag `cpq_llm_first_universal_enabled` (default
   **off**) gating specifically "run regardless of status" (item 2
   above) and the 6 new dispatch branches (item 3), so the existing,
   already-shipped awaiting_approval-only behavior is untouched until
   this is explicitly turned on.
2. Enable in staging/shadow first; log dispatch vs fallback vs
   disagreement rates per category, same `run_id`-keyed grep-analysis
   approach Phase 1 already established — no new logging mechanism
   needed.
3. Flip `cpq_llm_first_universal_enabled` to default-on only after a
   measured disagreement rate is reviewed for the 5 newly-mutating
   categories (quantity/country/bulk-quantity/approval/response-mode)
   specifically — these are the ones with real blast radius; read-only
   categories (`ATTR_QUERY`, `QA_QUESTION`) already carry lower risk
   and were exactly the pattern Phase 3 used to justify shipping ahead
   of full evidence.

### Test plan

*Positive:*
- `test_dispatch_runs_during_configuring_status_not_just_awaiting_approval` — the core regression this phase exists to fix: a configuring-stage turn with `cpq_llm_first_universal_enabled=True`, LLM confirms `MULTI_SELECT_REMOVAL`, assert `_handle_multi_select_removal` is called from the dispatcher, not the confirm-after checkpoint (distinguish via call count / mock target).
- `test_product_quantity_change_dispatches_directly` / `test_country_change_dispatches_directly` — each new branch, mirroring the existing `MULTI_SELECT_REMOVAL` dispatch test shape in the current suite.
- `test_classify_intent_timeout_falls_through_to_deterministic_path` — mock `_pinned_chat` to hang past the new timeout, assert `action="fallback"` and the turn completes via the regex-plus-confirm path, not an error or a hang.
- `test_single_call_site_no_double_dispatch` — regression-protect §5's convergence discipline: assert `gateway_classify_intent` is called at most once per turn for the dispatch attempt (the confirm-checkpoint's OWN call, when the dispatch path already resolved, must never also fire — dispatch success short-circuits before any gate's confirm-checkpoint runs).

*Negative:*
- `test_universal_flag_off_preserves_todays_awaiting_approval_only_behavior` — flag off (default) → a configuring-stage turn behaves exactly as it does today (confirm-after checkpoints only, dispatcher inert), full existing suite unaffected.
- `test_dispatch_disagreement_falls_through_never_double_mutates` — dispatcher resolves+calls a handler; assert the SAME gate's confirm-after checkpoint from Issues 6/7 is never ALSO reached for that turn (the two mechanisms must be mutually exclusive per turn, not additive) — direct regression test for item 4's "worst case is 2 calls, never 2 mutations."
- `test_product_mention_still_falls_through_undispatched` — confirms the explicit deferral in item 3 remains inert, not silently half-wired.

### Status

**Implemented 2026-08-13, off by default pending shadow-mode validation.**

- **Critical bug found and fixed before implementation started**:
  `classify_intent` bailed to `action="fallback"` whenever `attrs` was
  empty, WITHOUT ever calling the LLM — the PRODUCT_QUANTITY_CHANGE and
  COUNTRY_CHANGE confirmation checkpoints from Issues 6/7 (already
  merged via PR #188) both call this with `attrs=[]` by design, meaning
  the country-change gate was a silent no-op in production despite
  passing every test. Fixed: only an empty question bails now.
- **Timeout wrapper** — new `cpq_intent_classify_timeout_s` (default
  10s), same `ThreadPoolExecutor` pattern as `classify_ask_route`.
- **Scope correction**: `_dispatch_intent_result` turned out to already
  resolve 12 of 16 categories, not the 4-10 this doc's earlier sections
  suggested (the docstring had drifted from the actual code) — only
  `PRODUCT_QUANTITY_CHANGE`/`COUNTRY_CHANGE` needed new branches;
  `BULK_QUANTITY_CHANGE`/`RESPONSE_MODE_REQUEST`/`APPROVAL` were already
  wired. `PRODUCT_MENTION` remains the one deliberate, permanent
  deferral (needs a different resolution shape entirely).
- **Single call site achieved**: the ~200-line inline gateway-consult
  block was extracted into a shared `_llm_first_gateway_turn` function,
  now called from both the pre-existing awaiting_approval/post_approval
  site AND a new configuring-stage site (right after rule loading),
  gated by new setting `cpq_llm_first_universal_enabled` (default
  **off**). No double-dispatch: the configuring-stage site explicitly
  skips when `session.status` is awaiting_approval/post_approval,
  deferring to the existing site.
- New `GatewayIntentResult.country_text` / `IntentResult.country_
  description` fields, validated via `CpqEngine.is_recognized_country`
  in `validate_gateway_quarantine` — also fixed `parse_gateway_intent`,
  which never read `country_text` off the raw LLM JSON at all (caught
  by the new dispatch branch's own test).
- **Shared response-building**: `_build_product_quantity_change_
  response`/`_build_country_change_response` factored out so the
  deterministic gates (Issues 6/7) and the new dispatch branches use
  identical logic, not duplicated copies.

**Tests**: `tests/test_cpq_llm_first_universal_cutover_2026_08_13.py`
(5 new) covers flag-off inertness, flag-on dispatch during configuring
stage, single-call-site discipline when both call sites exist in one
turn, and both new dispatch branches end-to-end. Plus 2 new tests in
`test_cpq_intent_gateway.py` for the empty-attrs fix and the timeout
wrapper. Full CPQ suite: **1064 passed**, rebuilt and redeployed.
Branch `feature/cpq-llm-first-universal-cutover`.

**Not yet done, deliberately deferred**: `PRODUCT_MENTION` dispatch
branch; the shadow-mode staging rollout itself (flag ships off);
several of the negative test cases from this section's own test plan
above (`test_dispatch_disagreement_falls_through_never_double_mutates`,
`test_product_mention_still_falls_through_undispatched`) — the
single-call-site tests actually shipped cover the same discipline via
call-count assertions, but not every scenario listed above was written
individually.
