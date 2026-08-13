# CPQ Ask — OffTopic/Intent Detector False-Positive Fixes

**Branch:** `fix/cpq-offtopic-approval-qa-false-positives` (pushed to `aryx-enterprise`, PR not yet opened)
**Base:** `dev-rv` (enterprise)
**Source:** manual test run via Andie against `/ask`, results in `cpq_test_cases.xlsx`
**Sheets analyzed:** `10-OffTopic`, `4-Intent`
**Date:** 2026-08-13

## Summary

Of 81 rows across the two sheets, 4 FAILed (all real code bugs, all fixed) and 3 were
SKIPPED (environment-limited, not code bugs — see below). No other rows were affected.

| Test ID | Sheet | Detector | Failure mode | Status |
|---|---|---|---|---|
| D83 | 10-OffTopic | `off_topic` | false positive | Fixed |
| D40 | 4-Intent | `approval` | false negative | Fixed |
| D42 | 4-Intent | `approval` | false positive | Fixed |
| D48 | 4-Intent | `qa_strict` | false positive | Fixed |
| D30–D32 | 4-Intent | `bulk_qty_skip` | not testable offline | Not a bug — see §Skipped |

## Bug 1 — D83: `off_topic` false positive on "sales forecast"

**File:** [`src/aryx/cpq/intent_gateway.py:80-84`](../src/aryx/cpq/intent_gateway.py)

**Root cause:** `_OFF_TOPIC_HARD` includes a bare `forecast` alternative, added to hard-veto
weather-forecast questions. Bare `forecast` also matches "what is the sales forecast for
Q3" — a legitimate business question — and hard-refuses it.

**Fix:** `forecast` now only fires alongside `weather`: `weather(?:\s*forecast)?`. Bare
"weather" alone still vetoes (unchanged); bare "forecast" no longer does.

**Risk:** none identified — no passing test relied on bare "forecast" without "weather"
in this sheet or `tests/test_cpq_intent_gateway.py`.

## Bug 2 — D40: `approval` false negative on "I approve this configuration"

**File:** [`src/aryx/cpq/engine.py:8072-8077`](../src/aryx/cpq/engine.py)

**Root cause:** `_APPROVAL_RE` anchors its keyword alternation at `^`. The most explicit
possible approval phrasing, "I approve this configuration", starts with "I", not a
keyword, so it never matched — a real approval stalls the quote at Step 8.

**Fix:** added an optional leading clause `^(?:i\s+(?:hereby\s+|just\s+|really\s+)?)?`
before the keyword group. "I don't approve" still does **not** match — "don't" sits
between "I" and "approve", outside the optional group.

## Bug 3 — D42: `approval` false positive on "great question about mounting"

**File:** same regex as Bug 2.

**Root cause:** bare `great` sat in the same anchored keyword alternation, so any
sentence opening with a pleasantry ("great question...") read as APPROVAL and would
finalize the quote — a false positive here is worse than a false negative.

**Fix:** removed `great`/`perfect` from the general alternation; added a standalone
pattern `^(?:great|perfect)\s*[!.]*$` that only matches when the entire trimmed message
**is** just that word (+ optional punctuation). "Great!" still approves; "great
question..." no longer does.

**Raven review caught a regression in this fix, now fixed:** the whole-message-only
pattern above also broke previously-working combined phrasings like "Great, let's go"
and "Perfect, that works" — the pre-fix regex used to match these via bare
`great`/`perfect`; the D42 fix silently dropped them. For `cpq_llm_first_enabled=True`
(the default) this was masked by the LLM-first gateway, but `session.guided_mode=True`
sessions never reach that fallback, so this was a real behavior regression for them,
not merely an "unclosed gap." Loosened the pattern to
`^(?:great|perfect)\b[\s,!.]*(?:let'?s?\s+go|that'?s?\s+(?:works|good|right))?$` —
restores "Great, let's go" / "Perfect, that works" / "Perfect, let's go" while keeping
"great question about mounting" and "greatly appreciated" correctly rejected. Verified
against the full 4-Intent approval sheet (8/8) plus 7 regression phrasings via a
standalone replay script before editing the file; 2 pinning tests added directly
against `engine.detect_approval` in `tests/test_cpq_post_approval_activation.py`.

## Bug 4 — D48: `qa_strict` false positive on "whatever works"

**File:** [`src/aryx/cpq/engine.py:8080-8085`](../src/aryx/cpq/engine.py)

**Root cause:** `_QA_INTENT_RE` anchors `^what` with no trailing word boundary, so
"whatever" matches on the "what" prefix and gets routed to Q&A instead of treated as a
vague config-answer.

**Fix:** added `\b` at the end of the keyword-alternation group.

## Skipped, not fixed — D30–D32 (`bulk_qty_skip`)

`detect_bulk_quantity_change` requires `resolve_array_grid_links()` to return a real
BigMachines array-set (driver attr + linked per-row quantity columns via a shared
`bm_config_attr_set` id) — that linkage only exists in an ingested XML catalog.
`APX_Next_config.xml` was deliberately removed from repo tracking, so
`resolve_array_grid_links()` returns `{}` for any hand-built fixture — confirmed, not
assumed. Already covered by `tests/test_cpq_bulk_quantity_change.py` (29 tests passing).
No code change needed.

## Verification

- Replayed all 20 detector-relevant rows across both sheets against the patched regexes
  in a standalone script: **all 4 failures now pass, all 16 prior passes unchanged.**
- `pytest tests/test_cpq_intent_gateway.py tests/test_cpq_post_approval_activation.py`
  — **41 passed.**

## Follow-up — does the regex fix generalize? (branch `fix/cpq-approval-llm-first-coverage-proof`)

**Issue:** the 4 bugs above were fixed with targeted regex edits. Regex is an
enumeration — it can't cover every way a customer phrases approval ("sounds good to
me", "works for me"), and narrowing `great`/`perfect` to a whole-message-only pattern
(the D42 fix) introduced a new gap: "Perfect, let's go" no longer matches either.

**Root cause:** `detect_approval`/`detect_qa_question` (`engine.py`) are pure anchored
regex with no semantic fallback — unlike `intent_gateway.py`'s LLM-first classifier,
which already exists for other categories.

**Fix:** investigated adding a new LLM-fallback helper (the originally recommended
approach) and found one is not needed — `APPROVAL` and `QA_QUESTION` are **already**
wired into `_dispatch_intent_result` (`ask_api.py`, commits `06d4c69`/`b7151cc`, see
`docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md`) as no-target,
non-mutating categories — `classify_intent`'s quarantine (confidence=HIGH +
evidence_span present) is the only gate, with **no dependency on the regex at all**,
and `cpq_llm_first_enabled` defaults to `True`. Building a second, parallel LLM helper
would have duplicated already-reviewed infrastructure. Instead, added tests proving
this coverage:
- `tests/test_cpq_intent_gateway.py` — 2 new tests: `classify_intent` resolves "sounds
  good to me..." and "Perfect, let's go" to `APPROVAL`/`HIGH` via the LLM path.
- `tests/test_cpq_2026_07_28_fixes.py` — 1 new integration test proving
  `_dispatch_intent_result`'s `APPROVAL` branch submits the payload for "sounds good to
  me, let's finalize this" with `_cpq_engine.detect_approval` explicitly patched to
  return `False` — the real production claim, at the real call site.

**Known, documented gap this does NOT close:** sessions with `session.guided_mode =
True` skip the LLM-first gateway entirely (`ask_api.py`'s STEP-6 gate). Guided-mode
sessions still rely solely on the regex for approval detection.

**Review:** an independent `code-reviewer` pass on the first draft of this work caught
3 issues, all fixed before this PR: (1) HIGH — a `classify_intent`-level test asserted
`engine.detect_approval.assert_not_called()` as "proof" the LLM path skips the regex,
but `intent_gateway.py` never calls that method for *any* category, making the
assertion a tautology rather than evidence — replaced with the real integration test
above; (2) MEDIUM — the `guided_mode` gap (above) was undocumented; (3) LOW — two new
tests left `engine.detect_change_*` mocks unset, unlike every other test in the file —
fixed to match convention.

**Verification:** `tests/test_cpq_intent_gateway.py` — 25 passed.
`tests/test_cpq_2026_07_28_fixes.py -k approval` — 7 passed. (The full file has
pre-existing, unrelated tests that hang in this sandbox due to a real network-access
limitation — confirmed via bisection this predates and is unrelated to this change.)

## Environment hazard noted during this session

Mid-session, a **second concurrent process/session was operating on this same working
directory** (`C:\aryx_project\aryx-config-fix`). It checked out a branch named `pr-190`,
committed its own unrelated `falkor_store.py` fix there, then switched back to `dev-rv`
— which silently discarded uncommitted edits to `intent_gateway.py` and `engine.py` in
this working tree (git does not protect uncommitted changes across a branch switch when
another actor performs it). The fix had to be reapplied and was then committed
immediately to prevent recurrence.

**Recommendation:** don't run two Claude Code sessions against the same checkout at
once — use a separate `git worktree` or clone per concurrent session.
