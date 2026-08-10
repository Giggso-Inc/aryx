# Data-Gap Skip + Rule-Governed Blind-Pick — Plan

## Context

The layout-visibility baseline fix (`CPQ_DATA_TABLE_GOVERNED_LAYOUT_VISIBILITY_GAP_PLAN_2026_08_10.md`)
got a real conversation's pending count down from 37 to 11, exactly matching the layout-visible
set. Those 11 split into two groups with different, confirmed root causes:

- **Group 1 (3 attrs — `cBPQRCode_astro`, `fedQRCode_astro`, `dHSAssetTagLabel_astro`):** share one
  hiding rule ("Hide DHS Asset tag label and CBP qr code unless part of APXRADIOs9YRS customer
  group") whose script queries a `UserGroupMapping` data table — confirmed absent from every
  ingested catalog in this system (`CPQ_USER_GROUP_MAPPING_HIDING_RULE_PLAN_2026_08_10.md`). The
  hiding rule can never resolve; nothing else fills a value; they land in `pending` forever until
  that data is actually located and ingested.
- **Group 2 (8 attrs — Include Accidental Damage, Train the Trainer Training, Device Management
  Training, Application Services Bundle Duration, Wireless Carrier, Select End User Type, Agency
  has Motorola evidence solution, Subscription Billing):** each has real recommendation/
  constraint/hiding rules, but none of those rules' conditions match this exact product/region/
  bundle combination, and none has a catalog `default_value`. Genuine, real product decisions —
  today's code correctly refuses to guess and asks.

Decision (HITL, `/andie` session 2026-08-10): change both outcomes.
- Group 1 → don't keep asking about something that can never resolve. Warn (so it's traceable) and
  skip — leave unfilled, don't block the quote.
- Group 2 → don't ask when the catalog's own rules had a real chance to decide and didn't. Blind-
  pick the first rule-valid option instead, same "never leave a customer stuck on an unanswerable
  rule gap" tradeoff already accepted for Data-Table-sequence-governed attrs earlier today. This is
  a **generic** rule (any rule-governed attr, any workspace, not just these 8 named ones) — a real,
  intentional, permanent narrowing of "ask, never guess" for this specific class of attribute:
  rule-governed, no default, no rule fired.

## Approach

Both hooks live in `CpqEngine.auto_fill`'s existing pending-decision block (`engine.py`, the final
`elif` around the `_dt_governed_vns`/`_dt_never_governed_anywhere` block from today's earlier fix),
inserted in this order — order matters, since Group 1 attrs are *also* rule-governed and would
otherwise qualify for Group 2's blind-pick:

1. **Forced-ask exceptions unchanged first:** `is_decision_attr` (Country/Region/Hardware
   Version/Product anchors) and `vn in grid_selector_vns` still always reach `pending` — untouched.
2. **Group 1 — missing-data-table skip:** a new module-level registry,
   `_KNOWN_MISSING_DATA_TABLES = ("UserGroupMapping",)` (extend this tuple, never hardcode
   attribute names, if another confirmed-absent table surfaces later), and a helper
   `_hiding_rule_needs_missing_data_table(rule)` that checks whether a `HidingRule`'s
   `script`/`condition_script` text references any of those table names. `auto_fill` gains a new
   optional `hiding_rules: list[HidingRule] | None = None` parameter; a precomputed set
   `_missing_data_target_ids` (built once, before the main loop, same pattern as
   `_dt_governed_vns`) maps `target_attr_id -> blocked`. When a pending-bound attr's entity_id is
   in that set: `logger.warning(...)` and `continue` — no fill, no `pending.append`, nothing asked.
   `hiding_rules=None` (the default) is a complete no-op, identical to today's behavior for every
   caller that doesn't pass it.
3. **Group 2 — rule-governed blind-pick:** when an attr reaches this final decision point, isn't
   caught by step 2, and `attr.entity_id in rule_governed` (the same set `governed_source` already
   checks a few lines earlier in this same function) — blind-pick `valid_opts[0]` respecting
   `constrained_opts`, exactly the same pattern as the existing `_dt_governed_vns` blind-pick a few
   lines above, just for the ordinary-rule-governed case instead of the Data-Table-sequence case.
   Tag `sources[vn] = "blind_pick_rule_governed"` (distinct from the existing
   `"blind_pick_governed"` tag) so this is traceable/distinguishable in `filled_source` later.
4. **Unchanged fallback:** `display_order is None` (no layout loaded) or
   `(vn in display_order and _dt_never_governed_anywhere(vn))` still reaches `pending` — this is
   now ONLY hit for attrs with genuinely zero rule governance at all (nothing to blind-pick from),
   preserving the original safety net's purpose.

Both `hiding_rules` (new param) and the two new call-site wiring points (`evaluate_rules_loop`'s
internal `auto_fill` call, and `ask_api.py`'s `_recompute_pending`'s final `auto_fill` call — the
one that actually produces the `pending` list surfaced to the customer) need the new argument
threaded through; every other existing caller that omits it keeps today's behavior unchanged.

## Critical files

- `src/aryx/cpq/engine.py` — `_KNOWN_MISSING_DATA_TABLES`, `_hiding_rule_needs_missing_data_table`,
  `auto_fill`'s new `hiding_rules` param and the two new branches in the pending-decision block;
  `evaluate_rules_loop`'s internal `auto_fill` call updated to pass `hiding_rules=hiding_rules`.
- `src/aryx/api/ask_api.py` — `_recompute_pending`'s final `auto_fill` call updated to pass
  `hiding_rules=hiding_rules`.
- `tests/test_cpq_auto_fill_data_table_tier.py` or a new
  `tests/test_cpq_data_gap_skip_and_rule_governed_blind_pick.py` — unit tests for both branches.

## Verification results (live, 2026-08-10)

Two real bugs found and fixed while implementing this, beyond the plan above:

1. **Ordering vs `_dt_governed_vns`**: the real Group 1 attrs (`cBPQRCode_astro`/`fedQRCode_astro`/
   `dHSAssetTagLabel_astro`) turned out to ALSO be attrSequence-Data-Table-governed. The pending-
   decision `elif` chain checks `_dt_governed_vns` before anything else, so without reordering,
   that branch's own (separately buggy) blind-pick/pending logic claimed them first and Group 1's
   check was unreachable. Fixed by checking `_missing_data_target_ids` before `_dt_governed_vns`.
2. **`entity_id` vs `source_id`**: the real hiding rule's `target_attr_id` (e.g. `18302531462`) is
   the BM-native `source_id`, not the FalkorDB graph `entity_id` (e.g. `292414`) — confirmed live
   by loading the real product config and comparing both ids for all 3 Group 1 attrs. `attr.
   entity_id in _missing_data_target_ids` alone silently never matched anything real; fixed to
   check `attr.source_id` too, same convention `_satisfied_recommendation` already uses elsewhere
   in this file.
3. **Bonus fix, same root cause as Group 2's own key-presence bug**: the pre-existing
   `_dt_governed_vns` branch's `_blind_allowed` computation had the identical `.get(id, [])`
   flaw — treating "this attr isn't a key in `constrained_opts`" the same as "constrained to zero
   options," which is why `wirelessCarrier_astro`/`subscriptionBillingAddDMSCoverage_astro` (both
   confirmed DT-governed, not just rule-governed) were landing in `pending` with an artificially
   empty blind-pick list even before this session's Group 2 work started. Fixed with the same
   key-presence check.

Live replay (workspace 39005, same conversation used throughout this investigation) after all
three fixes: turn 2's pending count dropped from 9 attributes (including all 3 Group 1 + 5 of the
8 Group 2 attrs) to **1** (`modelSelectionFrequencyBands_astro`, a genuine remaining product
decision). Turn 3 reached **"Configuration complete"** — previously this conversation needed 5+
turns and still ended with 11 unresolved attributes. `docker logs` confirms the Group 1 warning
fires correctly for all 3 attrs on every pass, and no unexpected warnings for any other attribute.

## Verification

1. **Unit tests**: Group 1 — a `HidingRule` whose script references `UserGroupMapping` targeting
   an unfilled attr with real options → attr is skipped (not in `pending`, not in `filled`), and a
   warning is logged; a hiding rule referencing an unrelated/absent table name not in the registry
   is unaffected (still asks, proving this isn't a blanket "any unresolvable hiding rule" bypass).
   Group 2 — a rule-governed attr (via `rule_governed_ids`) with real options, no default, no
   fired recommendation → blind-picks `valid_opts[0]` respecting `constrained_opts`; an attr with
   zero rule governance at all in the same shape still reaches `pending` (safety net unchanged);
   `is_decision_attr`/grid-selector attrs still always ask regardless of rule governance.
2. **Regression check**: full `-k cpq` suite. Expect some existing tests asserting "rule-governed,
   no value, no default → pending" to now correctly assert "blind-picked" instead — update them
   deliberately, one at a time, confirming each was asserting the now-intentionally-superseded old
   behavior rather than a still-valid, different case.
3. **Live verification**: replay the same real conversation; confirm the final "incomplete —
   N attributes" count drops from 11, and that the 8 Group-2 attributes now appear filled (with
   `filled_source` tagged `blind_pick_rule_governed`) rather than asked, while the 3 Group-1 attrs
   are silently absent from both `filled` and the pending list, with a warning in the logs.
4. Rebuild, redeploy, live-verify — same discipline as every fix today.
