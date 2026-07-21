# BigMachines Array-Set Payload — Implementation Plan

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

`state.py:125-180`, three new fields (mirroring how `is_array_control`
was added for the size/control attr concept):

```python
array_set_id: int | None = None      # shared set id, None = not a set member
array_set_role: str = ""             # "driver" | "member"
array_col_order: int = 999           # ordinal position within the set's row
```

`classify_select_type()` keeps its existing logic UNCHANGED for attrs with
`array_set_id is None` — this is additive, not a reclassification of the
whole multi/boolean/single split. A NEW check in the `ConfigAttr`
construction loop (`engine.py:1908-1923`) sets `array_set_id`/`array_set_
role`/`array_col_order` from the new `fetch_attr_set_assoc` data, keyed by
`source_id` (the same BM-native id every other rule/set join already uses
to cross-reference `ConfigAttr`).

### 3. `build_payload` — group array-set members into one indexed row

`engine.py:4770-4784`'s `filled_multi` loop gains a branch BEFORE the
existing flat-serialization fallback: if `attr.array_set_id is not None`,
route it to a separate accumulator keyed by `array_set_id` instead of
`out[k]` directly. After the main loop, one pass over that accumulator
builds the real shape:

```python
for set_id, members in array_set_accum.items():
    driver = next(m for m in members if m.role == "driver")
    rows = []
    max_len = max(len(m.values) for m in members if m.role == "member")
    for idx in range(max_len):
        row = {"_index": idx}
        for m in members:
            if m.role == "member" and idx < len(m.values):
                row[m.display_label] = {"value": m.values[idx], "displayValue": m.display}
        rows.append(row)
    out[f"_set{driver.variable_name}set_{driver.catalog_suffix}"] = {"items": rows}
```

(Pseudocode — the real member/value alignment needs confirming against a
live array-set payload sample once one is available; see Open Questions.)
The top-level key naming convention (`_set{Name}set_{suffix}`) is taken
directly from the user's own confirmed real payload
(`_setmountingTypeArrayset_viSoln`) and the `_setCountryArray` example in
§15c — both follow `_set{DriverName}(set)?_{catalogSuffix}`.

## Files to Change

| File | Change |
|---|---|
| `src/aryx/cpq/rdb.py` | Add `fetch_attr_set_assoc()` (Postgres + Oracle variants), mirroring existing fetch_* methods. |
| `src/aryx/cpq/state.py` | Add `array_set_id`/`array_set_role`/`array_col_order` to `ConfigAttr`. |
| `src/aryx/cpq/engine.py` | Wire the new fetch into `ConfigAttr` construction (~1908-1923); add the array-set grouping branch to `build_payload`'s `filled_multi` loop (~4770-4784). `classify_select_type` unchanged. |
| `tests/test_cpq_payload_shapes.py` | New tests (see below) — same file the `mountingArrayControl_viSoln` exclusion test already lives in. |

## Test Plan

1. **`test_array_set_member_groups_into_indexed_rows_not_flat_items`** —
   2 member attrs sharing an `array_set_id`, each with `filled_multi`
   values → asserts the payload key is the driver-named `_set{name}set_`
   wrapper, `items` contains one dict per index with `_index` present and
   BOTH member columns nested inside, NOT two separate flat top-level keys.
2. **`test_non_array_set_multi_select_still_serializes_flat`** — a plain
   `select_type=="multi"` attr with no `array_set_id` keeps the EXISTING
   flat shape unchanged — regression guard, this fix must be purely
   additive.
3. **`test_array_set_driver_control_attr_itself_excluded_from_member_rows`**
   — the driver/control attr's own raw value (e.g. `mountingArrayControl_
   viSoln`) doesn't ALSO appear as a flat top-level key once grouped (this
   builds on the already-shipped exclusion for `is_array_control`,
   confirming the two mechanisms compose correctly rather than double-
   counting or conflicting).
4. **`test_fetch_attr_set_assoc_returns_ordered_member_columns`** — rdb.py
   unit test against a fake cursor/connection, confirming set→member
   ordering survives the fetch.

## Risks

- **Member/value alignment is the one real unknown.** The pseudocode above
  assumes member columns' `filled_multi` LISTS are already positionally
  aligned by index (row 0's mount type pairs with row 0's quantity) — this
  needs confirming against how `resolve_pending_grid_quantities` (the
  existing per-option quantity heuristic, `engine.py:2255-2286`) actually
  populates these lists today; it may already produce aligned per-option
  lists, or it may need a small adjustment to guarantee alignment before
  `build_payload` can safely zip them by index.
- **Only 6 confirmed array-sets in one catalog family (APX NEXT/DM4400).**
  SVX's `mountingTypeArray_viSoln` needs the SAME direct-XML confirmation
  §15c did for the APX catalog (parse `bm_config_attr_set`/`_assoc` for the
  SVX export specifically) before assuming it's definitely a `driver` +
  `mountingTypeShirtMagneticMountQuantity_viSoln`/`...JacketMagneticMount
  Quantity_viSoln` member-column set rather than a coincidentally similar
  but differently-modeled construct — the user's own pasted "payload
  original from CPQ engine" sample is strong evidence but not yet cross-
  checked against SVX's raw `bm_config_attr_set` rows the way APX's was.
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

This resolves Open Question 2 in the direction this plan already assumed
— the selector value AND its per-row quantity (`mountingTypeArrayqty_
viSoln`) are sibling keys inside the SAME `_index` row, confirming
`mountingTypeArrayqty_viSoln` is a genuine array-set MEMBER column, not an
independently-fetched flat attr the way `resolve_pending_grid_quantities`
currently treats it.

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
