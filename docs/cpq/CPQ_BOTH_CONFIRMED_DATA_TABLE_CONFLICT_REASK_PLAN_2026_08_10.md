# Re-ask When Both Sides of a Data-Table Conflict Are Customer-Confirmed — Plan

## Context

Today's earlier fix to `CpqEngine._invalidate_inconsistent_paired_values` (commit `8b392f6`)
widened the set of "customer-confirmed" sources it never silently clears from `{"user"}` to
`CpqEngine._CONFIRMED_SOURCES` (`{"user", "hint", "cascade"}`) — closing a live bug where a
hint-mined answer (e.g. `ultimateDestinationCountry`) got silently cleared and re-asked the moment
an unrelated later cascade changed the base model enough for that pass's Data-Table pairing check
to flag it.

`/andie` review (2026-08-10) surfaced a real gap in that fix: `data_table_resolver.
find_inconsistent_filled_pairs` only ever flags a pair when a **real ingested Data Table row
proves the two attributes are linked, and the current combination matches none of the real rows**
— by its own docstring ("a confident contradiction, not a guess"), a flag here is never a false
positive; it is a genuine, data-proven rule violation. The fix's `{vn for vn in invalid if
sources.get(vn) not in _CONFIRMED_SOURCES}` return correctly keeps self-correcting the common case
(one confirmed value + one auto-derived value — clear the derived one, keep the customer's fact).
But when **both** sides of a genuinely-invalid pair are confirmed-sourced (two facts both mined
from free text, or one typed answer plus an earlier cascade), the comprehension excludes both,
`_invalidate_inconsistent_paired_values` returns nothing for that pair, and the invalid combination
silently persists all the way to the final BOM with no re-ask at all — the opposite of "ask when
the rules disagree," and a direct violation of this codebase's own "never generate a BOM holding a
value the rules have already ruled out" discipline (the same discipline
`_reask_stale_constraint_violations`/`recheck_constraints` already enforces for constraint-rule
violations, `docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md` §4.1).

## Approach

Reuse the exact same architecture already proven for constraint-rule violations rather than
inventing a new one:

1. **New engine method** `CpqEngine.find_confirmed_data_table_conflicts(attrs, filled, sources,
   workspace_id, catalog_prefix, cache) -> set[tuple[str, str]]` (`src/aryx/cpq/engine.py`, next to
   `_invalidate_inconsistent_paired_values`) — reuses `dt_find_inconsistent_filled_pairs` the exact
   same way, but instead of returning a flat set of variable names to clear, returns the **pairs**
   `(attr_a, attr_b)` where the pair is genuinely invalid AND both `sources.get(attr_a)` and
   `sources.get(attr_b)` are in `_CONFIRMED_SOURCES` — the specific case
   `_invalidate_inconsistent_paired_values` now deliberately leaves untouched.
2. **New ask_api check, same call site as the existing stale-constraint recheck**
   (`_reask_stale_constraint_violations`, `ask_api.py:1486`, called right before "Configuration
   complete" is shown): add a check for `find_confirmed_data_table_conflicts` immediately after the
   existing `missing_required`/`recheck_constraints` checks and before returning `None`. When a
   conflicting pair is found: `push_snapshot` (same audit trail every other reask uses), clear both
   attrs from `session.filled`/`display_filled`/`filled_source`/`filled_multi` as appropriate, push
   both onto the front of `session.pending_variables`, set `session.status = "configuring"` /
   `session.complete = False`, and return a message following the exact wording pattern the
   existing rule-conflict branch already uses (`"⚠️ **Rule conflict detected.** ... Please change
   one of your earlier selections."`), naming both attributes and noting the catalog's own data
   proves them incompatible — then ask about the first one, noting the second follows next (same
   `also_note` pattern as the stale-constraint re-ask).
3. **No change to `_invalidate_inconsistent_paired_values` itself** — its existing per-pass
   behavior (silently self-correct the non-confirmed side of a mixed pair) is correct and stays
   exactly as shipped today; this plan only adds the missing safety net for the both-confirmed edge
   case, checked once at the same "about to declare complete" gate the constraint-conflict check
   already uses, not on every pass.

This mirrors, rather than duplicates, the already-accepted pattern: a per-pass auto-corrector for
the easy case, plus a pre-completion gate that surfaces the case auto-correction can't resolve on
its own — exactly how constraint-rule staleness is already handled.

## Verification results (live, 2026-08-11)

Implemented as planned, with one placement fix found during implementation: the original draft
would have wired the new check only inside `_reask_stale_constraint_violations`'s `if not stale:`
branch, which sits AFTER `if not con_rules: return None` — meaning the data-table-conflict check
would never run at all for the very common case of zero active constraint rules. Fixed by
extracting the check into its own `_reask_confirmed_data_table_conflict` helper, called both when
`con_rules` is empty and when the constraint recheck finds nothing stale — so it now runs
independently of constraint-rule presence, as the plan actually intended (data-table conflicts are
a separate mechanism from constraint rules).

`data_table_resolver.find_inconsistent_filled_pairs` only ever returned a flattened `set[str]` of
variable names, not the actual pairs — insufficient for a re-ask that must name both sides. Added
`find_inconsistent_filled_pairs_detailed` (returns `set[tuple[str, str]]`) alongside it; the
existing flat function now delegates to the new one, so its own return contract and all of its
existing tests are byte-for-byte unchanged.

Unit tests: 6 new tests (`find_inconsistent_filled_pairs_detailed` — 2, `CpqEngine.
find_confirmed_data_table_conflicts` — 4) plus 2 new `ask_api`-level tests (`_reask_stale_
constraint_violations` now fires on a both-confirmed conflict even with zero constraint rules;
stays a no-op when the engine reports no conflict). Full `-k cpq` regression: 884 passed (up from
876), same 3 pre-existing unrelated failures, same 13 pre-existing collection errors.

Live verification: replayed both the plain "APX NEXT All Band" flow and the Hardware-Version-
cascade-to-Enhanced flow from today's earlier investigations — both still complete normally with no
spurious conflict re-ask, confirming the new check only fires on a genuine, data-proven conflict
(neither real reproduction today happened to hit one — `modelSelectionFrequencyBands_astro`/
`modelSelectionFrequencyBandMsl_astro` are not linked by any real ingested row in this catalog, per
the earlier constraint-rule audit) and does not regress the common completion path.

## Critical files

- `src/aryx/cpq/engine.py` — new `find_confirmed_data_table_conflicts` method.
- `src/aryx/api/ask_api.py` — new check inside `_reask_stale_constraint_violations` (or a sibling
  helper it calls), reusing the exact clear/pending/message pattern the existing stale-constraint
  branch already uses.
- `tests/test_cpq_data_table_resolver.py` or a new file — unit tests for
  `find_confirmed_data_table_conflicts` (synthetic linked-pair fixture, both confirmed vs. one
  confirmed vs. neither).
- `tests/test_cpq_*` (ask_api-level) — a test replaying the real "two hint-mined, mutually
  incompatible values" shape and asserting the re-ask message and cleared pending state.

## Verification

1. **Unit tests**: `find_confirmed_data_table_conflicts` returns the pair only when both sides are
   confirmed AND the combination genuinely doesn't match any real row; returns nothing when the
   pair is valid, when only one side is confirmed (that case stays `_invalidate_inconsistent_
   paired_values`'s job), or when the pair isn't linked by any real data row at all.
2. **Regression check**: full `-k cpq` suite — confirm `_invalidate_inconsistent_paired_values`'s
   own existing tests (including today's new hint/cascade test) are unaffected, and the existing
   stale-constraint re-ask tests still pass unmodified.
3. **Live verification**: construct (or find, if one exists in the real catalog) a real two-hint
   conflicting-value scenario; confirm the customer sees an explicit re-ask naming both attributes
   instead of either a silent pass-through or an incorrect single-side clear.
4. Rebuild, redeploy, live-verify — same discipline as every fix today.
