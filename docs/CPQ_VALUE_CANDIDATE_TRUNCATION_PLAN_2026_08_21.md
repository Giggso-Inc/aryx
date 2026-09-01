# CPQ Value-Candidate Truncation — Fix Plan

**Date:** 2026-08-21
**Status:** Implemented and live-verified (branch `fix/cpq-value-candidate-truncation-2026-08-21`)
**Severity:** High — customer-visible dead end on large-option attributes. A
customer naming an attribute AND its exact, valid value still gets asked to
disambiguate the attribute, or has the value silently discarded and the menu
re-shown, purely because of where the value happens to sit in the catalog's
raw storage order.

## Problem (live-reproduced)

Two symptoms reported against the same conversation, both on `productSelectionProduct_all`
(328 real catalog options):

1. `"change the product to APX NEXT XE (4G LTE+5G)"` — despite the message
   unambiguously naming the attribute ("product") — produced "Which attribute
   did you mean? Product / Delete LTE Capability" instead of applying the
   change.
2. `"Change the Product to APX NEXT Enhanced"` — despite giving an exact,
   verbatim, valid option string — produced "Which value would you like for
   Product?" with the option menu re-shown, discarding the stated value.

## Root cause (verified against real code + live catalog data)

`build_candidate_bundles` (`src/aryx/cpq/intent_gateway.py:196`) builds the
value list shown to the LLM classifier for validating a change request's
target value, truncating every attribute's real option list to
`_VALUE_CAP = 40` (`intent_gateway.py:82`) in **raw catalog/database storage
order** — never reordered by relevance to the customer's message:

```python
for i, o in enumerate(a.options[:_VALUE_CAP]):
    values.append(ValueCandidate(index=i, item_value=o.item_value, display_name=o.display_name))
```

Confirmed directly against the live catalog (workspace 39004,
`productSelectionProduct_all`, 328 real options, ordered starting "APX 6500",
"APX 6500Li", "APX 5500" — legacy SKU order, not relevance or recency):

- `"APX NEXT XE (4G LTE+5G)"` sits at **index 325**
- `"APX NEXT Enhanced"` sits at **index 323**

Both are far outside the 40-item window ever shown to the LLM. The gateway's
own logged reasoning for the reproduced turn confirms the LLM is being
truthful about a truncated view, not making a real classification error:

```
cpq_intent_gateway: ambiguous run_id=... reason="The user wants to change
the 'Product' attribute, but the specified value 'APX NEXT XE (4G LTE+5G)'
is not a valid option in the candidate list for that attribute."
```

Once the gateway can't validate the value, it degrades to
`IntentCategory.AMBIGUOUS`, which then either (a) pulls in an unrelated
second attribute via a separate word-overlap disambiguation path
(`_ground_clarify_candidates`, `ask_api.py`), producing symptom 1, or (b) for
a message the system now believes has "no resolvable value," falls to
`CHANGE_TARGET_WITHOUT_VALUE` and re-shows the menu, producing symptom 2.

**Why this only bites large-option attributes**: Hardware Version (2 options)
is always fully inside any cap regardless of order. Any attribute with more
than 40 real catalog values is silently exposed to this bug for any option
past position 40 in storage order — a threshold with no relationship to how
likely a customer is to actually pick that option.

## Fix

Change `build_candidate_bundles` so the 40 values that survive the cap are
chosen by relevance to the customer's message, with a hard guarantee for
exact matches — not raw storage order. Two parts:

### Part 1 — exact-match guarantee (closes the verbatim-echo case definitively)

Before truncating, scan `a.options` for any option whose `display_name` or
`item_value` matches (case-insensitive, trimmed) a substring of the
question. Any such option is included regardless of score or position —
this is the single most common trigger (a customer echoing back an option
the system itself just showed), and deserves a guarantee, not improved odds.

### Part 2 — rarity-weighted relevance ordering (handles paraphrased/fuzzy values)

For the remaining slots, rank options by the SAME rarity-weighted
word-overlap scoring `_resolve_target_description` already uses
(`ask_api.py:4982`) — reused here, not reinvented, because this codebase
already hit and fixed the exact failure mode plain overlap-count scoring has
for this shape of data: its own docstring documents that raw overlap count
ties a distinctive word ("solution") together with a generic word shared by
dozens of labels ("type"). Product's option list has the identical shape —
"APX," "NEXT" appear in dozens of the 328 entries — so reusing rarity
weighting (1 / document-frequency per matched word, computed per-attribute
over that attribute's own option vocabulary) avoids silently reintroducing a
bug this codebase already paid to fix once elsewhere.

```python
def _rank_value_candidates_by_relevance(
    options: list[MenuOption], q_words: set[str],
) -> list[MenuOption]:
    """Order `options` so values relevant to the customer's message survive
    _VALUE_CAP's truncation, instead of raw catalog/database storage order.
    docs/CPQ_VALUE_CANDIDATE_TRUNCATION_PLAN_2026_08_21.md.

    Exact matches (case-insensitive, on display_name or item_value) against
    the message always sort first, regardless of score -- the single most
    common trigger of the bug this closes is a customer echoing back an
    option the system itself just displayed, and that case gets a
    guarantee, not just better odds.

    Remaining options are ranked by rarity-weighted word overlap (mirrors
    _resolve_target_description's scoring, ask_api.py:4982 -- reused
    because raw overlap-count ties a distinctive word to a generic word
    shared by dozens of this attribute's own options, e.g. "APX"/"NEXT"
    appear in dozens of this catalog's 328 Product entries).
    """
    q_lower = " ".join(q_words)  # already-tokenized; substring check below re-tokenizes source text at the call site
    exact: list[MenuOption] = []
    rest: list[MenuOption] = []
    for o in options:
        if o.display_name.strip().lower() in q_lower or o.item_value.strip().lower() in q_lower:
            exact.append(o)
        else:
            rest.append(o)

    vocabs = [set(_WORD_RE.findall(o.display_name.lower())) for o in rest]
    doc_freq: dict[str, int] = {}
    for vocab in vocabs:
        for w in vocab:
            doc_freq[w] = doc_freq.get(w, 0) + 1
    scored = []
    for o, vocab in zip(rest, vocabs):
        overlap = q_words & vocab
        score = sum(1.0 / doc_freq[w] for w in overlap) if overlap else 0.0
        scored.append((score, o))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return exact + [o for _score, o in scored]
```

Called from `build_candidate_bundles` right before the existing
`a.options[:_VALUE_CAP]` slice, replacing `a.options` with
`_rank_value_candidates_by_relevance(a.options, q_words)` for that slice
only — `_VALUE_CAP` itself stays 40, unchanged; this changes WHICH 40
survive, not how many.

## Why this direction, not an alternative

- **Rejected: just raise `_VALUE_CAP`.** Doesn't fix anything — it moves the
  cliff edge, it doesn't remove it. Product has 328 options; any cap smaller
  than that reintroduces the identical bug for whatever now sits just past
  the new, larger cutoff. Also directly increases LLM prompt size/cost on
  every large-catalog attribute, on every turn, regardless of whether that
  attribute is even the one being discussed.
- **Rejected: relevance-order by raw overlap count only (no rarity
  weighting).** Works for this specific reproduced case but silently
  reintroduces the exact scoring bug `_resolve_target_description` was
  built to avoid, for the same reason: Product's 328 options share enough
  generic words ("APX," "NEXT") that raw counts would tie a genuinely
  relevant option against several irrelevant ones, especially once the
  message also contains attribute-naming words unrelated to the value
  itself.
- **Rejected: exact-match guarantee alone, no relevance ordering.** Would
  fully fix the verbatim-echo case (the two reproduced symptoms) but leaves
  the door open for a paraphrased or partially-typed value to still fall
  outside the cap with no mitigation at all.

## Risk assessment

- **Blast radius**: `build_candidate_bundles` runs on every turn that
  reaches the LLM intent gateway with a nonzero `q_words` set for a
  change-request-shaped message — i.e. broadly, not scoped to Product or
  large catalogs specifically. The new ranking is a no-op in effect for any
  attribute whose total options already fit under `_VALUE_CAP` (order
  changes, but nothing gets excluded either way), so small-option attributes
  (Hardware Version, Country, etc.) see no behavior change.
- **Needs verification**: confirm the exact-match substring check doesn't
  false-positive on short/generic option display names (e.g. an option
  literally named "Yes" or "1") matching unrelated words in a long message —
  may need a minimum-length guard or word-boundary check rather than a bare
  substring test.
- **Not a gap, and not something this fix should try to close**: a value
  with genuinely zero word overlap against every real catalog option (e.g. a
  customer's own external nickname/shorthand never reflected in the
  catalog's own text) has no lexical evidence for the system to act on —
  falling through to a clarifying question in that case is the CORRECT,
  intended outcome, not a failure this fix should try to eliminate. The bug
  this fix closes is specifically FALSE ambiguity: a real, matchable value
  (exact or clearly word-overlapping) existing in the catalog but getting
  discarded purely by truncation before the system ever gets to recognize
  the match. Genuine ambiguity (no match exists) should keep producing a
  clarifying question exactly as it does today.

## Verification plan

1. Unit tests for `_rank_value_candidates_by_relevance` in isolation:
   exact match (case-insensitive) always sorts first regardless of score;
   rarity-weighted ordering among non-exact matches (a rare-word match
   outranks a common-word-only match); a message with zero overlap returns
   options in a stable (not crashing, not reordered nondeterministically)
   fallback order.
2. Regression test reproducing this doc's exact scenario: a synthetic
   attribute with 300+ options where the target value sits past index 40 in
   storage order, confirming it survives truncation after the message names
   it (both verbatim and via partial/paraphrased overlap).
3. Full CPQ regression suite — confirm no new failures against the
   established pre-existing baseline (per this session's established
   worktree-comparison discipline for any ambiguous failure).
4. Live replay: rebuild + redeploy `api`, replay both reported transcripts
   (change Product to "APX NEXT XE (4G LTE+5G)"; change Product to "APX NEXT
   Enhanced") and confirm both apply directly without a disambiguation or
   re-ask detour.

## Implementation summary (2026-08-21)

- Added `_rank_value_candidates_by_relevance` (`intent_gateway.py`) exactly
  as designed: exact matches (boundary-aware, not a naive substring check —
  see below) always sort first, remaining options ranked by rarity-weighted
  word overlap. Wired into `build_candidate_bundles` at both places
  `a.options[:_VALUE_CAP]` was previously sliced directly — the VALUE
  CANDIDATES bundle sent to the LLM, and the attribute's own relevance-vocab
  computation (the same truncate-then-slice pattern, same underlying bug,
  fixed with the same helper rather than left half-fixed).
- **Found and fixed during testing, not left as a known issue**: the first
  implementation used a bare `\b...\b` regex for the exact-match check,
  which fails to match values ending in punctuation (e.g. "APX NEXT XE (4G
  LTE+5G)" — `\b` cannot match at a boundary where both sides are
  non-word characters, like right after a closing paren). Replaced with
  alphanumeric-adjacency lookaround (`(?<![a-z0-9])...(?![a-z0-9])`),
  confirmed working for both punctuation-heavy display names and
  single-character item_values that previously false-positived via naive
  substring matching.
- New `tests/test_cpq_value_candidate_truncation_2026_08_21.py` (8 tests,
  all passing): exact-match guarantee (including case-insensitivity and
  item_value matches), rarity-weighted ordering, zero-overlap stability,
  survival past `_VALUE_CAP` in a 328-option fixture mirroring the real
  catalog shape, and end-to-end `build_candidate_bundles` wiring (including
  a control test proving small-option attributes see no behavior change).
- **Found and left alone, correctly out of scope**: while testing, a
  genuinely pre-existing, independent bug surfaced in
  `tests/test_cpq_2026_07_28_fixes.py::test_llm_first_gate_falls_through_to_deterministic_on_unparseable_reply`
  — confirmed via worktree comparison against unmodified `dev-rv-msi`,
  running in complete isolation (fresh process, empty cache), that this
  test already fails on the base branch. It was previously masked only by
  incidental module-level cache-hit ordering in full-suite runs. Not fixed
  here — unrelated to this plan's scope, and worth its own investigation
  separately. One test in the same file
  (`test_llm_first_gate_calls_the_llm_and_dispatches_when_enabled`) DID
  need updating: its hardcoded `value_ref: 1` assumed old raw-order
  semantics (CloudRC at index 1); updated to `value_ref: 0` with a comment
  explaining the new, correct ordering promotes it to index 0 via the exact-
  match guarantee.
- Full CPQ regression suite (`pytest tests/ -k cpq`): 1312 passed, 13
  pre-existing failures (byte-identical to the established baseline,
  including the one confirmed-pre-existing bug above) — zero new failures.
- Live-verified against the real APX Next catalog (workspace 39004, rebuilt
  + redeployed `api` container): replayed both reported transcripts.
  `"change the product to APX NEXT XE (4G LTE+5G)"` now applies directly
  (`"Updated Product → APX NEXT XE (4G LTE+5G)..."`) instead of the false
  "Which attribute did you mean?" disambiguation. `"Change the Product to
  APX NEXT Enhanced"` likewise applies directly instead of re-showing the
  option menu.
