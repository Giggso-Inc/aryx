# "APX" suggests the wrong family — root cause and residual limitations

**Status:** Fixed. `src/aryx/cpq/engine.py` — `_fuzzy_score_candidates` (shared
by `detect_product_mention` and `suggest_product_candidates`).
**Reported by:** g.sivasankari@giggso.com. Reproduction: "Give me quote of
APX with 10 qty" → *"I didn't get ... for product family — did you mean
videoSolutions_BOM? ..."*

## Symptom

A short/vague product mention ("APX" instead of "APX NEXT") triggered a
"did you mean" suggestion pointing at an unrelated ingested family
(`videoSolutions_BOM`), instead of any real APX-family candidate.

## Root cause

Product-mention resolution in `engine.py` runs a two-tier ladder:

1. **Exact substring** — is a real candidate's full normalized name
   contained inside the user's normalized message? ("Quote APX Next
   Enhanced radios" contains "apxnextenhanced" → matches directly.)
2. **Fuzzy fallback** (`_fuzzy_score_candidates`) — slide a window the
   length of each candidate's name across the whole normalized question
   and score via `SequenceMatcher`.

Both tiers only look for **candidate-inside-question** containment. Neither
checks the opposite, equally common direction: the user's mention is
*shorter* than every real candidate ("apx" vs. "apxnext", "apx6500").
Tier 1 can never fire (a short string can't contain a longer one). Tier 2
degrades for the same reason: when the query is shorter than the
candidate's name, the sliding window collapses to a single comparison of
the *entire raw sentence* — including filler words, quantities, and units
("give", "quote", "with", "10", "qty") — against the candidate's full name.
For a genuinely short brand token, that whole-sentence comparison carries
essentially no real signal, so whichever unrelated candidate happens to
share the most incidental characters with the filler text can outscore the
real match. That is exactly what happened: `videoSolutions_BOM` scored
higher than any APX-family candidate purely by character-overlap
coincidence with words like "quote"/"of", not because of any relationship
to "APX".

## Fix

Added a third, word-level signal alongside the existing two: split the
question into individual normalized word tokens (≥3 chars) and check
whether any token is a genuine **prefix** of a candidate's normalized name
(`_ABBR_PREFIX_MIN_LEN`, `_ABBR_PREFIX_SCORE` in `engine.py`). This is
fully dynamic — it runs against whatever `ingested_product_alias_map`
actually returns for the workspace, with no product name, prefix, or list
hardcoded anywhere in the fix. "APX" now scores every ingested
APX-prefixed alias into the "suggest" band (`_PRODUCT_FUZZY_SUGGEST_THRESHOLD`
≤ score < `_PRODUCT_FUZZY_MATCH_THRESHOLD`) — high enough to surface as a
suggestion, but deliberately capped below the confirm-match threshold, so
an ambiguous abbreviation (APX NEXT vs. APX6500 vs. any other APX-prefixed
family) is never silently auto-picked; it always resolves through a
"did you mean ...?" turn, consistent with this engine's existing
"never guess" discipline for the product selector.

## Why this survives even after the fix — residual limitations

The fix is a **prefix** heuristic, not general abbreviation understanding.
It resolves cleanly when the customer's shorthand is literally the leading
characters of the real name — true for essentially every case in the
report ("APX", "APX NEXT", "APX NExt" all prefix "APX NEXT"/"APX6500"/etc.).
It will **not** help when:

- **The abbreviation isn't a prefix.** A nickname that maps to the *middle*
  or *end* of a name (e.g. an internal codename with no literal character
  overlap at the start) gets no boost from this fix — it still depends on
  the sliding-window fuzzy score alone, which remains the pre-existing
  behavior (and pre-existing limitation) for that shape of input.
- **The abbreviation prefixes multiple, unrelated real families.** If two
  *different* product lines both happen to start with the same three
  letters by coincidence, both still surface as suggestions — this is
  working as intended (ask rather than guess), not a bug, but it means a
  short enough abbreviation can still produce a multi-item "did you mean"
  list even after this fix, by design.
- **No ingested catalog contains anything starting with the token at all.**
  Then there is genuinely no signal to boost, and the flow correctly falls
  through to the generic "which product family?" prompt — this is the
  correct behavior for a truly product-less message ("I need a quote for
  some radios," "Quote 50 units for the United States"), not a residual
  bug, but worth stating explicitly since it looks superficially similar
  to the original symptom (no specific suggestion offered).
- **A maintained alias/synonym table is still out of scope.** If the
  business wants "moto" to resolve to `MOTOTRBO` (not a character-level
  prefix relationship at all — it's a dropped-suffix brand shorthand that
  happens to also prefix-match here, but the general class of *arbitrary*
  nicknames unrelated to spelling) that requires a real alias mapping, not
  a string-similarity heuristic; this fix does not add one.

## Verification

Direct engine-level check against a fake two-APX-family + one-video-family
catalog (see `tests/test_cpq_product_switch.py::
test_vague_abbreviation_suggests_the_real_matching_family_not_an_unrelated_one`
and the companion `..._with_no_matching_family_gets_no_suggestions`):

```
detect_product_mention("Give me quote of APX with 10 qty", ...) == ""
suggest_product_candidates("Give me quote of APX with 10 qty", ...)
    == ["APX6500", "APX NEXT"]   # videoSolutions_BOM no longer present
```
