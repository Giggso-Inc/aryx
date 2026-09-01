# CPQ Product Attribute — Missing Menu Option Due to Graph Ingestion Gap

**Date:** 2026-08-17
**Attribute affected:** `productSelectionProduct_all` (display label "Product")
**Catalog:** ApxnextCnofigdata / aSTRO25_bom, workspace_id=43 (local)
**Missing option:** item_value `APX NEXT XE 4G LTE PLUS 5G`, display "APX NEXT XE (4G LTE+5G)"

## Problem Statement

When configuring APX NEXT for USA with Hardware Version = "APX NEXT (4G LTE+5G)"
(`hWVersion_astro = "NEXT ENHANCED LTE PLUS 5G"`), the CPQ engine's "Restrict APX
Next Product Selection based on HW Version selection" constraint rule correctly
resolves **two** legal Product values:

```
APX NEXT ENHANCED
APX NEXT XE 4G LTE PLUS 5G
```

But the Product menu shown to the user only ever offers **one** option
(`APX NEXT Enhanced`), because `APX NEXT XE 4G LTE PLUS 5G` is missing from the
in-memory `ConfigAttr.options` list the engine builds from the ingested graph
data — even though the underlying option data is fully present and correctly
linked in FalkorDB.

This was initially misdiagnosed twice before the real mechanism was found:
1. First guess: a rule-authoring typo (constraint returns a string with no
   catalog match). **Wrong** — disproved by finding the exact node in FalkorDB.
2. Second guess: the parent attribute's graph node had no outgoing edges at
   all (broken `REL` edges from the attribute itself). **Wrong** — the base
   attribute (native id `39427019`) legitimately has 0 direct edges because,
   for this attribute, options are meant to come from a `bm_config_att_override`
   entity instead (BigMachines' catalog-specific override mechanism).
3. **Confirmed root cause:** the *override* entity itself has zero outgoing
   graph edges to its menu-item children, despite the menu items existing and
   being correctly linked via a `ref_id` property.

## Evidence (Cypher queries run live against local FalkorDB, workspace 43)

**1. The option exists as a real node, in 3 override-version copies:**
```cypher
MATCH (e:Entity)
WHERE toString(e.item_value) = 'APX NEXT XE 4G LTE PLUS 5G'
   OR toString(e.name) = 'APX NEXT XE 4G LTE PLUS 5G'
RETURN e.id, e.type, e.name, properties(e)
LIMIT 10
```
Returns 3 `ApxnextCnofigdataBmMenuItem` nodes (ids `2195131`, `2195775`,
`2196127`), each with `item_value = 'APX NEXT XE 4G LTE PLUS 5G'`,
`item_text = 'APX NEXT XE (4G LTE+5G)'`, `order_number = '325'`.

**2. The correct override entity for this attribute:**
```cypher
MATCH (o:Entity {type: 'ApxnextCnofigdataBmConfigAttOverride'})
WHERE o.src_id = '18131370277'
RETURN o.id, o.src_id, properties(o)
```
Returns override entity `id=2251385`, with `attribute_id = '39427019'` —
correctly pointing at `productSelectionProduct_all`'s native BigMachines id.

**3. The property-based join proves the data is complete and correctly linked:**
```cypher
MATCH (m:Entity {type: 'ApxnextCnofigdataBmMenuItem'})
WHERE m.ref_id = '18131370277'
RETURN count(m) AS total, collect(m.item_value)[0..5] AS sample
```
Returns `total = 325` — the full, correct menu list for this override,
**including** `APX NEXT XE 4G LTE PLUS 5G` at `order_number = 325`.

**4. The actual gap — the override entity has NO graph edges to its children:**
```cypher
MATCH (o:Entity {id: 2251385})-[r:REL]->(b:Entity)
RETURN count(r)
```
Returns **0**. Same result via the application's own `reader.neighbors(2251385)`
call. The 325 real, correctly-labeled menu-item nodes exist and are correctly
linked via the `ref_id` **property**, but no `REL` **edges** connect them to
their parent override node.

## Why the Engine Doesn't Self-Heal Here

`src/aryx/cpq/engine.py` (`load_product_config`, ~lines 3460-3538) already has
a documented fix for exactly this class of bug: it detects
`bm_config_att_override` entities and merges their menu items into the base
attribute's option list, specifically to handle the case where the base
attribute's own graph neighbors are stale/incomplete. However, that merge
logic itself depends on `reader.neighbors(override_entity_id)` — the same
graph-edge traversal that's empty for this override. So the merge correctly
runs, finds 0 override neighbors, and silently falls back to whatever stale
base-attribute menu list already existed (325 *other* items, not including
this one).

Separately, `load_product_config` already has an `orphan_eids` FK-fallback
(~line 3390) for **base attributes** that have a real Postgres row but no
graph edges — that fallback re-queries menu items by their Postgres foreign
key instead of graph traversal. **This fallback was never extended to cover
`bm_config_att_override` entities**, which is exactly the gap hit here.

## Fix Needed

**Primary fix (data/ingestion team):** re-run or patch the graph-ingestion
step so it creates the missing edges from `bm_config_att_override` entities to
their `bm_menu_item` children — the same edge type already created correctly
for base attributes and for the other 13 override entities in this catalog
that don't exhibit this gap. The property data (`ref_id`) needed to build
these edges already exists; ingestion only needs to also emit the edge.

**Defensive code-side mitigation (CPQ engine team, optional but recommended):**
extend the existing `orphan_eids` FK-fallback pattern (engine.py ~3390-3428) to
also apply to `bm_config_att_override` entities with zero graph neighbors —
detected structurally (an override row exists in Postgres but
`reader.neighbors(override_eid)` returns empty), not by hardcoded attribute
name, so it self-heals for any future catalog hitting the same ingestion gap.

## Verification Checklist

- [ ] Confirm graph-ingestion pipeline creates `REL` edges for override→menu-item
      relationships (not just the `ref_id` property).
- [ ] Re-ingest or backfill edges for override entity `2251385` (and audit the
      other 13 `ApxnextCnofigdataBmConfigAttOverride` entities for the same gap —
      all 14 currently show 0 graph edges in a broad sweep, though most may be
      structurally edge-less by design; needs per-entity confirmation against
      their expected menu-item counts).
- [ ] After ingestion fix, confirm `productSelectionProduct_all`'s Product menu
      shows both `APX NEXT Enhanced` and `APX NEXT XE (4G LTE+5G)` for
      HW Version = 4G LTE+5G.
- [ ] Re-verify against the dev environment (Postgres `163.192.204.187:15432`,
      FalkorDB `163.192.204.187:6379`) — not yet done as of this writing;
      the dev FalkorDB's workspace-graph naming (`aryx_ws_<id>`) doesn't map
      1:1 to local workspace id 43, so the correct dev graph name needs to be
      resolved first (e.g. via `SELECT id, name FROM aryx_workspace` in the
      dev Postgres) before re-running the same Cypher queries there.

## Related Code Fixes Shipped Same Day (Independent, Not a Substitute)

Two `engine.py` fixes were shipped today as defense-in-depth against this
class of gap producing *worse* symptoms (silent auto-fill or menu
flip-flopping) rather than as a fix for the gap itself:

1. **`is_decision_attr` guard** on the `len(valid_opts) == 1` auto-fill
   shortcut — Product (and other decision-required attrs) now always asks
   the customer instead of silently auto-filling when a constraint's
   real-catalog-matching set narrows to exactly one option.
2. **Partial narrowing** instead of all-or-nothing fallback, in both
   `auto_fill`'s `valid_opts` computation and `next_question_prompt` — when a
   constraint's resolved values are a mix of real and non-matching entries,
   the engine now keeps the real matches instead of either wrongly including
   a non-existent option or discarding the whole narrowing and showing the
   full unconstrained catalog.

Neither fix touches the ingestion gap itself; both remain correct and
necessary regardless of when the ingestion gap is resolved.
