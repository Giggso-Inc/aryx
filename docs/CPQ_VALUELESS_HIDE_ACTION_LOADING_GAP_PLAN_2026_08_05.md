# CPQ Valueless-Action Rule Loading Gap — Plan (2026-08-05)

**Status: Phase 1 shipped and live-verified (2026-08-05).** Deployed to the
running container and re-checked against the real Astro-APX catalog:
`load_hiding_rules(39004, "AstroApx")` went from 396 → 527 rules (+131,
matching the audit), and rules targeting Frequency Band specifically went
from 4 → 7, now including `"Associated rec rule to Hide Frequency Band for
Single Band"` — the rule this investigation started from.

**Correction during implementation:** the live verification used to trace
the original Frequency Band symptom used the wrong `catalog_prefix`
(`"Astro-APX"`, the raw landed-record dataset name) instead of the real
ontology-type prefix (`"AstroApx"`). With the wrong prefix, EVERY rule
query silently returns zero rows — not just the ones for this attribute —
so the original "0 hiding/rec/con rules target Frequency Band" claim was an
artifact of that bug, not a finding specific to this rule. Re-verified with
the correct prefix: the rule actually gating Frequency Band in that live
scenario, `"Hide Frequency Band for Single Band"` (`rule_type=11`), already
loads correctly today and is unaffected by this plan — its own problem is
a separate condition-value mismatch (`"APX NEXT SINGLE"` authored vs. the
real menu item_value `"APX NEXT SINGLE BAND"`), tracked as a follow-up, not
part of this fix. The value-less-action loading gap itself remains real and
independently confirmed (via direct SQL against the raw rule/action tables,
unaffected by the catalog_prefix bug) — this plan's scope and the 1,096/421
audit numbers are unchanged.

**Design correction during implementation:** the original approach widened
`load_recommendation_and_constraint_rules`'s return to a 3-tuple. That
method is monkeypatched with a bare `(rec, con)` 2-tuple stub across ~20
sites in the existing test suite, so the arity change broke 43 previously-
passing tests. Reverted: `load_recommendation_and_constraint_rules`'s
signature is untouched. Instead, `load_hiding_rules()` — the one method
every real caller already uses to get the complete hiding rule set —
internally calls `_load_value_rules()` a second time and merges in the
value-less-action subset before returning. This costs one extra `_load_
value_rules()` fetch wherever `load_hiding_rules()` is called (a real,
accepted perf tradeoff, consistent with this codebase's existing documented
double-fetch cost when `load_recommendation_rules()`/`load_constraint_
rules()` are each called independently) but requires zero call-site changes
anywhere and breaks zero existing tests.

## Context

While investigating a live conversation (order 50 APX NEXT radios, Houston TX,
destination country US) where `modelSelectionFrequencyBandMsl_astro`
("Frequency Band") was asked even after Product was answered
`"APX NEXT SINGLE BAND"`, traced the rule meant to hide it —
`"Associated rec rule to Hide Frequency Band for Single Band"` — and found it
**never loads into any rule bucket in this codebase at all.**

Root cause, pinned to one line in `CpqEngine._load_value_rules` (engine.py):

```python
for aid, _at, val, act_fn, set_type, _comments in acts:
    if act_fn != -1 or not val:
        continue
```

Any declarative action (`function_id=-1`, not script-backed) whose `value1`
is `NULL` is dropped unconditionally, before `set_type` is even inspected.
There is no code path that turns "no value" into a `HidingRule` — these
actions vanish silently. This is a rule **loading/classification** gap,
distinct from `docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md`'s
condition-*evaluation* gap (that fix is unrelated and, as of this writing,
not yet merged into `feature/msi_intent` — this plan's branch was cut from
the same tip, `f45a91c`, and does not depend on it).

## Scale — confirmed across every ingested catalog, not just APX Next

Queried the same shape (`function_id=-1 AND value1 IS NULL`, on a rule whose
`rule_type != 11`) against every catalog currently ingested:

| Catalog | Dropped actions | Distinct rules affected |
|---|---|---|
| APX Next (workspace 3) | 851 | 245 |
| Astro-APX (workspace 39004 — the live Frequency Band case) | 169 | 121 |
| SL3500e | 64 | 43 |
| SVX | 12 | 12 |
| **Total** | **1,096** | **421** |

This is generic, catalog-agnostic code — every catalog is affected in
proportion to how much its rule authors used this "value-less action" shape.

## The semantics are NOT uniform — split by `set_type`

Sampled real rule names in each `set_type` bucket (Astro-APX numbers shown;
the same split holds, proportionally, in the other 3 catalogs):

| `set_type` | Share | Real rule names | Confidence | Phase |
|---|---|---|---|---|
| 1, 3 | 105/169 (62%) | Overwhelmingly `"Hide..."` / `"Associated rec...Hide...if no values available"` — clean, consistent hide intent | **High** | **Phase 1 (this plan)** |
| 2 | 12/169 (7%) | Mixed: some `"Hide..."`, but also `"Show SIM Card Selection only for..."` (the *opposite* of hide), `"Set Encryption Type=\"\" if..."`, `"Set Submersible Delta T to Blank..."` (a third, "clear to blank" semantic) | Low — genuinely ambiguous per-rule | Deferred |
| -1 | 21/169 (12%) | Genuinely mixed: some `"Restrict NONE/blank if..."` (plausible "make required"), but also `"Restrict value of Astro System Id to 4 hexadecimal chars"`, `"Restrict Number Of Seats between 1 and 12"`, `"Validate Technical Contact Email Address"` — format/range validation, unrelated to hiding | Low — likely an unimplemented format/range-constraint feature entirely, not a hiding gap | Out of scope |

**Phase 1 scope, precisely**: `function_id=-1 AND value1 IS NULL AND set_type IN (1, 3) AND rule_type != 11` → load as a `HidingRule` with `hide=True`.

**Note on the original live example, corrected during implementation**: the
rule actually gating Frequency Band visibility in that scenario turned out
to be `"Hide Frequency Band for Single Band"` (`rule_type=11`) — a
DIFFERENT, similarly-named rule that already loads correctly today via
`load_hiding_rules()` and is entirely unaffected by this plan. Its own
condition value is authored as `"APX NEXT SINGLE"`, while the real menu
item_value for what a customer picks is `"APX NEXT SINGLE BAND"` — an
exact-match (`operator1=4`) mismatch, tracked as a separate follow-up, not
part of this fix. `"Associated rec rule to Hide Frequency Band for Single
Band"` (`rule_type=1`, the one this plan's fix actually loads) appears to be
a redundant companion rule with the identical condition-value issue — fixing
its loading alone does not resolve the live symptom, since the OTHER rule
already covers the same case and has the same unrelated value bug.

## Approach

`_load_value_rules` already iterates every action row (`acts`) per rule and
already extracts `cond_attr_id`, `cond_value`, `cond_operator` (or
`condition_script`) via the exact same logic `HidingRule` construction needs
elsewhere (`load_hiding_rules`, the `restrict_by_target`/`recommend_by_target`
branches). Adding a third bucket, `hide_targets: set[int]`, collected
alongside `restrict_by_target`/`recommend_by_target` in the same loop, and
turning it into `HidingRule` objects with the same `cond_attr_id`/
`cond_value`/`cond_operator`/`condition_script` this rule already resolved,
is a minimal, low-risk addition — no new fetch, no new join, reusing
data already in memory.

`_load_value_rules`'s return type grows from
`tuple[list[RecommendationRule], list[ConstraintRule], list[ValidationRule]]`
to a 4-tuple with `list[HidingRule]` appended (this internal, `_`-prefixed
method has exactly one caller family — its own 4 public wrappers — so
widening it is safe). All 4 public wrappers (`load_recommendation_and_
constraint_rules`, `load_validation_rules`, `load_recommendation_rules`,
`load_constraint_rules`) keep their EXISTING return arity unchanged,
discarding the new 4th element internally — see the "Design correction"
note above for why `load_recommendation_and_constraint_rules` specifically
must not grow its own arity (~20 existing test monkeypatches assume a bare
2-tuple). Instead, `load_hiding_rules()` itself calls `_load_value_rules()`
a second time at the end of its own body and merges the new list into what
it already built from `rule_type=11`, before returning — every real caller
of `load_hiding_rules()` gets the complete set with ZERO call-site changes
anywhere in `engine.py` or `ask_api.py`.

## Critical files

- `src/aryx/cpq/engine.py` — `_load_value_rules` (the classification loop,
  now a 4-tuple), `load_hiding_rules` (merges the 4th element in), and
  `load_recommendation_and_constraint_rules`/`load_recommendation_rules`/
  `load_constraint_rules`/`load_validation_rules` (discard the new 4th
  tuple element, arity otherwise unchanged).
- `src/aryx/api/ask_api.py` — no changes needed.
- No `state.py` changes — reuses the existing `HidingRule` dataclass as-is.

## Testing plan

1. Unit test replaying the real shape: a value-less declarative action
   (`function_id=-1`, `value1=None`, `set_type=3`) on a rule with a
   declarative condition — must produce a `HidingRule` with the right
   `target_attr_id`/`condition_attr_id`/`condition_value`.
2. Same for `set_type=1`.
3. Regression: `set_type=-1` (constraint) and non-empty-value declarative
   actions must be completely unaffected — same `ConstraintRule`/
   `RecommendationRule` output as before.
4. Regression: `set_type=2` and any action WITH a real value1 must still
   route through the existing recommend/restrict branches unchanged — this
   fix only ever touches the previously-`continue`d, value-less path.
5. End-to-end: replay the real Frequency-Band-for-Single-Band shape through
   `apply_hiding_rules` with a matching `filled` state and confirm the
   attribute is hidden (separately noting, in the test's own docstring, that
   the real catalog's own condition-value mismatch is a known, NOT-fixed-
   here follow-up — the test uses a condition value that DOES match, to
   isolate what this fix actually changes).
6. Full CPQ suite green in the container (bare local pytest works too now
   that `ARYX_RDB_DSN`/`ARYX_GRAPH_URL` can be pointed at the host-exposed
   `localhost:15432`/`localhost:6379` ports instead of the Docker-network-
   only `postgres`/`falkordb` hostnames).

## Verification

- Audit script (already written) re-run post-fix to confirm the previously-
  dropped 1,096 actions across 4 catalogs now load as `HidingRule`s (the
  `set_type in (1,3)` subset only — `set_type in (2,-1)` remain dropped,
  unchanged, exactly as scoped).
- Live re-run of the exact Houston/US scenario against the real Astro-APX
  catalog: confirm `modelSelectionFrequencyBandMsl_astro` now behaves
  correctly for a condition value that actually matches the real menu
  item_value (proving the LOADING fix), while separately confirming the
  known condition-value mismatch on the real authored rule is unchanged
  (not silently "fixed" by guessing a corrected value).
- Rebuild/redeploy, confirm no regression in existing hiding/recommendation/
  constraint behavior already covered by the existing test suite.
