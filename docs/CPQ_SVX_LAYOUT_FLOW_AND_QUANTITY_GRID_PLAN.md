# CPQ SVX Layout-Flow & Quantity-Grid Requirement

Status: **Proposed — not yet implemented.** Investigated and scoped live against workspace 19
(both APX Next and SVX Video Remote Speaker Microphone catalogs, fully ingested and verified
byte-accurate to their raw XML exports).

---

## 1. Trigger

Live screenshot from `msicpq-dev1.motorolasolutions.com/config/videoSolutions_BOM/mobile_BOM/vX650_BOM`
(the real BigMachines native UI for the SVX Video Remote Speaker Microphone catalog) shows:

- **No "Product" field anywhere on screen.** The visible fields are: Ultimate Destination
  Country, Solution Type, Subscription Duration, Select Model — no product picker.
- **A mounting-type quantity grid** (6 rows — Shirt Magnetic, Jacket Magnetic, Shirt Clip, Jacket
  Clip, Locking Molle, TEK-LOK Belt Mount — each with its own Quantity column), rendered as a
  native BigMachines array editor.

Our conversational ask-flow does the opposite of both: it prompts the user for
`productSelectionProduct_all` (a field the real UI never shows for this catalog), and it never
asks for any of the 6 mounting-type quantities at all.

---

## 2. Problem statement

**2a — False "Product?" prompt.** The engine's `is_decision_attr` override
(`engine.py`, added earlier this session for APX Next) unconditionally always-asks
`productSelectionProduct_all` regardless of catalog, because no single rule reliably narrows its
325-option list. This override never checks whether the real native UI would show this field at
all. For SVX, it wouldn't — so the ask-flow interrupts the customer with a question BigMachines
itself never asks.

**2b — Quantity-grid attributes are invisible to the ask-flow.** The 6
`mountingType*MountQuantity_viSoln` attributes are `hidden=1` in the raw XML and driven entirely
by an array-control attribute (`mountingArrayControl_viSoln` / `mountingTypeArray_viSoln`). The
engine's attribute model only understands scalar values and flat multi-select lists — it has no
concept of "a grid of per-row quantities gated behind an array controller." These 6 fields are
therefore silently never asked, never filled, and never appear in the final payload, even though
a real customer configuring this BOM through the native UI would set them explicitly.

---

## 3. Root-cause analysis (verified against raw XML + live graph, workspace 19)

### 3a. Why `productSelectionProduct_all` is asked when it shouldn't be

Confirmed via `bm_config_layout_attr_assoc` (which attribute sits under which native-UI layout
node) and `bm_config_rule` (`rule_type=6`, "Configuration Flow" rules — these define which layout
tree is actually active for a given BOM flow):

| Flow rule | `variable_name` | `status` | Meaning |
|---|---|---|---|
| id `19435423792` | `configurationFlowForVX650VideoSolutions_BOM` | **3 (inactive)** | Dead flow — layout tree not rendered |
| id `22194434699` | `configurationFlows_vx650_SysConfig` | **1 (active)** | The real, live flow for this catalog |

`productSelectionProduct_all` is associated to a layout node under **both** flows. Since one is
inactive, the field's real visibility depends on which flow is live — but the engine's
`is_decision_attr` override has no path awareness at all; it always asks, independent of
`status`.

**Existing infrastructure not yet wired up:** `engine.py` already has
`_detect_layout_tier()` and `resolve_ui_layout_scope()` (added in an earlier session,
`docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md`) — built specifically to resolve which attributes the
real native UI shows. **Neither function is called anywhere in the codebase.** They were left
unwired because of a documented, real ambiguity: **APX Next has 3 `rule_type=6` flows, two of
which are simultaneously active** (confirmed live):

| Flow rule | `variable_name` | `status` |
|---|---|---|
| id `22194396138` | `configurationFlowForAstroDevicesPortable` | 1 (active) |
| id `19435387689` | `configurationFlowForAstroDevicesPortable` (duplicate name) | 3 (inactive) |
| id `22194396144` | `systemConfigUsers` | 1 (active) |

With 2 active flows for APX Next, there's no safe way to pick "the" flow — any heuristic tried in
the earlier session picked the wrong one when checked against ground truth. This is exactly why
the resolver was left disconnected rather than guessing.

**The key insight this analysis adds:** `rdb.fetch_rules()` (the function both resolver methods
call to fetch `rule_type=6` rows) **never filters by `status` at all** — it returns every
`rule_type=6` rule regardless of whether it's active or inactive. Filtering to `status='1'` alone:
- Resolves SVX cleanly down to exactly **1** active flow.
- Still leaves APX Next at **2** active flows — genuinely ambiguous, unresolved by this filter
  alone.

This is why the fix below is scoped to activate ONLY when the filter resolves to exactly one
active flow — APX Next's existing behavior is structurally guaranteed to stay untouched.

### 3b. Why quantity-grid attributes are never asked

Confirmed via `bm_config_attr` + `bm_config_rule_action`: the 6 mounting-type quantity attributes
are all `hidden=1`, `data_type=3` (integer), and are targets of action rule
`forceSetMountingArraySizeOptionalAccessoriesArraySizeAndValues` — a rule that sizes and
populates these fields based on which rows the array-control attribute
(`mountingArrayControl_viSoln`, `is_array_control_attr=1`) has selected. This is a structural gap
in the engine's attribute model, not a bug in existing logic — there has never been a
representation for "array of rows, each contributing its own sub-attribute value" in the ask-flow.
`classify_select_type` (extended earlier this session for Date/Currency/Integer/Float/Array
payload *rendering*) only covers how a value is *serialized* into the payload — it does not cover
how the engine *asks* for an array-backed value in conversation.

---

## 4. Verified facts (not assumptions)

- Both catalogs are fully and correctly ingested into workspace 19 — `Svx Video Remote Speaker
  MicrophoneBmConfigAttr` has exactly 235 entities, matching the raw XML's `bm_config_attr` count
  1:1. `ApxNextConfigBmConfigAttr` has 427, matching APX Next's raw XML.
- `productSelectionProduct_all` exists in both catalogs' graph data.
- Both `rule_type=6` flow rules' `status` values survived ingestion unchanged (`3` and `1`
  respectively for SVX) — verifiable directly via `GraphReader.find_entities` against workspace
  19 today, no re-ingestion required.
- `resolve_ui_layout_scope()` and `_detect_layout_tier()` already exist in `engine.py` but are
  dead code (zero call sites outside their own definitions) — confirmed via full-repo grep.

---

## 5. Proposed fix — two files

### File 1: `src/aryx/cpq/rdb.py`

**Change:** `fetch_rules(self, workspace_id, rule_type, catalog_prefix="")` — add a `status='1'`
filter to the existing query (both the SQLite/Postgres and any Oracle-flavored implementations of
this method in the file) so only active configuration-flow rules are returned.

```python
# Before (conceptually):
SELECT id, ... FROM aryx_entity
WHERE workspace_id = :1 AND ontology_type LIKE :3
  AND JSON_VALUE(attributes, '$.rule_type') = :2

# After:
SELECT id, ... FROM aryx_entity
WHERE workspace_id = :1 AND ontology_type LIKE :3
  AND JSON_VALUE(attributes, '$.rule_type') = :2
  AND JSON_VALUE(attributes, '$.status') = '1'
```

This is a narrow, purely additive filter — every existing caller of `fetch_rules` for
`rule_type` values other than `"6"` is unaffected in shape (hiding/constraint/recommendation
rules already filter active-vs-inactive at a different layer); confirm this doesn't change
existing hiding/constraint/recommendation rule counts before merging (regression check: rerun
`count_rules.py`-style counts against workspace 3/19 pre- and post-change).

### File 2: `src/aryx/cpq/engine.py`

**Change A — wire the existing (currently dead) layout resolver into the always-ask override:**

In `auto_fill`, where `is_decision_attr` is computed for `productSelectionProduct_all`
(around the `or vn == "productSelectionProduct_all"` branch), add a guard:

```python
if vn == "productSelectionProduct_all":
    scope = self.resolve_ui_layout_scope(workspace_id, catalog_prefix)
    if scope and scope["tier"] == 1 and len(scope["flows"]) == 1:
        # Exactly one active flow resolved — trust native UI truth: only
        # force this question if the field actually appears in that flow.
        the_flow = next(iter(scope["flows"].values()))
        if attr.entity_id not in the_flow["all"]:
            is_decision_attr_override = False  # don't force-ask
    # else: tier != 1, or >1 active flows (e.g. APX Next) — fall through
    # to today's unchanged always-ask behavior. No regression risk.
```

(Exact integration point needs a careful read of the current `auto_fill` control flow around
`is_decision_attr`'s existing boolean expression — this is pseudocode showing the *shape* of the
gate, not a literal diff.)

**Change B — new array-grid quantity attribute-kind:**

1. Detection: an attribute is array-grid-backed when it's the target of a rule whose condition
   references an `is_array_control_attr=1` attribute (e.g. `mountingArrayControl_viSoln`) AND the
   attribute itself is `hidden=1` with `data_type` numeric (int/float) — matches the
   `mountingType*MountQuantity_viSoln` pattern exactly, generically (not VX650-specific).
2. Ask-flow: per the design agreed earlier this session —
   a. First ask which array-control options the customer wants (multi-select over the control
      attribute's own menu items, e.g. mount types).
   b. Then batch a single follow-up question asking quantities for only the chosen options
      (skips the other rows entirely — mirrors the array-control rule's own gating).
3. `build_payload`: include only the rows the customer actually selected and quantified: skip
   zero/unselected rows exactly like `hidden_vns` already does for hiding-rule exclusions.

---

## 6. Non-goals / explicit exclusions

- Does **not** attempt to resolve APX Next's 2-active-flow ambiguity — that remains an open,
  separate problem, deliberately left unsolved per the earlier session's "never guess" principle.
- Does **not** change `is_decision_attr`'s behavior for any catalog where the layout resolver
  can't cleanly resolve to one active flow — existing conversations for APX Next are
  byte-for-byte unaffected.
- Does **not** require re-ingesting either XML file — workspace 19's existing graph data is
  sufficient to implement and verify both changes live.

---

## 7. Verification plan

1. Unit: extend `tests/test_cpq_e2e.py` with a case asserting `productSelectionProduct_all` is
   NOT prompted for a synthetic catalog with exactly one active `rule_type=6` flow that excludes
   it from the layout tree.
2. Regression: rerun the full `test_cpq_e2e.py` suite — must stay at the current baseline (37
   passed / 3 pre-existing unrelated failures) with zero new failures.
2b. Regression check specifically for APX Next: confirm `productSelectionProduct_all` is still
   always-asked (tier resolves to 2 active flows → override never applies).
3. Live: re-run the exact SVX conversation from the screenshot against workspace 19 post-fix —
   confirm no "Product?" prompt appears, and confirm the mounting-quantity question flow surfaces
   correctly for a customer requesting 2-3 mount types.
4. Independent-oracle cross-check (`scripts/check_cpq_rule_loop.py`) against both workspace 19
   catalogs to confirm no new rule-consistency regressions from either change.
