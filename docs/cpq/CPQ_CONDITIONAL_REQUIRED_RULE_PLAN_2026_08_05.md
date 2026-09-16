# CPQ Declarative Validation-Message Rules ("set_type=-1, no value") — Scope (2026-08-05)

**Status: Shipped (2026-08-05).** Implemented with the 15-rule
same-attribute-operator-collision exclusion from the Addendum below (the
50 non-colliding rules load correctly; the 15 stay excluded pending
`docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md`). Live-
verified against the real Astro-APX catalog: `load_validation_rules`
now returns real declarative rules (previously always 0), and the
confirmed collision case (`"Restrict Number Of Seats between 1 and 12"`)
is confirmed absent, as intended.

**Standing rule for this doc: do not implement any part of it while a
listed ambiguity is unresolved.** This plan went through two rounds of
open questions (see "Open questions" below) — both are now resolved
against real, cross-catalog data, with no guessing involved. That is the
bar every other fix this session met before shipping (operator `3`,
operators `7`/`8`, the value-less hiding-action gap): a classification
signal confirmed against real data with no remaining ambiguity. If any
future edit to this plan reopens a question, implementation must pause
again until it's answered the same way — never by picking the
most-likely-looking interpretation.

## Revision note — this doc supersedes its own first draft

The first version of this doc scoped a brand-new `RequiredRule` mechanism
for a 7-row "make required" sub-bucket, based on the hypothesis that
`"NONE"`/`"blank"` in these rule names meant "the target attribute must not
be left empty." Re-investigating the FULL `set_type=-1` bucket (not just
those 7 rows) surfaced a better-fitting, already-existing mechanism that
covers nearly all of it at once — see below. The `RequiredRule` design is
retired in favor of the design in this revision. Nothing from the first
draft was implemented, so there is nothing to migrate away from.

## Context

Follow-up to `docs/CPQ_VALUELESS_HIDE_ACTION_LOADING_GAP_PLAN_2026_08_05.md`'s
deferred/out-of-scope buckets. That plan's own audit flagged `set_type=-1`
(21/169 value-less actions in Astro-APX) as "genuinely mixed... likely an
unimplemented format/range-constraint feature."

## The corrected finding: this is (almost) all one thing — declarative validation messages

Pulling the full `bm_config_rule_action` row for every `set_type=-1`,
value-less action (not just the `value1`/`comments` fields checked before)
shows every one of these rows carries a `comments` field — and for the
large majority, that comment is a real, human-authored, catalog-specific
message, not boilerplate:

| Rule | Message (`comments`) |
|---|---|
| `Restrict Number Of Seats between 1 and 12` | "Number Of Seats must be between 1 and 12" |
| `Restrict value of Astro System Id to 4 hexadecimal chars` | "Invalid ASTRO System ID: Must be 4 hexadecimal characters (0-9 and A-F). Letters must be upper-case." |
| `Restrict blank for Sales Approver if Is provisioning = yes` | "Input required" |
| `Restrict Custom Application Service years to the same no. of years` | "When 2 or more application services are selected, they must have the same duration." (+ "Invalid selection" on 3 sibling targets) |
| `Restrict Blank value for DMS Duration(Years) if...` | "The user must select Duration if Service Type=\"ESSENTIAL\" OR \"ESSENTIAL WITH ACCIDENTAL DAMAGE\"" |
| `Prevent None Selection APXNEXT` | "Make a selection" |
| `Restrict NONE if Add VX650 is checked` (×3 targets) | "Invalid selection" |
| `Require Qty of SVX if Add SVX is checked Next and N70` | "Enter quantity" |
| `Spares : Constrain Quantity for Spares If Include A Spare? is selected` | "Please enter a valid Quantity" |
| `Constraint Qty of XVN500 Remote speaker mic>0 if...` | "Qty entered must be greater than 0 and should match the total qty of APX Next XN devices you plan to order." |
| `NEW Constrain Wireless carrier` | "Current selection is invalid, please change it to a valid option." |
| `PD : Constraint System ID for Astro Portables` | "Invalid System Key ID: Must be 1-4 hexadecimal characters (0-9 and A-F)." |
| `Restrict Astro System Id value to have at least 1 non-zero char` | "Astro System Id cannot be all zeros" |

**This is not a new rule shape.** `ValidationRule` (`state.py`) already
exists for exactly this concept — "condition true → show this message, no
value change" — and its own docstring already anticipated this exact gap:

> *"a message-only action (function_id=-1, empty value1, but a real
> human-authored `comments` string) is neither a hide, a set, nor a
> restrict... Every confirmed real case gates on a script condition
> (e.g. 'Constrain video devices'), so scoped to that for now — **a
> declarative-condition version would need separate confirmation before
> being added here**."* — `engine.py`, `_load_value_rules`

That confirmation is what this investigation provides. The ONLY thing
different about this batch is that the condition is declarative
(`bm_config_rule_input` rows, e.g. the "between 1 and 12" rule's own
condition literally uses operators `1`/`5` — `<`/`>`, confirmed and shipped
earlier today) rather than a BML script — everything else (the message, the
target, the "no value change" semantics) is identical to the
already-implemented, already-shipped script-gated case.

## Scale — confirmed across all 4 catalogs

| Catalog | Total `set_type=-1`, value-less rows | Has a real comment (candidate `ValidationRule`) | No comment (nothing to build from) |
|---|---|---|---|
| Astro-APX (workspace 39004) | 21 | 19 (90%) | 2 |
| APX Next (workspace 3) | 107 | 97 (91%) | 10 |
| SL3500e | 16 | 16 (100%) | 0 |
| SVX | 6 | 6 (100%) | 0 |
| **Total** | **150** | **138 (92%)** | **12** |

The split is consistent across every catalog, not just Astro-APX — strong
evidence this is one uniform, catalog-agnostic gap, not a coincidence in
one dataset.

**The 2 no-comment Astro-APX rows** (`"Validate Technical Contact Email
Address"`, `"Constrain Carrier Selection Maximum Based on Dual Sim
Toggle"`) — and the 10 in APX Next — have nothing to surface: no message,
no explicit bounds/pattern anywhere in the row. These stay out of scope,
same reasoning as every other "nothing to build from" case this session:
never guess a validation message or a numeric bound that isn't actually
present in the data.

## Addendum (same day) — 15 of these rules excluded pending a separate fix

While implementing, testing surfaced a real, additional gap: some of these
138 candidate rows condition on the SAME attribute via *two rows with
different operators* — e.g. `"Restrict Number Of Seats between 1 and 12"`
carries one condition row `numberOfSeats_astro < 1` (operator `1`) and a
second `numberOfSeats_astro > 12` (operator `5`) on the identical
attribute. `evaluate_declarative_conditions` groups same-attribute rows
under a single shared operator (the first row's) and `_operator_hit`'s
numeric path only reads the first expected value — so the second bound is
silently dropped. Loading these as `ValidationRule`s as-is would not be
"not yet implemented," it would be **actively wrong** (e.g. only ever
checking `< 1`, never `> 12`).

Quantified by grouping each candidate rule's own conditions by
`attribute_id` and checking for 2+ distinct `operator1` values on the same
attribute — a purely structural signal, no rule names involved:

| Catalog | Candidate rules (distinct, this bucket) | Collide (same-attr, different operators) |
|---|---|---|
| Astro-APX | 14 | 4 |
| APX Next | 30 | 8 |
| SL3500e | 15 | 1 |
| SVX | 6 | 2 |
| **Total** | **65** | **15 (~23%)** |

(65 distinct rules here vs. 138 action rows above: several rules target
multiple attributes from one rule, e.g. "Restrict Custom Application
Service years..." has 4 targets under 1 rule — same rule counted once
here, 4 times in the action-row table above.)

**Decision**: ship the 50 non-colliding rules now; explicitly exclude the
15 colliding ones via the same structural check
(`_condition_has_operator_collision`, grouping `conditions` by `attr_id`
and checking for 2+ distinct operators) rather than block everything on
fixing the underlying evaluator gap. The 15 stay exactly as dropped as
they are today — no regression, just not yet gained.

**This same collision pattern is not unique to this bucket** — it exists
catalog-wide, including in already-shipped `HidingRule`/`ConstraintRule`/
`RecommendationRule` instances from this morning's operator work. That is
a separate, higher-priority, already-live issue, scoped in
`docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md`.

## Proposed design

1. **`ValidationRule` gains the same condition fields every other rule
   type already has**: `condition_attr_id`, `condition_value`,
   `condition_operator`, `conditions` (mirroring `HidingRule`), alongside
   its existing `condition_script`. Exactly one of `condition_script` /
   `conditions` is set per instance, same convention as the other three
   rule types.
2. **Loading** (`_load_value_rules`, `engine.py`): the existing
   message-only detection loop —
   ```python
   if (act_fn == -1 and not val and comments
           and comments.strip().lower() != "system recommendation"):
   ```
   — currently sits inside `if condition_script is not None:`. Move it
   outside that guard so it also runs when the rule's condition is purely
   declarative (`inp_list` present, `condition_script is None`), populating
   the new `conditions`/`condition_attr_id`/`condition_value`/
   `condition_operator` fields from the same `inp_list` the constraint/
   recommend branches already use.
3. **No new apply function needed — confirmed location.**
   `CpqEngine.apply_validation_rules` (`engine.py`, ~line 3728) is the sole
   consumer: for every rule it unconditionally calls
   `bml_eval.condition_holds(rule.condition_script, filled)` and surfaces
   `rule.message` when that returns `True`. This would break on a
   declarative-only rule (`condition_script is None`) as-is. The fix:
   branch the same way `apply_hiding_rules` already does — when
   `condition_script` is set, evaluate it via `bml_eval.condition_holds`
   (unchanged); when `conditions` is set instead, evaluate via the existing
   `evaluate_declarative_conditions` (shipped earlier today) and surface
   the message only when it resolves to definitively `True` — same D2
   "never guess on unknown" contract this function already documents for
   the script case.
4. **✅ Resolved**: is `"System recommendation"` the *only* boilerplate
   default comment to exclude across the declarative-condition path too?
   Scanned all 138 candidate comments (22 distinct strings) across all 4
   catalogs — no other content-free placeholder exists. The existing
   single exclusion check is sufficient; see "Open questions" below for
   the full reasoning.

## Critical files (if this proceeds)

- `src/aryx/cpq/state.py` — extend `ValidationRule` with the condition
  fields.
- `src/aryx/cpq/engine.py` — `_load_value_rules` (move the message-only
  branch outside the `condition_script is not None` guard, and skip
  construction when `_condition_has_operator_collision(inp_list)` is
  True — see Addendum), and whichever function currently evaluates a
  `ValidationRule`'s truth value (extend it to branch on `conditions` vs
  `condition_script`, same pattern as `apply_hiding_rules`).
- No changes needed to `ask_api.py`/`bom_gate.py` — `ValidationRule` is
  already wired into the turn flow for the script-gated case; this only
  widens which rows populate the same list.

## Open questions — all resolved during scoping

1. ~~**Boilerplate-comment scan**~~ — **Resolved.** Scanned all 138
   comments across all 4 catalogs (22 distinct strings). No content-free
   placeholder besides `"system recommendation"` exists. Two strings repeat
   often (`"Invalid selection"` ×45, `"Input required"` ×12), but unlike
   `"system recommendation"` these are still genuinely informative —
   generic wording reused across similarly-shaped rules, not BM-inserted
   filler that says nothing about the actual problem. The existing single
   exclusion check is sufficient as-is; no change needed there.
2. ~~**Consuming function**~~ — **Resolved** (see design item 3):
   `apply_validation_rules`, confirmed by reading the code directly.

**No blocking questions remain for this plan.** Approved for implementation
(2026-08-05).

## Impact analysis

**This is a real, active enforcement mechanism, not a passive warning.**
`apply_validation_rules`'s one call site (`ask_api.py`, ~line 7372) fires
right after a customer answers a pending question: if the matching
`ValidationRule`'s condition holds, the code **deletes the just-accepted
answer from session state** and re-prompts with `"⚠️ {message}"` — a real
rejection with rollback, not a note sitting next to an accepted value.
This exact mechanism is already live today for the 1 script-gated case in
this catalog family; this change only widens which rows can populate the
same list and trigger the same existing code path.

**What changes**: 138 rules across all 4 catalogs, currently 100% silent
no-ops (their conditions have never once been evaluated, confirmed via the
audit above), start actively firing. Examples:

| Today (silently accepted) | After this fix |
|---|---|
| 13 seats entered | Rejected: *"Number Of Seats must be between 1 and 12"*, re-prompted |
| Astro System ID all zeros / wrong length | Rejected with the specific format message |
| Sales Approver left blank while provisioning=yes | Rejected: *"Input required"* |
| Two application services with different durations | Rejected: *"...they must have the same duration."* |
| Various VX650/RSM combinations | Rejected: *"Invalid selection"* |

**Direction of the change**: these 138 checks are today pure dead code —
real, catalog-authored business rules that have never once fired. This
converges Aryx's behavior with what the source BigMachines system was
designed to enforce, the same category of fix as operator `3`, operators
`7`/`8`, and the value-less hiding-action gap: turning on dormant logic,
never inventing new logic.

**Real risk — same shape as the op7/op8 rollout**: because these checks
have been silent, any live conversation flow that happens to depend on the
current permissive behavior could hit a rejection it never hit before —
e.g. a flow that previously entered 13 seats and had it accepted will now
bounce back. That is the correctness fix working as intended, but it is a
genuine behavior-change surface worth watching in live traffic after
deploy, not a risk-free no-op.

**Scope limits** (pre-existing, not introduced by this change):
- Only the one call site fires this check (answering a pending question
  directly). It does not retroactively re-validate values already filled
  before this fix ships, and it is not wired into final BOM/payload
  submission (`bom_gate.py`) — a value reaching `filled` through a
  different path (e.g. a change-request/pending-change flow) can still
  slip through uncaught, the same limit the script-gated case already has
  today.
- Only fires when `bml_eval` is available — always true in real traffic,
  same as today.

## Testing plan

1. Unit tests replaying 3–4 of the confirmed real shapes (Number Of Seats
   range, Astro System Id format, Sales Approver required, Custom
   Application Service years cross-field) as synthetic declarative
   `ValidationRule`s, confirming the message surfaces when the condition
   holds and does not when it doesn't.
2. Regression: existing script-gated `ValidationRule` behavior (e.g.
   "Constrain video devices") completely unchanged.
3. Regression: the 12 no-comment/boilerplate-only rows across all 4
   catalogs continue to produce nothing, exactly as today.
4. Full CPQ suite green; live re-verification against real catalog data
   (same discipline as the value-less-hide-action fix) showing the
   `ValidationRule` count increasing by roughly 138 across the 4 catalogs
   post-fix.
