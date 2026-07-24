# CPQ User-Value Precedence in Rule Evaluation — Plan

**Status:** Proposed — root cause fully traced against a real catalog,
design scoped, not yet implemented.
**Date:** 2026-07-23
**Depends on:** `docs/CPQ_CASCADE_CONVERSATION_PLAN.md` (STEP 6 — cascade
on change) — this plan hardens that step's existing guarantee, it does
not redesign it.

---

## 1. Problem statement (client language)

> When the client explicitly changes an attribute to a specific value,
> that value must be preferred over any other rule that would otherwise
> reassign it — run the full rule-evaluation pass as normal, but treat
> the value the client just selected as fixed input, not something a
> recommendation rule gets to override. Every other attribute's rules
> should still evaluate normally against that selected value — cascading
> effects are unaffected, only the selected attribute itself is
> protected from being silently swapped back.

## 2. Real, live-verified failure (not hypothetical)

Real transcript, SVX Video Remote Speaker Microphone quote (workspace 14):

```
what are the billing Option available?
→ Up Front / Monthly / Quarterly / Annual / Immediate / Monthly in Arrears

change the Biling Option to Annual
→ "Updated Billing Option → Immediate. Removed ANNUALLY from Billing
   Option — no longer valid after this change."
```

The client's explicit choice ("Annual") was accepted, then silently
replaced with "Immediate" in the SAME turn — with a note that reads as
if the substituted value were the correct outcome, not an override of
what was actually asked for.

## 3. Root cause, traced against the real catalog (not assumed)

Queried the SVX catalog's actual rules directly. `billingOptions_viSoln`
has an active **recommendation rule** (BML script):

```
if(archeType_viSoln=="CAPEX PURCHASE") { return "IMMEDIATE"; }
else { return "ANNUALLY"; }
```

`archeType_viSoln` is `"CapEx Purchase"` in this session, so the
condition is stably true — it fires on every rule-evaluation pass,
including the one immediately after the client sets Billing Option to
"Annual" this same turn.

**Two compounding gaps**, confirmed by reading the actual code:

1. `apply_recommendation_rules()` only checks `if filled.get(vn):
   continue` (skip if already truthy) — it has NO concept of "this was
   just explicitly set by the client this turn," so a stably-true
   condition reasserts its recommended value regardless of what the
   client just chose.
2. A **separate**, narrower gap already found and partially fixed this
   session: `auto_fill`'s `len(valid_opts) == 1` branch (the "exactly
   one option remains, auto-fill without asking" shortcut) also had no
   such awareness — fixed via the existing `user_answered_dropped_ids`
   set — **but that set is local to a single `auto_fill()` call.** A
   turn actually calls `auto_fill` **twice** (once inside
   `evaluate_rules_loop`'s internal iteration, once again afterward to
   compute the final `pending` list) — the second call starts with a
   fresh, empty set and has no memory of what the first call protected.
   Threading that memory through both calls *and* into
   `apply_recommendation_rules` would work, but is a much larger change
   than the actual problem needs.

## 4. Resolved decision (HITL, this session)

**D1 — User-selected value precedence.** A value the client's message
explicitly set THIS TURN is authoritative input to the rest of this
turn's rule evaluation. The full evaluation pass still runs unchanged —
every other attribute's rules (hiding, recommendation, constraint) still
evaluate normally, using the client's value as part of the current
state, so real cascades onto OTHER attributes are completely unaffected.
Only the explicitly-set attribute itself is protected from being
reassigned back to something the client didn't ask for, by any
mechanism — a recommendation rule, a blind auto-fill fallback, or
anything else, present or future.

**Scope, deliberately narrow:** enforced by CHECKING THE OUTCOME, not by
threading new state through every internal fill mechanism
(`auto_fill`, `apply_recommendation_rules`, `evaluate_rules_loop`). This
catches the bug regardless of which internal mechanism causes it —
today a recommendation rule, potentially something else tomorrow —
without widening the blast radius of the fix into engine internals
multiple call sites depend on.

**Scope, also narrow in a second sense — this session/turn only, never
the catalog's rule itself:** the fix does not disable, override, or
cache anything against the recommendation rule that caused the reported
bug (`if(archeType_viSoln=="CAPEX PURCHASE") return "IMMEDIATE";`
stays completely untouched, in the ingested rule data, forever). The
correction lives entirely inside `CpqSession` — the plain,
client-echoed JSON blob already scoped to one conversation (same object
`pending_change_collision_vns`/`pending_label_collision_vns` already
live on) — so it structurally cannot leak into another customer's
quote, another session, or even a LATER point in this same session.
Concretely:
- The rule fires normally for every other quote, every other customer,
  every other session — nothing about this fix is global or persisted
  outside this one session's echoed state.
- It is a same-turn, one-time correction, not a standing override even
  within this session: if this same customer later clears Billing
  Option (D4) or triggers a genuine later cascade that legitimately
  should re-derive it, the recommendation rule fires again completely
  normally. This check only ever compares against what THIS turn's
  message set, never a value from a prior turn.

## 5. Design

### 5.1 Where: `_handle_cascade`/`_handle_cascade_multi` only

No changes to `auto_fill`, `apply_recommendation_rules`, or
`evaluate_rules_loop`. Both cascade handlers already lock in the
client's chosen value (`session.filled[vn] = value`,
`filled_source[vn] = "user"`) before running the rule-evaluation pass —
this plan adds a check immediately AFTER that pass completes, using
data already available at that point.

### 5.2 Mechanism

1. Before calling `evaluate_rules_loop`, remember each attribute this
   turn's message explicitly set, as `{variable_name: value}` — for
   `_handle_cascade`, that's just `{changed_attr.variable_name: result[0]}`;
   for `_handle_cascade_multi`, one entry per matched change in the
   message (it already applies up to 3 per turn).
2. After `evaluate_rules_loop` + the final `auto_fill` call produce the
   turn's `filled`/`display_filled`/`pending`, compare: for each
   remembered `(vn, value)` pair, does `filled.get(vn) == value` still
   hold?
3. If NOT — something reassigned it within this same turn — revert:
   pop it from `filled`/`display_filled`, prepend its `ConfigAttr` to
   `pending`, and word the cascade note honestly ("Your choice for
   **Billing Option** (**Annual**) isn't currently valid — here's what
   IS available:" followed by the real remaining options), instead of
   reporting the substituted value as if it were accepted.
4. If the check passes (the common case — most changes stick), behavior
   is completely unchanged from today.

### 5.3 What this does NOT change

- Genuine cascades onto OTHER attributes — untouched. If changing
  Billing Option legitimately invalidates a DIFFERENT attribute, that
  attribute's own invalidation/re-ask behavior is unaffected by this
  plan.
- A recommendation rule reasserting a value on a LATER, unrelated turn
  (e.g., the client changes `archeType_viSoln` itself later, which
  legitimately should flip Billing Option's recommended value) — this
  check only ever compares against what THIS turn's message set, never
  a stale value from a previous turn.
- The separate, already-fixed `len(valid_opts) == 1` gap (§3 item 2) —
  stays in place as a real, independent protection for its own
  (narrower) scenario; this plan does not revert or depend on it.

## 6. Testing plan

1. **Unit** (`ask_api.py` handler-level, mirroring existing
   `_handle_cascade`/`_handle_multi_select_removal` test patterns): a
   recommendation rule whose condition is stably true targets the same
   attribute the client just explicitly changed — assert the FINAL
   `session.filled` value matches what the client asked for, not the
   rule's recommendation, and that the attribute appears in `pending`
   with an honest note if the client's value genuinely isn't allowed by
   an active CONSTRAINT (not just out-voted by a recommendation).
2. **Regression**: existing cascade/change-request test suite
   (`test_cpq_e2e.py`, `test_cpq_cascade_user_answered_reask.py`,
   `test_cpq_change_request_multi.py`) re-run unchanged — proves normal
   cascade behavior for every OTHER attribute is untouched.
3. **Live verification**: replay the exact real transcript above
   (SVX quote, Billing Option → Annual, workspace 14) — confirm the
   final configuration actually shows Annual (or, if a genuine
   constraint rejects it, an honest re-ask naming Annual specifically
   as rejected) rather than a silent substitution.

## 7. Risk

- **Blast radius:** low — confined to 2 functions, checking an outcome
  against data already computed; no changes to shared rule-evaluation
  internals.
- **Real risk to verify:** if a recommendation rule's reassignment was
  actually *correct* from a business standpoint (e.g., the client's
  requested value is genuinely incompatible with something else they
  already confirmed, and the rule is the catalog's own way of enforcing
  that), reverting to `pending` is the right call per this engine's
  "never guess, ask instead" principle — same reasoning as the existing
  `user_answered_dropped_ids` fix — but it does mean the client sees an
  extra question turn instead of a silent (if wrong) resolution. This
  is the intended tradeoff, not a bug, but worth confirming live against
  more than one catalog before considering this fully closed.
