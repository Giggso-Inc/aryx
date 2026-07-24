# Aryx XML Ingestion Improvement Plan

**Status:** Proposed for implementation
**Audience:** Engineering, ingestion/ontology owners
**Prepared for:** XML ingestion architecture decision
**Date:** 2026-07-08

## 1. Executive Summary

Aryx currently ingests XML by flattening it into per-entity-type CSVs (`_xml_to_csvs`) and running those CSVs through the same tabular pipeline used for native CSV/JSON sources — Discover → Resolve → Relate → FK-Link → Project. This works well for shallow, record-like XML (catalogs, product lists) but has two concrete failure modes on deep, structural XML such as CPQ/configurator exports:

1. **Entity types beyond a configurable cap are silently dropped** — not degraded, dropped entirely, with only a log warning.
2. **Every extracted type — whether it's a real business entity or internal wiring — goes through the same expensive entity-resolution/dedup funnel**, which is unnecessary for single-sourced structural data and produces noisy, hard-to-query graphs (confirmed live during Ask API debugging this week — see §3).

The recommended solution is a **hybrid two-track ingestion model**: keep the existing tabular pipeline (with two targeted extensions) for record-like entities, and add a lighter, non-resolving direct-projection path for structural/wiring entities. A new deterministic ID/IDREF cross-reference scanner replaces reliance on column-naming conventions alone for relationship discovery.

This should be implemented as an extension of `doc_discovery.py`, not a rewrite of the ingestion pipeline.

## 2. Problem Statement

### Current implementation (verified against code, not assumption)

`_xml_to_csvs()` (`src/aryx/pipeline/doc_discovery.py:143-404`) is more capable than a naive flatten:

- It walks the **entire XML tree** (no depth limit in the walk itself).
- Each entity element gets an FK column to its **nearest enclosing parent** (`{parent_tag}_id`), and this parent-tracking updates at every nesting level as the walk descends (`_collect_tag`, line 316-353) — so a chain like `Root → A → B → C` produces `C.B_id`, `B.A_id`, `A.Root_id` as three separate pairwise links, not a single flattened link. Multi-hop relationships between distant types are then reconstructed transitively by graph traversal once each direct edge exists — this part already works correctly.
- `_detect_fk_links()` (line 504-603) does a full **O(N²) pairwise scan across every extracted type**, not just adjacent ones, matching column names against `{Type}_id` / `{Type}_name` patterns (singular/plural, tag-word forms).

### What actually breaks

- **`ARYX_XML_MAX_ENTITY_TYPES` (default 20, `config.py:95-102`)**: only the top-N entity types (named types first by frequency, then unnamed) are extracted as CSVs at all (`doc_discovery.py:303-314`). A CPQ/BigMachines export with 25+ distinct element types silently loses the excess 5+ — no CSV, no graph nodes, no relationship, nothing. We observed at least 7 distinct entity types (`ConfigAttr`, `ConfigRule`, `MenuItem`, `ConfigPageTemplate`, `ConfigLayoutAttrAssoc`, `ConfigZipCache`, `PrdFamily`) just from one entity's 1-hop neighbor list in production data — real CPQ exports plausibly exceed the default cap.
- **`ARYX_XML_MAX_ROWS_PER_TYPE` (default 500, `config.py:103-107`)**: rows beyond this are dropped per type, logged as a warning (`doc_discovery.py:384-389`).
- **No distinction between record types and structural types.** `ConfigRule`/`ConfigPageTemplate`-style wiring entities compete for the same 20-type budget as `Product`/`ConfigAttr`-style business entities, and both go through the full Resolve funnel (blocking, embedding, four-band adjudication) even though wiring entities are canonical within one file and never need cross-source dedup.
- **Relationship discovery is naming-convention-dependent.** `_detect_fk_links` only fires when a column name matches the `{Type}_id`/`{Type}_name` pattern. True cross-references via arbitrary ID/IDREF-style attributes (e.g. `<line-item product-ref="P1">` pointing at an `id="P1"` element elsewhere in the tree, not its parent) are not detected unless the column happens to be named in the expected pattern.

## 3. Why This Matters Now

This surfaced directly while debugging the Ask API's configurator-confirmation flow this week: `render_context()` (`src/aryx/graph/retrieve.py`) dumping a `ConfigAttr` entity's full neighbor list returned mostly `ConfigRule`/`ConfigPageTemplate` wiring edges, not the `MenuItem` values actually needed to answer the question — requiring a purpose-built filter (`render_configurator_context`, later reverted) to work around. That symptom traces back to ingestion: wiring and business-entity types are stored identically, so retrieval has no way to distinguish "useful" edges from "internal plumbing" edges without hardcoding a type-name filter per use case.

## 4. Recommendation

Adopt a **two-track ingestion model**, classified per entity type at discovery time.

### Track A — record-like entities (unchanged pipeline, two fixes)

Entities with genuine business identity that plausibly duplicate across sources (`Product`, `Customer`, `ConfigAttr`-with-confirmed-values). Continue through the existing `run_pipeline` (Discover → Resolve → Relate → FK-Link → Project) — this is where cross-source dedup, confidence-weighted golden-record merge, and the human-adjudication queue earn their cost.

**Fix 1 — raise or auto-scale the type cap.** Rather than a fixed default of 20, detect the actual distinct-type count during the tree walk and either raise `ARYX_XML_MAX_ENTITY_TYPES` automatically (with a hard ceiling and a loud log/metric) or surface the true count to the operator before silently truncating.

**Fix 2 — nothing else changes.** The nearest-parent FK chaining and pairwise `_detect_fk_links` already handle multi-hop correctly; no rework needed here.

### Track B — structural/wiring entities (new, lighter path)

Entities that are canonical within one file/system and never need cross-source dedup (`ConfigRule`, `ConfigPageTemplate`, `ConfigZipCache`, junction/association tables). Project these directly as graph nodes/edges, **skipping the Resolve stage** — identity comes from the source's own element ID, not fuzzy matching. This removes them from the type-cap competition entirely (they can have their own, more generous cap since there's no expensive per-type resolution cost) and stops them from drowning out business-entity edges in retrieval.

**Classification rule (first pass, not required to be perfect):** reuse the existing `_is_entity` heuristic plus a name-field signal already computed in `_xml_to_csvs` (`type_has_name` dict, line 265) — types that never carry a human-readable name field are already deprioritized for the type-cap slot ordering (line 311-313); the same signal is a reasonable starting point for the Track A/B split. Support an explicit config override list for known structural type names per source (mirrors the existing `ARYX_XML_MAX_ENTITY_TYPES`-style settings pattern in `config.py`).

### Cross-cutting — deterministic ID/IDREF relationship detection

Add a tree-wide ID index pass: walk the full document once, record every element's declared `id`, then scan all attribute/child-text values (not just column names matching `{Type}_id`) against that index to find true cross-references regardless of nesting position. This runs once per document and benefits both tracks. Reserve the existing LLM Relate stage (`src/aryx/pipeline/...` relate step, capped by `ARYX_MAX_RELATE_PAIRS`) for pairs with no explicit ID reference — same mechanism as today, applied to a smaller, cheaper pool since the deterministic pass catches the obvious links first.

## 5. Technical Direction — Phased

### Phase 1: Visibility before any behavior change

- Add a metric/log line in `_xml_to_csvs` reporting the true distinct-entity-type count found vs. the configured cap, so truncation is never silent.
- No pipeline behavior changes yet — this is a diagnostic prerequisite for Phase 2/3 decisions.

### Phase 2: Track classification + Track B projection path

- Implement the record-vs-structural classifier (reusing `type_has_name` plus an override list).
- Build the direct graph-projection path for Track B types: element → node, nesting → edge, source element ID → node identity. This bypasses `run_pipeline`'s Resolve stage entirely — new, smaller code path, not a modification of the existing resolution funnel.
- Track A continues unchanged through `run_pipeline`.

### Phase 3: Deterministic cross-reference scanner

- Add the tree-wide ID index + attribute/value cross-reference scan, producing relationship edges independent of column-naming convention.
- Narrow the LLM Relate stage's input to pairs the deterministic scanner did *not* already link, reducing `ARYX_MAX_RELATE_PAIRS` pressure and cost.

### Phase 4: Type-cap auto-scaling

- Replace the fixed default-20 cap with a workspace-aware cap that reacts to Phase 1's visibility data (e.g., raise automatically up to a hard ceiling, alert when the ceiling itself is hit).

## 6. Scope Definition

### In scope

- `src/aryx/pipeline/doc_discovery.py`: `_xml_to_csvs`, `_detect_fk_links`, `_is_entity`, `ingest_confirmed`
- `src/aryx/config.py`: `xml_max_entity_types`, `xml_max_rows_per_type`, new Track B settings
- New: a direct XML→graph projection path (new module, e.g. `src/aryx/pipeline/xml_structural_project.py`)
- New: tree-wide ID/IDREF cross-reference scanner

### Out of scope

- Changing the CSV-based ingestion path for native CSV/JSON sources (unaffected)
- Rework of the Resolve stage's scoring/adjudication logic (Track A reuses it unchanged)
- Schema-aware (XSD/DTD) parsing — considered and deferred; most real-world exports observed so far (CPQ/BigMachines) don't ship reliable schemas, so the payoff doesn't currently justify the cost
- Ask API / retrieval-layer changes (the configurator-prompt work from this week was reverted; retrieval-side filtering is a separate, later decision once ingestion produces cleaner track-separated data)

## 7. Options Considered

### Option A: Extend the tabular pipeline only (raise caps, deepen FK chaining)

**Assessment:** Insufficient alone.

Reason: solves the type-cap truncation risk but does nothing about wiring entities drowning out business entities in retrieval, and doesn't add deterministic cross-reference detection.

### Option B: Full graph-native mapping for all XML (no tabular path)

**Assessment:** Not recommended as the sole approach.

Reason: discards the entity-resolution/dedup funnel entirely, including for entities that genuinely need cross-source dedup. Produces a graph that mirrors XML's literal (often accidental) structure rather than a curated ontology.

### Option C: Hybrid two-track model with deterministic cross-reference scanning

**Assessment:** Recommended.

Reason: keeps dedup where duplication is real (Track A), removes resolution overhead and type-cap competition where it isn't needed (Track B), and replaces brittle naming-convention-dependent FK detection with a real tree-wide reference scan that benefits both tracks.

## 8. Delivery Plan

1. Phase 1 — add truncation visibility (log/metric only). Ship first; informs real-world cap tuning before anything else changes.
2. Phase 2 — classifier + Track B projection path, gated behind a feature flag so Track A behavior is provably unchanged during rollout.
3. Phase 3 — deterministic ID/IDREF scanner, wired to reduce (not replace) the LLM Relate stage's input pool.
4. Phase 4 — auto-scaling type cap, informed by Phase 1 telemetry across real workspaces.
5. Validate against a real CPQ/BigMachines-style export known to exceed the current type cap (the APX Next config data used in this week's Ask API debugging is a good candidate).

## 9. Acceptance Criteria

- No entity type is dropped from an XML source without an explicit, visible log/metric — silent truncation is eliminated.
- Structural/wiring entity types no longer flow through the Resolve stage, verified by absence of `aryx_adjudication`/embedding calls for those types.
- A cross-reference between two elements that are not in a direct parent-child relationship (e.g., sibling-level ID reference) is captured as a graph edge without requiring an LLM call.
- Track A entities (record-like) show no behavior change versus current production — same resolution, same golden-record output — confirming Track B is additive, not a regression risk.
- Retrieval on a workspace ingested this way shows a measurable drop in wiring-type edges surfaced for business-entity questions (informal validation via the Ask API test harness used this week).

## 10. Risks and Mitigations

### Risk: Track A/B classification misclassifies a type

**Mitigation:** Start with the config override list as the authoritative signal per known source; treat the heuristic as a fallback default only, not the sole mechanism.

### Risk: Track B's direct-projection path introduces a second, divergent code path to maintain

**Mitigation:** Keep it deliberately small — node/edge emission only, no scoring, no adjudication. Explicitly out of scope: any future feature parity with Track A beyond structural projection.

### Risk: Raising the type cap increases ingest time/cost proportionally

**Mitigation:** Phase 1's visibility work informs this tradeoff with real numbers before Phase 4 auto-scaling ships, rather than guessing at a new default.

### Risk: Deterministic cross-reference scanner produces false-positive links on coincidental ID matches

**Mitigation:** Scope the scanner to attributes/values that look ID-shaped (matches an existing element's `id` exactly, not a substring or fuzzy match) — same conservative-match philosophy already used in `_detect_fk_links`'s `_col_is_varying` check (`doc_discovery.py:522-542`), which exists specifically to avoid cartesian-product false edges from constant-value columns.

## 11. Recommended Decision

Proceed with the **hybrid two-track model**, phased as above, starting with Phase 1 (visibility) as a low-risk, immediately shippable first step. This directly addresses the two concrete failure modes found in this week's debugging — silent type-cap truncation and resolution-funnel noise from wiring entities — without discarding the resolution machinery that record-like entities still need.

## 12. Technical Notes for Engineering Handoff

- XML→CSV extraction, entity classification, FK detection: [src/aryx/pipeline/doc_discovery.py](../src/aryx/pipeline/doc_discovery.py) — `_xml_to_csvs` (143-404), `_is_entity` (216-231), `_detect_fk_links` (504-603), `ingest_confirmed` (820+)
- Type-cap / row-cap settings: [src/aryx/config.py](../src/aryx/config.py) — `xml_max_entity_types`, `xml_max_rows_per_type`
- Retrieval-side symptom that motivated this (for context, not in scope here): [src/aryx/graph/retrieve.py](../src/aryx/graph/retrieve.py) `render_context`/`gather`
- Reference flow doc for the current XML + OCI pipeline end-to-end: [docs/api-flows/xml-oci-full-flow.html](api-flows/xml-oci-full-flow.html)

### Suggested implementation shape

- New Track B module should accept the same `(data: bytes, stem: str)` shape as `_xml_to_csvs` for drop-in compatibility with `_read_job()`'s existing file-routing call site.
- Cross-reference scanner should run once per document (not per type-pair) and produce a spec list shaped like `_detect_fk_links`'s existing `auto_fk` output, so `ingest_confirmed`'s existing `fk_links=auto_fk if is_last else None` wiring can consume both sources without a new integration point.

## 13. Final Summary

The right next step is not a full rewrite toward graph-native XML ingestion, nor is it a minor cap bump on the existing pipeline. It's a targeted split: keep the resolution pipeline for entities that need it, stop forcing structural/wiring entities through the same expensive and noisy path, and add real cross-reference detection instead of relying on column-naming conventions. This is scoped as an extension of `doc_discovery.py`, phased to ship the lowest-risk visibility work first and validate each subsequent phase against real CPQ-style data before expanding further.
