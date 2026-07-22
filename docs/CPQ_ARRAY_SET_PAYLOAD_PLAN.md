# BigMachines Array-Set Payload — Implementation Plan

**STATUS: IMPLEMENTED AND VERIFIED LIVE** (see "Implementation & Live
Verification" at the end of this doc). No re-ingestion was needed — the
`bm_config_attr_set`/`bm_config_attr_set_assoc` data was already ingested
into workspace 19's Postgres store from the original XML import; the fix
only needed to READ it, which nothing in this pipeline did before.

Scopes the fix for `docs/CPQ_RULE_TOOL_FLOW_PLAN.md` §15c: composite
"array-set" attributes are currently misclassified as ordinary multi-select
and serialized flat, which BigMachines rejects for genuine array-set columns
(confirmed live: *"itemTypeVX650_astro is an array attribute. Please use
array set payload to modify it's value"*).

## Problem Statement

BigMachines models a repeating multi-column row (e.g. one mount option +
its own quantity, or one promotion + its message/instructions/opt-out) as
an **array set**: a driver/control attribute plus several named member
columns, all grouped by a shared `bm_config_attr_set` id and ordered via
`bm_config_attr_set_assoc`. The wire format for these is:

```json
"_setCountryArray": {
  "items": [
    {"_index": 0, "Country": {"value": "US", "displayValue": "United States"}, "startDate": "...", "endDate": "..."},
    {"_index": 1, "Country": {"value": "CA", "displayValue": "Canada"}, "startDate": "...", "endDate": "..."}
  ]
}
```

— one top-level key (the set), one `items` row per index, sibling columns
grouped INTO that row. This is structurally different from an ordinary
multi-select checkbox list (`{"items":[{"value","displayValue"}, ...]}`,
one top-level key PER selected value's attribute, no grouping).

`classify_select_type()` (`engine.py:528-576`) has no `"array"` branch —
its first check, `is_array_control_attr=="1" OR attr_type=="1" OR
display_type in ("6","8")` → `"multi"`, catches array-set driver/member
attrs too (docstring already calls this "directionally right but
underspecified"). `build_payload()`'s multi-select emission
(`engine.py:4770-4784`) then serializes each member column as its OWN
top-level key with a flat `{"items":[{"value","displayValue"}]}` — never
grouped by set, never `_index`-keyed. Confirmed live in this session: the
ARYX-produced SVX payload emits `mountingTypeArray_viSoln` this flat way;
the correct wire format nests it as
`_setmountingTypeArrayset_viSoln.items[n]`.

**Confirmed real, not hypothetical** (`CPQ_RULE_TOOL_FLOW_PLAN.md` §15c):
6 genuine array-sets exist in the ingested XML — `promotions`,
`provAgenciesArraySet`, `commandCentralArraySet_astro`,
`solutionCategoryArraySet_astro`, `relatedSoftwareAndServicesArraySet_astro`,
`vX650EnergySolutions_astro` — each with a real driver/control attr and
named member columns (`bm_config_attr_set`: 37 rows, `bm_config_attr_set_
assoc`: 31 rows, both entirely unread by `rdb.py`/`engine.py` today —
confirmed zero references anywhere in `src/`).

## Design — 3 layers, same shape as every prior CPQ gap-closure in this repo

### 1. Ingestion: read `bm_config_attr_set` / `bm_config_attr_set_assoc`

New `rdb.py` fetch method, `fetch_attr_set_assoc(workspace_id, catalog_
prefix)`, mirroring the existing one-method-per-relationship pattern
(`fetch_rule_inputs`/`fetch_marked_attrs`/etc., both Postgres and Oracle
variants). Returns, per set: `set_id`, driver/control attr id
(`size_attr_id`), and an ORDERED list of member attr ids (from `attr_set_
assoc`'s own ordering column). No new ingestion PASS is needed at the
`doc_discovery.py` level — unlike the BML array-iteration plan, this data
already exists as real ingested tables; it just needs a new fetch, same as
any other rule-join table (`fetch_marked_attrs` etc.).

### 2. `ConfigAttr` — add array-set membership fields

`state.py:125-180`, four new fields (mirroring how `is_array_control` was
added for the size/control attr concept). Note the SET's own identity
(`variable_name`, e.g. `"mountingTypeArrayset_viSoln"`) lives on the
`BmConfigAttrSet` DRIVER ROW — a distinct entity from `mountingArrayControl
_viSoln` (the real control ConfigAttr, referenced only via that driver
row's `size_attr_id`) that is NEVER itself ingested as a `ConfigAttr` (the
construction loop only walks `BmConfigAttr` entities). So the wrapper-key
string has to be carried on the control attr as its own field — there is
no other place for it to live:

```python
array_set_id: int | None = None       # shared set id, None = not a set member/driver
array_set_role: str = ""              # "driver" | "member"
array_col_order: int = 999            # ordinal position within the set's row
                                       # (real source field: display_order_number)
array_set_wrapper_key: str = ""       # DRIVER ONLY — e.g. "_setmountingTypeArrayset_viSoln",
                                       # precomputed as "_set" + the BmConfigAttrSet
                                       # driver row's own variable_name (Open Question 3)
```

`array_set_role == "driver"` is assigned to the CONTROL attr (the one
already flagged `is_array_control=True` today, resolved via the driver
row's `size_attr_id`) — not a new, separately-ingested entity. `classify_
select_type()` keeps its existing logic UNCHANGED for attrs with `array_
set_id is None` — this is additive, not a reclassification of the whole
multi/boolean/single split. A NEW check in the `ConfigAttr` construction
loop (`engine.py:1908-1923`) sets all four fields from the new `fetch_
attr_set_assoc` data, keyed by `source_id` (the same BM-native id every
other rule/set join already uses to cross-reference `ConfigAttr`).

**Dummy/placeholder member filter**: member rows whose own `ConfigAttr` is
`hidden=1` with a boolean/no-real-content default (confirmed real example:
`MountingQuantityDummyArrayAttribute_viSoln`, order 3 in the Mounting Type
set — `hidden:1`, `data_type:4` boolean, `default_value:"false"`, absent
from every real payload sample) must be EXCLUDED from the emitted row.
These survive the general hidden-attr drop filter today only because their
name matches the `"quantity" in vn_lo` carve-out
(`engine.py:1883`) meant for the REAL quantity member — so `build_payload`'s
grouping pass (§3) needs its own filter, not a reclassification at
ingestion: skip any member whose value is empty/absent/the attr's own
unmodified `default_value` when building each row, same "nothing real to
contribute" logic the existing hidden-attr drop already uses elsewhere.

### 3. `build_payload` — group array-set members into one indexed row

`engine.py:4770-4784`'s `filled_multi` loop gains a branch BEFORE the
existing flat-serialization fallback: if `attr.array_set_id is not None`
and `attr.array_set_role == "member"`, route it to a separate accumulator
keyed by `array_set_id` instead of `out[k]` directly (the DRIVER's own
value is handled separately — see below, NOT accumulated here). After the
main loop, one pass over that accumulator builds the real shape:

```python
for set_id, members in array_set_accum.items():
    driver = drivers_by_set_id[set_id]  # the control ConfigAttr, role=="driver"
    real_members = [m for m in members if _has_real_content(m)]  # drops dummy placeholders
    rows = []
    max_len = max((len(m.values) for m in real_members), default=0)
    for idx in range(max_len):
        row = {"_index": idx}
        for m in real_members:
            if idx < len(m.values):
                row[m.variable_name] = {"value": m.values[idx], "displayValue": m.display[idx]}
        rows.append(row)
    if rows:
        out[driver.array_set_wrapper_key] = {"items": rows}
        # The driver's own value ships as a SIBLING bare int (row count),
        # NOT nested inside the wrapper — confirmed by the second reference
        # payload (see "Update" section below). This supersedes the earlier,
        # narrower is_array_control heuristic (single control + single
        # multi-select, docs/CPQ_SESSION_2_OPEN_ISSUES.md item 3) once this
        # real linkage exists — that heuristic can be retired.
        out[driver.variable_name] = len(rows)
```

(Pseudocode — member/value alignment inside a row, i.e. whether row 0's
`mountingTypeArray_viSoln` genuinely pairs with row 0's `mountingTypeArray
qty_viSoln` in `filled_multi`'s own list order, is still the one real
unknown — see Open Question 2, still open.) The top-level key is read
directly from `driver.array_set_wrapper_key` (precomputed at ingestion, §2)
— NOT constructed here from a template; Open Question 3 already proved a
per-catalog naming template is unnecessary since the source data's own
`variable_name` supplies the exact string needed.

## Files to Change

| File | Change |
|---|---|
| `src/aryx/cpq/rdb.py` | Add `fetch_attr_set_assoc()` (Postgres + Oracle variants), mirroring existing fetch_* methods. |
| `src/aryx/cpq/state.py` | Add `array_set_id`/`array_set_role`/`array_col_order`/`array_set_wrapper_key` to `ConfigAttr`. |
| `src/aryx/cpq/engine.py` | Wire the new fetch into `ConfigAttr` construction (~1908-1923); add the array-set grouping branch to `build_payload`'s `filled_multi` loop (~4770-4784). `classify_select_type` unchanged. |
| `tests/test_cpq_payload_shapes.py` | New tests (see below) — same file the `mountingArrayControl_viSoln` exclusion test already lives in. |

## Test Plan

1. **`test_array_set_member_groups_into_indexed_rows_not_flat_items`** —
   2 member attrs sharing an `array_set_id`, each with `filled_multi`
   values → asserts the payload key is the driver's own precomputed
   `array_set_wrapper_key` (NOT a template built at serialization time —
   see Open Question 3's resolution), `items` contains one dict per index
   with `_index` present and BOTH member columns nested inside, NOT two
   separate flat top-level keys.
2. **`test_non_array_set_multi_select_still_serializes_flat`** — a plain
   `select_type=="multi"` attr with no `array_set_id` keeps the EXISTING
   flat shape unchanged — regression guard, this fix must be purely
   additive.
3. **`test_array_set_driver_ships_as_sibling_row_count_not_nested_or_duplicated`**
   — the driver/control attr (e.g. `mountingArrayControl_viSoln`) ships as
   its OWN top-level bare int equal to `len(rows)`, is NOT nested inside
   the `_set...` wrapper, and does NOT also appear as a flat top-level key
   the old ungrouped way — confirms this supersedes (not merely coexists
   with) the narrower is_array_control heuristic already shipped for the
   ambiguous-link case.
4. **`test_array_set_dummy_placeholder_member_excluded_from_rows`** — a
   3rd member matching the confirmed `MountingQuantityDummyArrayAttribute_
   viSoln` shape (`hidden=1`, boolean, untouched `default_value`) is
   dropped from every row; the 2 real members still group correctly.
5. **`test_fetch_attr_set_assoc_returns_ordered_member_columns`** — rdb.py
   unit test against a fake cursor/connection, confirming set→member
   ordering survives the fetch, and that the driver row's `variable_name`/
   `size_attr_id` are returned alongside (not just the Assoc rows) so
   `array_set_wrapper_key` can be computed.

## Risks

- **Member/value alignment is the one real unknown.** The pseudocode above
  assumes member columns' `filled_multi` LISTS are already positionally
  aligned by index (row 0's mount type pairs with row 0's quantity) — this
  needs confirming against how `resolve_pending_grid_quantities` (the
  existing per-option quantity heuristic, `engine.py:2255-2286`) actually
  populates these lists today; it may already produce aligned per-option
  lists, or it may need a small adjustment to guarantee alignment before
  `build_payload` can safely zip them by index.
- ~~Only 6 confirmed array-sets in one catalog family (APX NEXT/DM4400)...~~
  **RESOLVED** — see Open Question 1 below: SVX's own `bm_config_attr_set`/
  `_assoc` rows were queried directly against Postgres (workspace 19) and
  confirm the exact same driver+ordered-members mechanism, not a
  coincidentally similar construct.
- **Blast radius is payload-shape-only**, same class of change as the
  Date/Currency/Integer/Float serialization fix already shipped
  (`CPQ_RULE_TOOL_FLOW_PLAN.md` §15b) — no rule-evaluation, cascade, or
  conversation-flow code is touched; low regression risk to anything
  outside `build_payload`'s final serialization step.

## Open Questions — status

1. **RESOLVED, confirmed directly against Postgres (workspace 19).** SVX
   genuinely has its own ingested array-set data — `Svx Video Remote
   Speaker MicrophoneBmConfigAttrSet` (27 rows) and `...BmConfigAttrSetAssoc`
   (23 rows), stored as `ontology_type`-tagged rows in `aryx_entity_ws19`
   (JSONB `attributes`, not separate relational tables — see "Actual
   storage shape" below). The Mounting Type set specifically:
   - Driver row (`BmConfigAttrSet`, entity id 115689): `"id": "19435423713"`,
     `"variable_name": "mountingTypeArrayset_viSoln"`,
     `"size_attr_id": "19435423551"` (→ `mountingArrayControl_viSoln`'s
     real BM attribute id), `"default_attr_id": "-1"` (driver rows never
     have one — only members do).
   - `BmConfigAttrSetAssoc` rows with `"set_id": "19435423713"`:
     `attr_id 19435423613` order 1 (→ `mountingTypeArray_viSoln`),
     `attr_id 19435423615` order 2 (→ `mountingTypeArrayqty_viSoln`),
     `attr_id 19435423627` order 3 (→ `MountingQuantityDummyArrayAttribute_
     viSoln` — an internal "dummy" 3rd column, absent from every real
     payload sample seen so far; almost certainly excluded from the wire
     format, same class of internal bookkeeping as the array-control's own
     raw value).
   This is the exact `driver + ordered members` shape the design section
   already assumed — SVX is not "coincidentally similar," it's the same
   real mechanism as APX's confirmed sets.
2. **Still open.** Member/value alignment (does `filled_multi` already
   preserve per-row order for `mountingTypeArray_viSoln` vs. however
   `mountingTypeArrayqty_viSoln`'s values get collected today via
   `resolve_pending_grid_quantities`) — not resolved by this pass; needs
   tracing that function's actual list-building against a live session.
3. **RESOLVED, confirmed exactly.** The top-level payload key is literally
   `"_set" + {driver row's own variable_name}` — `"_set" +
   "mountingTypeArrayset_viSoln"` = `"_setmountingTypeArrayset_viSoln"`,
   an EXACT match to the real payload. This is simpler than the originally
   guessed `_set{Name}set_{suffix}` pattern: no suffix concatenation logic
   needed at all, just prepend `"_set"` to the set's own `variable_name`
   field (which, in this catalog, already happens to end in `...set_
   viSoln` as part of its own native name — that's baked into the source
   data, not something the code needs to construct).

## Actual storage shape (corrects an implicit assumption in "Files to Change")

`bm_config_attr_set`/`bm_config_attr_set_assoc` are NOT separate Postgres
tables — confirmed via `\dt` against the live `aryx` database, no such
tables exist. Like every other BM entity, they're rows in the generic,
workspace-partitioned `aryx_entity_ws{N}` table, distinguished by
`ontology_type` (`"{CatalogPrefix}BmConfigAttrSet"` /
`"...BmConfigAttrSetAssoc"`) with the real fields inside a JSONB
`attributes` column. This means `fetch_attr_set_assoc()` (§1 above) is a
`SELECT ... WHERE ontology_type = $1` against `aryx_entity_ws{workspace_id}`
— the SAME query shape `rdb.py`'s other `fetch_*` methods already use for
every other rule-join type (e.g. `fetch_marked_attrs`) — not a new SQL
table/schema to design. It also needs to read from BOTH ontology types, not
just the Assoc one: `BmConfigAttrSetAssoc` gives the set→member ordering,
but the driver's own `variable_name` (for the top-level key, per Open
Question 3's resolution) and `size_attr_id` (for the driver/control attr
link) only live on the `BmConfigAttrSet` driver row itself.

## Update — second reference payload confirms the full row shape

A second, more complete sample confirmed the exact per-row grouping this
plan's design section already predicted:

```json
"mountingArrayControl_viSoln": 6,
"_setmountingTypeArrayset_viSoln": {
  "items": [
    {"_index": 0, "mountingTypeArray_viSoln": {"value": "Shirt Magnetic Mount", "displayValue": "Shirt Magnetic Mount"}, "mountingTypeArrayqty_viSoln": 10},
    {"_index": 1, "mountingTypeArray_viSoln": {"value": "Jacket Magnetic Mount", "displayValue": "Jacket Magnetic Mount"}, "mountingTypeArrayqty_viSoln": 10}
  ]
}
```

This confirms the WIRE SHAPE half of Open Question 2 — the selector value
AND its per-row quantity (`mountingTypeArrayqty_viSoln`) are sibling keys
inside the SAME `_index` row on the wire, confirming `mountingTypeArrayqty_
viSoln` is a genuine array-set MEMBER column, not an independently-fetched
flat attr the way `resolve_pending_grid_quantities` currently treats it.
**Does NOT resolve the other half** — whether ARYX's OWN internal
`filled_multi` list order for `mountingTypeArray_viSoln` already lines up
positionally with however `mountingTypeArrayqty_viSoln`'s values get
collected today is a question about this codebase's existing collection
mechanism, not about BigMachines' wire contract, and a reference payload
can't answer it either way — Open Question 2 stays open on that count
until `resolve_pending_grid_quantities` is traced directly.

It also corrects this plan's own driver-attr assumption:
`mountingArrayControl_viSoln` (the driver/control attr) ships as its OWN
bare top-level int (`6`, the row count), separate from and NOT nested
inside the `_set...set_` wrapper — the earlier draft of this plan assumed
the driver would key the wrapper itself; it's actually a sibling key. A
narrow, heuristic-based partial fix for the driver-count case (unambiguous
1 control + 1 multi-select only) has been shipped ahead of the full
array-set implementation — see `docs/CPQ_SESSION_2_OPEN_ISSUES.md` item 3's
"Fix implemented, then CORRECTED" note — but the real fix is still this
plan's full `bm_config_attr_set` ingestion, which removes the "exactly one
of each" restriction entirely.

## Implementation & Live Verification

All 3 design layers implemented as scoped, with the corrections from the
"analyze this" pass applied:

- **`rdb.py`**: `PostgresCpqRdb.fetch_attr_set_assoc()` — reads both
  `BmConfigAttrSet` (driver rows: `size_attr_id`, `variable_name`) and
  `BmConfigAttrSetAssoc` (ordered member rows: `set_id`, `attr_id`,
  `display_order_number`) via the existing dialect-agnostic
  `fetch_entities_by_type` — one implementation serves Oracle too through
  inheritance, same as `fetch_function_scripts`. Trivial self-wrap sets
  (`size_attr_id=-1`) are skipped.
- **`state.py`**: `ConfigAttr` gained `array_set_id`, `array_set_role`
  (`"driver"`/`"member"`/`""`), `array_col_order`, and `array_set_wrapper_key`
  (driver-only, precomputed `"_set" + set.variable_name`).
- **`engine.py`**: `load_product_config()` fetches `fetch_attr_set_assoc`
  once per catalog and stamps the 4 fields onto matching `ConfigAttr`s by
  `source_id`. `build_payload()`'s `filled_multi` loop routes array-set
  members into a `set_id`-keyed accumulator instead of flat top-level keys;
  a follow-up pass groups them into `_index`-keyed rows, filters `hidden`
  dummy/placeholder members, and emits the driver's own row-count as a
  sibling bare int — exactly resolving the design-section bugs found
  during doc review (wrong key template, missing sibling-int emission).

**Tests** (13 new, all passing):
- `tests/test_cpq_rdb_attr_set_assoc.py` (3) — ordered member fetch,
  self-wrap skip, orphan-assoc-row handling.
- `tests/test_cpq_array_set_payload.py` (5) — indexed-row grouping, plain
  multi-select regression guard, driver sibling-int (not nested/duplicated),
  dummy-member exclusion, no-selection no-op.
- 2 existing test doubles (`test_cpq_engine_catalog_scope.py`,
  `test_cpq_e2e.py`) updated with a no-op `fetch_attr_set_assoc` stub —
  regression fallout from the new call in `load_product_config`, not new
  behavior.

**Live verification against the real ingested SVX catalog** (workspace 19,
no re-ingestion needed — this data was already there):

```
mountingArrayControl_viSoln -> array_set_id=19435423713 role='driver'
    wrapper_key='_setmountingTypeArrayset_viSoln' hidden=True
mountingTypeArray_viSoln    -> array_set_id=19435423713 role='member' order=1
mountingTypeArrayqty_viSoln -> array_set_id=19435423713 role='member' order=2
MountingQuantityDummyArrayAttribute_viSoln -> NOT LOADED (filtered upstream
    of build_payload entirely — the code's own dummy-member filter is
    defense-in-depth, not load-bearing for this specific attr)
```

`build_payload()` output, given `mountingTypeArray_viSoln = ["Shirt
Magnetic Mount", "Jacket Magnetic Mount"]` and `mountingTypeArrayqty_viSoln
= ["10", "10"]`:

```json
"mountingArrayControl_viSoln": 2,
"_setmountingTypeArrayset_viSoln": {
  "items": [
    {"_index": 0, "mountingTypeArray_viSoln": {"value": "Shirt Magnetic Mount", "displayValue": "Shirt Magnetic Mount"}, "mountingTypeArrayqty_viSoln": 10},
    {"_index": 1, "mountingTypeArray_viSoln": {"value": "Jacket Magnetic Mount", "displayValue": "Jacket Magnetic Mount"}, "mountingTypeArrayqty_viSoln": 10}
  ]
}
```

An exact structural match to the original reference payload (row count
reflects the 2 simulated selections here vs. the original's 6 — the shape
is what's being verified). Neither member appears as a flat top-level key.

**Open Question 2 — RESOLVED (and fixed).** Traced `resolve_pending_grid_
quantities` directly and confirmed live against real workspace-19
conversation transcripts: `mountingTypeArrayqty_viSoln` is indeed NEVER
populated by the real conversation flow — quantities are filled via
per-option NAMED attrs instead (e.g. `mountingTypeLockingMolleMountQuantity_
viSoln`), one per real mount option, via the existing
`resolve_array_grid_links`/`resolve_pending_grid_quantities` heuristic.
Confirmed live this left the real per-option quantity leaking as a
SEPARATE flat top-level key (e.g. `"mountingTypeLockingMolleMountQuantity_
viSoln": 7`) alongside the correctly-grouped `_setmountingTypeArrayset_
viSoln` row — which then had NO quantity nested inside it at all, a real
gap in the initial implementation.

**Fix implemented**: `build_payload()` now computes, once before either
serialization loop, which real per-option quantity attrs feed which
array-set qty member (`resolve_array_grid_links(attrs)` scoped to the
set's own selector member). The array-set grouping pass folds each row's
real per-option quantity value into that row under the qty member's own
key name (`mountingTypeArrayqty_viSoln`), sourced per-row from the
selector's own selected value at that index; the flat scalar loop excludes
these per-option attrs from shipping as separate top-level keys, since
they're now represented inside the row instead. Verified live end-to-end
(SVX, workspace 19) including through a real "change quantity to 10"
request — the updated value correctly appears nested in the row, and the
per-option attr no longer leaks flat. Test:
`test_array_set_qty_member_falls_back_to_the_real_per_option_quantity_attr`
(`tests/test_cpq_array_set_payload.py`).

## Re-ingestion Verification (from the real source XML, not just pre-existing data)

The earlier "Live Verification" section above only proved the fix reads
`bm_config_attr_set`/`_assoc` data already sitting in Postgres from a prior
ingest — it didn't prove the ingestion PATH itself produces that data
correctly from a fresh file. Re-verified end-to-end against the actual
source file (`SVX Video Remote Speaker Microphone.xml`, 12,484 lines):

1. Created a fresh workspace (id 24, via `POST /admin/workspaces`) to avoid
   touching the already-ingested workspace 19/100 data.
2. `POST /admin/docs/read` (discovery) then `POST /admin/docs/confirm`
   (ingest all 30 discovered CSV files, including `bm_config_attr_set.csv`
   and `bm_config_attr_set_assoc.csv`) — completed in ~10 minutes (LLM-based
   discovery + FK-link inference over 12,244 graph nodes / 12,659
   relationships), no errors.
3. Confirmed identical row counts to the pre-existing workspace 19 data:
   27 `BmConfigAttrSet` rows, 23 `BmConfigAttrSetAssoc` rows — deterministic
   re-ingestion.
4. Ran the exact same `load_product_config()`/`build_payload()` check
   against workspace 24 (product hint resolved cleanly to the single
   catalog this time, no cross-catalog ambiguity warning) — **byte-for-byte
   identical output** to the workspace-19 check: `mountingArrayControl_
   viSoln` correctly linked as driver (`array_set_id=19435423713`,
   `wrapper_key='_setmountingTypeArrayset_viSoln'`), both real members
   correctly ordered, dummy member correctly absent, and the final payload
   producing the exact grouped `_index`-keyed shape with the driver as a
   sibling row-count int.

This confirms the fix works from a genuine, fresh ingestion of the actual
BigMachines export — not just against data that happened to already be in
the store. Workspace 24 was left in place (not deleted) as a clean,
disposable verification fixture; safe to remove if no longer needed.

## Cross-Catalog Verification (APX NEXT/DM4400) — 2 real bugs found and fixed

Re-ingested `APX_Next_config.xml` (46,837 lines, ~24MB) from scratch into a
new workspace (25) — same read → confirm flow, no shortcuts. Result: 1
entity, 48,093 relationships, 46,498 graph nodes. Confirmed 37
`BmConfigAttrSet` + 31 `BmConfigAttrSetAssoc` rows, matching `CPQ_RULE_TOOL_
FLOW_PLAN.md` §15c's original count exactly.

Testing against this SECOND, differently-shaped catalog (not just SVX)
surfaced two real bugs the SVX-only verification had accidentally masked:

**Bug 1 — duplicate driver rows, non-deterministic winner.** BigMachines
emits a redundant, 1-member internal set alongside every real business
set — named `_array_key_{ControlAttrName}`, sharing the exact same
`size_attr_id` as the real set. Confirmed present in BOTH catalogs (SVX
had `_array_key_mountingArrayControl_viSoln` sitting right next to the
real `mountingTypeArrayset_viSoln` — this was in the data all along, just
not flagged during the SVX-only pass). Without a filter, `fetch_attr_set_
assoc`'s dict-building loop let whichever set was fetched LAST silently
win the driver→set mapping — non-deterministic, and wrong whenever the
`_array_key_` row happened to win. **Fixed**: skip any `BmConfigAttrSet`
row whose own `variable_name` starts with `_array_key_` — a stable,
universal BigMachines naming convention confirmed across both catalogs,
not a guess.

**Bug 2 — a real array-set member excluded by the generic `set_type=="2"`
check.** APX's `quantityVX650ItemType_astro` (a genuine, needed-in-every-
row array-set member) is itself flagged `set_type=="2"` — the same code
used to drop genuinely transient UI/action-layer attrs (the original
workspace-14 evidence). Because that exclusion ran BEFORE the array-set
member-routing check, this real member was silently dropped entirely
instead of being grouped into its row. SVX's own members happened to be
`set_type=="1"`, so this never surfaced there. **Fixed**: array-set
membership now checked and routed FIRST, before the `set_type=="2"`
exclusion — membership in a real array-set is a more specific fact than
the generic transient-layer heuristic and takes precedence.

Both fixes verified live against the fresh workspace-25 ingest:
`vX650ItemTypeArrayControl_astro` correctly resolves to the REAL driver
set (`vX650EnergySolutions_astro`, 4 real members) rather than its
`_array_key_` counterpart, and the resulting row correctly nests BOTH
`itemTypeVX650_astro` and `quantityVX650ItemType_astro` (the latter
despite `set_type=="2"`), with the driver shipping as the correct sibling
row-count int.

2 new tests: `test_fetch_attr_set_assoc_skips_the_internal_array_key_
counterpart` (`tests/test_cpq_rdb_attr_set_assoc.py`),
`test_array_set_member_included_even_when_flagged_set_type_2`
(`tests/test_cpq_array_set_payload.py`). Full CPQ/BML suite: 144/144.

**Takeaway for future catalog verification**: single-catalog verification
is not sufficient proof for a cross-catalog mechanism — both of these bugs
were latent in the FIRST (SVX) pass and only surfaced once tested against
a second, independently-modeled real catalog.
