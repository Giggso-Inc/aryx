# CPQ Product/Family Scope-Reply LLM-First Classification — Plan (2026-08-13)

Status: **design only — not implemented, not approved for code changes**

Note: this doc's first draft (§ "Root cause" below) proposed an
LLM-as-fallback design — LLM only tried after the deterministic ladder
missed. That was superseded same-day (see "Revised 2026-08-13" section)
per owner directive: the LLM classifies FIRST, deterministic matching
validates second. The file was renamed from `..._LLM_FALLBACK_PLAN...`
to `..._LLM_FIRST_PLAN...` to match; the "Root cause" section below is
kept as-written for the investigation trail, but the "Design" section
further down is the one actually current.

## Source

Live transcript (reported same day as Issues 6/7, docs/CPQ_QUANTITY_
COUNTRY_SUMMARY_FIXES_2026_08_13.md): a customer replying "go further"
and later "I want quote for APX Next radios" to a pending "Product —
choose one" question both got the same unhelpful "I didn't get X for
Product" re-ask, verbatim, with no attempt at semantic understanding.

## Root cause (confirmed via code read)

`src/aryx/cpq/pending_scope.py`'s `resolve_against_scope` — the function
every pending product/family/attr-option reply is matched against — is a
**pure deterministic ladder**: exact string match → substring/partial →
fuzzy edit-distance (`SequenceMatcher`, thresholds 0.55/0.65/0.72) →
miss. There is no LLM anywhere in this function or its 5 call sites in
`ask_api.py` (lines ~7463, ~7513/7557, ~8063, ~9094, plus the
`_scoped_reask_response` shared re-ask builder at line ~1456).

**A fallback for exactly this shape of problem already exists and is
already proven** — just not applied here. `_llm_resolve_label_collision`
(`ask_api.py:5840`) does the identical job (classify a free-text reply
against a small, fixed candidate list, using an LLM only after the
deterministic ladder misses, never trusting anything not in the
candidate list) for **attribute** label collisions ("the second one,"
"the array one"). It is even already reused, awkwardly, for exactly one
of the 5 product-scope call sites — the model-leaf disambiguation path
(`ask_api.py:8075`) wraps each plain leaf-name string in a synthetic
`ConfigAttr` just to satisfy that function's attribute-shaped signature.
The other 4 call sites (family disambiguation, product options, product
suggestions, attr options) have no LLM fallback wired at all.

## Revised 2026-08-13 — LLM-first, deterministic-second (owner directive)

Owner directive, after reviewing the first draft of this plan: the LLM
should classify the reply FIRST; deterministic matching is the
resolution/validation layer underneath, not the primary decision-maker
— the same two-layer shape already established in docs/CPQ_LLM_
INTENT_FIRST_UNIVERSAL_PLAN.md §5 (LLM names intent in plain language,
deterministic resolves it to the exact real value, never the reverse).
This also folds "go further" INTO scope, reframed correctly per owner
feedback: it isn't a failed product-name match at all — it's the
customer asking to move past/skip the current question, a distinct
intent the old design (string-similarity-only) had no way to even
recognize as a category, let alone resolve.

**Country/quantity investigation (7→11 products), checked against the
code before this revision**: `apply_constraint_rules` (the function
that actually computes an attribute's allowed-value list) takes NO
`country` parameter at all. `evaluate_rules_loop`/`auto_fill` (a layer
above it) DO take `country=session.country`, and can auto-fill a
Region-type attribute from country, which a constraint rule could then
key off — so an indirect country→region→constraint chain is
architecturally real in this codebase, supporting the country-dropped
hypothesis as plausible. Equally plausible: a quantity-gated
constraint/recommendation rule exposing more SKUs once quantity is
known (this session's original hypothesis). Static code reading can't
distinguish between these two without the actual `run_id` trace from
that live session — **still an open item, not resolved by this plan**,
tracked separately below.

## Design

**1. New function, `_llm_classify_scope_reply`** (`ask_api.py`) — the
FIRST thing a pending-scope reply hits, before any string matching:

```python
def _llm_classify_scope_reply(
    reply: str, candidates: list[str], scope_label: str,
    session: Any, workspace_id: int,
) -> tuple[Literal["candidate", "skip", "unrelated"], str | None]:
```

Classifies into exactly one of three outcomes:
- `"candidate"` — the reply clearly points at one specific option;
  second element is the LLM's plain-language best guess at which one
  (still just a POINTER, never trusted as the final value — see step 2).
- `"skip"` — the reply is asking to move past/skip/defer this question
  ("go further," "skip this," "let's continue," "come back to this
  later") rather than naming any option at all.
- `"unrelated"` — neither of the above (off-topic, a new unrelated
  request, or genuinely too vague to classify either way) — the
  existing miss/reask behavior owns this case unchanged.
- Low-confidence classifications collapse to `"unrelated"` — same
  "ask, don't guess" discipline as every other gate this session.

**2. Deterministic resolution — validates, never invents.** When the
classification is `"candidate"`, the plain-language guess is resolved
against the REAL candidate list via `resolve_against_scope` (unchanged,
still the exact/partial/fuzzy ladder) — this is the exactness step,
mirroring `_resolve_target_description`'s job elsewhere in this
codebase. If it doesn't resolve to a real, unique candidate, that's
treated as `"unrelated"` too (the LLM's own guess wasn't grounded in
anything real) — never a guess promoted directly to an answer. This is
what keeps "LLM first" safe: the LLM never gets to hand a final value
to the rest of the system, only a pointer the deterministic layer must
independently confirm exists.

**3. New `_resolve_scope_reply` — the single integration point**,
replacing every existing `resolve_against_scope(...)` call:

```python
def _resolve_scope_reply(
    reply: str, candidates: list[str], scope_label: str,
    session: Any, workspace_id: int,
) -> ScopeResolve | Literal["skip"]:
    outcome, guess = _llm_classify_scope_reply(reply, candidates, scope_label, session, workspace_id)
    if outcome == "skip":
        return "skip"
    if outcome == "candidate" and guess:
        res = resolve_against_scope(guess, candidates)
        if res.tier != "miss":
            return res  # LLM pointer, deterministically confirmed real
    return resolve_against_scope(reply, candidates)  # unchanged fallback path
```

The plain deterministic ladder is still run directly on the ORIGINAL
reply as the final fallback (not just on the LLM's guess) — this
preserves 100% of today's behavior for every reply the LLM call fails,
times out, or returns `"unrelated"` for, matching the reject-on-failure
discipline from Issues 6/7 (an LLM problem must never make things worse
than doing nothing).

**4. Handling `"skip"`** (owner decision: ask what they'd like to do
instead, never auto-pick, never silently escalate). New response
shape, reusing `_scoped_reask_response`'s persistence/logging pattern
but with different wording:

> "This choice determines the rest of the configuration, so I can't
> skip it yet — could you tell me which {scope_label} you'd like, or
> what you're trying to configure? Here are the choices again:
> [candidates]"

Distinct `tools_called` tag (`cpq_scope_skip_declined()`) so this is
separately visible in telemetry from an ordinary miss/reask.

**5. Call-site update — mechanical, 5 sites**, same as the original
draft: every `resolve_against_scope(reply_or_question, candidates)`
call becomes `_resolve_scope_reply(...)`, with the caller branching on
a `"skip"` return before its existing `if res.matched is None:` reask
branch.

**6. Cost.** One LLM call per pending-scope reply now — a real
increase from the original draft's "only on deterministic miss" design,
since the LLM now runs first, always, for this specific reply-matching
moment (never every turn — still only when a `pending_scope_*` state
is active). Accepted per owner directive; scoped narrowly to this one
reply-matching moment, not a blanket policy change elsewhere.

## Test plan

*Positive:*
- `test_llm_classifies_and_resolves_a_specific_candidate` — reply "the
  international one" → classified `"candidate"`, resolves to "APX NEXT
  (International)" exactly.
- `test_llm_classifies_go_further_as_skip` — "go further" →
  classified `"skip"`, response asks what they'd like instead, never
  silently picks a default, candidates list still shown.
- `test_skip_response_uses_distinct_tools_called_tag` — regression-
  protects telemetry visibility for the new outcome.

*Negative:*
- `test_llm_candidate_guess_not_in_real_list_falls_through` — LLM
  returns `("candidate", "some hallucinated name")` not in the real
  candidate list → treated as `"unrelated"`, deterministic ladder runs
  on the original reply, exactly as it does today.
- `test_i_want_quote_for_apx_next_radios_still_asks_to_disambiguate` —
  names the family but no variant → classified `"unrelated"` (correct:
  it genuinely doesn't specify one), falls to the existing reask —
  this is expected, not a regression; the family-name-only case was
  never claimed to resolve on its own.
- `test_llm_call_failure_falls_through_to_deterministic_miss` — same
  reject-on-failure discipline as Issues 6/7: an exception/timeout
  degrades to running `resolve_against_scope` on the original reply
  directly, never crashes the turn.
- `test_all_5_call_sites_wired` — parametrized, one per call site.

## Open items (not part of this plan's implementation)

1. **7→11 product-count discrepancy** — still unconfirmed between the
   country-region-constraint chain and the quantity-gated-constraint
   hypothesis (see investigation note above). Needs the live `run_id`
   trace/logs from the reported session, not further static code
   reading, to settle which mechanism actually fired.
2. Real-model smoke test recommended before enabling in production —
   confirm the model doesn't overreach and guess a candidate for a
   genuinely vague reply, and correctly classifies "skip"-shaped
   phrasing across more examples than the ones in this transcript.

## Verification

- Run the new/updated tests plus the full existing CPQ suite (no
  existing behavior should change for any deterministically-resolvable
  reply — the wrapper is a strict superset of today's ladder).
- Rebuild, redeploy, spot-check against 2-3 real "loose but specific"
  phrasings from the live catalog before considering this validated.
