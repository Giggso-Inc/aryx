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
