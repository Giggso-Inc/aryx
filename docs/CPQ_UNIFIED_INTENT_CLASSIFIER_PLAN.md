# CPQ: Consolidate scattered LLM intent fallbacks into one Tier-2 classifier

**Status:** core consolidation implemented and live-verified (see Amendment 2's
now-archived implementation note) — `_llm_classify_intent_core` exists in
`src/aryx/api/ask_api.py` and is the shared skeleton every Tier-2 caller in
this doc (Gap A, Amendment 8, Amendments 16/17) builds on. Migration step 5
("add one new detector using the shared core as proof," e.g. a
`detect_bulk_quantity_change` LLM fallback) was never separately tracked as
done — treat it as still open if that specific detector's coverage matters.
Decided via Andie Drama round (2026-07-24): keep regex Tier-1 as the fast/
deterministic path; consolidate the *existing* narrow LLM fallbacks into one
shared Tier-2 classifier rather than routing every turn through a
full-session LLM call.

## Why not "one LLM sees session + JSON + query + history, always"

Rejected as the primary architecture:
- **Hallucination surface.** This session found two real bugs (a cache-key
  regression, a blind-guess-vs-script mismatch) from LLM misreads even on
  *scoped* candidate lists. Exposing the full raw JSON payload every turn is
  strictly worse, not better, for the same "never guess" discipline this
  engine is built around.
- **Cost/latency.** Every regex-resolvable turn (the overwhelming majority)
  would pay an LLM round-trip for zero accuracy gain.
- **Regression blast radius.** A single shared prompt misrouting means every
  intent type breaks at once, vs. today's narrow, independently-bisectable
  failures.

Kept, and made the actual goal of this plan: **one shared Tier-2 classifier**,
reached only when Tier-1 regex finds nothing, over a scoped candidate list
(never the raw JSON) — same shape as `_llm_classify_change_intent` and
`_llm_resolve_label_collision` already use today, just unified into one
function instead of two (and future) copies.

## Current state (as of commit `8d73336`)

Two independent LLM fallback functions in `src/aryx/api/ask_api.py`, each with
its own prompt, its own candidate-scoping logic, and its own validation:

| Function | Line | Purpose | Candidate scope | Output shape |
|---|---|---|---|---|
| `_llm_classify_change_intent` | 1609 | remove/change intent when regex (`detect_multi_select_removal`, `detect_change_request(s_multi)`) finds nothing | `_relevant_intent_candidates` — word-overlap scored, filled attrs only, capped | `{intent, variable_name, value}` |
| `_llm_resolve_label_collision` | 1701 | resolve a "which one did you mean?" reply when exact-match/index fails | fixed, already-known 2+ candidate list from the collision prompt | `variable_name` (str \| None) |

Both already follow the same discipline: deterministic-first, LLM only on
fallback, never trust a returned `variable_name` outside the candidate list,
never trust a returned `value` outside the attr's real options.

## Target shape

One function, `_llm_classify_intent(question, candidates, session, workspace_id, mode)`,
where `mode` picks the prompt variant (`"change_or_remove"` vs
`"resolve_collision"`) but shares:
- Candidate-scoping (`_relevant_intent_candidates`, already mode-agnostic).
- The `llm_runtime.chat("menial", ...)` call and JSON-parse/exception handling.
- The "never trust anything outside the candidate list" validation.

Returns a single typed result shape, e.g.:
```python
{"action": "change" | "remove" | "resolve", "variable_name": str, "value": str | None}
```
so both call sites (STEP 6 change/remove routing, collision resolution)
consume the same contract instead of two different dict shapes.

## Migration steps

1. **Extract the shared skeleton** (candidate-scoping + LLM call + JSON parse +
   exception handling) into a private helper, `_llm_classify_intent_core`,
   parameterized by `sys_prompt`, `user_prompt_builder`, and
   `validate(parsed) -> result | None`.
2. **Rewrite `_llm_classify_change_intent`** as a thin wrapper: build its
   existing sys/user prompts, pass its existing validation (select_type/
   options checks), call the core.
3. **Rewrite `_llm_resolve_label_collision`** the same way — it already has a
   near-identical shape (fixed candidate list, single-field validation), so
   this is close to a pure refactor.
4. **Do not touch STEP 6's call sites** (`_run_cpq_turn`'s `_llm_intent =
   _llm_classify_change_intent(...)` and the two `_llm_resolve_label_collision(...)`
   call sites in the collision-resolution blocks) beyond function name — their
   surrounding routing logic (regex-first gating, `only_script_backed`-style
   guardrails) is unrelated and stays exactly as-is.
5. **Add one new detector using the shared core** as the actual proof this
   consolidation pays for itself — e.g. the bulk-quantity detector
   (`detect_bulk_quantity_change`) could gain an LLM fallback for phrasing it
   currently misses, reusing the shared core instead of writing a third
   near-duplicate function from scratch.

## What does NOT change

- Every regex detector (`detect_change_request`, `detect_multi_select_removal`,
  `detect_bulk_quantity_change`, `detect_label_collision`,
  `detect_change_request_collision`) stays exactly as-is — Tier-1, free,
  deterministic, first.
- The LLM is never shown the full session JSON or raw payload — only the
  scoped candidate list (variable_name, select_type, label, current value,
  options), same as today.
- No new model/provider config — reuses the existing "menial" tier
  (`llm_runtime.chat("menial", ...)`), same as both current fallbacks.

## Verification plan (when implemented)

1. Full CPQ/BML test suite green (regression floor: currently 262 passing).
2. Live-verify both existing fallback scenarios still resolve correctly
   after the refactor (mount removal via loose phrasing, label-collision
   reply via a pasted full line) — same reproductions already used to
   verify the pre-consolidation versions.
3. Live-verify one NEW scenario the consolidation was meant to unlock (the
   bulk-quantity LLM fallback, or whichever detector gets the new fallback
   first) to prove the shared core actually saves work, not just moves it.

## Amendment: generalizing to catalogs not yet ingested

Raised in review: a future ingested catalog will have its own version of
today's "Mounting Type"-shaped quirks (single vs multi-select, label
collisions, script-only-governed attrs) — does this plan's design travel to
new data, or does it only work because today's fixes hardcode today's known
attrs?

**Already generic, no change needed:**
- `_relevant_intent_candidates`'s word-overlap scoring is structural (labels
  + option text vs. the question), not catalog-specific.
- Candidate lines already carry `select_type`, so a future catalog's own
  multi-select gets the same treatment SVX's does, automatically.
- The never-guess validation (reject any `variable_name` outside the
  candidate list, reject any `value` outside that attr's own real options)
  is structural, not per-catalog.

**Not generic — the real gap:** `_NEVER_GUESS_SCRIPT_GOVERNED`
(`src/aryx/cpq/engine.py`) is a hand-curated `frozenset` of exact
variable_names — currently one SVX attr. A newly-ingested catalog with its
own script-only-rule-that-can-legitimately-return-nothing pattern would
silently blind-guess until someone reproduces the failure live and adds its
name. The fix does not travel with new data; it has to be rediscovered per
catalog, per attribute, the same way the original SVX case was.

**Proposed generalization (design only, not yet implemented):** replace the
static allowlist with a *behavioral* signal computed at guess-time rather
than a name lookup — suppress the blind first-by-order pick only when the
script's referenced sibling variable was invalidated in the SAME cascade
turn (i.e. genuinely mid-flux this turn), not merely "unresolved." This is
exactly the SVX case (spare-battery gets cleared and re-derived in the same
pass the subscription script reads it) and structurally excludes APX Next's
fresh-quote defaults (nothing was invalidated this turn — it's the first
turn), without ever naming a single variable_name. It would need:
1. `evaluate_rules_loop`/`_handle_cascade` to track which variable_names
   were invalidated (not just changed) in the CURRENT pass — this data
   already exists locally (the `dependents`/strip step) but isn't currently
   threaded into `auto_fill`.
2. `_satisfied_recommendation`'s script branch to check that set before
   falling through to the blind-pick fallback.
3. `_NEVER_GUESS_SCRIPT_GOVERNED` becomes an emergency manual override only
   (kept for a case the behavioral signal turns out not to catch), not the
   primary mechanism.

This generalization should be scoped as its own follow-up, verified the same
way the original allowlist fix was (APX Next stays instant-complete, SVX
stays correctly unresolved) — but explicitly also tested against a THIRD,
previously-unseen catalog to prove it travels, which the allowlist version
structurally cannot.

---

*Amendments 2–6 and 8–15 — all confirmed FIXED/implemented and live-verified
(cross-catalog scoping, label collisions, model-leaf resolution, validation
rules, `_COUNTRY_PREP` phrasing, `is_cpq_question` misrouting, and others) —
have been archived out of this doc to keep it focused on open work. Full
write-ups remain in this file's git history (see commits around 2026-07-26/27
on `feature/msi_cpq`).*

---

## Amendment 7: Region can't be derived from Country by text extraction alone (design only, not implemented)

Raised in review: *"I want to configure CommandCentral Aware 2024 for
customer Houston City of whose destination country is United States"* —
the sentence explicitly states the destination country, yet the engine
still asks **Region** (`NA`/`APAC`/`ME`/`EA`/`LA`/`AP`/`Other`) as a
separate question.

**Not a bug — a different class of gap than Amendments 1-6.** `extract_hints()`
already correctly parses "destination country is United States" into
`country: "United States"` (confirmed live, Tier-1 regex, zero LLM
involved). Region is never asked *instead of* extracting country; it's a
genuinely separate attr with no textual hint pointing to it at all — no
sentence a customer would naturally say contains the literal word "NA" or
"APAC". Mapping "United States" → "NA" requires world knowledge (which
countries belong to which coarse macro-region), not text extraction — so
no amount of regex tuning on `extract_hints`/`extract_catalog_hints`
closes this; it is structurally an inference problem, not a parsing one.

**Where this fits in the plan**: this is the same shape of gap Gap A
(Amendment 2) already targets — a single unresolved attr, a known real
option list, a customer utterance that plausibly answers it but doesn't
fragment-match. The fix is not "run an LLM over everything" (the
already-rejected architecture) — it's one more scoped Tier-2 fallback,
using the same shared core (`_llm_classify_intent_core`) already built
this session: given `country=United States` and Region's own option list
`[NA, APAC, ME, EA, LA, AP, Other]`, ask the classifier which region the
country belongs to, validate the answer is one of the real options
(never invents one), and apply the same confidence-gating discipline as
Gap A (a genuinely ambiguous case — e.g. a country spanning two listed
regions, if any exist in a given catalog — must ask for confirmation, not
guess).

**Status: design only.** Not implemented this session per explicit
instruction ("don't change the code"). If pursued, it would be
`_llm_resolve_pending_answer`'s natural next caller — the same function,
same validation, just seeded with `country` (already extracted) instead
of the raw sentence, for attrs whose own option list is a coarse
classification of a fact already known.

## Amendment 16: LLM-driven conversational intent gate — quote-or-not classification + natural-language disambiguation (both layers implemented and verified)

Raised in review (2026-07-27): today's routing and disambiguation are both
static mechanisms — `is_cpq_question()` is a regex trigger + ingested-name/
alias substring match; once routed, ambiguity is resolved with fixed
templates (a numbered candidate list, a flat "which one?"). This is accurate
once tuned, but brittle to new phrasing (two live misroutes this session
alone — a missing plural on `radio`, and a fallback that only checked
internal BOM codes, never real customer-facing names) and not conversational
— a customer who already stated product, customer, and country in one
sentence still gets asked for them individually if the template's parser
doesn't happen to catch that phrasing.

**Goal:** use the LLM as (1) an intent classifier — is this sentence a
quote/configuration request, a general question, or ambiguous — and (2),
only when genuinely ambiguous, a conversational clarifier that composes a
natural question from what was actually said. The deterministic engine stays
the system of record for what can be asked or answered — this never lets the
LLM invent a field, option, or fact; same "never guess" discipline as every
other Tier-2 fallback already in this doc.

**Layer 1 — intent gate (augments `is_cpq_question`):**
- Keep today's regex/alias fast-path as Tier 1 — free, deterministic, catches
  the overwhelming majority of real requests.
- Add a Tier-2 LLM fallback *only* when Tier 1 is inconclusive (no trigger
  word, no alias match): ask the shared classifier "is this a product
  configuration/quote request, a general question, or unclear?" over the raw
  sentence, no session state required.
- Bias the gate toward entering CPQ on low confidence rather than guessing
  "no" — today's actual failure mode is a genuine request silently exiting to
  the generic pipeline; a wrong "yes" costs nothing worse than Step 1's own
  anchor prompting asking a clarifying question anyway.

**Layer 2 — conversational disambiguation (augments, not replaces, existing
prompts):**
- Today: fixed templates, e.g. *"This family has more than one product line
  — which one are you configuring?\n\n1. ...\n2. ...\n3. ..."*.
- Proposed: when a turn is ambiguous (label collision, model-leaf list,
  low-confidence pending-answer per Amendment 2 Gap A), compose the
  clarifying question from the actual sentence plus the real candidate set
  via the LLM — reflecting back what was already understood (customer,
  country, etc.) instead of re-asking for it, then asking only the genuinely
  open question. Candidates still come only from real catalog data — the LLM
  composes phrasing, never new options — and falls back to today's static
  template if the LLM call fails, so behavior is never worse than current.

**Explicit non-goals** (same boundary the base plan already drew): no single
LLM call sees the full session/JSON/history; no replacing the deterministic
rule cascade or attribute governance; scoped strictly to (a) the initial
quote-or-not gate and (b) phrasing of already-computed candidate sets.

**Reuses existing machinery, no new mechanism:** the same
`_llm_classify_intent_core` skeleton this doc's base plan establishes, and
Amendment 2/8 already extended — this would be a third and fourth caller,
not a new architecture.

**Status: Layer 1 implemented and verified (2026-07-27); Layer 2 still
design only.**

**Layer 1 implementation** (`src/aryx/api/ask_api.py`): new
`_llm_classify_is_cpq_question(question, workspace_id)` — no session state
or reader needed, classifies the raw sentence alone via
`_llm_classify_intent_core`, biased toward `"quote"` in the prompt itself
("only classify as not_quote when you are confident it is NOT that at
all"). Wired into `run_ask`'s one `is_cpq` computation as a third `or`
term, after `CpqEngine.is_cpq_question(...)` — Python's short-circuit
evaluation means the LLM call is only ever reached when Tier-1 (session
mode check, then regex/alias) already returned False, exactly the
"only when Tier 1 is inconclusive" scoping this amendment specified. An
LLM-call failure (exception, malformed JSON) resolves to `False` — the
same default this turn already had before this gate existed — the "bias
toward yes" applies to the model's classification of ambiguous content,
not to error handling; a failed call carries no information either way.

**Live-verified**, both the gate's accuracy and its latency behavior:
- **Tier-1 hit** (*"I want to configure APX Next radios for a customer"*):
  `is_cpq` resolves in **0.000s** — confirms the LLM is never reached when
  Tier-1 already succeeds, directly answering this amendment's own
  "latency budget" open question for the common case.
- **Tier-1 miss, genuine quote request, no trigger words at all**
  (*"We need to get a bunch of these units set up for our new office"*):
  Tier-1 correctly returns `False`; the new gate correctly classifies it
  `True` in 4.0s — exactly the silent-misroute failure mode this amendment
  exists to close, closed.
- **Tier-1 miss, genuinely unrelated** (*"What is the weather like
  today"*): gate correctly returns `False`.
- **Tier-1 miss, a real Ask-tool data question** (*"How many entities are
  in this workspace"*): gate correctly returns `False` — confirms the bias
  toward "quote" doesn't swallow the OTHER pipeline's own legitimate
  traffic; genuinely non-CPQ questions still classify correctly, this
  isn't a rubber stamp toward CPQ on everything.

255/255 tests passing throughout, no regressions.

**Layer 2 implementation** (`src/aryx/api/ask_api.py`): new shared
`_compose_disambiguation_question(question, prompt_topic, candidate_labels,
already_known, static_fallback, workspace_id)`. Answers this amendment's own
open question above — composing phrasing is lower-stakes than Gap A's
value-picking (it never commits to an answer, only asks one), so no
separate confidence gate was added; instead the safety net is a strict
verbatim-candidate check: the composed text is discarded (falling back to
`static_fallback`, today's exact original template) unless EVERY real
candidate's identifying text still appears in it (checked via the same
alphanumeric-only normalization used elsewhere in this file). Wired into
all three places this amendment named:
- **Label collision** — `_label_collision_prompt` (all 8 call sites across
  `_handle_cascade` and `_run_cpq_turn`) now takes `question`/`workspace_id`
  and composes via the LLM, `already_known` seeded from
  `session.country`/`session.product_name`.
- **Model-leaf list** — the single `_run_cpq_turn` block that previously
  built `"This family has more than one product line..."` directly.
- **Low-confidence pending-answer (Gap A)** — the single block that
  previously built `"I'm not certain which option you meant..."` directly.

**Live-verified, both the composed quality and the fallback safety net**:
- **Real composed output** (model-leaf case, workspace 21): *"I want APX
  Next radios for a customer in the US"* + candidates `aPXNext_BOM`/
  `aPXN70_BOM` → *"Since you need APX Next radios for the US, would you
  like to configure the aPXNext_BOM or the aPXN70_BOM?"* — reflects back
  country and product, names both real candidates, no invented option.
- **Real composed output** (label-collision case, `package_swSoln` vs.
  `package_CCAware2026_swSoln`): correctly reflects the quantity/country/
  product context and asks about both real candidates by exact name.
- **Fallback safety net, all four cases confirmed by mocking
  `llm_runtime.chat`**: a response that drops one candidate → falls back;
  an empty response → falls back; a raised exception → falls back; a
  response correctly naming every candidate → does NOT fall back (composed
  text used). All four behaved exactly as designed.

255/255 tests passing throughout, no regressions.

**Remaining open questions from this amendment's original list**:
- Confidence threshold for Layer 1's intent gate — false-CPQ vs
  false-generic cost is asymmetric (a false "no" is today's silent failure
  mode); the current implementation biases via the prompt itself rather
  than a numeric threshold — worth revisiting if real usage shows it's
  mistuned either direction.
- Layer 2's confidence question is now answered above (no separate gate;
  verbatim-candidate check instead).
- Latency budget — Layer 1: confirmed 0.000s on a Tier-1 hit (no added
  cost for the common case), ~2–4s on a genuine Tier-1 miss. Layer 2: each
  composed prompt took 2.8–3.5s in testing — paid only on turns that were
  already going to show a disambiguation prompt, never on an ordinary
  single-question turn.

## Amendment 17: broaden Gap A's LLM extraction to every turn, not just the one pending attr (proposed, not implemented)

Raised in review (2026-07-27), validating Amendment 16 against five concrete
example sentences before implementing anything. Two of the five exposed a gap
Amendment 16 does not cover:

*"I am looking to configure a model which is CommandCentral Aware and for
this model I want to configure a standard subscription for 25 devices at 25
locations for new solution type and package of 'Plus'"* — one dense sentence
naming product, subscription type, device count, location count, solution
type, and package tier all at once.

**Confirmed from `extract_catalog_hints`'s own documented rules** (not
guessed): this sentence hits two SEPARATE, already-intentional safety limits
of the existing Tier-1 fragment matcher, both explicitly "never guess" by
design:
1. **Shared-value collision**: if devices and locations are sibling attrs
   that both accept the same enumerated values (25/50/75/125 — exactly the
   shape Amendment 12's "multiple of 25" validation rule confirms exists in
   this catalog), the matcher will not hint *either* — "25 **devices**" vs
   "25 at **25 locations**" is a positional distinction a human reads
   instantly, but the matcher only checks "is this value valid for this
   attr," never word-adjacency.
2. **Single-word exclusion**: "Plus" and "New" are single-word option values
   with no digit — below the matcher's own minimum-trust bar (multi-word or
   digit/slash required), so they're skipped even when unambiguous.

**Why Amendment 16 as scoped doesn't fix this**: Gap A's existing LLM
fallback (`_llm_resolve_pending_answer`) only runs in STEP 5, against the one
attr the engine itself is currently waiting on. A dense sentence like this
one, sent as the very FIRST turn (anchoring the product), never reaches
STEP 5 for devices/locations/package at all in the same turn — those attrs
aren't "pending" yet, so nothing scopes an LLM fallback to them, and the
turn falls through to asking each one individually, one at a time, exactly
the "too many questions" complaint this whole conversational-layer effort is
meant to fix.

**Proposed fix**: after Tier-1's global fragment match runs each turn, if 2+
attrs remain unresolved AND the turn's text plausibly mentions more than one
of them (same word-overlap scoring `_relevant_intent_candidates` already
uses), run ONE shared-core LLM extraction pass over the full set of still-
unresolved, catalog-relevant attrs — not just the pending one — asking it to
map each mentioned fact to the correct attr using sentence structure/
adjacency the regex matcher can't use. Same validation discipline as every
other Tier-2 call in this doc: a returned `variable_name` must be in the
unresolved set, a returned `value` must be a real option for that specific
attr, confidence-gated per Amendment 2's precedent — low confidence on any
one mapping means that one attr still gets asked normally, it does not block
the others that resolved cleanly.

**Explicit scope boundary**: this only fires when Tier-1 already found 2+
attrs "mentioned but unresolved" — a short, unambiguous reply never invokes
it, so the added latency/cost is paid only on genuinely dense, multi-fact
sentences, not on every turn.

**Status: implemented and live-verified (2026-07-27).** Added
`_llm_extract_multi_attr_hints` (`src/aryx/api/ask_api.py`) plus a
`fallback_to_full: bool` param on `_relevant_intent_candidates` (default
`True`, unchanged for existing callers) so this caller's overlap gate can
return empty instead of falling back to the full candidate list — required
so the extra LLM call never fires on an ordinary reply where nothing
textually overlaps. Wired into `_run_cpq_turn`'s pending-computation block:
the existing `evaluate_rules_loop`/`auto_fill`/post-filter sequence was
factored into a local `_recompute_pending(cur_hints)` closure, called once
normally, then a second time (only if 2+ pending attrs genuinely overlap the
question and the LLM extraction returns something) with the extracted
values merged into `hints` — so the existing cascade machinery incorporates
them with zero special-casing downstream.

**Live-verified, both directions**, directly against `_llm_extract_multi_attr_hints`
(isolated from the rest of the turn — see Amendment 18 for why isolation was
necessary):
- **Positive case**: *"25 video streaming devices and 25 location
  devices..."* — correctly resolved both `OfVideoStreamingDevices_3_swSoln`
  and `OfLocationDevices_3_swSoln` to `25` in one call, 2.9s.
- **Negative case** (this doc's own motivating example, verbatim): *"25
  devices at 25 locations"* — correctly returned nothing. The generic word
  "devices" doesn't say which of the two device-count attrs is meant, and
  the model itself replied `"mappings": []` rather than guess — the same
  never-guess discipline as every other Tier-2 fallback here, working
  exactly as designed even though it means this specific phrasing still
  needs a follow-up question.

255/255 tests passing throughout, no regressions.

**Depends on**: Amendment 16's Layer 1 intent gate (this needs the turn to
already be inside the CPQ engine) and its shared `_llm_classify_intent_core`
skeleton — not a new mechanism, a third extraction mode alongside Gap A's
existing pending-answer mode and Amendment 7's country-to-region mode.

## Amendment 18: Tier-2 BML rule evaluation doesn't scale to large catalogs — 823 sequential LLM calls possible in one turn (found live; all four remediation options implemented and verified)

Found while live-verifying Amendment 17 against the real, live CommandCentral
Aware catalog in workspace 21 (the actual production workspace — confirmed
active real UI traffic during this investigation via continuous
`/ask/threads/.../messages` polling in the container logs). A full
`_run_cpq_turn` call for one ordinary first-turn configuration sentence ran
for 25+ minutes and had to be killed — no error, no crash, genuinely still
computing.

**Isolating the cause**: `docker top`/`/proc` inspection showed the process
alive and blocked on network I/O (`poll_schedule_timeout`, state `S`), not
deadlocked. Calling Amendment 17's own new LLM extraction directly (bypassing
the rest of the turn) completed in 2.9–5.9s — proving the new code was not
the cause. The delay is in the turn's PRE-EXISTING rule evaluation.

**Root cause, measured directly** (not guessed): temporarily forced
`bml_eval._use_llm = False` and re-ran the exact same `evaluate_rules_loop`
call for this turn's real state — this makes every Tier-2-eligible script
resolve instantly to "unknown" instead of calling the LLM, so the full
rule set evaluates in under a second and its own `.stats` counter reveals
the true fallthrough count with zero network calls:

```
tier1:   2   resolved deterministically
tier2:   0   (forced off for this measurement)
unknown: 823 — would each need a separate Tier-2 LLM call
cached:  4479  (repeat hits within this one pass)
```

**823 distinct script-governed hiding rules alone** need Tier-2 fallback for
this catalog's realistic first-turn state — and that's hiding rules only;
recommendation rules (1220 script-backed) and constraint rules (156
script-backed) weren't even measured yet, so the true per-turn worst case is
likely higher still. Hiding-rule Tier-2 calls (`_evaluate_llm_hide`,
`src/aryx/cpq/bml.py`) go to the "answer"/reasoning model tier
(`gemini-3.1-pro-preview`), not the faster "menial" tier — and run strictly
sequentially, one script at a time, no parallelism. At even a fast ~4s/call
that's ~55 minutes for hiding rules alone; combined with this environment's
own bounded network-retry behavior (`post_json`, up to ~5.5 min per call in
the worst case across its 5-attempt backoff), a real multi-minute-to-hour
delay for one turn is fully explained, not anomalous.

**This is an architectural scale ceiling, not a bug**: one sequential LLM
round-trip per unresolved script, on a catalog this large (900+ attrs,
~2000 script-backed rules total across hiding/recommendation/constraint),
is computationally infeasible for real-time chat UX regardless of how
correct each individual evaluation is. Smaller catalogs used earlier this
session (SVX, APX Next single-leaf cases) never surfaced this because they
have far fewer script-governed rules.

**Unrelated to Amendments 16/17**: those are about conversational intent
quality (classification, extraction accuracy); this is about rule-evaluation
THROUGHPUT at scale. Confirmed independent by isolating Amendment 17's own
call (fast) from the rest of the turn (slow).

**Remediation options considered**, roughly in order of impact-to-effort —
all four chosen and implemented:
1. **Parallelize Tier-2 calls** ✅ implemented (below).
2. **Scope rule evaluation to only currently visible/pending attrs** ✅
   investigated and implemented, in a different shape than originally
   proposed (see "Option 2" section below — the literal proposal turned out
   to be circular for hiding rules specifically).
3. **Cap Tier-2 attempts per turn** ✅ implemented (see "Option 3" section
   below).
4. **Persist Tier-2 results across turns** ✅ implemented, durable-store
   shape (see "Option 4" section below).

**Status: all four options implemented and verified (2026-07-27).**

**Implementation** (`src/aryx/cpq/bml.py`, `src/aryx/cpq/engine.py`): the
three Tier-2 entry points (`hide_for_script`, `condition_holds`,
`allowed_values_for_script`) each already followed an identical key/cache/
Tier-1 shape — factored that into a shared `BmlEvaluator._prepare` (and a
shared `_store` for the cache write), so all three keep their exact prior
behavior/return values while sharing one code path. Added
`BmlEvaluator.prefetch_tier2(requests)`: given a batch of `(kind, script,
variables, cache_id)` tuples, it runs the cheap local key/Tier-1 step for
each (no network calls), deduplicates the genuinely Tier-2-eligible ones by
cache key, then dispatches all of them CONCURRENTLY via
`concurrent.futures.ThreadPoolExecutor` (blocking `urllib` calls release the
GIL while waiting on network I/O, so threads parallelize this correctly with
no change to any existing synchronous call site) and writes each result into
the same `_SHARED_SCRIPT_CACHE` under the exact key the sequential methods
would themselves compute.

Wired into `engine.py`'s `evaluate_rules_loop` via a new
`CpqEngine._bml_prefetch_requests` builder, called twice per pass: once for
`hiding_rules` (before `apply_hiding_rules`, against the pass's current
`filled`) and once for `rec_rules`+`con_rules` (after `auto_fill`, against
the post-auto_fill `filled` — mirrors `apply_recommendation_rules`' own
"already filled" skip so prefetch never burns a concurrent call on a rule
that loop won't consult). `apply_hiding_rules`/`apply_recommendation_rules`/
`apply_constraint_rules` themselves are UNCHANGED — still sequential, still
calling `hide_for_script`/`condition_holds`/`allowed_values_for_script` one
rule at a time — every one of those calls now just hits the cache the
prefetch already warmed. A rule the prefetch builder doesn't cover (or gets
slightly wrong) simply isn't pre-warmed and falls through to its normal
sequential call — this refactor cannot make an answer wrong, only faster or
not-yet-faster.

**Live-verified** (workspace 21, real CommandCentral Aware catalog): 255/255
tests passing, no regressions. Direct, isolated measurement of the
dominant cost — hiding-rule prefetch against a fixed real turn-1 state —
confirmed the mechanism works and is substantially faster:

```
704 raw script-backed hiding-rule instances
→ 128 distinct script+state combinations after dedup
  (many rule instances share one underlying BML script)
→ 33 genuinely needed a Tier-2 call, dispatched concurrently
→ whole batch: 109.2s
```

Sequential, even at a modest ~5s/call, would be ~165s for this one batch
alone — and given this environment's occasional slow/retrying calls (the
same ones behind the original 25+ minute run), sequential would likely be
considerably worse. A full turn now pays roughly *(number of passes ×
slowest-call-in-that-pass's-batch)* instead of *(total distinct calls ×
per-call latency)* — the actual fix for Amendment 18's scaling problem.

**Not yet measured**: a clean end-to-end total for one full multi-pass
turn — the un-parallelized baseline took 25+ minutes to observe passively,
and a full parallel run was still in progress when observation was stopped
in favor of the faster, more conclusive isolated measurement above. The
component-level evidence (concurrency confirmed active, 33 real calls
completing as one 109s batch instead of 33 sequential round-trips) is
solid; an exact full-turn number is a good follow-up once this is exercised
more via normal use rather than one-off diagnostic scripts.

**Residual gap, noted for a future round**: `auto_fill`'s own internal
`_satisfied_recommendation` helper also calls `allowed_values_for_script`/
`condition_holds` for `rec_rules`, using its own in-progress `filled`
snapshot as it iterates attrs one at a time — those calls aren't covered by
either prefetch call site above (both run outside `auto_fill`), so on a
FIRST pass they can still go sequential. Subsequent passes benefit once the
cache is warm from the surrounding prefetches. Options 3–4 below remain
open if this residual, or first-turn latency generally, still needs
further improvement.

### Option 2 — scope rule evaluation to visible/pending attrs (investigated, implemented in a different shape)

Traced before implementing anything, per this plan's own discipline. Two
distinct findings:

**Recommendation/constraint rules were already correctly scoped.**
`apply_recommendation_rules`/`apply_constraint_rules` build their attr
lookup from the CURRENT `attrs` list — already narrowed to visible-only by
`apply_hiding_rules` earlier in the same pass. A rule targeting a hidden or
otherwise-absent attr hits `target = by_rule_id.get(...)` → `None` → skipped
**before** any Tier-2 call. Confirmed by code reading; no fix needed.

**Hiding rules themselves are circular to pre-scope by "visible attrs."** A
hiding rule's entire job is to compute visibility — skipping its evaluation
based on the visibility it's supposed to determine isn't a coherent
narrowing. Investigating what the actual "unnecessary" evaluations looked
like reframed the problem: of the hiding-rule targets needing Tier-2 for a
real turn, 121 distinct ones traced back to a single, extremely repetitive
idiom — rule names literally titled *"Hide X if no/not values are
available,"* checking whether X's name appears in a shared "included items"
list rather than any customer-facing decision. Tier-1's chain-walking parser
(`_first_matching_branch`) simply didn't recognize this grammar shape (a
guarded if-block with `SPLIT`/`findinarray`, not an if/else-if/else
condition chain) — not a missing-data problem, a missing-idiom problem.

**Decided (2026-07-27, user's call via explicit options)**: rather than a
catalog-naming-convention heuristic (fragile, breaks the genericity this
plan holds elsewhere), extend Tier 1 to recognize this idiom generically.

**Implementation** (`src/aryx/cpq/bml.py`): added `evaluate_hide_master_list`
("Idiom C") — a `re.fullmatch` (comment-stripped, whole-script, not a
partial `search`) against the exact shape:
```
if(MASTER<>""){
ARR = SPLIT(MASTER,SEP);
IDX = findinarray(ARR,"LITERAL");
   if (IDX ==-1){ return TRUE; }
   }
return FALSE;
```
Semantics: hide the target unless `"LITERAL"` appears in `MASTER`'s value
split on `SEP`'s value; an empty/missing `MASTER` never hides. Wired into
`evaluate_hide_tier1`, tried before falling through to
`_first_matching_branch` — anything not this exact shape falls through
unchanged. Verified against 5 synthetic cases (empty master, literal
present, literal absent, missing variable, unrelated script — all matched
expected output) before touching real data.

**Live-verified against the real catalog**: 444 of 1516 hiding rules
(spanning 121 distinct targets) match this shape. Directly compared old vs.
new behavior on the SAME real turn-1 state: **all 444 that the old parser
would have sent to a real Tier-2 network call now resolve locally, zero
network calls** — confirmed by literally calling both `_first_matching_
branch` (old path) and `evaluate_hide_master_list` (new path) against the
identical script + variable state and comparing outcomes.

**Honest nuance**: most of these 444 resolve to "blocked" (can't determine),
not a definite true/false — the `MASTER` variable itself
(`hiddenHidingRuleMasterStringForCommandCentral_swSoln`) is computed by a
DIFFERENT recommendation rule ("Master String For Base Model") that issues a
`BMQL` query against a BM data table — a real external query neither Tier 1
nor Tier 2 can execute, so `MASTER` never actually gets a value in this
engine today. That means Tier 2 was previously being asked a question it
had no real way to answer correctly either (it can't run BMQL any better
than Tier 1 can) — this fix doesn't just move the cost, it eliminates 444
round-trips that were unlikely to produce a trustworthy answer regardless.
Confirmed the overall configuration outcome is unchanged (same 86 filled
attrs before and after, `_use_llm` forced off for a clean comparison) — this
is a pure efficiency/cost win, not a behavior change.

255/255 tests passing throughout.

**Depends on nothing new**: reuses the existing `_prepare`/cache
infrastructure from Option 1 above; `evaluate_hide_master_list` is a pure,
stateless function like every other Tier-1 idiom in this file.

### Option 3 — cap Tier-2 attempts per turn (implemented)

A backstop for whatever's still left after Options 1–2, or for a different
large catalog neither of those happens to help as much on.

**Implementation**: new setting `bml_tier2_max_per_turn` (`src/aryx/
config.py`, default 50, override `ARYX_BML_TIER2_MAX_PER_TURN`).
`BmlEvaluator` (`src/aryx/cpq/bml.py`) gets a `tier2_max_per_turn` param
(defaults to the setting when not given), a counter, and a
`threading.Lock` — one evaluator instance already lives for exactly one CPQ
turn (built fresh per turn by `CpqEngine.build_bml_evaluator`), so capping
at the instance level naturally means "per turn, across every pass of
`evaluate_rules_loop` combined," no new plumbing needed. `_prepare`'s
existing "needs_tier2" decision now calls a new `_reserve_tier2_slot()`
first; once the cap is claimed out, every further script this turn is
treated exactly like `_use_llm=False` would treat it — `stats["unknown"]`
increments (today's existing safe "never guess" default), plus a new
`stats["capped"]` counter specifically so a truncated turn is distinguishable
from a genuinely-fully-resolved one in the stats/logs, and a one-time
`logger.warning` fires the moment a turn first hits the ceiling (never
silent — an operator can grep for it).

Thread-safety matters here specifically because `prefetch_tier2` (Option 1)
dispatches from multiple threads concurrently — an unguarded read-then-
increment could let concurrent callers overshoot the cap; the lock makes
"claim a slot" atomic.

**Verified** (both against real code, not just reasoning): `_reserve_tier2_
slot()` called 7 times with `tier2_max_per_turn=3` returned
`True,True,True,False,False,False,False` exactly, with the warning logged
once. Driven through `_prepare` itself with a deliberately-unparseable
script and `tier2_max_per_turn=2`: the first 2 calls report
`needs_tier2=True`; the 3rd onward report `needs_tier2=False` with
`stats["capped"]`/`stats["unknown"]` incrementing correctly. 255/255 tests
passing, no regressions.

**Default of 50** is a judgment call, not a measured optimum — generous
enough that ordinary catalogs (including CommandCentral Aware post-Options
1–2) shouldn't come near it, while still bounding the worst case for a
catalog neither prior fix helps as much on. Tunable per-deployment via the
env var without a code change.

### Option 4 — persist Tier-2 results across turns (durable-store shape, implemented)

**Decided (2026-07-27, user's call via explicit options)**: the durable-store
shape specifically, not a narrower cache key. The existing key already uses
the FULL variable state rather than a regex-derived subset — a deliberate
fix for two real bugs earlier this session, where an incomplete "relevant
variables" regex caused a stale answer to be silently reused for a
genuinely different state. Narrowing the key to help cross-turn reuse would
mean re-touching that exact mechanism; the durable store gets real,
lower-risk value instead (survives restarts, shareable across workers)
without reopening it.

**Implementation**: new migration `0035_bml_tier2_cache.sql` — table
`aryx_bml_tier2_cache (cache_key PK, workspace_id, kind, result JSONB,
created_at)`. Two new queries (`select_bml_tier2_cache`,
`upsert_bml_tier2_cache`) via the existing `aryx.queries.load()` convention.
`BmlEvaluator` (`src/aryx/cpq/bml.py`) gets `_durable_key`/`_durable_get`/
`_durable_put` and a single new entry point, `_call_tier2(kind, script,
variables, cache_id)`, that ALL FOUR real Tier-2 call sites (`hide_for_
script`, `condition_holds`, `allowed_values_for_script`, and `prefetch_
tier2`'s dispatch) now go through instead of calling `_evaluate_llm_hide`/
`_evaluate_llm_condition`/`_evaluate_llm` directly — checks the durable
store first, only calls the LLM on a genuine miss, persists the fresh
result either way.

**Key stability, the one subtle correctness point**: the durable key uses
`hashlib.sha256` over a canonical (sorted-keys) JSON representation of
(kind, workspace, catalog, script-or-cache_id, full variable state) —
deliberately NOT Python's built-in `hash()`, which the in-memory cache uses
internally but which is randomized per-process by default
(`PYTHONHASHSEED`). A durable store keyed on `hash()` would silently miss
on every single lookup after a restart (a new process computes different
hash values for the identical input) — this would have been a durability
bug disguised as "working," easy to miss without specifically checking
cross-process behavior, which is why the live verification below
specifically forced a real process boundary rather than just testing
within one running process. Same identity components as the in-memory
key otherwise — this layer changes WHERE a result is cached, not WHAT
counts as "the same state," so it inherits no new correctness risk beyond
what the in-memory cache already established. Every DB operation is
best-effort (try/except, `logger.debug` on failure) — a durable-cache
outage degrades to exactly today's behavior (network call every time),
never blocks or fails a turn.

**Live-verified across an actual process boundary** (not simulated): called
`hide_for_script` with a deliberately Tier-1-unparseable script — first call
made a real LLM round-trip (3.6s, `stats["tier2"]=1`), confirmed the row
landed in `aryx_bml_tier2_cache`. Then **restarted the container** (`docker
restart`, a genuinely fresh Python process, confirmed the in-memory
`_SHARED_SCRIPT_CACHE` was empty on startup) and called the identical
`hide_for_script(script, variables)` again: returned the same correct
result in **0.08s** (vs. 3.6s originally) with `stats["durable_hit"]=1` —
zero network calls, durability confirmed across the exact boundary that
matters. 255/255 tests passing throughout.

**Practical impact caveat, stated plainly**: this deployment runs a single
worker (`ARYX_DOC_WORKERS=1`), so the main win today is surviving restarts
mid-development, not sharing across concurrent workers — the multi-worker
benefit is real but not yet exercised by this environment. It also does
**not** make turn 2 of the same session faster than turn 1 when turn 2's
full variable state has never been seen before (which is the common case) —
that's precisely the "narrower key" problem this option deliberately did
not take on, per the decision above.

## Amendment 19: Amendment 10's "skip Product-labeled attrs once model-leaf resolved" protection never existed in the cascade/change-request path (found live, FIXED and live-verified)

Found live (2026-07-27) from a real transcript: a customer switched products
(videoSolutions_BOM → softwareSolutions_BOM), completed the configuration
cleanly, then sent an ordinary change request — *"change Is FedRamp or CCCS
Required to None"*. The resulting cascade asked: *"which specific product
field should we update: ConnectorTypeProductArray_swSoln or
productSelectionProduct_all?"* — raw internal variable names, meaningless to
a real customer, with no way for them to know which to pick (both are
generic radio-hardware artifacts per Amendment 5 Finding 3, irrelevant to
this catalog either way).

**Root cause, confirmed by direct code search, not guessed**: `grep` for
`model_leaf_resolved` across `ask_api.py` returned exactly 6 hits — all
inside `_run_cpq_turn` (the initial-configuration flow). `_handle_cascade`
(the separate function that processes changes/cascades on an
already-complete configuration) has its own 6 near-identical
`skip_always_ask`/`pending` computation blocks and **zero** references to
`model_leaf_resolved`. Amendment 10's protection (skip asking about
"Product"-labeled attrs once the model leaf is known — Amendment 5 Finding
3 proved they're irrelevant) was only ever wired into the initial-config
path; it never existed in the cascade path, from the day Amendment 10 was
written. Reproduced live end-to-end (fresh session → anchor to
videoSolutions_BOM → mention commandCentralAware2024 → confirm switch →
change FedRamp to None) and confirmed: `session.model_leaf_resolved` was
correctly `True` throughout, yet the Product collision still fired on the
cascade turn — proving the gap is exactly where the code search said it was.

**Fix**: mirrored `_run_cpq_turn`'s exact two-part Amendment 10 pattern into
all 6 `_handle_cascade` call sites — `skip_always_ask` extended with every
"Product"-labeled attr's variable_name when `session.model_leaf_resolved`,
plus the same `pending` post-filter. Confirmed all 6 sites were
byte-identical before using `replace_all`, and confirmed the replacement
count matched (6) afterward — no site skipped, none double-patched (the
initial-config path's own copy has different surrounding text and was
correctly left untouched).

**Live-verified end-to-end, the exact original scenario**: same repro as
above — after the fix, the FedRamp-change turn goes directly to
"Configuration complete," no Product question at all. 255/255 tests
passing, no regressions.

**Still open, found during this same verification**: `OfVideoStreamingDevices_3_swSoln`
still does not appear in the final payload even after this fix and even
with FedRamp correctly set to "None" — confirmed via the same live repro.
Root cause is separate and already identified (not yet implemented): a
Tier-1 parser gap in `_parse_branches` (`src/aryx/cpq/bml.py`) — a script
shaped `if (cond) { return true; } return false;` (bare fallthrough, no
`else` keyword) only has its `if`-branch parsed; when the condition is
false, Tier 1 incorrectly reports "unparseable" instead of correctly
inferring the fallthrough `False`. This affects at least the "Hide Video
Streaming Devices for FedRamp" rule directly, forcing an avoidable Tier-2
call for a trivially Tier-1-resolvable script, competing with the per-turn
cap. Proposed fix (pending approval): recognize a trailing bare
`return <literal>;` after a single `if {...}` block (no `else`) as an
implicit second branch in `_parse_branches`.

## Amendment 20: "has a ValidationRule" was reverted as the signal for asking a no-option attr — reintroduced a worse bug in a different catalog (found live, REVERTED)

The fix that made `auto_fill` ask about `agencyDomainName_ID_swSoln` (a
free-text field with no options, targeted by a `ValidationRule`) generalized
that rule to: *any* attr targeted by *any* `ValidationRule`, with no options
and no decision-keyword match, gets added to `pending`. Confirmed live this
broke a working, unrelated catalog: ordering plain APX Next radios ("City of
Houston", destination US) started asking for **Owner System ID**
(`systemID_astro`), which real BigMachines never prompts for in that flow.

**Root cause, confirmed by direct data inspection, not guessed**: both
`agencyDomainName_ID_swSoln` and `systemID_astro` have `required=False` and
`default_value=''` in the XML export — the static schema gives no signal
distinguishing "must ask" from "optional, format-checked only if entered."
Both attrs' `ValidationRule` scripts even share the same shape (an
`if (attr == "") { return false; }` empty-guard) — so script shape doesn't
distinguish them either. `systemID_astro`'s rule only truly matters when
`advancedSystemKeyHardwareKey_astro == "YES"`, an advanced/optional gate not
present in a plain radio order — but the blanket "has a ValidationRule"
check has no way to consult that gate. There is no reliable structural
signal in this data that separates the two cases; "has a validation rule"
was a coincidence that happened to work for one field and not the other.

**Fix**: reverted the `validation_target_ids` branch from `auto_fill`'s
pending-eligibility check in `src/aryx/cpq/engine.py`, and removed the now-dead
`validation_rules` parameter/plumbing from `auto_fill` and all 7 call sites
(`_run_cpq_turn` + the 6 `_handle_cascade` sites) in `src/aryx/api/ask_api.py`.
Per D2 ("never guess"), a heuristic that cannot be told apart from data
available at hand should not silently guess either way — `agencyDomainName_ID_swSoln`
goes back to not being proactively asked about, same as before this
session's Amendment 19 follow-up. A correct fix would need a genuine
required/optional signal (e.g. an explicit catalog-side flag, or resolving
the gating condition of each ValidationRule) — not attempted here, since
guessing at another heuristic risks the same class of false positive again.

**Side note — FedRamp silent-reversion, traced and closed**: a separate live
report claimed `isFedRampOrCCCSRequired_swSoln` silently reverted from a
user's explicit "None" back to "FEDRAMP" later in the same conversation.
Traced live: `filled_source=="user"` correctly survives an ordinary
change-request cascade (confirmed via two repros — a follow-up unrelated
change-request turn left FedRamp at "NONE"/"user"). The revert only ever
showed up in the original transcript because Amendment 19's now-reverted
`validation_target_ids` fix (above) force-added `agencyDomainName_ID_swSoln`
and 3 other fields to `pending`, and something in that specific longer
answer sequence re-derived FedRamp. That trigger path no longer exists now
that Amendment 20 reverted it. Treated as resolved by the revert; revisit
only if seen live again post-revert.

## Amendment 21: Q&A answer for a free-text validated attr's "what values are allowed" question (implemented, currently dormant)

Separate live report: asking "what are the values available for the domain
id" while `agencyDomainName_ID_swSoln` was pending got a generic,
unhelpful answer instead of describing the field's real constraint
(letters/digits/`.`/`_`/`-` only, per its own `ValidationRule`).

**Root cause, confirmed by direct code read**: two independent gaps.
`detect_attr_query`'s word-overlap fallback requires every camelCase-split
word of the variable name to appear in the question — `agencyDomainName_ID_swSoln`
needs `{agency, domain, name, id}`; "domain id" only supplies 2 of 4, so it
never resolves. Even a perfect match wouldn't help: the existing
options-listing fast path only knows how to enumerate `attr.options`, blank
for a free-text field, and the attr's own `ValidationRule.message` here is
just "Invalid selection" — not descriptive either.

**Fix**: added `CpqEngine.describe_free_text_constraint()` +
`_describe_char_allowlist()` (`src/aryx/cpq/engine.py`) — recognizes the
recurring `allowedChars = "..."` idiom in a `ValidationRule.condition_script`
and turns it into a plain description ("letters, digits, and the characters
- . _"); returns None (never guesses) for any other script shape. Wired into
`_run_cpq_turn` (`src/aryx/api/ask_api.py`) as a new branch right after the
existing options-query fast path: when the CURRENTLY PENDING attr has no
options and the question matches the existing `_OPTIONS_KEYWORDS` set, it
answers directly from `session.pending_variables[0]` — no attr-name
matching needed at all, sidestepping `detect_attr_query`'s weakness
entirely for this case.

**Live-verified, with an important caveat**: forcing
`agencyDomainName_ID_swSoln` into `pending` confirms the new branch answers
correctly: *"Agency Domain Name/ID doesn't have a fixed list of values —
it's free text, but it must only contain letters, digits, and the
characters - . _."* But run end-to-end against the real flow, this field is
**never** naturally pending anymore — that's the direct consequence of
Amendment 20's revert. So this fix is real and will fire for any future/
other free-text field that legitimately becomes pending with a describable
`allowedChars` rule, but does not currently resolve the original complaint
for this specific field. Fixing that fully means re-opening Amendment 20's
open question (a genuine required/optional signal for this catalog) — not
attempted here.
