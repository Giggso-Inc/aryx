# Respect Layout Visibility in Every Governed-Attribute Fallback — Plan (Shipped)

## Context

After the `hiddenMasterStringForAstroPortable_astro` fix, a live "incomplete configuration"
check on a real order (`turn >= MAX_TURNS`, 37 attributes still unresolved) surfaced a sharper
question: **should any attribute the layout export marks `hide:true` ever be asked at all,
regardless of what any other rule or data table says?** Checking the real 37 against the layout
file directly confirmed it should not be, and at the time it sometimes was:

- 11 of the 37 were genuinely layout-visible (`hide:false`) — correctly asked.
- **26 of the 37 were `hide:true` in the layout (or non-menu) — the layout export explicitly said
  never show these — yet they were asked anyway.**
- 0 of the 37 were absent from the layout export entirely.

None of the 26 are `required=True` in the raw catalog, ruling out `bom_gate.
find_missing_required_fields` as the source (it only flags required attrs). The real mechanism
turned out to be **three separate, structurally identical gaps** inside `CpqEngine.auto_fill`,
found one at a time as each fix's live-verified impact was smaller than expected.

## The three gaps (all in `engine.py`, all in the same governed-attribute handling section)

**1. The dominant branch (~line 6663, dated 2026-08-09, "§2f superseded by explicit
instruction"):**

```python
elif display_order is not None:
    # governed, no active constraint/recommendation/default resolved a value
    # -- blind-pick the first real catalog option.
    value = valid_opts[0].item_value
```

Fires for ANY rule-governed attribute once a layout map is loaded, with no check that the
attribute is actually in that layout's visible set — only that a layout exists at all. This was
the dominant cause: any rule-governed attribute could reach it, not only `attrSequence`-confirmed
ones.

**2. The `_dt_governed_vns` branch (~line 7008, dated 2026-08-10, HITL-approved
turn-count-vs-correctness tradeoff):**

```python
if vn in _dt_governed_vns:
    ... blind-pick the first real catalog option ...
    else:
        pending.append(attr)          # no display_order check at all
```

Same flaw, narrower trigger (only attrs the real `attrSequence` Data Table confirms apply).

**3. The `_dt_never_governed_anywhere` safety net (~line 7030, pre-existing):**

```python
elif (
    display_order is None or is_decision_attr
    or vn in grid_selector_vns
    or _dt_never_governed_anywhere(vn)
):
    pending.append(attr)
```

Exists to never silently drop an attribute the catalog tracks nowhere at all (genuine "unknown,
ask to be safe"). This turned out to be **the actual dominant mechanism for most real leaking
attributes** (`backupPTT_astro`, `rFIDRFIDEquipped_astro`, `cableDataCable_astro`, and 19 more) —
confirmed live via temporary debug logging showing `is_governed=True`, real non-empty
`valid_opts`, and `display_order` correctly excluding the attribute, yet it still reached
`pending` because `_dt_never_governed_anywhere(vn)` alone forced it, with no layout check either.

Each gap was found only after fixing the previous one and re-measuring live impact — fix #1
alone moved the pending count 37→34; adding #2 made no additional measurable difference for the
real catalog; #3 was the one that finally produced the full expected drop.

## Approach

All three get the identical guard shape: preserve existing behavior exactly when no layout map
is loaded or when the attribute IS in the layout's visible set; skip (never ask, never blind-fill)
when the layout explicitly excludes it.

```python
# 1.
elif display_order is not None and vn in display_order:
    value = valid_opts[0].item_value
    ...
elif display_order is not None:
    pass  # layout hides it -- skip

# 2.
if vn in _dt_governed_vns and (display_order is None or vn in display_order):
    ...

# 3.
elif (
    display_order is None or is_decision_attr
    or vn in grid_selector_vns
    or (vn in display_order and _dt_never_governed_anywhere(vn))
):
    pending.append(attr)
```

The principle behind #3 in particular: `_dt_never_governed_anywhere` protects against *silence*
(the catalog gives no signal either way). A layout `hide:true` is not silence — it is an explicit
instruction, and it must win the same way it wins everywhere else in this codebase.

## Critical files

- `src/aryx/cpq/engine.py` — three guard additions (~lines 6663, 7008, 7030), each with an
  inline comment cross-referencing this plan doc.
- `tests/test_cpq_auto_fill_data_table_tier.py` — 9 new/updated tests reusing the existing
  `_patch_rdb`/`AttrSeqTest` fixture pattern. One pre-existing test
  (`test_auto_fill_asks_an_attr_never_governed_anywhere_even_with_layout_loaded`) had its fixture
  updated to include the target attribute in `display_order`, preserving its original intent
  (layout-visible + never-governed → still ask) now that the layout-hidden case is handled
  separately by a new sibling test.

## Verification — confirmed live, not just unit-tested

1. **Unit tests**: 35 tests in the file, all passing — one per guard × (layout-visible regression,
   layout-hidden new behavior, no-layout-map regression), plus the updated never-governed-anywhere
   pair.
2. **Regression check**: full `-k cpq` suite, 843 passed, same 3 known pre-existing failures
   (confirmed unrelated via `git stash` comparison earlier this session), no new failures.
3. **Live verification against the real container** (workspace 39005), replaying the exact
   conversation that surfaced this (`APX NEXT All Band` → `700/800 MHz` → `No` → `Software Key`
   → confirm/turn-cap):

   | | Before any fix | After fix #1 only | After all 3 fixes |
   |---|---|---|---|
   | Pending/incomplete count | 37 | 34 | **11** |

   The final 11 are exactly the confirmed layout-visible set: `cBPQRCode_astro`, `fedQRCode_astro`,
   `dHSAssetTagLabel_astro` (blocked on the separate, already-documented `UserGroupMapping` data
   gap — see `CPQ_USER_GROUP_MAPPING_HIDING_RULE_PLAN_2026_08_10.md`), plus
   `includeAccidentalDamageAddDMSCoverage_astro`, `trainTheTrainerTraining_astro`,
   `deviceManagementTraining_astro`, `applicationServicesIntroBundle_astro`,
   `wirelessCarrier_astro`, `selectEndUserType_astro`, `agencyHasMotorolaEvidenceSolution_astro`,
   `subscriptionBillingAddDMSCoverage_astro` — every one of these is genuinely layout-visible and
   a real, applicable question for this configuration.

**Status: shipped and fully verified.** The layout config is now the enforced ceiling across
every code path that decides whether to ask, blind-fill, or skip a governed attribute — not just
the ones already covered by `§2c`/`§2f`.
