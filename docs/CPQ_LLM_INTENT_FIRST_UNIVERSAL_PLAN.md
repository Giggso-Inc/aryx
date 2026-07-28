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
