# CPQ Same-Attribute Multi-Operator Condition Collision — Investigation (2026-08-05)

**Status: Safety net applied everywhere (2026-08-05); the underlying
combining-rule fix is still NOT implemented.**

Following a code-review finding, `_condition_has_operator_collision` (built
for the declarative `ValidationRule` fix) is now applied consistently at
**every** declarative rule-construction site — `load_hiding_rules`'s
`rule_type=11` path, and `_load_value_rules`'s `ConstraintRule`/
`RecommendationRule`/value-less-`HidingRule`/`ValidationRule` branches. A
rule hitting this collision is skipped and logged the same way everywhere,
rather than silently mis-evaluated in some rule types and guarded in
others. This closes the inconsistency the review flagged; it does **not**
implement the actual combining-rule fix below — that remains open.

**Correction to an earlier claim in this doc/PR**: the two rules used
earlier as illustrative examples of "already-shipped rules that might be
mis-evaluating right now" — `"Do not allow Smartlocate to be deselected
when Smartvideo or SmartEvidence selected"` and `"Allow Multi-Code Plug
Programming only when Enhancement Level is selected"` — were re-checked
after applying the guard everywhere and turned out to be **script-backed**
`ConstraintRule`s in this catalog (their allowed-values come from a BML
script attached to the action, not from `evaluate_declarative_conditions`;
`condition_script`/`conditions` are both unset on these instances). They
were never actually at risk from this specific bug. The underlying
collision is still real and still confirmed at 80 rules catalog-wide
(e.g. `"Restrict Number Of Seats between 1 and 12"`, a genuinely
declarative rule) — only the choice of illustrative example was wrong,
not the finding itself.

**Standing rule for this doc, same as every other plan this session: do
not implement the combining-rule fix below until the semantics are
confirmed against real data with no remaining ambiguity.** The exclusion
guard above is a safety net, not a fix — excluded rules still don't
evaluate their real condition; they just no longer do so incorrectly.

## Discovery context

Surfaced while testing the declarative-`ValidationRule` extension
(`docs/CPQ_CONDITIONAL_REQUIRED_RULE_PLAN_2026_08_05.md`): a synthetic test
for `"Restrict Number Of Seats between 1 and 12"` failed because
`evaluate_declarative_conditions` cannot correctly represent that rule's
real condition shape — two rows on the *same* attribute
(`numberOfSeats_astro < 1`, operator `1`; `numberOfSeats_astro > 12`,
operator `5`).

## The bug, precisely

`evaluate_declarative_conditions` (`bml.py`) groups a rule's condition rows
by `attr_id`; rows sharing an `attr_id` are treated as one OR-group and
**assumed to share a single operator — the first row's**:

```python
for attr_id, value, operator in conditions:
    if attr_id not in by_attr:
        order.append(attr_id)
        op_by_attr[attr_id] = operator   # <-- first row's operator wins
    by_attr.setdefault(attr_id, []).append(value)
```

For same-attribute rows that all share one equality/inequality operator
(the case this grouping was actually designed for — e.g. multiple `<>`
exclusions, or an OR-list of acceptable values), this is correct. For rows
with *different* operators on the same attribute (a genuine range check:
"reject if `< 1` OR `> 12`"), it silently drops every row after the first:
`op_by_attr[attr_id]` never updates past the first-seen operator, and
`_operator_hit`'s numeric branch only reads `expected_values[0]` — so only
`< 1` is ever checked; `> 12` is never evaluated at all.

## Scale — confirmed catalog-wide, not isolated to the new work

Grouped every real rule's condition rows by `(rule_id, attribute_id)` and
counted rules where any attribute has 2+ distinct `operator1` values:

| Catalog | Total rules with any condition | Rules with a same-attr/multi-operator collision |
|---|---|---|
| Astro-APX (workspace 39004) | 654 | 23 |
| APX Next (workspace 3) | 1,299 | 46 |
| SL3500e | 364 | 4 |
| SVX | 102 | 7 |
| **Total** | **2,419** | **80** |

Breaking the 80 down by which rule type they'd already load as:

| `rule_type` | Astro-APX | APX Next | SL3500e | SVX | Meaning |
|---|---|---|---|---|---|
| `11` (Hiding) | 1 | 2 | 1 | 2 | **6 already-shipped `HidingRule`s** (today's op7/8/valueless-hide work) |
| `1`/`2` (value rules) | 22 | 44 | 3 | 5 | **74 rows** — 15 are the new `ValidationRule` candidates (excluded per the sibling plan doc); the remaining **59 are already-shipped `ConstraintRule`/`RecommendationRule`s** from this morning's operator-1/7/8 fix |

**This means up to 65 real, already-deployed rules (6 hiding + 59
constraint/recommendation) may be silently mis-evaluating a same-attribute
range or multi-condition check right now**, independent of anything new
being scoped today. This is the highest-priority open item from today's
work — it affects live, shipped behavior, not a deferred feature.

## What's NOT yet known — this is where the investigation continues

1. **Does every same-attribute/multi-operator collision represent a
   genuine "range check" (OR the violating bounds together)?** The one
   confirmed real example (`"between 1 and 12"`) is a range. Not yet
   checked whether all 80 are this same shape, or whether some are a
   different pattern (e.g. same attribute checked with `=` in one row and
   `<>` in another — which would need different combining logic, not a
   simple OR-the-bounds range).
2. **For rows already loaded as `HidingRule`/`ConstraintRule`/
   `RecommendationRule` (65 of the 80), what does the current (wrong)
   behavior actually produce vs. what the correct behavior would produce?**
   Needs the same "replay 3–4 real examples, compare before/after" rigor
   every other fix this session used before touching code.
3. **Does the fix belong in `evaluate_declarative_conditions` alone, or
   does `_operator_hit`'s numeric branch also need to accept multiple
   expected values (not just `expected_values[0]`) for this to work at
   all?** Both look implicated from the one example checked so far — needs
   confirming against a wider sample before designing a fix.
4. **Is "OR the bounds together" even always the right combining rule?**
   For a genuine range ("must be between 1 and 12"), OR-ing "violates
   lower bound" with "violates upper bound" is correct for a *rejection*
   condition. Whether that generalizes to every one of the 80 rules, or
   whether some need AND semantics instead, is not yet checked.

## Progress — two confirmed combining patterns, ~76% of cases

Grouped all 80 collisions by their exact operator-pair signature (e.g.
`{7,8}`, `{1,4}`) and checked whether one universal combining rule
("same-operator rows OR together, different operators AND together")
holds. **It does not hold universally** — confirmed via a direct
counter-example: `"Restrict Number Of Seats between 1 and 12"` (`op1 <1`,
`op5 >12`) needs OR (`< 1 OR > 12`; AND would be logically impossible,
satisfiable by no value), while `"Do not allow Smartlocate to be
deselected when Smartvideo or SmartEvidence selected"` (`op7`×2, `op8`×1)
needs the opposite: same-operator rows (`op7`+`op7`) OR together, then AND
with the `op8` row. Same shape, opposite correct combination — no single
rule covers both.

Refining further, by operator-pair signature, found two patterns that DO
hold consistently within their own scope:

| Pattern | Operator-pairs covered | Occurrences | Confirmed rule |
|---|---|---|---|
| **Membership grouping**: group same-attribute rows BY operator; OR within each operator's own group; AND the per-operator group results together | `{7,8}` | 36 | `op7` rows (any selected) OR together; the `op8` row(s) AND in as "and this NOT selected" — matches `"Do not allow Smartlocate..."`, `"Restrict Provisioning Federal Bundle if Core Bundle is not Selected"`, and 2 other independently-authored rules checked |
| **Numeric range + blank-check**: an `op4` row with an EMPTY/`None` value1 is a special "is blank" clause, always OR'd in; the remaining numeric operators (`1`/`2`/`5` — `<`/`<=`/`>`) on the same attribute OR together (any bound violated) | `{1,4}`, `{2,4}`, `{1,4,5}`, `{2,4,5}` | 10+6+3+6 = 25 | `"Require Qty of SVX if Add SVX is checked"` (blank OR `<1`), `"Restrict Number Of Seats between 1 and 12"` (`<1` OR `>12`, blank row also present) |

**Together these two patterns cover 61/80 (76%) of all collisions** with
real, cross-referenced confirmation — the same bar as every operator
finding shipped this session.

## What's still genuinely unresolved (~24%, 19 rules)

Checked one example from the next-largest remaining group, `{3,4}`
(11 occurrences) — `"Allow 'Radio FED TA FCC Trigger'... only for Federal
non-US customers"` — and it does not fit either confirmed pattern. Its
condition spans **4 rows across 3 different attributes** (country, customer
type, and what looks like another blank-check), mixing what appear to be
blank-checks (`op3`/`op4` with `None` values) with real value checks
(`country == US`, `customerType <> FEDERAL`) in a way that would need
DIFFERENT-ATTRIBUTE rows to combine via OR for the visible message ("only
for Federal non-US customers") to make sense — contradicting the
already-confirmed, already-shipped "different attributes AND together"
convention this session's earlier work relies on everywhere else.

This is genuinely complex enough that it should not be force-fit into a
quick pattern match. Options once this doc is revisited:
1. Treat `op4`/`op3` rows with an empty value1 as a distinct, third
   category ("presence/absence check") separate from both the membership
   pattern and the numeric-range pattern, and re-derive the combining rule
   for the remaining `{3,4}`/`{2,3,5}`/`{4,7}`/`{2,6}` groups (19 rows)
   with that distinction factored out first.
2. Accept that some rules in this remainder may need per-rule
   confirmation rather than a generic structural rule — same "never guess"
   boundary as the deferred `set_type=2` bucket.

**No implementation should touch `evaluate_declarative_conditions`'s
grouping logic until at least the confirmed 76% is formalized AND a
decision is made on how to handle (or explicitly continue excluding) the
remaining 24%.**

## Next steps

1. ~~Pull full condition rows + rule names for a representative sample~~ —
   **done** for the two largest groups (`{7,8}`, and the numeric-range +
   blank-check family); see "Progress" above.
2. **Remaining**: resolve the `{3,4}` group (11 occurrences, the
   next-largest) and the smaller `{2,3,5}`/`{4,7}`/`{2,6}` groups
   (19 rows total) — likely needs the "presence/absence check" recategorization
   noted above before a combining rule can even be tested, plus checking
   whether cross-attribute OR (not just same-attribute) is a real,
   distinct third phenomenon here, separate from everything confirmed so
   far.
3. Once (or if) the remaining 24% resolves to the same ~90%+ confirmation
   bar as the other operator findings this session, design the fix to
   `evaluate_declarative_conditions`/`_operator_hit`, write it up as its
   own section here, and get explicit sign-off before touching code —
   this function is relied on by every rule type in every catalog, so the
   blast radius of getting it wrong is larger than anything shipped so
   far today.
4. If the remaining 24% does not resolve to a confident generic rule,
   the honest fallback is documented in "What's still genuinely
   unresolved" above: implement the fix for the confirmed 76% only, and
   continue excluding the rest via the same structural collision check
   already used for the 15 `ValidationRule` candidates, rather than guess.
