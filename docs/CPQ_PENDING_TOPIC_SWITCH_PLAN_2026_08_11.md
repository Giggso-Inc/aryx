# CPQ Pending-Answer Topic-Switch Fix — 2026-08-11

## Issue

When a single-select attribute is actively pending (e.g. Hardware Version),
a customer redirecting to a different attribute in plain language is
misread as a failed answer attempt to the pending question, and the same
question is re-asked forever.

Live-reported transcript: Hardware Version pending. Three real redirect
attempts, all failed:

1. "I wanted to check the carrier selection value"
2. "I don't want hardware version but carrier selection"
3. "I don't want to select the hardware version but i wanted to check with carrier selection"

Each produced "I didn't recognise that as a valid choice for Hardware
Version. Please pick one" instead of switching context to Carrier
Selection.

## Root cause

`_pending_reply_looks_like_new_request` (ask_api.py) is the only gate
deciding whether a reply to a pending question is actually a fresh
request about something else. It requires an explicit change-verb
(`_CHANGE_VERB_RE`: choose/select/pick/swap/change/switch/replace/
update/modify/actually/instead/"make it"/"i want") or an arrow (`->`,
`→`) AND a deterministically-resolvable other attribute.

None of the three real messages match:
- Message 1 has no change-verb vocabulary at all.
- Message 2's `i\s+want` pattern requires "i" immediately followed by
  "want" — "I **don't** want" breaks the match.
- Message 3 does contain "select", so it matches the verb regex, but
  `detect_change_request`/`detect_change_target_without_value` both
  require the *target* attribute to already be in `session.filled` —
  Carrier Selection was never filled yet, so nothing resolves and the
  message still falls through to the pending-answer lock.

This is a keyword-list ceiling, not a logic bug — real conversational
phrasing for "I want to talk about something else instead" is too
varied to enumerate with regex.

## Fix

Add a narrow, single-purpose LLM fallback — same shape as this
session's `_llm_resolve_quantity_target` / `_llm_resolve_label_collision`
— tried **only** when the deterministic check already says no:

- `_llm_detect_pending_topic_switch(question, pending_attr, other_attrs, workspace_id)`
  — asks whether the message names/refers to one specific candidate
  attribute other than the pending one. Returns an exact candidate
  `variable_name` or `None`; never invents a name.
- `_pending_reply_is_topic_switch(...)` — wraps the existing
  deterministic `_pending_reply_looks_like_new_request` check and only
  calls the LLM when it returns `False` and at least one other real
  attribute exists. Deterministic-true short-circuits before any LLM
  call (same cost discipline as every other fallback in this file).

Both call sites of `_pending_reply_looks_like_new_request` (the
LLM-first gateway's pre-STEP-5 gate, and STEP 5's own pending-answer
lock) now call `_pending_reply_is_topic_switch` instead, passing
`req.workspace_id`. `_pending_reply_looks_like_new_request` itself is
unchanged — still the pure, deterministic building block, still
directly unit-testable on its own.

## Why not extend the big LLM-first gateway

Same reasoning as the earlier quantity-target decision this session:
the gateway's schema is about classifying a message into an intent
category against the WHOLE catalog, not "does this redirect away from
one specific pending attribute" — cramming a narrow, pending-state-aware
question into that general-purpose machinery would be a worse fit than
a dedicated helper.

## Tests

`tests/test_cpq_pending_topic_switch.py` (10 tests): the LLM helper in
isolation (resolves a named redirect, rejects an invented variable
name, returns `None` on model "none"/call failure), and the combined
check (short-circuits before any LLM call on a genuine deterministic
match, falls back to the LLM for all three real reported phrasings,
stays `False` for a genuine answer attempt, and skips the LLM entirely
when there's no pending attribute or no other candidate attrs to name).

## Verification

Full CPQ regression: 936 passed, 0 failed (up from 926 baseline + 10
new tests), same pre-existing unrelated `datetime.UTC` collection
errors, untouched.

## Follow-up: a second, separate pending mechanism had the same gap (2026-08-11)

Live-reported after the first fix shipped: with **Hardware Version**
pending via the *"Which value would you like for Hardware Version?"*
no-value-change flow, the message **"First i wanted to changed Wireless
Carrier"** still failed with *"I couldn't match that to a valid option
for Hardware Version."*

Root cause: that prompt is tracked by `session.pending_change_no_value_vn`
— a completely different pending-answer mechanism from
`session.pending_variables` (STEP 5), set by `_build_no_value_response`
and consumed unconditionally at the top of `_run_cpq_turn_inner`
(ask_api.py ~line 6662). It had **no topic-switch check of its own** —
the fix shipped for STEP 5 never covered it. It always treated the next
message as the literal new value, and on a failed match forced it
straight into `_handle_cascade` against the pending attr — exactly
matching the "I couldn't match..." error text, which comes from
`_handle_cascade`, not STEP 5.

Separately: "wanted to **changed**" doesn't match `_CHANGE_VERB_RE`
either — the regex requires "change"/"changing", and "changed" breaks
the `\b` boundary right after "chang" fails to fire for this
conjugation — so even the deterministic layer had nothing to catch here.

Fix: applied the exact same `_pending_reply_is_topic_switch` check to
this branch too, right after `session.pending_change_no_value_vn` is
read and before it's used to force a value match — when the check
returns `True`, the branch's local pending-attr reference is dropped so
the message falls through to normal routing instead of being coerced
into `_handle_cascade`.

Added `test_combined_check_live_2026_08_11_wireless_carrier_phrasing`
to `tests/test_cpq_pending_topic_switch.py` (11 tests total) — proves
the combined check now correctly resolves this exact reported phrasing
to `carrierSelection_astro`. Full CPQ regression re-run: 937 passed, 0
failed. Rebuilt and redeployed the API container.

Live multi-turn e2e replay of the full reported transcript in the local
dev stack did not reach the same session state (an unrelated
country-capture quirk in this local catalog data stalled the flow
before Hardware Version); the fix itself is verified at the unit level
against the exact reported message text and confirmed via full
regression. Recommend a live check against the real environment to
close the loop end-to-end.
