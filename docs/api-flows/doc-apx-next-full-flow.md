# APX Next — Full XML Flow Walkthrough (Postgres backend, no OCI)

A single, concrete, real-numbers trace of **one specific file**
(`APX_Next_config.xml`, 23.8 MB, a real BigMachines/Oracle CPQ product
export) through all three stages: **discover-read → discover-confirm →
ask (CPQ conversation)**. Every count below was verified directly against
this file and against the live `workspace_id=14` database — nothing here
is hypothetical or generic.

This document assumes:
- **Backend:** Postgres (`ARYX_OCI_MODE` off / unset — the normal path)
- **Deployed settings** (this repo's `.env`, verified): `ARYX_XML_MAX_ENTITY_TYPES=50`,
  `ARYX_XML_MAX_ROWS_PER_TYPE=1200000` — **not** the code's own defaults
  (20 / 500). This matters a great deal (§1.3).

For the generic, any-file version of stages 1–2, see `doc-discover-read.md`
/ `doc-discover-confirm.md`. For the generic ask-flow mechanics, see
`doc-cpq-ask-flow.md`. This document is the concrete instance of all three,
for this one real file.

---

## Ground truth — what's actually inside this file

Parsed directly (not estimated): **31 distinct entity element types, 46,500
total entity rows.**

| Rank | Entity type | Row count | What it is |
|---|---|---|---|
| 1 | `bm_config_layout_attr_prop` | 32,268 | Per-field UI formatting properties (alignment, width, label position) |
| 2 | `bm_menu_item` | 3,423 | Dropdown/radio option values for attributes |
| 3 | `bm_config_rule_input` | 1,694 | Rule condition clauses ("if attribute X = value Y") |
| 4 | `bm_layout_model` | 1,154 | Layout tree nodes (tabs/sections/rows/fields) |
| 5 | `bm_entity_image` | 1,148 | Product images |
| 6 | `bm_config_rule_action` | 1,007 | Rule outcomes (hide/recommend/constrain a field) |
| 7 | `bm_config_layout_attr_assoc` | 1,001 | Which field sits at which layout-tree position, for which flow |
| 8 | `bm_config_rule_input_action` | 955 | Combined input+action linkage rows |
| 9 | `bm_function` | 923 | BML (BigMachines script language) function bodies |
| 10 | `bm_config_rule` | 688 | The rules themselves (hiding/recommendation/constraint/flow) |
| 11 | `bm_layout_model_props` | 557 | Layout node formatting properties |
| 12 | `bm_lib_func_assoc` | 551 | Function-to-library linkage |
| 13 | `bm_config_marked_attr` | 457 | Real target linkage for many declarative hiding rules |
| 14 | `bm_config_attr` | **427** | **The actual configurable fields — the whole point of this file** |
| 15 | `bm_config_rule_assoc` | 104 | Rule-chains-to-child-rule linkage |
| 16–20 | `bm_config_attr_set`, `_set_assoc`, `bm_shared_file`, `bm_config_att_override`, `bm_config_page_template` | 37 / 31 / 17 / 14 / 12 | Minor structural/asset types |
| 21–31 | `bm_layout`, `bm_config_rule_layout_assoc`, `bm_config_layout_properties`, **`bm_catalog`(3)**, `bm_config_flow_properties`, `bm_config_sspl_props`, `bm_config_layout_perm`, **`bm_prd_family`(1)**, `bm_config_pick_map_assoc`, `bm_config_integration`, `bm_config_layout_access` | 6/6/6/3/3/2/2/1/1/1/1 | Rare, one-off structural types |

Of the 427 real `bm_config_attr` fields, **688 real `bm_config_rule`
entities govern them, backed by 292 script-conditioned rules** (out of 923
total functions defined) and **1,694 declarative condition clauses**.

---

## PHASE 1 — `POST /admin/docs/read`

```
CLIENT
  │  POST /admin/docs/read
  │  multipart/form-data: files[]=APX_Next_config.xml (23.8 MB), workspace_id=1
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ HTTP HANDLER (doc_discover_api.py)                                    ║
║ 1. Read file bytes, check the 50 MB per-file limit — 23.8 MB passes   ║
║ 2. discovery_id = uuid4().hex                                         ║
║ 3. JobStore.create(discovery_id, "discovery", "APX_Next_config.xml",  ║
║    workspace_id) → INSERT aryx_jobs (status=queued)                   ║
║ 4. Schedule _read_job() as a BackgroundTask                           ║
║ 5. Return {"discovery_id": "<hex>"} — client gets this IMMEDIATELY,   ║
║    long before parsing/extraction actually finishes                  ║
╚══════════════════════════════════════════════════════════════════════╝
  │  (background thread now does the real work)
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ _read_job() — background thread                                      ║
║ File extension is .xml → goes to the DOC_EXTS path, not the tabular   ║
║ (.xlsx/.csv) path — that path is irrelevant for this file             ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ §1.1 — XML → CSV extraction (_xml_to_csvs)                           ║
║                                                                      ║
║ 1. Parse the XML tree                                                 ║
║ 2. Recursively walk it: an element counts as a real "entity" only if ║
║    it has 2+ DISTINCT non-container child tags, or (if childless)    ║
║    at least one attribute of its own — this is what tells apart a    ║
║    real record (bm_config_attr, many different sub-fields) from a    ║
║    pure list-wrapper container (many children, but all the SAME tag) ║
║ 3. Bucket every matching element by its tag name, count occurrences  ║
║ 4. Apply the two caps — THIS IS WHERE IT GETS INTERESTING FOR THIS    ║
║    FILE SPECIFICALLY:                                                ║
║      - ARYX_XML_MAX_ENTITY_TYPES: code DEFAULT is 20, but this        ║
║        deployment's .env overrides it to 50 → ALL 31 real types in   ║
║        this file survive (with the code default of 20, the bottom    ║
║        11 types — bm_layout, bm_catalog, bm_prd_family, and 8 more —  ║
║        would have been silently DROPPED entirely)                    ║
║      - ARYX_XML_MAX_ROWS_PER_TYPE: code DEFAULT is 500, but this      ║
║        deployment overrides it to 1,200,000 → every type keeps ALL   ║
║        its rows (with the code default of 500, 12 of the 14 CPQ-      ║
║        relevant types above — including rule_input, rule_action,     ║
║        layout_attr_assoc, layout_model, function, rule itself —      ║
║        would have been TRUNCATED to their first 500 rows only)        ║
║ 5. One CSV file produced per surviving entity type, e.g.              ║
║    APX_Next_config_bm_config_attr.csv (427 rows),                    ║
║    APX_Next_config_bm_config_rule.csv (688 rows), etc.                ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ §1.2 — Per-type extraction pipeline (runs once per surviving CSV)     ║
║ For each of the 31 CSVs: schema inference, FK-column detection        ║
║ (columns ending "_id" matched against other types' own id/guid        ║
║ columns), entity-mention extraction. All still in-memory/preview —    ║
║ nothing hits aryx_entity yet.                                         ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ JobStore.update_stage(..., "done", 100)                              ║
║ GET /admin/docs/summary/{discovery_id} now returns the full preview:  ║
║ 31 discovered types, their row counts, inferred FK relationships       ║
║ (e.g. bm_config_rule_input.bm_config_rule_id → bm_config_rule.id)     ║
╚══════════════════════════════════════════════════════════════════════╝
```

**Plain English — Phase 1 in one sentence:** Aryx reads the whole 23.8 MB
file, recognizes 31 distinct "kinds of things" inside it (fields, rules,
menu options, layout positions, etc.), and — specifically because this
deployment raised the normal 20-type/500-row safety caps — keeps every
single one of the 46,500 rows intact for the user to review, without
committing anything to the database yet.

---

## PHASE 2 — `POST /admin/docs/confirm`

The user (or an automated confirm step) approves all 31 discovered types.

```
CLIENT
  │  POST /admin/docs/confirm
  │  { discovery_id, approved_types: [all 31], workspace_id }
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ ingest_confirmed() → run_pipeline() → resolve_run()                   ║
║                                                                      ║
║ For EACH approved type, in order, an aryx_entity row is created per   ║
║ real record:                                                          ║
║   ontology_type = <SourceFilePrefix> + PascalCase(tag)                ║
║   e.g. "APX_Next_config" → prefix "ApxNextConfig"                    ║
║        bm_config_attr    → ontology_type "ApxNextConfigBmConfigAttr"  ║
║        bm_config_rule    → ontology_type "ApxNextConfigBmConfigRule"  ║
║                                                                      ║
║ This prefix is EXACTLY the "catalog_prefix" the CPQ engine later uses ║
║ to scope every rule/attribute query to just this one export — so a   ║
║ workspace holding a second product's XML (e.g. SL3500e) never lets    ║
║ one catalog's rules act on the other's attributes.                   ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ §2.1 — Entity resolution                                              ║
║ 427 bm_config_attr rows → 427 real aryx_entity rows (native BM `id`   ║
║ preserved in the JSONB attributes column, e.g. id=39427001 for the   ║
║ "commerceAttrs" field seen in the raw XML)                            ║
║ Exact-ID fast path (ARYX_ER_EXACT_ID_MATCH, default on): rows whose    ║
║ native id already matches an existing entity skip full resolution —   ║
║ not relevant on first ingest of a brand-new catalog, matters on        ║
║ re-ingest/updates                                                     ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ §2.2 — FK / relationship detection                                    ║
║ Two passes: (a) within THIS confirm batch, (b) against ontology       ║
║ types from EARLIER confirms in the same workspace (fixes single-file  ║
║ jobs where the target type was ingested separately)                   ║
║ Concretely for this file: bm_config_rule_input.bm_config_rule_id →    ║
║ bm_config_rule.id (1,694 edges), bm_config_layout_attr_assoc.attr_id  ║
║ → bm_config_attr.id (1,001 edges), bm_config_layout_attr_assoc.       ║
║ rule_id → bm_config_rule.id (1,001 edges), and so on for every real   ║
║ FK-shaped column across all 31 types                                  ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ §2.3 — Golden-record survivorship + isolated-node safety net          ║
║ Per-workspace merge policy (default "most_complete") reconciles any   ║
║ duplicate/overlapping records. _relate_isolated() runs unconditionally║
║ afterward — any entity with genuinely zero relationships gets a       ║
║ best-effort fallback edge so nothing is left as a true orphan node    ║
╚══════════════════════════════════════════════════════════════════════╝
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║ §2.4 — Graph projection (FalkorDB) + zero-loss validation             ║
║ project_graph()/project_incremental() mirrors the new aryx_entity     ║
║ rows into the graph. Post-ingest validation confirms row counts       ║
║ match between Postgres and the graph — this run: 46,500 in, 46,500    ║
║ projected, 0 lost                                                     ║
╚══════════════════════════════════════════════════════════════════════╝
```

**One real, verified consequence worth calling out explicitly:**
`bm_catalog` (3 rows) and `bm_prd_family` (1 row) are both real, tiny entity
types in this file — and both were confirmed earlier this session to carry
no usable `name` field. Product-family detection for "APX Next" therefore
does **not** depend on these two entity types at all; it resolves from the
`catalog_prefix` ("ApxNextConfig") derived from the source filename itself,
combined with the real product-option data inside `bm_config_attr`/
`bm_menu_item`. This is confirmed by the live system correctly resolving
`aPXNext_BOM` even though `bm_catalog`/`bm_prd_family` contribute nothing
functionally useful.

**Plain English — Phase 2 in one sentence:** every one of the 46,500
discovered rows becomes a real, permanent, queryable database record,
correctly linked to each other (which rule targets which field, which
field sits where on screen), scoped so this catalog's data can never
collide with a different product's data in the same workspace.

---

## PHASE 3 — `POST /ask` (CPQ conversation)

Full mechanics in `doc-cpq-ask-flow.md` — this section shows the SAME
flow with this file's real, specific values substituted in at every step.

```
CLIENT: "Quote APX Next Enhanced radios for a US customer."  workspace_id=14
  ▼
STEP 1 — Anchor gate
  • detect_product_mention() matches "APX Next" against the real ingested
    catalog_prefix "ApxNextConfig" → resolves immediately, no extra turn
  • Country: "for a US customer" → hint extraction resolves "United States"
    immediately too — BOTH anchors satisfied in this ONE message (real
    live test confirmed this exact scenario resolves in a single turn)
  ▼
STEP 2 — Load configuration
  • load_product_config() → all 427 ApxNextConfigBmConfigAttr entities,
    resolved product_name = "aPXNext_BOM"
  • catalog_prefix = "ApxNextConfig" — every rule query below scoped to it
  • load_hiding_rules() / load_recommendation_and_constraint_rules() →
    drawn from the 688 real ApxNextConfigBmConfigRule entities
  • build_bml_evaluator() loads all 923 ApxNextConfigBmFunction script
    bodies, ready to evaluate any of the 292 script-conditioned rules
  ▼
STEP 3 — Rule-evaluation loop (hide → fill → recommend → constrain)
  • Runs against all 427 attrs, using the real 1,694 rule_input condition
    clauses and 1,007 rule_action outcomes
  • "Hardware Version = Enhanced" + "Country = US" together satisfy enough
    real rule conditions that, per the live test, EVERY remaining field
    resolves automatically — Region→NA, Frequency Bands→700/800 MHz,
    Housing→Black, Battery Type→Standard, Solution Type→RadioCentral +
    CPS Programming, and ~45 more real decisions, all from actual
    recommendation/constraint rules firing, not guesses
  • productSelectionProduct_all is explicitly decision-required (a fix
    for this exact catalog — it's a shared, catalog-wide 325-option list
    with no rule reliably narrowing it) — resolves to "APX NEXT ENHANCED"
    because the customer's own words named it, not from blind first-pick
  ▼
pending is EMPTY after just this one message
  ▼
STEP 6 — FORMAT B (completion)
  status → "awaiting_approval"
  Plain-English summary of ~50 real decisions shown; JSON only on request
  ▼
CLIENT: "confirm"
  ▼
STEP 8 — Approval
  status → "approved", build_payload() emits the real BOM JSON —
  variable_name → item_value for every one of the resolved fields,
  noise/system fields (company-level currency/language/number-format,
  _BM_-prefixed, CRM_-prefixed) excluded from the payload
```

**Plain English — Phase 3 in one sentence:** by the time a customer's
opening sentence gives just two real facts (product + country), the
688 real rules and 1,694 real conditions already ingested from this exact
file are enough to resolve an entire APX Next radio order automatically —
the conversation only needs to ask more questions when a real,
unresolvable decision genuinely remains.

---

## End-to-end summary table

| Phase | Endpoint | Input | Output | Real count for this file |
|---|---|---|---|---|
| 1 | `POST /admin/docs/read` | 23.8 MB XML | 31 discovered types, preview only | 46,500 rows recognized, 0 written to DB |
| 2 | `POST /admin/docs/confirm` | 31 approved types | Permanent `aryx_entity` rows + graph projection | 46,500 rows committed, 0 lost |
| 3 | `POST /ask` (×N turns) | Natural-language quote request | Configured BOM payload | 427 configurable fields, 688 rules, resolves a full quote in as few as 2 turns |
