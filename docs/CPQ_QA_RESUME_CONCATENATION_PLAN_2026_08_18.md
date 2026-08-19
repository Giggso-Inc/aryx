# CPQ QA/Resume Double-Message — Fix Plan

**Date:** 2026-08-18
**Status:** Implemented and live-verified (branch `fix/cpq-qa-status-meta-resume`, based on
`dev-rv-msi` post-PR#209-merge)
**Severity:** Medium (confusing, contradictory output; not data-corrupting — the pending
question is still correctly re-asked, just buried under irrelevant text)
**Discovered via:** live customer-facing transcript pasted by the user, unrelated to
PR #208 (quantity-target-misroute) or PR #209 (gateway pending_attr conflation) — a
different function, different mechanism.

## Problem

While a real attribute question is still pending (e.g. Hardware Version, never answered),
asking a generic status/meta-question —

> "what is the next step for configuration"

— produces two contradictory fragments glued into one answer. Reported example:

> "Next, choose your specific product: APX NEXT Single Band / All Band / Multi Band / XE
> All Band ... Resuming your configuration... Hardware Version — choose one: ..."

Live-reproduced independently (different wording, same structure):

> "Based on the provided data, there isn't a single sequential 'next step,' but you have
> three primary configuration options available... [Custom/Recommended/ASTRO Express
> Configuration Manager layout-type text]... \n\n---\n\n*Resuming your configuration...*
> \n\nHardware Version — choose one: ..."

The QA half's exact wording varies run to run (confirmed non-deterministic graph-search
content) — the STRUCTURE (irrelevant answer + resume reminder) is what's confirmed, not one
specific wording.

## Root cause

Confirmed via direct code read + live repro (`tools_called: ['cpq_qa()']` byte-for-byte
matches this mechanism):

1. `_handle_cpq_qa` (`src/aryx/api/ask_api.py`) builds two independent fragments and
   concatenates them unconditionally at **line 1175**: `answer = qa_answer + resume`.
2. `resume` (lines 1161-1171): built whenever `session.pending_variables` is non-empty —
   correctly reflects that Hardware Version was never answered.
3. `qa_answer` (lines 1052-1150): "what is the next step for configuration" names no
   specific catalog attribute, so `detect_attr_query` misses and the message falls through
   to the generic graph-QA path (`_extract_terms` → `gather` → `render_context` →
   `_synthesise`, line 1147) — a free-form LLM answer over whatever the knowledge-graph
   search happens to retrieve for "configuration"/"next step". The LLM synthesizing this has
   zero awareness that Hardware Version is the actual pending item — `session_values`
   (lines 1086-1110) only injects already-*filled* attribute values, never what's still
   *pending*.
4. Called from STEP 7's gate (lines 9912-9918): `session.pending_variables` non-empty,
   `session.turn > 1`, not a mode-request, and `detect_qa_question(..., strict=True)`
   matches — with `resume_review=False`.

**The real gap:** `_handle_cpq_qa` treats every QA-shaped message identically, regardless of
whether it's a genuine knowledge question about the catalog ("what carriers are supported?")
or a session-status meta-question ("what's next?", "where am I?", "what should I do now?").
For the latter, when something is genuinely pending, the answer to "what's next" IS the
pending question — querying the graph for it produces noise, not signal.

## Fix design

**Rejected: try to make the two fragments coherent with each other.** Passing pending-state
into `_synthesise`'s context so the LLM "naturally incorporates" it was considered — but this
adds real judgment complexity (the LLM would need to correctly subordinate a real knowledge
answer to a status reminder, or vice versa, on a case-by-case basis) for a class of question
that doesn't need graph knowledge at all. Rejected as unnecessary complexity for a case with
a simpler, correct answer.

**Chosen approach — deterministic short-circuit for status/meta-questions when something is
genuinely pending:**

1. Add a narrow, deterministic detector for session-status meta-questions — phrasing like
   "what's next", "what is the next step", "where am I", "what should I do now", "what do
   you need from me" — **catalog-agnostic, not testing for domain content**, purely
   detecting the question's own shape (a question ABOUT the conversation/process, not about
   the catalog).
2. When that detector matches **and** `session.pending_variables` is non-empty, skip the
   graph-QA path (`_extract_terms`/`gather`/`_synthesise`) entirely and answer with **only**
   the resume block — the pending question genuinely IS the answer to "what's next" in that
   state. No concatenation, no irrelevant graph noise.
3. When nothing is pending, or the detector doesn't match (a real catalog knowledge
   question), behavior is **completely unchanged** — falls through to the existing
   `_handle_cpq_qa` graph-QA path exactly as today.
4. This is a narrow, additive short-circuit inside `_handle_cpq_qa` (or in the STEP 7 gate
   just before calling it) — no change to the graph-QA machinery itself, no change to
   `_synthesise`, no change to how real catalog questions are answered.

## Why this direction over alternatives

- **Suppress `resume` instead of `qa_answer` when both would fire:** rejected — the resume
  reminder is the CORRECT, useful part; suppressing it would silently drop the fact that a
  question is still pending, a worse outcome than today's confusing-but-complete answer.
- **Only append `resume` if `qa_answer` doesn't already "cover" the topic:** rejected — no
  reliable way to judge whether a free-form LLM answer "covers" a topic without another LLM
  call and more judgment complexity, for a case with a much simpler correct answer.
- **Chosen fix's narrowness is deliberate:** only status/meta-questions are affected; a real
  catalog question asked while something is pending still gets a real graph-QA answer AND
  the resume reminder, exactly as today (that combination isn't the bug — a real knowledge
  answer plus a status reminder is coherent; an irrelevant hallucinated answer plus a status
  reminder is not).

## Risk assessment

- **Blast radius is narrow, not shared like the gateway fix (PR #209).** This only touches
  `_handle_cpq_qa`'s own internal short-circuit, gated on a NEW, narrow detector — real
  catalog QA questions (the overwhelming majority of `_handle_cpq_qa` calls) are completely
  unaffected, unlike PR #209's change to the general-purpose intent gateway.
- **Detector false-positive risk:** a genuine catalog question that happens to use "next"
  phrasing (e.g. "what's the next hardware version after this one") could be misdetected as
  a status meta-question. Mitigate by keeping the detector narrow and phrase-specific (whole
  patterns like "what is the next step", "what's next", not a bare "next" keyword match) and
  testing this exact edge case explicitly.
- **Detector false-negative risk (lower severity):** a status question phrased unusually
  might not match and falls through to today's (buggy but not regressed) behavior — no worse
  than the current state, so this is a "doesn't fully fix" risk, not a "makes it worse" risk.

## Verify before implementing

- Live-reproduce the exact reported scenario and the live-repro'd variant again on the
  current code, confirming the bug still reproduces before the fix (baseline).
- After the fix: replay both; confirm the answer is JUST the resume block, no graph-QA
  preamble.
- Confirm a genuine catalog knowledge question asked while something is pending (e.g. "what
  carriers are supported?" with Hardware Version still pending) is UNCHANGED — real QA
  answer + resume reminder, both present, exactly as today.
- Confirm a status meta-question asked when NOTHING is pending falls through to normal QA
  handling unchanged (no resume block possible if nothing pending — the short-circuit
  condition itself prevents any behavior change here).
- False-positive edge case: test a real catalog question using "next"-adjacent phrasing
  (e.g. "what's the next hardware version model") to confirm the narrow detector doesn't
  misfire on it.
- Full CPQ regression suite re-run; any failure/timeout individually confirmed pre-existing
  via `git worktree` comparison against `dev-rv-msi` base, matching this session's established
  rigor.

## Files expected to change

- `src/aryx/api/ask_api.py` — new narrow status/meta-question detector (name TBD, e.g.
  `_is_session_status_meta_question`), and a short-circuit check inside `_handle_cpq_qa`
  (or immediately before its call at the STEP 7 gate, lines 9912-9918) that returns just the
  `resume` block when both conditions hold.
- New test file or additions to an existing `_handle_cpq_qa`-adjacent test file: the 5
  scenarios from "Verify before implementing" above, as committed regression tests.

## Implementation summary (2026-08-18)

**v1 (regex-based, superseded same day):** a phrase-specific regex list
(`_is_session_status_meta_question`/`_SESSION_STATUS_META_QUESTION_PATTERNS`). Worked and was
live-verified, but the owner asked for a more robust, non-pattern-matched detector — a fixed
phrase list under-generalizes across wording it was never written for, the same "not a regex/
deterministic pattern" reasoning already applied to `PRODUCT_QUANTITY_CHANGE` elsewhere in
this file. Removed entirely in v2, no trace left in the codebase.

**v2 (LLM-based, current):**

- New `IntentCategory.SESSION_STATUS_QUERY` added to the shared enum
  (`src/aryx/cpq/intent_schema.py`) — "a question ABOUT the conversation/process itself, never
  about catalog content."
- Reuses the SAME existing classifier `_llm_classify_intent_universal` already calls inside
  `_handle_cpq_qa` for its (flag-gated) ambiguity check — no new LLM integration, no new model,
  no new call site pattern. Its system prompt was extended with explicit guidance on this new
  category, including an explicit anti-false-positive instruction: "what's the next hardware
  version model" must classify as `ATTR_QUERY`/`QA_QUESTION` about the catalog, never
  `SESSION_STATUS_QUERY`, since it names a real catalog thing, not the conversation itself.
- **Not routed through the shared intent gateway** (PR #209's `classify_intent`/
  `_llm_classify_once` in `intent_gateway.py`), despite that being the more consistent-seeming
  "existing LLM" at first glance — investigated and rejected: `_llm_first_gateway_turn`
  deliberately DEFERS the gateway entirely when something is pending and the message isn't a
  topic switch (`_defer_gateway_to_pending_answer`, `ask_api.py` ~5811-5834), which is exactly
  this bug's own trigger condition. The live-reported transcript never touched the gateway at
  all — it reached `_handle_cpq_qa` through STEP 7's own separate deterministic
  `detect_qa_question(strict=True)` gate. Routing detection through the gateway would have
  required also reworking that deliberate pending-answer-priority skip logic — a much larger,
  riskier change unrelated to this bug.
- Call is gated on `not resume_review and session.pending_variables` — only pays the extra LLM
  round-trip when a short-circuit could even apply; `resume_review=True` and the
  nothing-pending case never trigger a classify call at all (zero added cost on those paths).
- Confidence gate mirrors the existing AMBIGUOUS branch a few lines below in the same
  function: `confidence != LOW` required to trust the category; a LOW-confidence result, or
  the classifier returning `None` (LLM error/unparseable — same fail-closed discipline every
  `_llm_*` helper in this file follows), falls through to normal QA handling unchanged.
- New test file `tests/test_cpq_qa_status_meta_resume.py` (9 tests, all passing): exact
  reported scenario short-circuits correctly (mocked classifier); falls through when nothing
  pending (classify call never made); real catalog question while pending unaffected; the
  "next hardware version" false-positive case; LOW-confidence result does not short-circuit;
  classifier failure (`None`) falls through safely; prompt-content test proving the new
  category and its anti-false-positive guidance actually reach the model; stale
  `pending_variables` fallthrough; `resume_review=True` never even calls the classifier.
- **Regression**: `tests/test_cpq_qa_status_meta_resume.py`, `test_cpq_intent_schema.py`,
  `test_cpq_2026_07_28_fixes.py`, `test_cpq_negative_harden.py`,
  `test_cpq_label_collision_memory.py` — 128/128 passing, zero regressions.
- **Live-verified** against a redeployed `api` container running the LLM-based version,
  replaying the exact reported transcript end-to-end: "what is the next step for
  configuration" (Hardware Version still pending) answers with ONLY the resume block,
  `tools_called: ["cpq_qa_status()"]`. Also live-verified: normal config flow unaffected; a
  real catalog QA question while pending still gets both a real answer and the resume
  reminder; PR #209's quantity-change reminder still works; a status question with nothing
  pending falls through unchanged; and — against the REAL model, not a mock — "what's the
  next hardware version model after this one" correctly classifies as a catalog question
  (`tools_called: ["cpq_qa()"]`), confirming the anti-false-positive prompt guidance holds up
  live, not just under a mocked unit test.
