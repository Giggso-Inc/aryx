# Tier-1 Mixed AND/OR Condition Parser — Plan

## Context

For product "APX NEXT All Band" (real catalog code `productSelectionProduct_all == "APX NEXT MULTI"`),
the customer is asked "Frequency Bands" with all 20 raw catalog values, unfiltered — confirmed via
`/andie` verification this should not happen. The real hiding rule, "Hide Frequency Bands and
additional frequency band," has this script:

```
if( ((productSelectionProduct_all=="APX NEXT MULTI") OR (productSelectionProduct_all=="APX NEXT XE MULTI") OR (productSelectionProduct_all=="APX NEXT XN ALL")) AND ((modelSelectionbaseModel_astro<>""))){
	return true;
}
return false;
```

Both conditions are true for this real state (confirmed live), so this should resolve to `hide=True`.
Confirmed live against the real evaluator (`BmlEvaluator.hide_for_script`) that it instead returns
`None` (unresolved) — even with the real evaluator, cache cleared. Traced to `bml._parse_condition`:
it supports a condition that's a UNIFORM chain of AND-only or OR-only comparisons, each optionally
wrapped in its own parens (`docs/...` history: added to handle a real 8-clause pure-OR condition).
It does NOT support a MIXED condition — one where an OR-group is combined with another clause via
AND. When it hits the outer `AND` split, each resulting part must itself match `_CMP_RE` (a SINGLE
comparison) — the OR-group part `((...) OR (...) OR (...))` fails that check, so the whole condition
(and therefore `_parse_branches`, and therefore the whole script) is rejected as "grammar
unsupported." Per `settings.bml_use_llm`'s own documented default (`False` — Tier-2 LLM disabled by
default to avoid stalling a live request), there's no fallback: this hiding rule permanently
resolves to "unknown," and per this codebase's own "never guess a hide" discipline, the attribute
stays visible. Since no constraint rule narrows this attribute for "APX NEXT All Band" specifically
(the only two constraint rules that target it are scoped to "Single Band"/"XE Single Band"
variants), all 20 raw catalog options show up unfiltered.

**Real-data impact check (done during planning, not hypothetical):** surveyed all 696 unique
hiding/recommendation/constraint scripts in the live catalog (workspace 39005). 614 scripts fail to
parse at all (`_parse_branches` returns `None`) — the overwhelming majority are genuinely complex
procedural scripts (loops, `bmql()`, `findinarray()`, nested nested structures) that Tier-1 was
never meant to handle and this plan does not touch. Of those 614, exactly **13 distinct real rules**
fail specifically because their first `if` condition mixes AND and OR — the precise shape this plan
targets, including the one causing the reported bug. The other 12: "If Is provisioning required =
NO then hide is fedRAMP high baseline required," "Hide Application Services if duration is not
<=0 or >48...," "Set Formula Version BOM," "Set HelpTtext info," two "Default Values for Base
Model" variants, "Default 7 YEARS for Application Services Duration...," three "Set
modelSelectionFrequencyBandMslDummy attributes" variants, "Set default values for APX N70 based on
attributions," and one genuinely ambiguous-precedence case ("Associated rec forceset Application
set up assistance...") flagged below as out of scope.

## Approach

`_parse_condition` currently tries, in order: (1) split the WHOLE condition on AND, require every
part to be a single comparison; (2) split the WHOLE condition on OR, require every part to be a
single comparison; (3) require the WHOLE condition to be one single comparison. All three require
uniformity. Add a fourth attempt, tried only when all three existing ones fail AND the condition
contains both `AND`/`&&` and `OR`/`||`:

**New helper `_parse_boolean_expr(cond: str) -> _BoolExpr | None`** — a small recursive-descent
parser respecting standard precedence (AND binds tighter than OR, matching how the 12 in-scope real
scripts are actually written and how virtually every C-like language resolves this):
1. Find top-level (paren-depth-0) `OR`/`||` occurrences; if any, split there, recursively parse
   each part, combine as `_BoolExpr(kind="or", parts=[...])`.
2. Else find top-level `AND`/`&&` occurrences; if any, split there, recursively parse each part
   (after `_strip_wrapping_parens`), combine as `_BoolExpr(kind="and", parts=[...])`.
3. Base case: a single comparison via the existing `_CMP_RE`, wrapped as `_BoolExpr(kind="cmp",
   var=..., op=..., value=...)`.
4. Any part that fails all three returns `None` — propagates up, whole parse fails (never guesses).

`_BoolExpr` is a new, small dataclass — deliberately NOT reusing `_parse_condition`'s existing flat
`list[tuple]` shape, so **zero existing callers or return-shape assumptions change**. `_parse_
condition`'s three existing fast paths are completely untouched, byte-for-byte; this is a pure
fourth fallback attempt.

**New evaluator `_eval_boolean_expr(expr, variables) -> tuple[bool | None, bool]`** (mirrors
`_first_matching_branch`'s existing per-chain evaluation contract: `(result, blocked_by_missing_
var)`), recursively evaluating `_BoolExpr` nodes with the same short-circuit discipline the existing
flat evaluator already uses (an `or` node already `True` from a resolved child short-circuits
regardless of a sibling's missing variable; symmetrically for `and`/`False`) — generalized to
nesting instead of one flat chain.

**Wiring**: `_parse_branches` (bml.py:359) tries `_parse_condition` first (unchanged); on `None`,
tries the new `_parse_boolean_expr` and stores whichever succeeded, tagged so `_first_matching_
branch` knows which evaluator to run. `_first_matching_branch`'s existing flat-chain evaluation path
is completely unchanged for every condition `_parse_condition` already handles; a new branch calls
`_eval_boolean_expr` only for conditions that needed the new parser.

This is purely additive: a script that resolves today keeps resolving via the exact same code path,
with the exact same result. Only scripts that were previously "unknown" (`None`) due to this one
specific grammar gap can now resolve — never the reverse.

## Explicitly out of scope

"Associated rec forceset Application set up assistance if apps selected Next" has a genuinely
ambiguous shape: `(A AND B AND C) OR D AND E` — whether the intended grouping is `(A AND B AND C) OR
(D AND E)` (standard AND-binds-tighter precedence, what this plan's parser would produce) or
something else depends on the original author's intent, not inferable from the text alone. Standard
precedence is the least-surprising default and this plan's parser will apply it — if this specific
rule's real behavior needs a different grouping, that surfaces as a separate, targeted follow-up
once real-data verification flags it, not guessed at now.

## Critical files

- `src/aryx/cpq/bml.py` — new `_BoolExpr` dataclass, `_parse_boolean_expr`, `_eval_boolean_expr`;
  `_parse_branches` and `_first_matching_branch` each gain one new fallback branch, existing logic
  untouched.
- `tests/test_cpq_bml_*.py` (extend or new file) — synthetic fixtures for the recursive parser
  (simple AND-of-ORs, OR-of-ANDs, nested parens, a genuine short-circuit-with-missing-variable case)
  plus replays of the 13 real script conditions found above (or their exact text) asserting the
  correct resolved value against a realistic `filled` state.

## Verification results (live, 2026-08-10)

One extra bug found and fixed while implementing: the real "Hide Frequency Bands..." script's
second AND-part is DOUBLE-wrapped (`((modelSelectionbaseModel_astro<>""))`), and
`_strip_wrapping_parens` only removes one layer per call. `_parse_boolean_expr` now loops it to
stability before attempting the final single-comparison match, or the leftover single layer made
`_CMP_RE` (which anchors on a leading word character, not `(`) fail every time.

Unit tests: 10 new tests (`tests/test_cpq_bml_mixed_and_or_condition.py`), including the exact real
script from workspace 39005 across true/false/unknown-due-to-missing-variable cases, an OR-of-ANDs
shape, short-circuiting through a nested OR-group, an intentionally-unparseable leaf (never
guessed), and two "existing uniform chain is unaffected" locks. Full `-k cpq` regression: 869
passed (up from 858), same 3 pre-existing unrelated failures, zero regressions.

Live verification: rebuilt, redeployed, replayed the exact real conversation. Frequency Bands is no
longer asked at all for "APX NEXT All Band" — the conversation now reaches "Configuration complete"
in **2 turns** (previously 3, after today's earlier layout-visibility/data-gap fixes; 5+ before any
of today's fixes). Spot-checked two of the other 12 real rules found in the catalog survey
("If Is provisioning required..." shape and "Set Formula Version BOM" shape) against representative
filled states — both now resolve correctly instead of `None`. No errors or exceptions in the logs
from the new parser across the full replay.

## Verification

1. **Unit tests**: nested AND/OR parsing correctness (both groupings, deeply parenthesized and not);
   short-circuit behavior matches the existing flat evaluator's semantics one level deeper; a
   genuinely unparseable expression (e.g. unbalanced parens, an unsupported operator) still returns
   `None`, never a guess. Replay all 13 real conditions found in the survey against representative
   `filled` states and assert the human-obvious correct outcome.
2. **Regression check**: full `-k cpq` and any dedicated `bml`/Tier-1 test files — confirm the 82
   scripts that already parse today are byte-for-byte unaffected (their conditions never reach the
   new fallback since `_parse_condition`'s existing paths still claim them first), and the 3 known
   pre-existing unrelated failures are the only failures.
3. **Live verification**: rebuild, redeploy, replay the exact real conversation ("APX Next radios 50
   qty... United States" → "APX NEXT All Band") and confirm Frequency Bands is no longer asked at
   all (hidden, matching the real business rule) — the "Configuration complete in 3 turns" outcome
   from today's earlier fix should still hold or improve, never regress.
4. Rebuild, redeploy, live-verify — same discipline as every fix today.
