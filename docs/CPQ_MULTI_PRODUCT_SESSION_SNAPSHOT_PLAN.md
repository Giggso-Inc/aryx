# CPQ Multi-Product Session Snapshot — Implementation Plan

## Problem Statement

Switching products mid-session (A → B → C → back to A) currently discards
each product's in-progress answers by design — `_complete_product_switch`
(`src/aryx/api/ask_api.py`) resets `session.filled`, `display_filled`,
`filled_source`, `pending_variables`, `country`, `negated_vns`, and
`product_entity_id` to empty on every confirmed switch. This was an
explicit, documented scope cut (see `test_switching_back_and_forth_does_not_
restore_prior_answers` in `tests/test_cpq_product_switch.py`), not a
technical limitation — a rep who configures APX NEXT, switches to SL3500e,
then switches back to APX NEXT starts that product from scratch again,
losing everything already answered.

Goal: restore a product's prior in-progress state when switching back to
it, without weakening the "never submit a guessed/stale value" guarantee
the rest of the CPQ engine enforces.

## Current Architecture (context)

- `CpqSession` (`src/aryx/cpq/state.py`) is a plain dataclass, serialized to
  a dict via `to_dict()`/`from_dict()` (generic `asdict` + field-filtering).
- There is **no server-side or DB-backed session store**. The full
  `session_data` dict round-trips through the client on every `/ask`
  request/response — the server is stateless between calls.
- `auto_fill` (`src/aryx/cpq/engine.py`) already has an `already_filled`
  parameter that seeds it with prior values and re-validates every one
  against the CURRENT rule/constraint/option set as it runs — this is the
  exact mechanism normal same-product cross-turn continuation already
  relies on. Nothing about "restore then re-check" is new machinery.

## Design

### 1. New `CpqSession` field

```python
# src/aryx/cpq/state.py
product_snapshots: dict[str, dict] = field(default_factory=dict)
```

Keyed by `product_name` — the FAMILY/catalog key `detect_product_mention`
resolves to (e.g. `"aSTRO25_bom"`, `"pCRBusinessLightDevices_bom"`,
`"videoSolutions_BOM"`), matching the identity that already gates a switch
(`session.product_name`).

Each value is a snapshot dict with exactly these keys (a subset of
`CpqSession`'s own fields — the config-scoped ones `_complete_product_switch`
currently resets):

```python
{
    "filled": dict[str, str],
    "filled_multi": dict[str, list[str]],
    "display_filled": dict[str, str],
    "filled_source": dict[str, str],
    "country": str,
    "negated_vns": list[str],
    "product_entity_id": int,
}
```

`pending_variables` is deliberately NOT snapshotted — it's re-derived from
scratch by `auto_fill` on restore anyway (see step 3), and storing stale
`ConfigAttr` objects would be redundant serialized weight.

### 2. Snapshot on switch-away

In `_complete_product_switch` (`ask_api.py`), BEFORE the existing reset
block, snapshot the CURRENT product's state under its own name:

```python
if session.product_name:  # skip on the very first turn (no prior product)
    session.product_snapshots[session.product_name] = {
        "filled": dict(session.filled),
        "filled_multi": dict(session.filled_multi),
        "display_filled": dict(session.display_filled),
        "filled_source": dict(session.filled_source),
        "country": session.country,
        "negated_vns": list(session.negated_vns),
        "product_entity_id": session.product_entity_id,
    }
```

This runs unconditionally on every switch — cheap (a few dict copies), and
means even a product visited only once is snapshotted, ready for a much
later switch-back.

### 3. Restore on switch-to

Still in `_complete_product_switch`, after committing `session.product_name
= new_product`, check for an existing snapshot:

```python
snap = session.product_snapshots.get(new_product)
if snap:
    session.filled = dict(snap["filled"])
    session.filled_multi = dict(snap["filled_multi"])
    session.display_filled = dict(snap["display_filled"])
    session.filled_source = dict(snap["filled_source"])
    session.negated_vns = list(snap["negated_vns"])
    session.product_entity_id = snap["product_entity_id"]
    # country: prefer the snapshot's own value UNLESS the caller already
    # validated a carried-over country for this switch (existing
    # _country_available_for re-validation in ask_api.py takes precedence —
    # do not overwrite a value that turn's own logic just confirmed).
    if not new_country:
        session.country = snap["country"]
else:
    session.filled = {}
    session.filled_multi = {}
    session.display_filled = {}
    session.filled_source = {}
    session.negated_vns = []
    session.product_entity_id = 0
```

**Critical: re-validation is not optional and is NOT new code to write.**
`session.filled` restored here is exactly the shape `already_filled` expects
(`engine.py:3050`, `auto_fill(attrs, hints, already_filled=filled, ...)`).
The very next turn's normal Step 2/3 flow (`ask_api.py`, already existing)
calls `auto_fill` with `session.filled` as `already_filled` regardless of
whether it came from a fresh `{}` or a restored snapshot — the engine
cannot tell the difference, and does not need to. Any restored value that
no longer resolves against current rules, hidden by an active constraint,
or missing from the current option set is naturally dropped/re-asked by
the existing cascade — the SAME guarantee that already protects every
normal turn.

### 4. Snapshot lifecycle / cap

- Snapshots are **kept** after being consumed on restore (not deleted) —
  switching away again re-snapshots the (possibly now-updated) state under
  the same key, so a product visited 3+ times always reflects its latest
  in-progress answers.
- **Cap:** bound `product_snapshots` to the 5 most-recently-touched products
  (evict the least-recently-switched-away-from entry when adding a 6th).
  Track recency via insertion order (Python dicts preserve it) — on
  snapshot-write, `pop` the key first if present, then re-insert, so the
  dict's iteration order IS recency order; evict from the front when
  `len() > 5`.

## Files to Change

| File | Change |
|---|---|
| `src/aryx/cpq/state.py` | Add `product_snapshots: dict[str, dict] = field(default_factory=dict)` to `CpqSession`. |
| `src/aryx/api/ask_api.py` | In `_complete_product_switch`: snapshot-on-away (step 2), restore-on-to (step 3), 5-entry cap (step 4). |
| `tests/test_cpq_product_switch.py` | New tests (see below). |

## Test Plan

1. **`test_switch_back_restores_prior_product_state`** — configure product
   A partially, switch to B, switch back to A; assert `session.filled`
   contains A's prior answers (replacing the existing
   `test_switching_back_and_forth_does_not_restore_prior_answers`, which
   currently asserts the OLD discard-by-design behavior and must be
   updated to assert restoration instead).
2. **`test_restored_snapshot_drops_now_invalid_values`** — snapshot A with a
   value, mock a rule/constraint change that makes that value no longer
   valid on restore, assert `auto_fill`'s normal re-validation drops it
   (proves restore doesn't bypass validation).
3. **`test_snapshot_cap_evicts_oldest`** — switch across 6 distinct
   products, assert only the 5 most recent remain in `product_snapshots`.
4. **`test_first_ever_switch_has_no_snapshot_to_restore`** — existing
   no-snapshot switch behavior (blank reset) is unchanged when the target
   product has never been visited this session.

## Risks / Open Questions

- **Blob size**: 5 cached products × full `filled`/`display_filled` dicts
  could meaningfully grow `session_data` for configs with 50+ answered
  attrs. Acceptable given client-held JSON has no hard size constraint
  observed elsewhere in this codebase, but worth a quick payload-size
  sanity check against a real large catalog (APX NEXT) during
  implementation.
- **Country carry-over interaction — RESOLVED.** Traced both call sites of
  `_complete_product_switch(new_product, new_country)` directly:
  - `confirm_switch` path (`ask_api.py:936`): `new_country = old_country =
    session.country`. If `old_country` is truthy, it's validated via
    `_country_available_for(new_product, old_country)` BEFORE the call
    (line 918) — only reaches `_complete_product_switch` empty when no
    country was ever set this session at all.
  - `switch_country` path (`ask_api.py:844`): `new_country` is always a
    freshly typed, just-validated replacement country (`hints.get("country")
    or req.question.strip()`), gated behind `_country_available_for` — never
    empty when this branch fires.

  So `new_country` is empty at snapshot-restore time **only** when neither
  existing branch had anything to contribute — the exact, and only, case
  step 3's `if not new_country: session.country = snap["country"]` fires.
  No extra validation call is needed for the restored value either: it was
  captured while THIS SAME product was previously configured, so it was
  already validated for it once — restoring it doesn't reach across
  products the way a fresh carry-over guess would. Net: the snapshot
  restore is a pure fallback for the one gap neither existing path covers,
  never overrides a value either path already produced. No code changes
  needed beyond the `if not new_country` guard already in the step 3
  design above.
