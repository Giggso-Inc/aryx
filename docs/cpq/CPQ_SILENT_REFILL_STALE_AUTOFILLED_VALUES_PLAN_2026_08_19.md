# CPQ Silent Re-fill of Stale Auto-Filled Values — Fix Plan

**Date:** 2026-08-19
**Status:** Planned, not yet implemented
**Severity:** Medium (confusing UX — the customer is asked to "fix" something they
never chose in the first place; not data-corrupting, since the current re-ask flow
always converges to a legal value)
**Discovered via:** live transcript — configuring APX NEXT for USA, after answering
Hardware Version then Product ("APX NEXT Enhanced"), the system said "Before
finishing — **Package Type** is no longer valid given your other selections" and
re-asked it, narrowed to a single option ("Single Pack Clamshell").

## Problem

`packingPackageType_astro` (Package Type) is on `_BLIND_FILL_RISK_ACCEPTED_VNS`
(`engine.py:1712-1752`) — a required attribute the system is explicitly allowed to
auto-fill with a guessed value (`valid_opts[0]`, tagged `filled_source =
"default_first_available"`) before the customer has answered attributes whose
constraints would narrow it correctly. When a later answer (here, Product) narrows
Package Type's legal values and the earlier guess falls outside the new set,
`_reask_stale_constraint_violations` (`ask_api.py:2011-2120`) — the proactive check
that runs right before a "Configuration complete" message — detects the staleness,
**clears the value and puts it back in `pending_variables`**, forcing the customer
to answer a question about an attribute they never actually chose a value for in the
first place.

The customer experience is: pick Product → get told something else is now "invalid"
and made to re-decide it — even though, in this case, only ONE legal value remains
(so their "decision" is forced and uninformative), and in general, the value being
flagged was never their choice to begin with.

## Root cause

Two mechanisms already exist to keep a blind-filled value fresh, but both are
*reactive*, not *preventive*, and the last one converts staleness into a forced
customer re-ask regardless of whether the original fill was ever a real decision:

1. **Same-turn self-correction** (`engine.py:8976-8999`): a value whose
   `filled_source == "default_first_available"` is re-opened and silently
   re-evaluated on every pass of `evaluate_rules_loop`, not locked in — this already
   works silently within the turn(s) where `auto_fill` itself re-runs and the newly
   narrowed `constrained_opts` are available in time.
2. **Last-resort, pre-completion check** (`_reask_stale_constraint_violations` →
   `bom_gate.recheck_constraints`): if a stale value slips past (1) — e.g. because
   the real governing rule is script/Tier-2 (LLM) evaluated and resolves later than
   `auto_fill`'s own synchronous check, per `_auto_resolve_singleton_pending`'s own
   docstring (`ask_api.py:1938-2008`, "can resolve to a single legal value too late
   for `auto_fill()`'s own check to catch it") — this function catches it. But
   **its only response, for every stale value regardless of origin, is to clear it
   and re-queue it as a pending question** (`ask_api.py:2100-2120`). It does not
   distinguish "the customer explicitly chose this and it's now invalid" (a real
   re-ask is the right call) from "the engine guessed this with no customer input
   at all" (silently re-guessing is strictly better than bothering the customer with
   a question about their own prior non-decision).

Neither mechanism, nor `auto_fill` itself, currently orders attribute resolution by
dependency (there is no use of the existing `_dependency_ordered_keys`/
`_attribute_depth_ranks` condition→target graph, `engine.py:12011-12079`/`11839-
11887`, to defer blind-filling a downstream attribute — e.g. Package Type — until
an upstream one it depends on — e.g. Product, via the real two-hop chain
`productSelectionProduct_all` → `additionalSystemEnhancementFeatureType_astro` →
`packingPackageType_astro`, confirmed in `docs/CPQ_APX_NEXT_RULE_CATALOG.md` lines
1070-1676 — has already been answered). So a guess-now-correct-later pattern is
structurally unavoidable for this class of attribute; the fix target is making the
*correction* invisible when the original fill was never the customer's decision,
not eliminating every guess.

## Fix design

**In scope: `_reask_stale_constraint_violations`'s stale-but-fixable branch**
(`ask_api.py`, the branch handling `stale` violations with `v.allowed` non-empty —
i.e., NOT the zero-legal-options `conflicted` branch, which is a genuine rule
conflict and must stay a hard re-ask/report regardless of origin).

For each stale violation, check `session.filled_source.get(v.attr.variable_name)`:

- **`== "user"`** (or any other tag meaning the customer explicitly chose this
  value): **unchanged** — clear and re-queue as a real pending question, exactly as
  today. A customer's own explicit choice going stale is genuinely their decision to
  re-make; silently overriding it would be a real regression (a config no longer
  matching what they think they selected).
- **anything else** (`"default"`, `"default_first_available"`, `"governed_source"`
  variants, cascade/recommendation-sourced, etc. — i.e., every tag meaning the
  engine picked this, not the customer): **silently re-fill** with a fresh legal
  value using the SAME selection policy `auto_fill` already uses for that attribute
  (first-available from the current `allowed`/`constrained_opts` set, single- and
  multi-select handled the same way `auto_fill`'s own branches do) — never clear
  into `pending_variables`, never surface a "no longer valid" message for that
  attribute.

**Transparency, not silence-with-no-trace**: when one or more attributes are
silently re-filled this way, append a brief, non-blocking note to whatever response
is otherwise returned (the "Configuration complete" message, or the next real
pending question if other GENUINE re-asks are also needed this turn) — e.g. "*(Note:
Package Type was automatically updated to **Single Pack Clamshell** based on your
selections.)*" This mirrors the existing convention of always surfacing auto-applied
changes (recommendation-application banners, `**Attr** → value` transparency lines
elsewhere in this file) rather than changing session state invisibly. It is NOT a
pending question — the turn proceeds to completion (or to the next genuine pending
attr) without waiting for any reply about this attribute.

**Mixed case**: if a turn has both a genuinely-conflicted attribute (zero legal
options) or a user-sourced stale attribute AND an auto-sourced stale attribute, the
auto-sourced one is silently fixed (with its transparency note appended) while the
user-sourced/conflicted one still drives the existing re-ask/conflict-report flow —
these are independent, per-attribute decisions, not an all-or-nothing gate.

## Why this direction over alternatives

- **Rejected: dependency-order `auto_fill` to defer Package-Type-style attributes
  until their real upstream dependency is answered.** This would need the
  condition→target graph (`_dependency_ordered_keys`/`_attribute_depth_ranks`) wired
  into `auto_fill`'s own per-pass attribute loop — a much larger, riskier change
  touching the core fill-ordering logic for every blind-fillable attribute, not just
  the one class of bug reported here. It also can't fully eliminate the problem:
  script/Tier-2 (LLM) constraints (per `_auto_resolve_singleton_pending`'s own
  documented gap) resolve asynchronously and can still narrow AFTER any ordering
  pass completes. Silently re-correcting the *result* is a smaller, more robust fix
  than trying to perfectly *order* every possible guess to avoid ever needing
  correction.
- **Rejected: make ALL stale values (including user-sourced) silently re-fill.**
  Explicitly rejected — a customer who chose a value and had it invalidated by a
  later choice deserves to know and re-decide; silently substituting a different
  real business choice on their behalf (e.g. a customer explicitly picked "DEMO KIT
  CASE" and a later selection invalidates it) would hide a real, customer-relevant
  change from them.
- **Rejected: fully silent re-fill with no transparency note.** Rejected for the
  same reason `auto_fill`'s own responses already show `**Attr** → value` — a
  config detail changing without any visible trace anywhere in the conversation
  would make the final summary/payload harder to trust and audit.

## Risk assessment

- **Blast radius**: scoped to `_reask_stale_constraint_violations`'s one branch —
  the `conflicted` (zero-legal-options) branch, `_reask_confirmed_data_table_conflict`,
  `find_missing_required_fields`, and every OTHER call site in this file are
  untouched.
- **Filled-source tagging completeness**: the "anything else means auto-filled"
  policy depends on `session.filled_source` being reliably tagged for every fill
  path (`user`, `default`, `default_first_available`, `governed_source` variants,
  cascade, recommendation, etc.) — need to enumerate the real set of tags this
  codebase uses (via `apply_answer`/`auto_fill`/cascade code) before implementing,
  to avoid accidentally treating an untagged/`None` source as "safe to silently
  override" when it might actually mean "unknown, assume user" for safety. Default
  stance if a tag is ambiguous or missing: treat as user-sourced (re-ask), never
  silently override on uncertain provenance.
- **Multi-select case**: silently re-filling a multi-select's now-partially-invalid
  list (keep the still-valid subset, or replace entirely) needs to mirror
  `recheck_constraints`'s existing multi-select stale handling (`ask_api.py:1959-
  1970`, already keeps the still-valid subset) — extending the "keep valid subset"
  behavior silently rather than requeuing, same distinction as the single-select
  case.
- **Confirm-time BOM gate** (`bom_gate.recheck_constraints`'s OTHER caller, the
  authoritative hard backstop at actual submission): deliberately left OUT of this
  fix's initial scope. It exists specifically as the last-resort, cannot-be-skipped
  gate before a real order is submitted; changing its behavior to silently rewrite
  data at the moment of submission is a materially different risk profile than doing
  so one turn earlier during ordinary conversation. Flagged as a candidate follow-up
  if this fix's pattern proves out, not bundled in.
- **No regression to the zero-legal-options conflict path**: the `conflicted` branch
  (real rule conflicts) is unchanged — a customer must still be told and asked to
  change an earlier selection when the active rules genuinely leave nothing valid,
  regardless of origin, since there is no legal value to silently substitute.

## Verify before implementing

- Live-reproduce the exact reported scenario on the current code, confirming the
  "Before finishing — Package Type is no longer valid" re-ask still fires today
  (baseline).
- After the fix: replay the same scenario — confirm the turn instead proceeds
  straight to "Configuration complete" (or the next real pending question) with
  Package Type silently set to "Single Pack Clamshell" and a transparency note
  present, no pending question about Package Type.
- Confirm a genuinely user-chosen value going stale (construct a case where
  `filled_source == "user"`) still triggers the existing clear-and-re-ask flow,
  completely unchanged.
- Confirm a genuine rule conflict (constructed so `v.allowed` is empty) still
  reports the "Rule conflict detected" message unchanged, regardless of the
  conflicted attribute's origin.
- Multi-select case: an auto-filled multi-select value that's now partially stale
  keeps its still-valid subset silently (no re-ask), matching single-select's
  intent.
- Mixed-turn case: one auto-sourced stale attr + one user-sourced stale attr in the
  same turn — confirm the auto-sourced one is silently fixed (with its note) while
  the user-sourced one still drives a real re-ask, in the same response.
- Full CPQ regression suite re-run; any failure/timeout individually confirmed
  pre-existing via the established `git worktree` comparison method.

## Files expected to change

- `src/aryx/api/ask_api.py` — `_reask_stale_constraint_violations`'s stale-but-fixable
  branch (~lines 1957-2013): branch on `filled_source` per attribute; silent-refill
  path reusing `auto_fill`'s own single/multi selection policy instead of clearing
  into `pending_variables`; append the transparency note to whatever response the
  turn ultimately returns.
- Possibly a small shared helper (e.g. `_pick_legal_value_for_stale_attr`) if the
  "first-available from allowed set" logic needs to be reused identically for both
  single- and multi-select, to avoid duplicating `auto_fill`'s own selection
  mechanics inline in this function.
- New test file (e.g. `tests/test_cpq_silent_refill_stale_autofilled_2026_08_19.py`)
  covering the "Verify before implementing" scenarios above as committed regression
  tests.
