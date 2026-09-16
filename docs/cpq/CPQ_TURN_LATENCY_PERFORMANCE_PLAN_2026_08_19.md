# CPQ Turn Latency — Performance Fix Plan

**Date:** 2026-08-19
**Status:** Implemented and live-verified (branch `perf/cpq-rule-loop-and-table-cache`,
based on `dev-rv-msi` post-PR#217/#218/#219-merge)

**2026-08-21 update:** rebased onto current `dev-rv-msi` as
`perf/cpq-turn-latency-only-2026-08-21` (RC1/RC2 only — the lazy JSON/Beautify
preview work referenced in the "Not fixed" note below was dropped from that
branch and lives only on the original `perf/cpq-rule-loop-and-table-cache`).
`engine.py` line numbers below reflect the plan as originally written; the "How
the signature is formed" section further down cites current, post-rebase line
numbers explicitly.
**Severity:** High (user-facing — turns observed taking 72-82s on average, up to 229s
worst-case; LLM calls are a small fraction of this, ~5.3s avg)
**Discovered via:** live log analysis of 6 real turns against the running `api`
container this session (`docker logs aryx-api-1`), correlating `cpq_step`/`cpq_perf`
timing lines.

## Measured baseline (before any fix)

| Cost center | Calls | Total | Avg | Max |
|---|---|---|---|---|
| `evaluate_rules_loop` (whole loop) | 6 turns | 429.7s | 71.6s | 185.9s |
| `auto_fill` (inside the loop) | 48 (6×8 passes) | 165.7s | 3.45s | 14.6s |
| `_load_all_tables` (fresh scan) | 6 (once/turn) | 89.7s | 14.95s | 32.6s |
| `_apply_series_mapping_exclusions` | 48 (6×8 passes) | 57.7s | 1.20s | 33.7s |
| LLM calls (all roles/models combined) | 10 | 52.8s | 5.28s | 10.1s |

Every one of the 6 observed turns ran the full `_MAX_LOOPS = 8` passes — none
converged early. Two independent root causes were identified and investigated at the
code level before writing this plan.

---

## Root cause 1 — the rule loop never converges before hitting the 8-pass cap

### Problem

`evaluate_rules_loop` always runs all 8 passes on every real turn, multiplying
`auto_fill`'s and `_apply_series_mapping_exclusions`'s per-pass cost by up to 8x per
turn regardless of whether the configuration actually needs that many iterations to
settle.

### Root cause

The loop's exit check (`engine.py:6587-6591`):

```python
if (not _resynced
        and not inconsistent_vns
        and set(filled.keys()) == prev_filled_keys
        and {a.entity_id for a in attrs} == prev_visible_ids):
    break
```

only compares *which keys* are present in `filled` (and which attrs are visible) —
never their *values*. In principle this should stabilize quickly once the same set
of attributes is filled pass over pass.

But `auto_fill` deliberately evicts and re-derives every attribute whose source is
`"default_first_available"` on **every single pass**, by design (`engine.py:7976-
8009`, comment at 7992-8006): *"Re-open it every pass instead of locking in a guess
forever... best case, a real answer now overrides the earlier guess before the
customer ever sees the wrong one."* This is deliberate, sound behavior on its own —
but the pop-then-re-derive happens against a `filled` context that's still growing
pass to pass (more Data-Table-dependent narrowing becomes resolvable as other
attributes fill in). On any pass where re-derivation momentarily narrows to **zero**
legal values (a transient state, not a real conflict), the attribute disappears from
`filled` for that pass, flipping `set(filled.keys())` relative to `prev_filled_keys`
and forcing another full pass — even though the "real" answer isn't actually still
changing, the bookkeeping mechanism keeps signaling that it is.

### Fix

Gate the re-derivation itself, not the convergence check. Per the correctness-risk
analysis (`docs/CPQ_TURN_LATENCY_FIX_CORRECTNESS_RISK_2026_08_19.md`), the signature
used to decide "has anything actually changed" must be **broad** (all filled state,
not one attribute's narrow constrained-options snapshot) to avoid silently missing a
script-driven narrowing — the exact failure class already seen once with Package
Type. The design below reflects that broad-signature decision concretely.

**What the signature is** — a plain, hashable Python tuple, never actually hashed
(no `hashlib`/`hash()` call at all — direct tuple equality is used, which sidesteps
any hash-collision or cross-process hash-instability concern entirely, since
`PYTHONHASHSEED` randomizes Python's built-in `hash()` per process and this
comparison must be trustworthy within a single turn either way):

```python
def _fill_signature(
    filled: dict[str, str],
    filled_multi: dict[str, list[str]],
    visible_ids: set[int],
) -> tuple:
    return (
        tuple(sorted(filled.items())),
        tuple(sorted((k, tuple(sorted(v))) for k, v in filled_multi.items())),
        tuple(sorted(visible_ids)),
    )
```

- **Includes every filled single- and multi-select value** — deliberately not
  scoped down to "only attributes this one plausibly depends on." A real dependency
  graph that could safely narrow this doesn't exist yet for script-backed rules
  (per the dependency-ordering discussion earlier this session) — narrowing the
  signature by guessing which attributes matter is exactly the unsafe shortcut the
  correctness-risk doc warns against. The accepted cost of the broad signature is
  some attrs re-deriving unnecessarily when an unrelated attribute's value changes
  (a minor efficiency loss, still far cheaper than today's unconditional
  every-attr-every-pass behavior); the benefit is zero risk of missing a real
  dependency, since nothing is excluded.
- **Includes the visible-attribute-id set** (`{a.entity_id for a in attrs}`) —
  mirrors what the OUTER convergence check already compares (`engine.py:6587-6591`).
  A hiding-rule-driven visibility change can alter which options are legal for a
  still-unresolved attribute even when no other attribute's *value* changed, so
  this must be part of the signature too, not just filled values.
- **Does not include `display_filled`** — display strings are derived from the
  underlying value and carry no independent information for this purpose.

### What problem the signature actually solves

Before this fix, `auto_fill` treated "a `default_first_available` guess might be
stale" as true on *every* pass, unconditionally — so it evicted and re-derived
every blind-picked attribute 8 times per turn even on the 6+ passes where nothing
that could possibly affect that guess had changed since the previous pass. The
signature exists to answer one narrow, specific question cheaply: **"has anything
this guess could plausibly depend on changed since I last (re)decided it?"** If
the answer is no, re-running the same derivation logic against the same inputs is
guaranteed (by construction — `auto_fill` has no hidden mutable state or
randomness) to produce the exact same output, so skipping it is a pure win with
zero behavior change. The signature is the mechanism that makes "nothing changed"
a cheap, checkable fact instead of an assumption.

Two things follow directly from that framing:
- It is a **memo key**, not a hash for storage or lookup efficiency — it is
  compared with `==` against the *previous* signature computed for this same
  attribute, on the *previous* pass, within the *same* turn. There is exactly one
  comparison per attribute per pass; nothing is bucketed or indexed by it.
- It has to be **conservative in one direction only**: it may include more than
  it strictly needs to (causing an occasional unnecessary re-derivation — cheap,
  self-correcting, harmless) but it must never exclude something the guess could
  actually depend on (which would suppress a re-derivation that should have
  happened — a silent correctness bug, the exact failure class this plan's
  correctness-risk companion doc is about). That asymmetry is why the signature
  was deliberately built broad rather than scoped to "only what this one
  attribute's own rule references."

### How the signature is formed — step by step

`_fill_signature(filled, filled_multi, visible_ids)` (`engine.py:1687-1708`) takes
the three pieces of turn state a `default_first_available` guess could plausibly
depend on and turns each into something orderable and comparable:

1. **`filled` → `tuple(sorted(filled.items()))`** — every single-select
   attribute's variable name (`vn`) paired with its current value, as a list of
   `(vn, value)` pairs, sorted by `vn`. Sorting matters: `filled` is a regular
   Python `dict`, and while modern dicts preserve insertion order, two passes
   that happen to fill the exact same keys in a different order (e.g. because one
   more attribute resolved earlier this pass than last pass) must still produce
   an *equal* signature if the resulting key→value mapping is identical — sorting
   by key removes insertion order as a source of spurious inequality.
2. **`filled_multi` → `tuple(sorted((k, tuple(sorted(v))) for k, v in
   filled_multi.items()))`** — same idea, one level deeper: each multi-select
   attribute's own list of selected values is itself sorted before being turned
   into a tuple (so `["A", "B"]` and `["B", "A"]` — same selections, different
   order — compare equal), and then the `(key, sorted-values-tuple)` pairs are
   themselves sorted by key for the same insertion-order-independence reason as
   above.
3. **`visible_ids` → `tuple(sorted(visible_ids))`** — the current pass's
   `{a.entity_id for a in attrs}`, i.e. which attributes are visible at all right
   now. Sorted for the same reason; included because a hiding-rule change can
   alter which options are legal for a still-unresolved attribute even when no
   filled *value* changed (visibility is not derivable from `filled`/
   `filled_multi` alone).

The three tuples are returned together as one outer tuple. Tuples compare equal
element-by-element, all the way down, so two signatures are `==` if and only if
every filled value, every multi-select selection set, and the visible-id set are
all identical between the two snapshots being compared — nothing more, nothing
less.

**Worked example.** Say on pass 2 of a turn, `filled = {"hardwareVersion":
"4G_LTE", "product": "APX_NEXT_ENHANCED"}`, `filled_multi = {}`, and
`visible_ids = {101, 102, 105}`. The signature is:

```python
(
    (("hardwareVersion", "4G_LTE"), ("product", "APX_NEXT_ENHANCED")),
    (),
    (101, 102, 105),
)
```

This gets stored as `default_fill_signatures["modelSelection"]` (say
`modelSelection` is the attribute currently being blind-picked). On pass 3, if
`filled`, `filled_multi`, and `visible_ids` are byte-for-byte the same when this
same attribute's branch is reached again, `_fill_signature(...)` produces the
identical tuple, `default_fill_signatures.get("modelSelection") == _cur_sig` is
`True`, and the pop-and-re-derive step is skipped entirely — the previously
computed `filled["modelSelection"]` value is kept as-is. If instead
`filled["hardwareVersion"]` had changed to `"5G"` in the meantime (or a hiding
rule had removed attribute `105` from `visible_ids`), the tuple would differ in
that one position, equality would be `False`, and `modelSelection` gets properly
re-derived against the new context — exactly the case the signature must never
suppress.

**Why direct tuple equality instead of hashing it.** No `hash()` or `hashlib`
call is involved anywhere in this comparison. Python's built-in `hash()` for
strings is randomized per-process (`PYTHONHASHSEED`) specifically to prevent
hash-flooding attacks, which means the same string can hash differently across
two runs of the interpreter — irrelevant here in principle, since everything
stays within one process and one turn, but comparing the tuples directly with
`==` sidesteps the question entirely rather than relying on that guarantee. It
also avoids any (astronomically unlikely, but non-zero) hash-collision risk from
condensing the tuple down to a single hash value before comparing — direct
structural equality has no collision case at all.

**Lifecycle within one turn.** `default_fill_signatures` (the dict that stores
one signature per attribute variable name) is declared once, empty, immediately
before `evaluate_rules_loop`'s pass loop (`engine.py:6605`) and threaded by
reference into every pass's `auto_fill(...)` call
(`engine.py:6770`/`auto_fill`'s `_default_fill_signatures` parameter,
`engine.py:7843`). Each attribute's entry is written the first time its branch
runs in a turn (pass 0, where there is nothing to compare against yet, so
re-derivation always happens and the resulting signature is recorded for next
time — `engine.py:8320-8332` for single-select, `8366-8380` for multi-select),
then read-and-possibly-rewritten on every subsequent pass. Because the dict
itself is a fresh local variable owned by the loop, it cannot leak state across
turns or across concurrent requests — the next turn's call to
`evaluate_rules_loop` always starts from an empty dict, so pass 0 of every new
turn always attempts a real derivation, identical to pre-fix behavior.

**Where it lives — local to one `evaluate_rules_loop` call, not session state.**
All 8 passes of a turn happen inside one Python function call (the `for pass_num in
range(_MAX_LOOPS):` loop, `engine.py:6339`), so a plain local dict declared once
before that loop is sufficient — no new `CpqSession` field, no serialization change,
nothing that crosses the HTTP request boundary:

```python
_default_fill_signatures: dict[str, tuple] = {}   # declared once, before the pass loop
```

This resets to empty at the start of every turn by construction (it's a fresh local
variable each time `evaluate_rules_loop` runs) — so **pass 0 of every new turn
always attempts re-derivation** for every `default_first_available` attribute,
exactly like today, since there's no prior-pass signature yet to compare against.
The gating only ever suppresses re-derivation on passes 1-7 of the *same* turn,
which is precisely where the wasted, repeated cost was measured.

**How it's threaded through `auto_fill`** — one new optional parameter, following
the exact convention `_dt_cache`/`hiding_rules` already use in this same function
signature (`engine.py:7540-7541`): default `None` = complete no-op, identical to
today's behavior for every existing call site (tests call `auto_fill` directly in
many places and must not be affected):

```python
def auto_fill(
    self,
    ...
    _dt_cache: dict[tuple[int, str], tuple] | None = None,
    hiding_rules: list["HidingRule"] | None = None,
    _default_fill_signatures: dict[str, tuple] | None = None,   # new
) -> tuple[dict[str, str], dict[str, str], list[ConfigAttr]]:
```

Only `evaluate_rules_loop`'s own call site (`engine.py:6481-6489`) passes a real,
freshly-initialized dict; it is mutated in place across the 8 passes within that one
loop, exactly like `dt_cache` already is.

**The gate itself**, inside the existing `default_first_available` branch
(single-select `engine.py:7976-8009`, multi-select `9080-9086`) — pseudocode
showing the change against the existing logic:

```python
elif sources.get(vn) == "default_first_available":
    if _default_fill_signatures is not None:
        current_sig = _fill_signature(filled, already_filled_multi or {}, visible_ids)
        if _default_fill_signatures.get(vn) == current_sig:
            continue  # nothing relevant changed since last derivation -- skip
        _default_fill_signatures[vn] = current_sig
    # ... existing pop-and-re-derive logic, unchanged ...
```

The signature is written **before** attempting re-derivation (using the state as of
the start of this pass, before this attribute's own value is touched) so the next
pass's comparison reflects "what the world looked like when this was last
(re)decided," not a half-updated intermediate state.

Left deliberately **unchanged**: the convergence check itself
(`set(filled.keys())`-based), `_resynced`/`inconsistent_vns` gating, and every other
`auto_fill` code path (attrs with sources other than `default_first_available`).

**Rejected alternative**: making the convergence check itself value-aware (hash
`filled`'s values, not just keys). Rejected — this treats the *symptom* (the check
can't tell "same guess" from "real change") without addressing why the guess keeps
getting re-attempted needlessly; it also risks masking genuinely unresolved
oscillations elsewhere in the loop by making the check more permissive across the
board, a broader and less predictable blast radius than gating one specific
re-derivation path.

### Impact after fix

Based on the measured 3.45s avg `auto_fill` cost and 1.20s avg
`_apply_series_mapping_exclusions` cost per pass: if real turns typically settle in
~2-3 passes instead of always hitting 8 (to be confirmed empirically after
implementing — see Verification below), that's roughly a 60-70% reduction in both
costs, i.e. on the order of **150-200s saved in aggregate across the same 6-turn
sample** (out of ~430s total `evaluate_rules_loop` time). This is the larger of the
two fixes' expected impact.

---

## Root cause 2 — the cross-turn table cache's TTL is too short to survive real conversation pacing

### Problem

`_load_all_tables` re-runs a full, expensive Postgres scan (up to 32.6s) on most
real turns, even though a cross-request cache for exactly this data already exists
in the code.

### Root cause

There are already two cache tiers in `_load_all_tables` (`data_table_resolver.py`):

1. A per-call ("call-local") cache, scoped to one `evaluate_rules_loop` invocation —
   this is why "CACHE HIT (call-local)" fires thousands of times *within* a turn.
2. A module-level, cross-request cache — `_TABLES_CACHE` with
   `_TABLES_CACHE_TTL_SECONDS = 30.0` (line 79), explicitly modeled on
   `engine.py`'s `_VALUE_RULES_CACHE`/`_LAYOUT_COMPONENTS_CACHE` pattern.

The cross-request cache is real and already correctly implemented — it is simply
**tuned too short to survive the time between two real conversational turns** (a
customer reading a question and typing a reply routinely takes longer than 30s), so
by the time the next turn's request lands, the TTL has already expired and it falls
straight through to a fresh, full scan again. The docstring's own reasoning for
choosing a TTL at all (line 74-77) is guarding against a Data Table CSV being
**re-ingested mid-session** — an occasional admin action, not something that happens
every 30 seconds — meaning the TTL is calibrated far shorter than the risk it exists
to protect against actually requires. The same exposure exists identically for
`_VALUE_RULES_CACHE`'s and `_RULE_JOIN_DATA_CACHE`'s own 30s TTLs (`engine.py:1358,
1386`), sharing the same root cause.

Additionally: no code path in the ingestion pipeline (`doc_discovery.py`'s
`ingest_confirmed()`) actually calls any of these caches' clear functions
(`_clear_tables_cache()`, `_clear_value_rules_cache()`, `_clear_rule_join_data_
cache()`) after a real re-ingest completes — today, the 30s TTL is the *only*
staleness guard for all three, and those clear functions are exercised only by
`tests/conftest.py`'s test-isolation fixture, never in production.

### Fix

Two-part, in order of how much risk each removes:

1. **Immediate, low-risk**: widen `_TABLES_CACHE_TTL_SECONDS` (and, consistently,
   `_VALUE_RULES_CACHE_TTL_SECONDS`/`_RULE_JOIN_DATA_CACHE_TTL_SECONDS`, since all
   three share this exact exposure) from 30s to a value that comfortably survives
   realistic turn-to-turn gaps — e.g. 10-15 minutes. This alone converts most
   same-session turns from a guaranteed fresh scan into a module-cache hit.
2. **Complete fix**: add an explicit invalidation call at the point a re-ingest
   actually completes (`ingest_confirmed()`, `doc_discovery.py:1108`) —
   `_clear_tables_cache()` / `_clear_value_rules_cache()` / `_clear_rule_join_data_
   cache()` for the affected workspace. Once staleness is guarded by a real event
   instead of a timer, the TTL stops being a freshness/latency tradeoff at all — it
   becomes a pure backstop, and can be set generously (or even removed in favor of
   invalidation-only) without a staleness risk being introduced.

### Impact after fix

`_load_all_tables` averaged 14.95s per turn across the 6-turn sample specifically
because every turn fell outside the 30s window. With a TTL wide enough to cover
normal turn pacing, only the first turn of a session (or the first turn after a real
re-ingest) pays this cost — every subsequent turn in the same session should see
this cost center drop to effectively zero (a module-cache hit, same cost class as
the thousands of already-free "call-local" hits observed). Across the 6-turn
sample, that's up to **~75-90s of the observed 89.7s total** becoming avoidable.

---

## Combined expected impact (both fixes)

These two costs overlap inside the same `evaluate_rules_loop` measurement window, so
their savings are additive against the 429.7s / 6-turn total observed:
- RC1: ~150-200s
- RC2: ~75-90s

That's roughly **225-290s of the ~430s total becoming avoidable** in this sample —
turns that currently average 71.6s (up to 185.9s) plausibly dropping toward a floor
set mostly by unavoidable costs: the LLM call(s) each turn actually needs (~5.3s avg
observed) plus whatever residual deterministic work remains after both fixes (a
single, now-shorter rule-evaluation pass, plus the one-time-per-session table scan).
**These are estimates from a 6-turn sample, not a guarantee** — real verification
requires re-running equivalent live scenarios after implementing and re-measuring
from the same logs, per this session's established rigor.

## Measured results after implementation (2026-08-19)

Both fixes implemented, unit-tested, full-regression-verified (identical 9
pre-existing failures, 101 files passing, 0 timeouts — see Verification below), then
live-measured against a rebuilt, redeployed `api` container.

### RC1 — per-turn `auto_fill` cost, on a clean, isolated, cold-start turn

| Metric | Before (avg per 8-pass turn) | After (same turn shape, measured) | Change |
|---|---|---|---|
| `auto_fill` total cost across all 8 passes | ~27.6s (8 × 3.45s avg) | **0.486s** | **~98% reduction** |
| Pass 0 (real derivation, unavoidable) | — | 9.999s | unchanged, expected |
| Passes 1-7 combined | previously repeated ~3.45s auto_fill cost 7 more times | **~8.8s total for all remaining passes** | |

Pass count itself is still **8/8** — the outer convergence check doesn't converge
early for this catalog for reasons unrelated to `default_first_available`. The win is
that each pass is now dramatically cheaper, not that there are fewer passes.

### RC2 — `_load_all_tables` fresh-scan frequency, across a full conversation

| Metric | Before | After |
|---|---|---|
| Fresh scans | 1 per turn (30s TTL always expired between turns) — avg 14.95s/turn, up to 32.6s | **1 total across the whole multi-turn conversation** (only the first turn scans; later turns hit the module cache) |

### Full end-to-end request time — before vs after, by turn type

**Product-selection cascade turn** (the heaviest turn type — triggers full rule
re-evaluation across ~300+ attributes; same live scenario measured both times):

| | Before | After |
|---|---|---|
| Sample 1 | 272.8s | 192.4s |
| Sample 2 | 233.1s | — |

**~29% reduction** on the single heaviest, most representative turn.

**Initial config-load turn** ("I want a quote/configure APX NEXT..."):

| | Before | After |
|---|---|---|
| Sample 1 | 36.7s | 43.6s |
| Sample 2 | 71.3s | — |

Roughly flat — expected, since this turn is a genuine cold start for both fixes (no
prior-turn cache for RC2 to help with, no prior-pass signature for RC1 to compare
against) and its cost is dominated by things neither fix targets (LLM extraction,
first-time table scan, first-pass rule derivation).

**Quantity-change / status-question turns** (lighter paths that never touch the
rule-evaluation loop at all):

| Turn | After |
|---|---|
| "change the quantity" | 18.0s |
| "change the quantity to 5" | 25.1s |
| "what is the next step for configuration" | 15.9s |

**No "before" number exists for these** — this exact 4-turn scenario was never run
against the unfixed codebase earlier in this session, so no honest before/after delta
can be claimed here. Since these turns don't touch the rule-evaluation loop, RC1/RC2
weren't expected to move them regardless.

### Follow-up investigation (2026-08-19): what was actually consuming the "unexplained" time

The gap flagged above was chased down with targeted instrumentation rather than left
as a guess. Two real findings:

1. **A second, separately-logged LLM call was being missed.** The answer/narration
   call (`cpq_llm_runtime`, model `gemini-3.1-pro-preview`) was the only one being
   tracked. The intent gateway's own classification call uses a completely different
   logging convention (`cpq_intent_gateway`, `intent_gateway.py:296-305`, model
   `gemini-2.5-pro`) that the earlier log analysis never grepped for — a real second
   LLM round-trip (6-8s) on any turn that needs actual classification (not every
   turn — a message matching a deterministic path, e.g. "change the quantity" with
   no explicit number, skips it entirely).
2. **`_attach_share_flags` (`ask_api.py:11458`) — a genuine, previously-invisible
   cost center, not a fix target, a new finding.** This function builds the web UI's
   JSON/Beautify preview payload and runs **unconditionally on every "ready" turn**
   (≥3 filled attrs, or once no longer "configuring"), regardless of whether the
   customer ever opens either panel. Measured directly (new `cpq_perf` log lines
   added, `ask_api.py:11458-11526`): **4.8-6.5s per turn**, dominated by an
   uncached `load_product_config` catalog re-fetch (4.6-6.2s of that).

| Turn | Gateway classify LLM | Answer/narration LLM | `_attach_share_flags` | Turn total |
|---|---|---|---|---|
| "change the quantity" | — (deterministic match) | 3.7s | 4.8s | 17.8s |
| "change the quantity to 5" | 6.4s | 2.8s | 5.6s | 23.0s |
| "next step for configuration" | (similar range) | ~2.8s | 6.5s | 18.7s |

These three cost centers, once correctly attributed, account for nearly the entire
turn duration in every case — closing the observability gap. The instrumentation
added to find this (`_attach_share_flags`'s two new `cpq_perf` log lines) is kept
permanently, matching this codebase's existing `cpq_step`/`cpq_perf` convention, so
this cost is never invisible again.

**Not fixed as part of this investigation** — `_attach_share_flags` running
unconditionally on every turn (rather than lazily, only when the customer actually
opens the JSON/Beautify panel) is a real, scoped optimization opportunity surfaced
by this work, deliberately left as a separate follow-up rather than bundled into
this fix.

### Correctness

Replayed the exact live scenario 3 times against the fixed, redeployed branch — all
answers identical to expected pre-fix behavior (Hardware Version → Quantity →
resume reminder → status short-circuit). No regressions observed.

### Honest gap this work does not close

The Product-selection cascade turn still takes ~192s even after both fixes — a real,
separate, unaddressed slow path. Its cost isn't concentrated in `auto_fill` or
`_load_all_tables`; something else (likely `_apply_series_mapping_exclusions` or
another rule-evaluation cost center specific to that cascade) dominates it and would
need its own investigation.

## Live testing results after rebase (2026-08-21)

Full live re-verification against the rebased branch (`perf/cpq-turn-latency-only-
2026-08-21`, merge commit `557ac03` onto current `dev-rv-msi`, 55 commits ahead of
where this plan was originally implemented). Purpose: confirm RC1 and RC2 still
function correctly against the much-changed codebase, not just that the merge was
textually clean.

**Setup**: `docker compose build api && docker compose up -d --force-recreate
--no-deps api` on the rebased branch; confirmed `healthy` and `/health` → 200
before testing. Replayed the same live APX NEXT scenario (workspace 39004) used for
this plan's original measurements, via direct `POST /ask` calls against the running
container (`http://localhost:8088`), extended with the lighter-path and cache-TTL
scenarios from the original plan's own verification checklist. 9 turns total, one
fresh session, real Postgres-backed catalog data — not mocked.

| # | Turn | Elapsed | What it exercises |
|---|---|---|---|
| A1 | "I want a quote for APX NEXT" | 11.4s | cold-start init, no rule loop yet |
| B1 | "United States" | 20.6s | first rule-loop pass |
| B2 | "APX NEXT (4G LTE+5G)" | 26.1s | rule loop, Hardware Version gates Product |
| B3 | "APX NEXT Enhanced" | 26.5s | product-selection cascade (heaviest turn type) |
| B4 | "H55TGT9PW8BN" | 27.3s | base model selection, further cascade |
| C1 | "change the quantity" | 25.7s | lighter path — should skip the rule loop |
| C2 | "change the quantity to 5" | 31.9s | lighter path — should skip the rule loop |
| C3 | "what is the next step for configuration" | 22.0s | status-question path — should skip the rule loop |
| D1 | "Set SmartProgramming to 2Yrs" (after a deliberate 35s sleep) | 29.7s | RC2 cache TTL survives realistic turn-to-turn think-time |

### RC1 verification — `auto_fill` cost per pass, live

Every turn that actually reached `evaluate_rules_loop` (B1-B4, D1 — confirmed by
grepping `cpq_step: evaluate_rules_loop done` in the container logs; C1-C3 correctly
show **no** `evaluate_rules_loop` line at all, confirming the lighter paths still
bypass the rule loop entirely post-rebase) ran the full `passes=8`, matching this
plan's original finding that RC1 doesn't reduce pass count — it makes each pass
cheap. Per-pass `auto_fill` cost, turn B4 (base model — the heaviest of the five):

| pass | auto_fill cost |
|---|---|
| 0 | 0.206s |
| 1 | 0.076s |
| 2 | 0.082s |
| 3 | 0.024s |
| 4 | 0.029s |
| 5 | 0.076s |
| 6 | 0.023s |
| 7 | 0.030s |
| **total (8 passes)** | **0.546s** |

All five rule-loop turns landed in the same range — total `auto_fill` cost across
all 8 passes stayed under 0.61s in every case (B1: 0.606s, B2: 0.194s, B3: 0.515s,
B4: 0.546s, D1: 0.206s), against this plan's own documented pre-fix baseline of
~27.6s (8 × 3.45s avg) for the same 8-pass shape. That's a **~97-99% reduction**,
consistent with (and slightly better than) the ~98% reduction measured at original
implementation time — confirming the signature-gating fix still works correctly
against `dev-rv-msi`'s 55 additional commits, including the newer
recommendation/constraint-rule handling those commits introduced.

### RC2 verification — cross-request table cache, live

Aggregated `_load_all_tables` cache outcomes across the entire 9-turn session
(container logs, `cpq.data_table_resolver`):

| Outcome | Count |
|---|---|
| CACHE HIT (call-local) | 8,177 |
| CACHE HIT (module) | 1,378 |
| MISS (fresh scan) | **1** (took 1.659s) |

Exactly one fresh scan for the entire session — the unavoidable first one on turn
A1 — and every subsequent turn hit the module-level cross-request cache, **including
D1, which followed a deliberate 35s sleep** (longer than the pre-fix 30s TTL that
this plan's RC2 specifically widened). This directly confirms the widened TTL
survives realistic turn-to-turn think-time post-rebase. The invalidation half of
RC2 (`ingest_confirmed()`'s cache-clear calls) was not exercised in this pass — no
re-ingest was triggered during this session — so that specific behavior still
relies on the unit test coverage added at original implementation time, not fresh
live evidence here.

### Correctness

The full scenario replayed with identical shape to prior sessions: Country →
Hardware Version → Product → Base Model → (configuration flagged incomplete,
re-asks Product/Feature Type) → quantity changes → status question → SmartProgramming
update, all producing coherent, expected answers. No crash, no stale/incorrect
auto-fill observed, no exceptions in the container logs across any of the 9 turns.
One pre-existing, unrelated behavior was reproduced identically to before this
rebase: after selecting base model `H55TGT9PW8BN`, the assistant re-asks Product and
then (once quantity/status turns are interleaved) degrades to "328 available
options, type the exact name" for Product — this is the same catalog/rule-governed
behavior observed and separately investigated in this session's `andie-jr` brownfield
debugging pass, unrelated to RC1/RC2, present on `dev-rv-msi` independent of this
branch, and outside this plan's scope.

### New observation confirmed still present post-rebase

The `_attach_share_flags` cost center flagged as a "not fixed, follow-up" finding in
this plan's original measurement (lazy JSON/Beautify preview) is confirmed to still
run unconditionally and remains the single largest cost component per turn on this
branch, since the lazy-preview work was intentionally dropped from this rebase (see
the 2026-08-21 update note at the top of this doc):

| Turn | `_attach_share_flags` (`load_product_config`) cost |
|---|---|
| A1 | — (turn not yet "ready", not triggered) |
| B1 | 6.98s |
| B2 | 7.81s |
| B3 | 7.17s |
| B4 | 7.23s |
| C1 | 7.24s |
| C2 | 7.10s |
| C3 | 6.92s |
| D1 | 7.32s |

Consistently ~7-7.8s per turn, on every turn from B1 onward — this now accounts for
roughly a quarter to a third of most turns' total wall-clock time (e.g. B2:
7.81s of 26.1s total). This is expected and unchanged from the original plan's own
finding; it is explicitly out of scope for RC1/RC2 and is the reason the (separately
tracked, currently un-merged into this branch) lazy-preview work exists at all.

## RC3 — paired-value invalidation false positives defeating RC1's gate (2026-08-24)

### Problem, discovered live

Live-testing the rebased branch through the web UI, the "APX NEXT Enhanced" product-
selection cascade turn took **792.6s** — far worse than the 26.5s measured for the
same turn shape during the Aug 21 verification pass. Tracing the run
(`run_id=9a9598d61c244bbf86b494f84fc46b59`, workspace 39005, catalog prefix
`ApxnextConfigdata`, base model `H55TGT9PW8BN`) showed `evaluate_rules_loop` itself
took 630s, with `auto_fill` costing **37-65s per pass** across all 8 passes — the
*pre-RC1* magnitude, not RC1's normal ~0.5s/pass.

### Root cause 1 — `find_inconsistent_filled_pairs_detailed` over-links narrow
exception rows onto an attribute's general domain

`_invalidate_inconsistent_paired_values` (`engine.py:7657-7700`, a `dev-rv-msi`
feature independent of RC1/RC2) runs after every `auto_fill` call and evicts any
auto-filled (non-confirmed) attribute whose currently-filled combination
contradicts a real ingested Data Table pairing — intended to catch genuine
cross-attribute contradictions like `modelSelectionFrequencyBands_astro`/
`modelSelectionFrequencyBandPlus_astro` independently auto-filling to the same
band when every real row pairs them with *different* bands
(`docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md`).

Direct investigation against the live workspace-39005 catalog (script run against
the same Postgres instance the container uses, calling the real
`_cpq_model_candidates`/`_load_all_tables`/`find_inconsistent_filled_pairs_detailed`
functions — not guessed) found the same ~14 attributes perpetually re-invalidated
on every one of the 8 passes without ever resolving. Two concrete, real-data-proven
causes:

1. **Narrow exception rows misapplied as an exhaustive pairing.**
   `find_inconsistent_filled_pairs_detailed` (`data_table_resolver.py:790-824`)
   treats *any* scoped row where both `attr1` and `attr2` are non-null and both are
   currently filled as proof the two attributes are permanently linked (line
   807-810), then requires the filled combo to match *some* row for that exact
   pair — correct when a pair's rows are a genuinely exhaustive enumeration (Bands/
   BandPlus: neither attribute ever appears in a standalone row), wrong when an
   attribute *also* has independent standalone (`attr2=None`) rows proving a
   broader domain. Confirmed live: `additionalSystemEnhancementFeatureType_astro`
   has 4 legitimate standalone values (`FPS APX TEST TRIGGER SR`, `ICE KIT`,
   `FPS APX TEST TRIGGER - SW VALIDATION`, `SEQUENTIAL SERIAL NUMBER`) *plus* one
   narrow exception row pairing it with `ultimateDestinationCountry` —
   `('DELETE NARROWBANDING-WAIVER REQUIRED', 'US')`, a specific waiver SKU, not a
   general rule. Once `ultimateDestinationCountry='US'` is filled (from the
   customer's own "United States" answer), the checker wrongly treats that one
   exception row as the pair's entire truth table, so *any* of the 4 legitimate
   standalone values fails the match and gets invalidated forever. The identical
   shape was confirmed for `subscriptionBillingAddDMSCoverage_astro` (linked to
   `ultimateDestinationCountry` via one `CA`-only row) and
   `additionalSystemEnhancementFeatureType_astro`'s separate narrow links to
   `customerType`/`customerUIN`.
2. **Union instead of intersection across cross-SKU `CPQModel` candidates — a
   real, separate defect, found by code reading, not confirmed as an active
   contributor to this specific incident.** `_invalidate_inconsistent_paired_
   values` calls `_cpq_model_candidates(...)`, which for this base model
   correctly returns multiple real candidates — `('APXNEXTENHANCED',
   'APXNEXTXN5G', 'APXNEXTENHANCED-btaDele')`, a genuine cross-SKU base-model-
   sharing case per that function's own docstring — then takes the **union** of
   what each candidate considers invalid (`invalid |= dt_find_inconsistent_
   filled_pairs(...)`). Initially suspected as the cause of `'ICE KIT'`/`'SINGLE
   PACK CLAMSHELL'` being invalidated (valid under `APXNEXTENHANCED`, the actual
   confirmed product, but absent from `APXNEXTXN5G`'s rows) — **on closer
   reading this turned out not to be how those two values actually got
   flagged**: `find_inconsistent_filled_pairs`'s `linked_pairs` only ever
   includes rows where BOTH `attr1` and `attr2` are non-null (`data_table_
   resolver.py:834-837`), so a purely standalone value like `'ICE KIT'` (only
   ever appearing in an `attr2=None` row) never enters a linked pair at all,
   regardless of which candidate model is checked — union vs. intersection is a
   no-op for it. Root cause 1 above (the narrow-exception-row over-linking) is
   sufficient on its own to explain all 14 attributes' invalidation. The union-
   vs-intersection defect is still real and worth fixing (a genuine two-
   attribute linked-pair row that legitimately differs between two base-model-
   sharing candidates would still be wrongly vetoed today), just not proven to
   be load-bearing for *this* incident — fixed as defense-in-depth alongside
   root cause 1, verified by a dedicated unit test rather than by live
   reproduction.

### Root cause 2 — RC1's broad signature has no defense against a churning subset

RC1's `_fill_signature` is deliberately the *whole* `filled` dict (a documented,
intentional choice — see "What the signature is" above — to never silently miss a
real dependency). Because the ~14 falsely-invalidated attributes get evicted from
`filled` at the end of *every* pass, the signature differs pass-over-pass for
*every* `default_first_available` attribute, not just those 14 — defeating RC1's
gate for the entire turn and forcing full unconditional `auto_fill` re-derivation
(~40-65s) on all 8 passes. RC1 and `_invalidate_inconsistent_paired_values` were
built independently (different sessions, different authors), each individually
correct in isolation, but interacting badly: one's "broad signature for safety"
assumption breaks down against the other's "clear non-converging guesses every
pass for correctness" behavior. Root cause 1's fix should eliminate this specific
stall; root cause 2 needs its own fix as insurance against any *future*
non-converging pairing this analysis didn't cover — a permanently-unresolvable
conflict is itself a legitimate scenario this codebase already has a surfacing
path for (`find_confirmed_data_table_conflicts`, the both-confirmed re-ask plan).

### Fix A — correctness: stop the over-linking at its source

**A1 — standalone-VALUE exclusion in `find_inconsistent_filled_pairs_detailed`.**
Scoped to the specific filled *value*, not the whole attribute — filling the
narrow exception row's own value with a mismatching second attribute is still a
real, data-proven contradiction and must still be caught (that specific value has
no standalone row of its own to exempt it). Compute, once per `scoped` row-set,
`standalone_values = {(attr, value) with a row where the partner side is None}`;
when checking a linked pair's match, skip enforcement if either side's *current*
value is in that set:

```python
standalone_values = {
    (r.get("attr1"), r.get("val1")) for r in scoped
    if r.get("attr1") and r.get("val1") and not r.get("attr2")
} | {
    (r.get("attr2"), r.get("val2")) for r in scoped
    if r.get("attr2") and r.get("val2") and not r.get("attr1")
}
...
for attr_a, attr_b in linked_pairs:
    val_a, val_b = filled.get(attr_a), filled.get(attr_b)
    if (attr_a, val_a) in standalone_values or (attr_b, val_b) in standalone_values:
        continue  # this side's value is independently valid on its own
    matches = any(...)  # existing match check, unchanged
```

Leaves the genuine Bands/BandPlus case untouched (no standalone rows for either
side's values) while suppressing the false positive for a legitimate standalone
value (e.g. `additionalSystemEnhancementFeatureType_astro='ICE KIT'`) without
losing detection of the exception row's own value used incorrectly (e.g.
`='DELETE NARROWBANDING-WAIVER REQUIRED'` paired with a non-`US` country).

**A2 — intersection instead of union across `CPQModel` candidates in
`_invalidate_inconsistent_paired_values`.** A combo is only a real contradiction
if *no* candidate model accepts it — matching the "try each candidate, only fail
if all fail" fallback philosophy `_cpq_model_candidates` already documents for
itself:

```python
per_model_invalid = [
    dt_find_inconsistent_filled_pairs(cpq_model, base_model, filled, workspace_id, catalog_prefix, cache)
    for cpq_model in cands
]
invalid = set.intersection(*per_model_invalid) if per_model_invalid else set()
```

### Fix B — performance containment (defense in depth, independent of Fix A)

Track repetition of the invalidated set across consecutive passes in
`evaluate_rules_loop`. Once the *same* set has failed to resolve two passes
running (proven non-convergent noise, not merely "this pass differs from last"),
exclude those specific keys from what's fed into `_fill_signature(...)` for every
*other* attribute's gate — without suppressing re-derivation of the oscillating
attributes themselves:

```python
if inconsistent_vns and inconsistent_vns == _last_inconsistent_vns:
    _oscillating_vns |= inconsistent_vns   # local to this evaluate_rules_loop call
else:
    _last_inconsistent_vns = inconsistent_vns

_sig_filled = {k: v for k, v in filled.items() if k not in _oscillating_vns}
_cur_sig = _fill_signature(_sig_filled, filled_multi, visible_ids)
```

This isolates the blast radius to only the attributes proven to be churning,
restoring RC1's gate for everything else starting the pass after oscillation is
detected, regardless of *why* something is oscillating — it is a safety net, not a
substitute for Fix A.

### Test coverage plan (implemented 2026-08-24)

- `tests/test_cpq_data_table_resolver.py`:
  - `test_standalone_domain_attr_not_flagged_by_a_narrow_exception_pairing` — an
    attribute with both a standalone domain (`attr2=None` rows) and a narrow
    exception link to a second, already-filled attribute is **not** flagged
    inconsistent when its filled value is one of its standalone values (the
    false-positive this fix removes) — mirrors the real
    `additionalSystemEnhancementFeatureType_astro`/`ultimateDestinationCountry`
    shape with synthetic attribute names.
  - `test_narrow_exception_pairing_still_enforced_for_its_own_value` — the
    exception row itself is still enforced when the filled value *is* the narrow
    exception's own value (`DELETE NARROWBANDING-WAIVER`) paired with a
    *mismatching* second value — confirms A1's value-level (not attribute-level)
    scoping doesn't blanket-disable detection.
  - Existing `test_find_inconsistent_filled_pairs_flags_a_real_contradiction`/
    `..._none_for_a_real_valid_combination`/`..._ignores_unlinked_attrs`/
    `..._detailed_returns_the_actual_pair`/`..._detailed_matches_flat_version_when_valid`
    re-run unchanged and green — all use fixtures with zero standalone rows for
    the Bands/BandPlus pair, confirming A1 doesn't regress the feature's original
    purpose.
- `tests/test_cpq_auto_fill_data_table_tier.py` (already had `_cpq_model_candidates`
  coverage — added alongside it):
  - `test_invalidate_inconsistent_paired_values_uses_intersection_not_union` — a
    value valid under one real `CPQModel` candidate (the confirmed product) but
    invalid under a different, also-real candidate sharing the same base model is
    **not** flagged (A2's intersection-not-union fix) — synthetic two-candidate
    fixture mirroring the real `APXNEXTSINGLE`/`APXNEXTXNSINGLE` base-model-sharing
    shape.
  - `test_invalidate_inconsistent_paired_values_still_flags_a_real_contradiction` —
    a value invalid under **every** candidate is still correctly flagged
    (intersection still catches a genuine contradiction, doesn't silently pass
    everything through).
- `tests/test_cpq_rule_loop_perf_gating_2026_08_19.py` (RC1's own suite) — tested
  at the `auto_fill`/`_signature_exclude_vns` mechanism level (the actual unit Fix
  B introduces), rather than a full `evaluate_rules_loop` integration test (would
  require substantial fixture engineering — real hiding/constraint rules,
  per-candidate Data Table rows — to organically trigger oscillation; the
  mechanism-level tests below plus the live re-verification give equivalent
  confidence more cheaply):
  - `test_signature_exclude_vns_keeps_the_gate_held_despite_an_unrelated_key_changing`
    — an unrelated key's value changing (simulating a churning, non-convergent
    attribute) does NOT break an unrelated attribute's gate when that key is
    excluded from the signature snapshot.
  - `test_without_exclusion_the_same_unrelated_change_breaks_the_gate` — negative
    control proving the exclusion itself is what holds the gate (identical setup,
    no exclusion, gate legitimately breaks) — confirms the test isn't a false
    positive.
  - `test_signature_exclude_vns_none_is_a_complete_noop` — `None` (every
    pre-existing call site) behaves identically to omitting the parameter.
- Full CPQ regression suite (`pytest tests/ -k cpq`) re-run after implementing;
  any failure/timeout individually confirmed against the established 13
  pre-existing-failure baseline before being accepted.
- Live re-verification: replay the exact "APX NEXT Enhanced" cascade turn
  (workspace 39005, base model `H55TGT9PW8BN`) against a rebuilt, redeployed `api`
  container; confirm `evaluate_rules_loop`'s pass-8 `auto_fill` costs return to the
  ~0.5s/pass range and the turn completes in the 20-30s range measured for
  equivalent turns during Aug 21 verification, not the 792s regression.

### Results (implemented and live-verified, 2026-08-24)

**Unit/regression tests**: all 7 new tests pass
(`test_standalone_domain_attr_not_flagged_by_a_narrow_exception_pairing`,
`test_narrow_exception_pairing_still_enforced_for_its_own_value`,
`test_invalidate_inconsistent_paired_values_uses_intersection_not_union`,
`test_invalidate_inconsistent_paired_values_still_flags_a_real_contradiction`,
`test_signature_exclude_vns_keeps_the_gate_held_despite_an_unrelated_key_changing`,
`test_without_exclusion_the_same_unrelated_change_breaks_the_gate`,
`test_signature_exclude_vns_none_is_a_complete_noop`). Full CPQ regression suite
(`pytest tests/ -k cpq`) re-run: **13 failed, 1345 passed, 47 skipped** — identical
13 failure names to the established pre-existing baseline (previously 1338 passed;
the +7 is exactly the new tests), zero new regressions.

**Live replay of the exact incident scenario** — rebuilt and redeployed the `api`
container on the fixed branch, then replayed the same "APX NEXT Enhanced"
product-selection cascade turn (workspace 39005) that produced the original 792.6s
incident:

| Metric | Before (2026-08-24 incident) | After (RC3 fix, same scenario) | Change |
|---|---|---|---|
| Total turn time (`request_end elapsed_s`) | 792.6s | **317.6s** | **~60% reduction** |
| `evaluate_rules_loop` total | 630.0s | **245.8s** | **~61% reduction** |
| `_invalidate_inconsistent_paired_values`'s `inconsistent=` | ~14 attrs, every single one of the 8 passes | **`[]` on every single pass** | false-positive churn fully eliminated |
| `auto_fill` per pass | 37-65s | 13-28s | reduced ~50-60%, but not down to RC1's normal ~0.5s/pass |

**Fix A confirmed working exactly as designed**: `inconsistent=[]` held on all 8
passes of the replayed turn — direct proof the narrow-exception-row over-linking
bug (Root cause 1) no longer fires. This was the specific defect causing the
original 630s outer-loop stall, and it is gone.

**Fix B had nothing to isolate on this run** — with Fix A already preventing the
churn from occurring at all, there was no oscillating set for Fix B's circuit
breaker to act on. This is expected and correct: Fix B is defense-in-depth for a
*future* non-converging pairing this analysis didn't cover, not the mechanism that
fixed this specific incident.

**Honest gap — what RC3 did NOT fix, by design**: `auto_fill` still costs
13-28s/pass on this specific turn, not RC1's normal ~0.5s/pass. This is a
*separate, legitimate* cost, not a residual bug: a Base Model/Product selection
turn brings hundreds of previously-hidden attributes into governance for the first
time in one turn, and RC1's gate correctly does **not** suppress derivation when
something is genuinely, newly resolvable — that is the gate's intended safety
property (see "What problem the signature actually solves" above), not a defect.
This matches an already-documented, pre-existing honest gap from this plan's
original Aug 19 measurement: *"The Product-selection cascade turn still takes
~192s even after both fixes... a real, separate, unaddressed slow path."* RC3
targeted and eliminated the specific oscillation defect (Root causes 1-2 above);
it was never intended to address this separate, already-known cost driver, which
remains open for a future, dedicated investigation.

## RC4 — a second, structurally identical churn source: `resync_stale_recommendations` (2026-08-24)

### Problem, discovered live

Immediately after RC3 shipped, a real live user test of the exact same "APX NEXT
Enhanced" turn (workspace 39005) took **836.98s total** — *worse* than the original
792.6s incident — despite `_invalidate_inconsistent_paired_values` correctly
reporting `inconsistent=[]`/`inconsistent=0` on every single one of the 8 passes
(direct proof RC3's fix was NOT regressing and its specific bug was not recurring).
`evaluate_rules_loop` itself took 669.1s (vs. 630.0s in the original incident) with
`auto_fill` costing 37-82s per pass throughout — RC1's gate was being defeated
again, but by something RC3 didn't cover.

### Root cause — a second correction mechanism with the identical interaction shape

Tracing the same `run_id`'s full logs surfaced `"cpq: resynced stale
recommendation-governed attrs ['getDataFromCookieFlag']"` firing on **every single
one of the 8 passes**, not just once. `resync_stale_recommendations`
(`engine.py:5953-6076`) re-applies recommendation rules to attributes the engine
itself already auto-filled, correcting them when a driving attribute's value
changes on a later pass (intended for the documented "first-by-order claimed it
before the real condition could be checked" race). Its own docstring already
documents the exact failure class this exposed: *"Live regression: auto_fill
correctly fell back to 'ESSENTIAL' once Hardware Version activated a constraint
excluding 'ADVANCED', but this method ran right after (same pass) and — seeing its
own unrelated condition (Solution Type) still held, with no constraint awareness at
all — 'resynced' it straight back to the excluded value, every single pass."` —
i.e. this is a previously-known, still-open correctness gap in the function itself,
now newly confirmed to also defeat RC1's gate.

Its corrections are applied directly into `filled` every pass
(`engine.py:6870-6874`, `filled[k] = iv`), unconditionally, with no gate of its own.
Since `getDataFromCookieFlag`'s value genuinely, permanently disagrees between what
`auto_fill` derives and what this method recommends — a real ping-pong, not a
one-time correction — `filled` changes on every pass regardless of whether
`_invalidate_inconsistent_paired_values` finds anything. Per RC3's own broad-
signature design (`_fill_signature` is the whole `filled` dict, deliberately), this
single oscillating attribute is enough to change the signature for every OTHER
`default_first_available` attribute too — the identical interaction shape as RC3's
Root cause 2, just via a second, independent churn source RC3's fix never covered.

### Fix — generalize RC3's containment to both known churn sources

Rather than patch `resync_stale_recommendations`'s own disagreement logic (a
separate, deeper investigation — see "Not fixed" below), RC4 generalizes RC3's
Fix B containment mechanism to cover this second source using the identical
pattern: track the corrected variable names from `resync_stale_recommendations`
across consecutive passes with their own independent "last seen" tracker
(`_last_resync_vns`, alongside RC3's `_last_inconsistent_vns`), both feeding the
same shared `_oscillating_vns` set an attribute alternating between the two
mechanisms is still caught by either tracker):

```python
_last_inconsistent_vns: frozenset[str] = frozenset()   # RC3
_last_resync_vns: frozenset[str] = frozenset()          # RC4
_oscillating_vns: set[str] = set()                      # shared by both

...
_resynced = self.resync_stale_recommendations(...)
_frozen_resynced = frozenset(_resynced.keys()) if _resynced else frozenset()
if _frozen_resynced and _frozen_resynced == _last_resync_vns:
    _oscillating_vns |= _frozen_resynced
_last_resync_vns = _frozen_resynced
if _resynced:
    for k, (iv, d) in _resynced.items():
        filled[k] = iv
        ...
```

No change was needed to `auto_fill`'s `_signature_exclude_vns` mechanism itself
(RC3's Fix B) — it already excludes whatever is in `_oscillating_vns` regardless of
which tracker populated it, so RC4 is purely an accumulation-side change.

### Not fixed as part of RC4 — deliberately out of scope

`resync_stale_recommendations`'s own root disagreement with `auto_fill` for
`getDataFromCookieFlag` is NOT fixed at the source. Its own docstring already
flags that it has "no constraint awareness" in the general case — a real,
separate, previously-documented correctness gap (not introduced by this session)
that would need its own dedicated investigation into why this specific attribute's
recommendation never agrees with its derivation. RC4 contains the *performance*
blast radius exactly like RC3 did for the pairing-invalidation case, without
requiring that deeper fix to land first — matching Fix B's original stated
purpose: "insurance against any future non-converging pairing this analysis
didn't cover," now proven necessary for a source beyond the one RC3 covered.

### Test coverage

RC4 changes only what feeds `_oscillating_vns`, not the gate mechanism itself
(`_signature_exclude_vns` in `auto_fill`) — already covered by RC3's
`test_signature_exclude_vns_keeps_the_gate_held_despite_an_unrelated_key_changing`/
`test_without_exclusion_the_same_unrelated_change_breaks_the_gate`/
`test_signature_exclude_vns_none_is_a_complete_noop` in
`tests/test_cpq_rule_loop_perf_gating_2026_08_19.py`. A dedicated
`evaluate_rules_loop`-level integration test proving the NEW `_last_resync_vns`
tracker itself correctly detects two-consecutive-identical-corrections is
deliberately deferred for the same reason RC3's own loop-level test was — it would
require substantial fixture engineering (real recommendation rules whose condition
permanently disagrees with a real `auto_fill` derivation) to organically trigger;
live re-verification (below) plus the shared gate mechanism's existing unit
coverage give equivalent confidence more cheaply.

### Results (live-verified, 2026-08-24)

Full CPQ regression suite (`pytest tests/ -k cpq`) re-run after implementing RC4:
**13 failed, 1345 passed, 47 skipped** — identical 13 failure names to the
established baseline, zero new regressions.

**Live re-verification of the exact same "APX NEXT Enhanced" turn, RC4-only**:
`evaluate_rules_loop` = **222.0s** (down from 669.1s with only RC3, down from the
original 630.0s incident), total request = **295.0s** (down from 836.98s RC3-only,
down from the original 792.6s incident) — a real, substantial improvement, but far
from RC1's normal ~1-2s ideal for this turn shape. This gap led directly to RC5
below.

## RC5 — RC3/RC4's oscillation detector used exact set equality, not intersection (2026-08-24)

### Problem, found during RC4's own live verification

Tracing the RC4-fixed live run's `"resynced stale recommendation-governed attrs"`
lines pass-by-pass: pass 0 corrected `['getDataFromCookieFlag']`, pass 1 corrected
`['packingPackageType_astro', 'getDataFromCookieFlag']`, pass 2 corrected
`['getDataFromCookieFlag']` again. `getDataFromCookieFlag` never stopped churning —
but the SETS were never twice identical (`packingPackageType_astro` sporadically
joined/left), so RC3's and RC4's `_frozen_X == _last_X` exact-equality check never
matched, `_oscillating_vns` was never populated, and RC1's gate stayed defeated for
the whole turn despite the oscillation-containment code being live and running.

### Fix — intersection, not exact equality

Changed both trackers (RC3's `_last_inconsistent_vns`, RC4's `_last_resync_vns`) to
fold the **intersection** of this pass's and the previous pass's set into
`_oscillating_vns`, instead of requiring the two full sets to match exactly:

```python
_oscillating_vns |= (_frozen_inconsistent & _last_inconsistent_vns)   # RC3, was: if == then |=
_oscillating_vns |= (_frozen_resynced & _last_resync_vns)             # RC4, was: if == then |=
```

A vn present in both consecutive sets is proven non-convergent for *that vn*
specifically, regardless of what else sporadically joins or leaves the set. A vn
that genuinely stops needing correction (real convergence) is correctly absent
from the next pass's set, so it's never added — the containment is exactly as
targeted as before, just no longer defeated by an unrelated attribute's noise.

### Test coverage

No new tests needed — RC5 only changes the accumulation logic feeding
`_oscillating_vns` inside `evaluate_rules_loop`; the gate mechanism it feeds
(`auto_fill`'s `_signature_exclude_vns`) is unchanged and already covered by RC3's
three tests in `tests/test_cpq_rule_loop_perf_gating_2026_08_19.py`. Existing
targeted re-run (`test_cpq_rule_loop_perf_gating_2026_08_19.py`,
`test_cpq_data_table_resolver.py`, `test_cpq_auto_fill_data_table_tier.py`,
`test_cpq_proactive_stale_constraint_reask.py`) stayed at the same 3 pre-existing
failures, zero new regressions.

### Results (live-verified, 2026-08-24)

Full CPQ regression suite re-run after RC5: **13 failed, 1345 passed, 47 skipped**
— identical failure names to the established baseline, zero new regressions.

Live re-verification of the exact same "APX NEXT Enhanced" turn, rebuilt and
redeployed with RC5 in place:

| Fix state | Total turn time | `evaluate_rules_loop` |
|---|---|---|
| Original incident | 792.6s | 630.0s |
| RC3 only | 836.98s (regression) | 669.1s |
| RC4 (before the RC5 intersection fix) | 295.0s | 222.0s |
| **RC5** | **273.3s** | **202.9s** |

Net result across this whole investigation: **792.6s → 273.3s, a ~66% reduction**.
`_invalidate_inconsistent_paired_values` reported `inconsistent=[]` on every pass
throughout (RC3's fix holding), and `getDataFromCookieFlag`'s persistent churn was
confirmed correctly detected and excluded from pass 2 onward (RC5's intersection
fix working as designed) — per-pass `auto_fill` cost dropped from 37-82s (original)
to a plateau of 5-16s, decreasing pass-over-pass as more churning attributes were
identified.

**Honest remaining gap**: the plateau (5-16s/pass `auto_fill`, ~15-20s/pass total)
did not reach RC1's normal ~0.5s/pass ideal. The residual cost sits in per-pass
overhead beyond `auto_fill` itself — likely genuine work inherent to this
catalog's 392-attribute governance expansion (script/BML evaluation inside
`resync_stale_recommendations` and `_apply_series_mapping_exclusions` running
their own real per-pass work), not a fourth oscillation bug — not investigated
further in this session. Matches the same category of already-documented,
out-of-scope gap as the original plan's "Product-selection cascade turn still
takes ~192s" finding.

## RC6 — `apply_constraint_rules` had no caching of its own, invisible until instrumented (2026-08-24)

### Investigation — closing the "honest gap" above

Live browser testing of the fully RC5-fixed branch still showed the "APX NEXT
Enhanced" turn taking ~690-700s total, far above the ~270s measured in synthetic
test replays. Rather than continue guessing, `apply_recommendation_rules`,
`resync_stale_recommendations`, `apply_constraint_rules` (in-loop), and
`bml_eval.prefetch_tier2` were each given their own `cpq_perf` timing log for the
first time — none of the four had ever been individually measured before, despite
all four running unconditionally inside every one of `evaluate_rules_loop`'s up-to-8
passes. Rebuilt, redeployed, and re-ran the exact live scenario:

| Pass | `auto_fill` | `prefetch_tier2` | `apply_recommendation_rules` | `resync_stale_recommendations` | **`apply_constraint_rules`** |
|---|---|---|---|---|---|
| 0 | 24.8s | 0.2s | 0.004s | 0.09s | **16.5s** |
| 1 | 15.6s | — | — | — | **12.6s** |
| (light turn) | ~0.01s | ~0.01s | ~0.004s | ~0.004s | ~0.01-0.13s |

`prefetch_tier2`, `apply_recommendation_rules`, and `resync_stale_recommendations`
are all cheap even on the heaviest pass. **`apply_constraint_rules` is not** — it
scales in direct proportion to `auto_fill`'s own magnitude on the heavy turn (roughly
60-70% of `auto_fill`'s cost, every single pass) while staying trivial on light
turns, exactly the profile of a genuine, previously-invisible cost center rather
than noise.

### Root cause

`apply_constraint_rules` (`engine.py:6176`) had **no caching or change-detection of
its own** before RC6 — unlike `auto_fill` (RC1's signature gate), it unconditionally
re-evaluates all constraint rules (186 in this catalog, many script-backed) against
the full attribute set on every single pass, regardless of whether `filled` actually
changed since the last pass. A likely contributing factor: `_bml_prefetch_requests()`
warms the script-evaluation cache using `filled` as it exists *before*
`resync_stale_recommendations` runs (`engine.py:6774`/`6840`-era call sites), but
`resync_stale_recommendations` mutates `filled` on nearly every pass (RC4's own
subject) — if BML's Tier-1/Tier-2 cache keys on the full `filled` snapshot, that
mutation invalidates the prefetch's warm cache for constraint scripts depending on
it, forcing cold re-evaluation. Architecturally this is the identical disease RC1
cured for `auto_fill`, in a sibling function nobody had measured until now.

### Fix — signature-gated cache, identical shape to RC1/RC3

`apply_constraint_rules` is pure with respect to its inputs (`attrs`, `rules`,
`filled`, `filled_multi`) — given the same inputs it always produces the same
`constrained_opts` dict, so a straightforward memoization is safe: skip the real
evaluation and return the previous pass's result when nothing in `_fill_signature`'s
broad snapshot has changed since it was last computed this turn.

**New parameters**, following the exact `_dt_cache`/`_default_fill_signatures`
convention — `None` (the default) is a complete no-op for every pre-existing call
site (including the two callers outside `evaluate_rules_loop`'s own per-pass loop):

```python
def apply_constraint_rules(
    self, attrs, rules, filled, bml_eval=None, filled_multi=None,
    workspace_id=None, catalog_prefix="", _dt_cache=None,
    _constraint_cache: dict[str, tuple] | None = None,
    _signature_exclude_vns: frozenset[str] | None = None,
) -> dict[int, list[str]]:
    if not rules:
        return {}
    _cur_sig = None
    if _constraint_cache is not None:
        _sig_filled = filled if not _signature_exclude_vns else {
            k: v for k, v in filled.items() if k not in _signature_exclude_vns}
        _sig_filled_multi = (filled_multi or {}) if not _signature_exclude_vns else {
            k: v for k, v in (filled_multi or {}).items() if k not in _signature_exclude_vns}
        _cur_sig = _fill_signature(_sig_filled, _sig_filled_multi, {a.entity_id for a in attrs})
        if _constraint_cache.get("sig") == _cur_sig:
            return dict(_constraint_cache["result"])  # shallow copy — see below
    ...  # existing evaluation body, unchanged
    if _constraint_cache is not None:
        _constraint_cache["sig"] = _cur_sig
        _constraint_cache["result"] = constrained
    return constrained
```

**`_signature_exclude_vns` is not optional polish — it is required for the fix to
actually work on the live scenario that motivated it.** Without it,
`getDataFromCookieFlag`'s still-unfixed-at-source churn (RC4/RC5's subject) would
change `filled` on essentially every pass, making this new signature miss just as
often as `auto_fill`'s did before RC5 — defeating the cache on the exact turn it was
built for. The same `_oscillating_vns` set RC5 already computes in
`evaluate_rules_loop` is threaded straight through:

```python
constrained_opts = self.apply_constraint_rules(
    attrs, con_rules, filled, bml_eval=bml_eval, filled_multi=multi,
    workspace_id=workspace_id, catalog_prefix=catalog_prefix, _dt_cache=dt_cache,
    _constraint_cache=constraint_cache,               # NEW: one fresh dict per turn
    _signature_exclude_vns=frozenset(_oscillating_vns),  # NEW: shared with RC5
)
```

`constraint_cache: dict[str, tuple] = {}` is declared once per turn in
`evaluate_rules_loop`, alongside `default_fill_signatures` — same lifecycle, pass 0
of every turn always computes fresh.

**Shallow-copy correctness note**: `_apply_series_mapping_exclusions` (the very next
step in the same pass) reassigns individual keys of the `constrained_opts` dict it
receives (`constrained_opts[target.entity_id] = [...]`) — never mutates a value list
in place. Returning `dict(cached_result)` (a fresh outer dict, sharing inner list
references) on a cache hit is therefore sufficient to prevent one pass's mutation
from corrupting what gets returned on a future cache hit, without needing a full
deep copy.

### Test coverage

Added to `tests/test_cpq_rule_loop_perf_gating_2026_08_19.py`, same sentinel
technique as the `auto_fill`/RC1 tests (seed a result that could never arise from
real evaluation, observe whether it's returned unchanged or overwritten):

- `test_apply_constraint_rules_cache_hit_returns_cached_result_unchanged` — a
  matching pre-seeded signature returns the cached (sentinel) result without
  running real evaluation.
- `test_apply_constraint_rules_cache_miss_runs_real_evaluation` — a mismatched
  signature lets real evaluation run and overwrites the cache with the fresh,
  correct result (not left stale).
- `test_apply_constraint_rules_cache_none_is_a_complete_noop` — `None` (every
  pre-existing call site) behaves identically to omitting the parameter.
- `test_apply_constraint_rules_signature_exclude_vns_keeps_the_gate_held` — an
  unrelated key's value changing does not break the gate when that key is excluded.
- `test_apply_constraint_rules_without_exclusion_the_same_change_breaks_the_gate`
  — negative control proving the exclusion itself is what holds the gate.

Regression: `tests/test_cpq_constraint_value_casing.py`,
`test_cpq_constraint_empty_intersection_fallback.py`,
`test_cpq_declarative_condition_operators.py`,
`test_cpq_recommendation_respects_active_constraint.py`,
`test_cpq_default_value_ignores_active_constraint.py`,
`test_cpq_multiselect_autofill_overselection.py`,
`test_cpq_proactive_stale_constraint_reask.py` re-run — same 2 pre-existing
failures from the established 13-failure baseline (both in
`test_cpq_multiselect_autofill_overselection.py`), zero new regressions. Full CPQ
regression suite (`pytest tests/ -k cpq`) re-run for final confirmation before
merge.

### Results (live-verified, 2026-08-24)

Full CPQ regression suite re-run after RC6: **13 failed, 1350 passed, 47 skipped**
— identical failure names to the established baseline, zero new regressions (the
+5 over RC5's 1345 is exactly the new RC6 tests).

Live re-verification of the exact same "APX NEXT Enhanced" turn, rebuilt and
redeployed with RC6 in place, via `/ask/threads/message` with `session_data`
correctly threaded (the same properly-fixed test harness used for RC5's final
confirmation):

| Fix state | Total turn time | `evaluate_rules_loop` |
|---|---|---|
| Original incident | 792.6s | 630.0s |
| RC3 only | 836.98s (regression) | 669.1s |
| RC5 (`/ask/threads/message`, final) | 269.9s | ~203s |
| Live browser session (pre-RC6) | 689.7s / 694.2s | 553.2s / (not captured) |
| **RC6** | **183.0s** | **125.8s** |

Per-pass `apply_constraint_rules` cost on the exact same heavy turn:

| Pass | Before RC6 | After RC6 |
|---|---|---|
| 0 | 16.5s | 16.2s (expected — pass 0 always computes fresh) |
| 1 | 12.6s | 12.4s (expected — oscillation exclusion not yet populated) |
| 2 | ~12s | 14.2s (expected — same one-pass lag `auto_fill`'s own RC5 gate shows) |
| **3-7** | **~12-16s each pass** | **0.000s every pass** |

The cache engages exactly on schedule (same lag pattern as `auto_fill`'s RC5 gate,
since both share `_oscillating_vns`) and, once engaged, eliminates the cost
entirely rather than merely reducing it — `apply_constraint_rules` was pure with
respect to its inputs, so a full cache hit is a correct zero-cost skip, not an
approximation. Net result across the whole RC3-RC6 investigation on the live
incident: **792.6s → 183.0s, a ~77% reduction** — the best result achieved this
session, and the first to bring the heaviest turn type within striking distance of
a normal turn's latency.

### Confirmation on a real user browser session (2026-08-24)

The synthetic test above used a scripted, clean-session replay. Immediately after,
the user re-tested the same "APX NEXT Enhanced" turn live, in the browser, against
the same RC6-deployed container — a genuinely independent confirmation, not a
repeat of the same measurement:

| Metric | Real browser session |
|---|---|
| `evaluate_rules_loop` | 268.2s |
| `apply_constraint_rules`, passes 0-2 | 43.7s / 22.6s / 23.7s (expected — cache not yet engaged) |
| `apply_constraint_rules`, passes 3-7 | **0.000s every pass** — RC6 confirmed engaging identically to the synthetic test |
| Total request (`request_end`) | **382.9s** |

Per-pass costs ran heavier than the synthetic replay (pass 0 `auto_fill` 67.1s vs.
~23s, reflecting this real session's own accumulated state rather than a clean
scripted one), so the absolute total (382.9s) is higher than the synthetic run's
183.0s — but the fix's *mechanism* is independently verified: `apply_constraint_rules`
engages at exactly the same pass (3) and drops to exactly the same value (0.000s)
regardless of how the session got there. Still a substantial improvement over both
the original incident (792.6s) and this same user's own pre-RC6 live sessions
(689.7s / 694.2s) — roughly a 44-51% reduction on real, unscripted usage.

## Risk assessment

- **RC1 fix blast radius**: touches only the `default_first_available` re-derivation
  branch inside `auto_fill` (single- and multi-select variants) — every other source
  tag's handling, the convergence check itself, and every other step of the loop
  (hiding, recommendation, constraint application) are untouched.
- **RC1 correctness risk**: if the "input signature" tracking is too coarse (misses
  a real upstream change that should have triggered re-derivation), a
  `default_first_available` guess could go stale one pass later than it does today —
  mitigated by choosing the signature from the same `allowed_for_attr`/
  `constrained_opts` data the derivation itself already consults, not an independent
  approximation.
- **RC2 fix blast radius**: a TTL constant change (mechanical, three constants) plus
  one new call site in the ingestion completion path — no change to what data is
  cached or how it's classified.
- **RC2 correctness risk**: between widening the TTL and adding the explicit
  invalidation hook, there's a window where a mid-session re-ingest could serve
  stale table/rule data for up to the new (longer) TTL — mitigated by implementing
  the invalidation hook in the same change, not as a separate follow-up, so the
  window never actually opens in practice.
- **Shared risk**: both fixes are inferred from a 6-turn sample gathered this
  session — real production traffic may reveal different pass-count/cache-hit
  patterns; the verification plan below re-measures after implementing rather than
  trusting the estimate alone.

## Verify before / after implementing

- **Before** (already done): live-captured the 6-turn baseline above via
  `docker logs aryx-api-1`, parsed for `cpq_step`/`cpq_perf` timing lines.
- **After RC1**: replay the same live scenarios; confirm `evaluate_rules_loop done`
  log lines show `passes` meaningfully below 8 for turns that don't need further
  narrowing; confirm a `default_first_available` attribute that DOES have a genuine
  later narrowing (e.g. the `extendRangeTo762764MHz_astro`-style case cited in the
  existing code comment) still resolves correctly within the same turn — not
  deferred incorrectly by the new signature-based gating.
- **After RC2**: replay two turns spaced further apart than 30s (simulating real
  user think-time); confirm the second turn's `_load_all_tables` line shows
  "CACHE HIT (module)" instead of "MISS (fresh scan)". Separately: trigger a real
  re-ingest for a workspace mid-"session" and confirm the very next turn sees fresh
  (not stale) table/rule data — proving the invalidation hook actually fires.
- **Combined**: re-run the full 3-turn APX NEXT scenario end-to-end and re-measure
  total wall-clock time and pass counts against this plan's baseline table.
- Full CPQ regression suite re-run; any failure/timeout individually confirmed
  pre-existing via the established `git worktree` comparison method.

## Files expected to change

- `src/aryx/cpq/engine.py`:
  - New module-level helper `_fill_signature(filled, filled_multi, visible_ids) ->
    tuple` (broad, unhashed, direct-tuple-equality signature — see Fix above).
  - `auto_fill()` signature: new optional parameter `_default_fill_signatures:
    dict[str, tuple] | None = None`, following the existing `_dt_cache`/
    `hiding_rules` convention (`None` = complete no-op for every other call site).
  - `auto_fill`'s `default_first_available` re-derivation branches (single-select
    ~7976-8009, multi-select ~9080-9086): gate the pop-and-re-derive step on
    `_fill_signature(...)` equality per the pseudocode above.
  - `evaluate_rules_loop` (`~6339` and the `auto_fill(...)` call at `6481-6489`):
    declare `_default_fill_signatures: dict[str, tuple] = {}` once before the
    `for pass_num in range(_MAX_LOOPS):` loop; pass it through on every pass's
    `auto_fill(...)` call.
  - `_VALUE_RULES_CACHE_TTL_SECONDS`/`_RULE_JOIN_DATA_CACHE_TTL_SECONDS` constants
    widened (RC2).
- `src/aryx/cpq/data_table_resolver.py` — `_TABLES_CACHE_TTL_SECONDS` widened (RC2).
- `src/aryx/pipeline/doc_discovery.py` — `ingest_confirmed()` (~line 1108): call
  `_clear_tables_cache()`/`_clear_value_rules_cache()`/`_clear_rule_join_data_cache()`
  for the affected workspace after a successful re-ingest (RC2) — contingent on
  resolving the multi-replica production-topology question in the correctness-risk
  doc first.
- New/extended test coverage:
  - A pass-count regression test proving a stable configuration converges in fewer
    than 8 passes once the gate is in place.
  - A test proving the gate correctly does NOT suppress re-derivation when the
    signature genuinely changes (a real narrowing on pass 2+ still gets picked up
    the same turn).
  - A dedicated test replaying the exact ICE-KIT/Package-Type-style scenario
    (script-backed dependency, per the correctness-risk doc) end-to-end through the
    new gated logic, confirming it still resolves correctly and isn't silently
    skipped.
  - A test confirming every existing direct `auto_fill(...)` call site (not routed
    through `evaluate_rules_loop`) is completely unaffected, since it never passes
    `_default_fill_signatures`.
  - A cache-hit test proving a simulated 60s+ gap between two calls still hits the
    module cache under the new TTL; an invalidation test proving
    `ingest_confirmed()` actually clears all three caches for the ingested
    workspace.
