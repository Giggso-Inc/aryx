# BML Array-Iteration Recognition — Implementation Plan

Two candidate approaches are scoped below: **Approach A** (a runtime
evaluator tier in `bml.py`, re-derives the fact on every evaluation) and
**Approach B** (a one-time static-analysis pass at ingestion, writes the
fact into the graph permanently). A comparison and recommendation follow
both designs.

## Problem Statement

`BmlEvaluator` (`src/aryx/cpq/bml.py`) has two tiers today:

- **Tier 1** — deterministic mini-evaluator for if/else-chain scripts
  (`evaluate_declarative_conditions`/`evaluate_tier1`/`evaluate_hide_tier1`).
  `_TIER1_BLOCKERS` explicitly excludes any script containing `for`/`while`
  — so every array-iteration script in a catalog is routed straight past
  Tier 1.
- **Tier 2** — LLM fallback (`_evaluate_llm`/`_evaluate_llm_hide`/
  `_evaluate_llm_condition`), given the script text and current scalar
  `variables` only.

Found while analyzing `mountingTypeArray_viSoln` (SVX catalog): a recurring
BML idiom —

```javascript
arrayRange = range(mountingArrayControl_viSoln);
for idx in arrayRange {
    if(mountingTypeArray_viSoln[idx]=="Shirt Magnetic Mount" AND mountingTypeArrayqty_viSoln[idx]>0)
    { val=true; }
}
return val;
```

— iterating an array-control attribute's size and cross-referencing a
selector array against a parallel quantity array. **Confirmed present in
all 3 available catalog exports**, not just SVX — the loop-variable name
differs per script (`idx`, `cnt`, `each`, `cntEach`, `i`, `k`), which an
initial narrow `[idx]`-only grep undercounted; broadening the search to
match whatever variable a script's own `for <var> in <rangevar>` line
declares (exactly what the recognizer design below already does — see
`_ARRAY_LOOP_RE`, which was loop-var-name-agnostic from the start) gives
the real picture:

| Catalog (XML file) | `range()` calls over an array-control attr | Total `[loopvar]` subscript reads found |
|---|---|---|
| SVX (`SVX Video Remote Speaker Microphone.xml`) | Mounting Type (×18), Accessories (×8), Accessory Type 2 (×6) | **124** across 4 loop-var conventions |
| APX NEXT + DM4400 (`APX_Next_config.xml` — both families share this export) | `relatedSoftwareAndServiceArrayControl_astro` (×12), `solutionCategoryArrayControl_astro` (×7), `vX650ItemTypeArrayControl_astro` (×3), plus a `_pcr`-suffixed one (DM4400's own family) | **162** across 6 loop-var conventions |
| SL3500e (`SL3500e_config.xml`) | `solutionCategoryArrayControl_apcr`, `relatedSoftwareAndServiceArrayControl_apcr` | **74** across 4 loop-var conventions |

This is a real, recurring, and CROSS-CATALOG construct — not a one-off —
and every instance of it currently falls through to Tier 2 (slow,
non-deterministic, costs an LLM round-trip) or times out unresolved. This
substantially strengthens the case for building it: the recognizer
investment pays off in at least 3 catalogs immediately, and — since the
`bm_prd_family` list is shared workspace-wide across these exports (DM4400
literally lives inside the same physical `APX_Next_config.xml` file as APX
NEXT) — likely in most catalogs any given workspace ingests.

Note one real nuance surfaced by the broader scan: not every script using
this loop shape does the same THING inside it — SVX's Mounting Type script
does a simple `selector[idx]=="Literal" AND qty[idx]>0` comparison (exactly
what `parse_array_iteration` below targets), while some APX NEXT scripts
use the same range()/subscript SHAPE but with dictionary lookups
(`containskey(quantityDict, ...)`) or string-splitting logic inside the
loop body instead. The recognizer must keep its "structural match or bail"
discipline — it will correctly pick up the simple comparison shape
wherever it recurs, and correctly decline (fall through to Tier 2) on the
more complex dictionary-driven variants, rather than mis-parsing them.

## Scope — what this DOES and does NOT solve

**Does:** let `BmlEvaluator` deterministically compute a rule's output
(allowed-values / hide-decision / condition) when that rule's script is
this specific "iterate an array, check a selector+quantity pair" shape —
replacing a Tier-2 LLM call with a fast, structural evaluation for rules
like the `isMountingType{Option}_viSoln` boolean flags, which are pure
**derived** values computed from data the session already has.

**Does NOT:** eliminate the need to ask the user for each mount option's
quantity. `mountingTypeJacketMagneticMountQuantity_viSoln` (and its
siblings) hold real business decisions ("how many of this accessory") that
exist nowhere else in session state until the user answers them —
`resolve_pending_grid_quantities`'s heuristic-driven ask flow is the ONLY
source for that value and is unaffected by this plan. This tier only helps
rules whose inputs (the selector array + quantities) are ALREADY filled by
the time the rule needs evaluating — e.g. the boolean flags, and any
downstream pricing/constraint rule that reads those flags or a rollup like
`mountingTypeArrayqty_viSoln`.

## Why the graph doesn't already know this (context for both approaches)

Traced via the ingestion code directly, not assumed:

- `doc_discovery.py`'s FK-relationship discovery (`_detect_fk_links`) is
  generic and schema-agnostic — it infers graph edges purely from **column
  naming conventions** (`*_id`/`*_name` matching a candidate entity type's
  name stem, e.g. `attr_set_id` → `BmConfigAttrSet`). *Structural* facts
  (which attrs belong to which `bm_config_attr_set`, what a set's
  `size_attr_id` points to) are likely already inferable this way, since
  those are literal FK columns.
- But the array-iteration logic itself (`range(control_attr)`,
  `selector[idx]`, `qty[idx]`) lives entirely inside `bm_function
  .script_text` — a single opaque string, fetched as-is in `rdb.py:366`
  (`script = attrs.get("script_text")`) and never parsed into graph
  relationships. There is no static-analysis step anywhere in the
  ingestion pipeline for BML script bodies.
- This is exactly why `bml.py`'s two-tier (structural-pattern / LLM)
  evaluator exists at all — script semantics are never captured at
  ingestion time; every prior "Gap A/Gap B" fix in this codebase's history
  closed exactly this class of hole (rule logic hiding in opaque script
  text that structural ingestion can't see into).

So: the graph captures *declared* relationships (rule → attribute via FK
columns) automatically; it does not capture *behavioral* relationships
embedded in script code. Approach A works around this at runtime, every
evaluation; Approach B closes it once, at ingestion.

## Approach A — Runtime Evaluator Tier (`bml.py`)

### 1. Structural recognizer (new function in `bml.py`)

```python
_ARRAY_RANGE_RE = re.compile(
    r'(\w+)\s*=\s*range\((\w+)\)', re.IGNORECASE)
_ARRAY_LOOP_RE = re.compile(
    r'for\s+(\w+)\s+in\s+(\w+)\s*\{', re.IGNORECASE)
_ARRAY_SUBSCRIPT_RE = re.compile(r'(\w+)\[(\w+)\]')

def parse_array_iteration(script: str) -> "ArrayIterationShape | None":
    """Recognize `<rangevar> = range(<control_attr>); for <idx> in
    <rangevar> { if(<selector>[<idx>]==\"<value>\" AND <qty>[<idx>]><n>)
    { <target>=<literal>; } } return <target>;` (or a bare
    `return <qty>[<idx>];` body for the quantity-copy variant).

    Returns None for anything not matching this exact recognized family —
    same "structural match or bail, never partial-guess" contract as
    evaluate_tier1. Any script this doesn't recognize still falls through
    to Tier 2 unchanged.
    """
```

Returns a small dataclass (`ArrayIterationShape`) carrying: `control_attr`
(the array-control/size attr name), `selector_attr`, `qty_attr`, the
condition's literal comparison value (e.g. `"Shirt Magnetic Mount"`), the
quantity threshold (`>0`), and the assigned/returned result (`val=true` or
`return qty_attr[idx]`).

### 2. Evaluator method (new tier, tried between Tier 1 and Tier 2)

```python
def evaluate_array_tier(
    shape: ArrayIterationShape,
    selected_items: list[str],
    quantities: dict[str, str],  # item_value(lower) -> quantity string
) -> str | bool | None:
    """Simulate the recognized loop against already-known session state.

    `selected_items` — filled_multi[selector_attr] (the array's selected
    rows). `quantities` — per-selected-item quantity, resolved the SAME
    way resolve_array_grid_links already links a selector's item_value to
    its own flat quantity attr — no new array-of-rows data model needed,
    reuses the existing selector->quantity heuristic linkage.

    Returns the boolean/value result, or None if selected_items or a
    needed quantity aren't filled yet (same "unknown, not false" contract
    as every other tier — caller must not treat None as a negative).
    """
```

### 3. Wiring into `BmlEvaluator`

`allowed_values_for_script`/`hide_for_script`/`condition_holds` each try,
in order: Tier 1 → **new array tier (only if `parse_array_iteration`
recognizes the script)** → Tier 2. The array tier needs `filled_multi` and
the selector→quantity linkage (`resolve_array_grid_links`'s output) that
today's callers don't pass through — **this is the one real interface
change**:

- `BmlEvaluator.allowed_values_for_script`/`hide_for_script`/
  `condition_holds` gain an optional `filled_multi: dict[str, list[str]]
  | None = None` parameter (default `None` preserves current behavior for
  every non-array-shaped script — Tier 1/Tier 2 never look at it).
- The ~6 call sites in `engine.py` (`hide_for_script` at line 2437,
  `allowed_values_for_script`/`condition_holds` at 2765/2772, 2881/2888,
  2987/2993) pass `filled_multi` (already in scope at every one of these
  call sites — it's threaded through `evaluate_rules_loop`/`auto_fill`
  already) alongside the existing `filled` argument.
- `build_bml_evaluator` (wherever it constructs the shared linkage) also
  passes `attrs` once so the evaluator can call `resolve_array_grid_links`
  itself and cache the selector→quantity map per catalog — avoiding a
  recompute per script evaluation.

### 4. Fallback safety

Any script `parse_array_iteration` doesn't recognize (different loop-var
naming, a condition shape not in the pattern, anything) returns `None`
from the recognizer and the evaluator falls through to Tier 2 exactly as
today — zero regression risk for scripts outside this exact family.

### Files to Change (Approach A)

| File | Change |
|---|---|
| `src/aryx/cpq/bml.py` | Add `ArrayIterationShape`, `parse_array_iteration()`, `evaluate_array_tier()`; wire as a new tier in `allowed_values_for_script`/`hide_for_script`/`condition_holds`; add `filled_multi` param to those three methods. |
| `src/aryx/cpq/engine.py` | Thread `filled_multi` through the 6 existing call sites; `build_bml_evaluator` passes `attrs` so the evaluator can compute/cache `resolve_array_grid_links` once. |
| `tests/test_bml_*.py` (new or existing) | See test plan below. |

### Test Plan (Approach A)

1. **`test_parse_array_iteration_recognizes_the_mounting_type_shape`** —
   feed the exact real script text (boolean-flag variant) extracted from
   the SVX XML, assert `control_attr`/`selector_attr`/`qty_attr`/literal
   value all parse correctly.
2. **`test_parse_array_iteration_recognizes_the_quantity_copy_variant`** —
   the sibling script (`return qty_attr[idx];`, no boolean literal) also
   parses.
3. **`test_parse_array_iteration_returns_none_for_unrecognized_loop_shapes`**
   — a `for`-containing script that ISN'T this exact family (e.g. a
   different loop idiom already seen elsewhere in this file, like the
   `jsonarraysize(...)`-driven loops) returns `None`, proving the
   recognizer doesn't over-match.
4. **`test_evaluate_array_tier_computes_boolean_flag_from_selected_items`**
   — `selected_items=["Jacket Magnetic Mount"]`, matching quantity filled
   → returns `True`; a DIFFERENT selected item → returns `False` (not
   None — the loop genuinely completes and finds no match, which is a
   real negative, distinct from "unknown").
5. **`test_evaluate_array_tier_returns_none_when_quantity_not_yet_filled`**
   — selected item present but its quantity attr not yet in `filled` —
   must return `None` (unknown), never guess `0` or `False`.
6. **`test_bml_evaluator_tries_array_tier_before_llm_fallback`** — mock the
   LLM call to fail the test if invoked; assert a recognized array-shaped
   script never reaches `_evaluate_llm`.
7. **`test_unrecognized_for_loop_script_still_falls_through_to_tier2`** —
   regression: an existing script already exercising Tier 2 (from
   `test_cpq_rule_validation_*` fixtures) is unaffected — this stays a
   Tier-2 hit, proving the new tier doesn't accidentally intercept
   unrelated `for`-containing scripts.

### Risks (Approach A)

- **Pattern brittleness**: the recognizer is deliberately narrow (same
  philosophy as Tier 1's own `_TIER1_BLOCKERS`/branch parser) — a
  catalog-specific loop-variable name or condition ordering outside the 3
  confirmed real examples simply won't match and falls through to Tier 2
  unchanged, so the risk is "misses an opportunity," never "computes a
  wrong answer."
- **`resolve_array_grid_links` reuse**: this plan reuses the EXISTING
  selector→quantity heuristic rather than inventing a new one — if that
  heuristic's own known limitation (ambiguous/short option tokens skipped,
  see its docstring) applies to a given selector, the array tier simply
  can't resolve quantities for it either and falls through to Tier 2 —
  consistent, not a new failure mode.
- **Recomputed every evaluation**: the recognizer re-parses the script
  text on every cache-miss (same cost model Tier 1 already has) — cheap
  per-call, but the FACT "this script array-iterates X/Y/Z" is rediscovered
  each time, never persisted anywhere for other tooling (e.g. a future
  catalog-audit report) to query directly.

## Approach B — Ingestion-Time Static Analysis (graph enrichment)

Instead of (or in addition to) re-parsing script text at runtime, run the
SAME structural recognizer **once, at ingestion**, over every
`bm_function.script_text` in a catalog, and materialize what it finds as
first-class graph edges — so "this rule array-iterates control-attr Y,
cross-referencing selector Z and quantity W" becomes a permanent, directly
queryable graph fact, not something re-derived per evaluation.

### Design

1. **New ingestion pass** in `doc_discovery.py`, sibling to `_detect_fk_links`
   (which already emits the same `{source_type, source_attr, target_type,
   target_attr, name}` link shape consumed downstream) — call it
   `_detect_script_data_flow_links(plans, log_id=None)`:
   - Finds the `bm_function` (or equivalent) plan among `plans`.
   - For each row, reads its `script_text` column and runs the SAME
     `parse_array_iteration()` recognizer Approach A defines (share the
     one recognizer — do not maintain two independent regex sets for the
     same idiom).
   - For each recognized script, emits 3 links from that `bm_function` row
     to the `bm_config_attr` rows matching `control_attr`/`selector_attr`/
     `qty_attr` by variable_name — named e.g. `BMFUNCTION_ARRAY_ITERATES`,
     `BMFUNCTION_READS_SELECTOR`, `BMFUNCTION_READS_QUANTITY` — reusing
     `_detect_fk_links`'s existing link-materialization path (same shape,
     just a different discovery mechanism than column-name inference).
2. **Wire into the pipeline**: call `_detect_script_data_flow_links`
   alongside the existing `_detect_fk_links` call (`ingest_confirmed` or
   wherever `_detect_fk_links`'s output currently gets merged into the
   final link list) — additive, not a replacement.
3. **Downstream consumers**: once these edges exist, `build_bml_evaluator`/
   `resolve_array_grid_links` could query the graph for
   `BMFUNCTION_ARRAY_ITERATES` edges instead of re-deriving the selector→
   quantity linkage via the current variable-name heuristic — a
   *separate*, later follow-up, not required for this plan to land value
   (the graph fact is useful to other tooling immediately, independent of
   whether the runtime path is ever switched to consume it).

### Files to Change (Approach B)

| File | Change |
|---|---|
| `src/aryx/pipeline/doc_discovery.py` | Add `_detect_script_data_flow_links()`; wire its output alongside `_detect_fk_links()`'s. |
| `src/aryx/cpq/bml.py` | Export `parse_array_iteration()` (already needed for Approach A) so the ingestion pass can import and reuse it — single source of truth for the pattern. |
| `tests/test_doc_discovery.py` (or similar) | New tests below. |

### Test Plan (Approach B)

1. **`test_detect_script_data_flow_links_finds_array_iteration_in_bm_function`**
   — feed a `bm_function` plan containing the real SVX script text, assert
   the 3 expected links (control/selector/quantity) are emitted with
   correct source/target types.
2. **`test_detect_script_data_flow_links_skips_unrecognized_scripts`** —
   a `bm_function` row with unrelated script text produces no extra links
   (reuses Approach A's recognizer, so this is really re-confirming
   `parse_array_iteration`'s own "return None" contract at the ingestion
   boundary).
3. **`test_ingestion_links_merge_with_fk_links_without_duplication`** — the
   new link source coexists with `_detect_fk_links`'s structural output
   for the same catalog without collision (different `name` values, no
   dedup needed, but worth asserting explicitly).

### Risks (Approach B)

- **Ingestion-time cost**: an extra full scan of every `bm_function` row's
  script text per ingest — cheap relative to the rest of ingestion
  (regex over already-loaded CSV rows), but adds a new pass to a pipeline
  already carrying several (`_detect_fk_links` itself, XML→CSV conversion,
  etc.).
- **Re-ingestion required**: catalogs already ingested before this change
  ships won't have these edges until re-ingested — this is a graph
  ENRICHMENT, not a retroactive migration, unless a backfill script is
  also written (out of scope for this plan; a one-off if ever needed).
- **Still needs Approach A (or equivalent) to actually USE the fact at
  runtime**: writing the graph edge doesn't by itself make CPQ turns
  faster or more deterministic — something still has to consume
  `BMFUNCTION_ARRAY_ITERATES` edges at evaluation time. Approach B makes
  the fact durable and queryable; it doesn't replace Approach A's runtime
  evaluation, though it COULD let a future runtime path skip re-parsing
  script text (query the graph edge instead of running the regex again).

## Comparison and Recommendation

| | Approach A (runtime tier) | Approach B (ingestion-time graph enrichment) |
|---|---|---|
| Where the fact lives | Re-derived every evaluation, in-process | Permanent graph edge, queryable anytime |
| Time to value | Immediate — lands the moment `bml.py` ships | Needs a fresh ingest to take effect on existing catalogs |
| Useful to other tooling (audits, docs, future features) | No — internal to one evaluator call | Yes — any graph query can see it |
| Implementation surface | `bml.py` + `engine.py` call-site threading | `doc_discovery.py` + ingestion pipeline wiring |
| Risk profile | Low — same "match or bail" safety as existing Tier 1 | Low — additive pass, but re-ingestion-dependent |

**Recommendation: build Approach A first, standalone.** It delivers the
actual runtime value (deterministic evaluation, no LLM round-trip) on its
own, works on already-ingested catalogs with zero re-ingestion, and — since
Approach B's design explicitly reuses Approach A's `parse_array_iteration()`
recognizer — building A first means B is a smaller follow-up (wiring an
already-written, already-tested recognizer into the ingestion pipeline)
rather than parallel, duplicated pattern-matching logic. Approach B is a
genuinely valuable next step once A proves the recognizer is solid against
real catalogs, not a competing choice.
