# CPQ Turn-1 Country Extraction Defect — Investigation + Plan (2026-08-13)

Status: **implemented** — primary wiring fix shipped (item 1 in "Proposed
fix" below). Items 2 (Country-once re-scan hardening) and 3 (regex
`\b` hardening) were NOT implemented in this round — owner explicitly
scoped this round to the primary fix only.

**Live-verified, 2026-08-13**: after also flipping `cpq_intent_mode`'s
default from `"shadow"` to `"llm_first"` (see below — a second,
necessary fix discovered during live verification, not in the original
plan), `"Give me a quote for APXNET in United States"` now correctly
sets `session.country = "United States"` on turn 1 and proceeds straight
to product disambiguation, instead of re-asking for the destination
country.

**Second bug found during live verification**: the primary wiring fix
alone did NOT close the live-reported bug. `route_meta` is only ever
populated with a real `.country`/`.quantity` when `cpq_intent_mode` is
`"llm_first"` — in `"shadow"` mode (the pre-existing default), the
top-level router runs for agreement logging ONLY and `route_meta.
country`/`route_meta.quantity` are deliberately stripped to `None`
before `_run_cpq_turn_inner` ever sees them (see `test_shadow_mode_
strips_quantity_and_country_before_the_turn`, docs/CPQ_QUANTITY_
COUNTRY_SUMMARY_FIXES_2026_08_13.md). Since this environment's default
was `"shadow"`, the primary fix's `route_meta.country` fallback was
structurally unreachable regardless of whether the wiring guard was
correct. Flipped `cpq_intent_mode`'s default in `config.py` from
`"shadow"` to `"llm_first"` so the turn-1 unified extraction plan this
whole fix relies on actually takes effect by default. Full CPQ suite
re-run clean after the flip (only the pre-existing unrelated
`test_mirrors_match_gateway_regexes` failure).

## Reported bug

Turn 1: `"Give me a quote for APXNET in United States"` gets:

> Thanks — and what's the **destination country** for this quote? (e.g., *United States*, *Canada*, *Germany*)

even though the country is stated plainly in the same message.

## Root cause (confirmed by running the live code, two compounding bugs)

**Bug 1 — regex false-positive, same known shape as an already-documented bug.**

`_COUNTRY_PREP` (`engine.py:422-428`):
```python
_COUNTRY_PREP = re.compile(
    r"(?i:\b(?:in|for|from|customer\s+in|located\s+in|based\s+in|"
    r"destination\s+country\s+is|destination\s+country\s+as|"
    r"destination\s+country|"
    r"whose\s+destination\s+country\s+is|country\s+is|country\s+as)\s+)"
    r"((?:[A-Z]{2}|[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)*)"
)
```
`re.search` returns the FIRST match. In `"...for APXNET in United States"`, trigger word `for` appears before `in`, and the capture alternative `[A-Z]{2}` (no trailing word-boundary) is satisfied by the first two letters of `APXNET` — match stops at `"for AP"`, never reaching `"in United States"` later in the string.

Verified directly:
```
eng.extract_hints("Give me a quote for APXNET in United States")
→ {'country': 'Ap'}
```

This is the exact bug shape `is_recognized_country`'s own docstring (`engine.py:5943-5964`) already cites for `"for APX Next"` → `"AP"`. `is_recognized_country("Ap")` correctly returns `False` — but rejection is where it stops; nothing re-scans the rest of the sentence.

**Bug 2 — wiring: a rejected-but-present `hints["country"]` masks every fallback, including the LLM's own correct value.**

Turn-1 unified extraction (`ask_api.py:7302-7337`) already runs a single fused LLM call (`classify_ask_route`) every turn 1 and populates `route_meta.country` — this is the exact "reuse the existing LLM call" mechanism this session already used for the quantity fix. But:
```python
hints = _cpq_engine.extract_hints(req.question)          # {'country': 'Ap'} -- WRONG, but present
...
elif (
    "country" not in hints                                 # False -- key exists (bad value)
    and route_meta is not None
    and route_meta.country
):
    hints["country"] = route_meta.country                  # never reached
if (
    "country" in hints and not session.country
    and _cpq_engine.is_recognized_country(hints["country"]) # False ("Ap")
):
    session.country = hints["country"]                      # never assigned
```
Because the regex already stuffed a wrong value into `hints["country"]`, the `"country" not in hints"` guard is `False`, so the LLM-derived `route_meta.country` (very plausibly holding the correct `"United States"` already) is never consulted at all. The later "Country-once" re-scan (`ask_api.py:8226-8244`) reruns the SAME buggy regex against the SAME message and reproduces the same failure — it also never consults `route_meta.country`. With `session.country` still unset, the clarifying question fires (`ask_api.py:8246-8251`).

## Why this closes with the LLM-first pattern, no new LLM call

Exactly like the quantity fix (docs/CPQ_QUANTITY_EXTRACTION_DEFECTS_PLAN_2026_08_13.md): `route_meta.country` is populated by a call that is **already made once, every turn 1**, by `classify_ask_route` — this isn't a new LLM round-trip, it's an existing result the wiring bug currently discards. Owner directive: fix this using the LLM-first value, not by trying to out-regex every future product-name shape.

## Proposed fix (LLM-first, no new call, turn-1 scoped)

1. **Wiring fix (the primary fix)**: change the guard at `ask_api.py:7302-7337` from `"country" not in hints"` to "hints has no *valid* country" — i.e. `not _cpq_engine.is_recognized_country(hints.get("country", ""))`. This lets `route_meta.country` (the LLM's own turn-1 extraction) win whenever the regex's candidate is present but wrong, without touching the case where the regex is already correct (still preferred first, matching this session's existing "regex-extracted values are not overwritten by the router" convention — see `test_regex_extracted_values_are_not_overwritten_by_the_router`).
2. Apply the identical "present-but-invalid == absent" fix to the Country-once re-scan block (`ask_api.py:8226-8244`) for defense in depth — this block runs on turns without a `route_meta` too (turn 2+, or re-scanning prior history), so it can't rely on `route_meta.country` itself, but it should at least stop treating a rejected regex match as if it were a successful commit that blocks the loop from trying the NEXT history source in the same iteration (needs a closer read during implementation to confirm whether this is already handled per-source correctly, or has the same masking bug across sources).
3. **Regex hardening (fallback path, matches the quantity fix's own "keep the mechanical fix as hardening" precedent)**: tighten `_COUNTRY_PREP`'s `[A-Z]{2}` branch with a trailing word-boundary (`[A-Z]{2}\b`) so it can never again match a 2-letter fragment of a longer all-caps product token. This is small, mechanical, and worth shipping regardless of the LLM-first fix landing — it's the same class of hardening as the quantity clusters (never the primary fix, but strictly improves the fallback's own correctness for when the LLM path isn't available).

## What this does NOT do

- Does not change the country-CHANGE gate (mid-session "change country to X" command) — that's a different code path (`COUNTRY_CHANGE` category, `country_text`, already LLM-confirmed per the earlier `_llm_confirm_deterministic_intent` checkpoint work) and is not reported as broken here.
- Does not add any new LLM call — `route_meta.country` is a side effect of the classification call `classify_ask_route` already makes on turn 1, same discipline as the quantity fix's "reuse the existing call" constraint.

## Test plan (for implementation phase)

1. Regression test mirroring the exact reported transcript: `"Give me a quote for APXNET in United States"` with a mocked `route_meta.country == "United States"` → `session.country == "United States"`, no clarifying question.
2. Existing regex-hardening tests extended with a product-name-then-real-country case (`APXNET`, `APX8000`) to lock in the `\b` fix.
3. Guard test: when the regex candidate IS valid (e.g. `"quote for Canada"`), it must still win over `route_meta.country` even if they disagree (matches `test_regex_extracted_values_are_not_overwritten_by_the_router`'s existing intent) — i.e. the fix only fires on invalid-regex-candidate, never overrides a correct one.
4. Full CPQ regression suite, live-test against the real container with the exact reported phrasing.

## Open question

Should the Country-once re-scan block's "present-but-invalid == absent" fix also be scoped in this same round, or deferred as a smaller follow-up once the turn-1 fix (the one actually reported) is verified live? Recommend doing both together since they're the same one-line pattern applied to two sites, but flagging in case reviewer wants a narrower diff.
