# CPQ Conversational-Flow Fixes — 2026-07-22/23

Live-verified issue log from real reported transcripts on `feature/msi_cpq`
(grid-quantity edits, mount removal, product-model switching), covering the
5 commits pulled `91b3b43..ce09d73`. Each entry: **Problem** (what was
observed, with the real example), **Root cause**, **Fix**, **Commit**,
**Tests**. Builds on `docs/CPQ_CASCADE_CONVERSATION_PLAN.md` (the base
conversational-flow spec) — this doc does not replace it.

---

## Overview

| # | Issue | Status |
|---|-------|--------|
| 1 | Cascade notes mislabel `set_type=2` attrs as "needing fresh values" | ✅ Fixed (`ce09d73`) |
| 2 | Bulk quantity changes not recognized without the literal word "quantity" | ✅ Fixed (`d9b737e`) |
| 3 | Bulk grid-quantity updates + label-collision prompt has no memory | ✅ Fixed (`2dd5d40`) |
| 4 | "Remove it" doesn't work after an unresolved-grid-quantity warning | ✅ Fixed (`49da9bb`) |
| 5 | LLM intent fallback capped candidates before relevance-scoring them | ✅ Fixed (`733392b`) |

All 5 are live-verified against real reported transcripts, each with new
regression tests, and merged into `feature/msi_cpq`.

---

## 1. Cascade notes mislabel `set_type=2` attrs as "needing fresh values"

**Problem statement:** Switching Select Model announced a dependent
attribute — "Include a Spare Battery with each body camera" — as
"recalculating," implying a new value would follow. It then silently
never reappeared in `filled`, `pending_variables`, or the summary, with
no explanation.

**Where in the flow:** `_handle_cascade`/`_handle_cascade_multi`
(`src/aryx/api/ask_api.py`) — the cascade-note builder that names every
invalidated dependent attribute.

**Root cause:** That attribute has `set_type="2"` (a transient BigMachines
UI/action-layer field) — `build_payload()` already excludes any
`set_type=="2"` attr from the BOM payload unconditionally, so its
disappearance from the conversation was *correct*. Only the wording was
wrong: the cascade note treated "no longer visible" as "needs a fresh
value," when for this class of attr it never re-enters `filled` or
`pending` at all.

**Fix:** `dependent_labels` (the list the cascade note is built from) now
filters out `set_type=="2"` attrs before naming dependents, in both the
single-change (`_handle_cascade`) and multi-change
(`_handle_cascade_multi`) paths.

**Live-verified:** the same product-model switch now only names "SVX TAA
Kit Help Text" (a real dependent) and omits the `set_type=2` attr
entirely.

**Commit:** `ce09d73`
**Tests:** none added — behavior-only wording fix, covered by existing
cascade-note assertions not regressing.

---

## 2. Bulk quantity changes not recognized without the literal word "quantity"

**Problem statement:** "Change both the mounting type to 25" says
"both," but never says "quantity." The existing `_BULK_QTY_RE` required
the literal word, so the message missed it and fell into
`detect_change_request_collision` instead — where `25` (never a real
mount *option*) couldn't resolve against either candidate attribute,
producing a dead end.

**Where in the flow:** `_BULK_QTY_RE` (`src/aryx/api/ask_api.py`) and its
downstream collision-resolution fallback.

**Root cause:** The regex was anchored on the word "quantity" itself,
not the more general "apply this value to more than one row" intent —
"both"/"all"/"every" phrasing carries the same intent without that word.
Separately, when the collision-resolution fallback DID fire and couldn't
parse a value, it silently dropped the reply instead of asking again.

**Fix:** Broadened the regex to also match `both`/`all`/`every`.
`detect_bulk_quantity_change`'s own restriction — only firing for
`resolve_array_grid_links`' real quantity selectors — remains the actual
safety net, not the regex itself. Also hardened the collision-resolution
fallback: an unparseable value now registers `pending_variables` (the
same resume-question mechanism used elsewhere in the engine) instead of
orphaning the follow-up reply.

**Live-verified:** replaying the real reported transcript, "change both
the mounting type to 25" now resolves directly via
`cpq_bulk_quantity_change()` — no collision detour, both rows set to 25.

**Commit:** `d9b737e`
**Tests:** `tests/test_cpq_bulk_quantity_change.py` (+16 lines)

---

## 3. Bulk grid-quantity updates + label-collision prompt has no memory

Two related gaps found from the same real transcript.

### 3a. Bulk grid-quantity misread as a single-attribute change

**Problem statement:** "Change both the mounting types quantity to 67"
was previously misread as a value change against the grid *selector*
attribute itself (67 is never a real mount option), or forced an
unresolvable disambiguation between two identically-labeled "Mounting
Type" attributes.

**Root cause:** No detector existed that specifically recognized "apply
one quantity to every row of a grid" as its own intent, distinct from
either a single-attribute value change or a genuine label collision.

**Fix:** Added `detect_bulk_quantity_change`, scoped strictly to
`resolve_array_grid_links`' real quantity-selector attrs — a plain
single-select sibling sharing the same `display_label` is never a
candidate, since it has no quantity links at all, so the collision path
never even fires for this phrasing.

### 3b. Label-collision prompt ("which one did you mean?") had no memory

**Problem statement:** Answering the collision prompt — even with the
exact `variable_name` — fell straight through to the generic "I didn't
quite catch that" nudge instead of resolving.

**Root cause:** `detect_change_request_collision` had no state carried
across turns; the next message was evaluated fresh with no awareness a
disambiguation question was pending.

**Fix:** Added `session.pending_change_collision_vns`/
`_pending_change_collision_question`, set when the prompt fires. The
next turn resolves against them by `variable_name` or 1-based list
index, then re-runs `detect_change_request` scoped to just that one
attribute (reusing its existing value-extraction machinery) before
dispatching to the normal cascade handler.

**Bonus fix (same commit):** a cosmetic duplicate in the bulk-quantity
cascade note — `resolve_array_grid_links`' substring heuristic can map
two distinct options (e.g. "MOLLE Mount" and "Locking Molle Mount") to
the same quantity attribute; now reported once, not once per option.

**Live-verified:** replayed the real reported transcript (bulk quantity
resolves cleanly with no collision) and a constructed collision scenario
(`mountType_viSoln` vs `mountingTypeArray_viSoln`, both sharing
"Mounting Type" — resolved correctly by `variable_name`).

**Commit:** `2dd5d40`
**Tests:** `tests/test_cpq_bulk_quantity_change.py` (+102 lines)

---

## 4. "Remove it" doesn't work after an unresolved-grid-quantity warning

**Problem statement:** After selecting a grid option with no resolvable
quantity attribute (e.g. SVX's bare "Magnetic Mount"), the engine warns:
"remove it or choose a different option." Typing exactly that did
nothing — the same warning repeated verbatim on every subsequent turn.

**Where in the flow:** STEP 3 (rule evaluation loop) vs. STEP 5 (answer
lock) in `_run_cpq_turn`, `src/aryx/api/ask_api.py`.

**Root cause:** The unresolved-grid-quantity warning block leaves
`session.pending_variables` empty, so STEP 5 (which locks in the user's
answer to a pending question) never runs. The turn fell straight to
STEP 3, which re-ran the rule loop against unchanged state and
re-emitted the identical warning every time — the user's reply was never
actually read as an instruction.

**Fix:** Added STEP 5b: when there's no pending question but the turn's
text carries a removal verb, first try `detect_multi_select_removal`
(option named explicitly), then fall back to resolving a bare pronoun
("remove it") to the single unresolved gap option when exactly one
exists. Reuses `_handle_multi_select_removal` unchanged.

**Separately confirmed by design, not a bug:** Magnetic Mount is a real
catalog option whose quantity attribute is genuinely ambiguous in the
catalog's own data (it shares a token with Jacket/Shirt Magnetic Mount's
quantity attrs) — surfacing and blocking on it, rather than silently
guessing or hiding it, was a deliberate prior fix
(`docs/CPQ_SESSION_2_OPEN_ISSUES.md` item 9). Only the "remove it" dead
end was the actual bug.

**Commit:** `49da9bb`
**Tests:** none added — behavior-only fix to an existing gap-handling
block; covered by the existing unresolved-grid-quantity test suite not
regressing.

---

## 5. LLM intent fallback capped candidates before relevance-scoring them

**Problem statement:** "I don't want the jacket mount anymore" (a phrase
no regex verb matches) fell through every detector to the LLM-based
intent fallback — which incorrectly answered "none" even though a real
target attribute existed.

**Where in the flow:** The LLM fallback for remove/change intent
(originally added in `8bc505a`), `src/aryx/api/ask_api.py`.

**Root cause:** The fallback capped the list of filled attributes to the
first 40 by catalog order *before* scoring relevance against the
message. On a catalog where dozens of unrelated promotion/accessory
attributes happen to come first in catalog order, the real target
(`mountingTypeArray_viSoln`) was cut off entirely before the classifier
ever saw it.

**Fix:** Reordered to relevance-score every candidate first, then cap
after scoring — the real target survives regardless of catalog order.
Also tightened the classifier's guardrails: rejects any "remove" intent
against a non-multi-select attribute, and rejects any value that isn't
a real option on the attribute the model actually named (two attributes
in this catalog share the display label "Mounting Type" but are
different fields — a naive match could cross-wire them).

**Live-verified:** "I don't want the jacket mount anymore" now correctly
removes Jacket Magnetic Mount and clears its orphaned quantity attribute.

**Commit:** `733392b`
**Tests:** none added in this commit — regression coverage lives in
`tests/test_cpq_llm_intent_fallback.py` (added with the original `8bc505a`
fallback), still green against this fix.
