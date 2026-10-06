# CPQ function scripts missing after XML ingest: issue, why it was missed, and the fallback fix

> **DOC CONTRACT**
>
> - **Purpose**: one record of why the CPQ engine finds no BML function scripts in some workspaces, why it was not caught, and the engine-side fallback that repairs existing workspaces without a re-ingest.
> - **Status**: LIVING. Fix on branch `fix/cpq-function-script-via-contains-link-2026-10-06` (off `dev_oci` at `968e8454`). Not yet merged or deployed.
> - **Last updated**: 2026-10-06.
> - **Related**: the ingest-side root cause analysis "script_text not on BmFunction" (2026-10-06, fold fix commit `740d4c13`, not in this repo yet). This document covers the engine side; the two fixes are complementary.
> - **Formatting**: bullets only, no tables.

---

## 1. Summary

- **Issue**: in workspace 1126 (and, per the ingest RCA, 1147, 1150 and 1166) every `BmFunction` entity has no `script_text`. The CPQ engine therefore loads no function scripts, so no script-backed rule can run.
- **Where the scripts actually are**: as separate `...ScriptText` entities, each linked from its function by a `CONTAINS` relationship. Nothing is lost; the scripts are one link away from the function.
- **Why the engine fails**: `fetch_function_scripts` reads only the function entity's own `script_text` attribute and never follows relationships.
- **Fix in this branch**: when a function has no script of its own, read it from the `ScriptText` entity the function `CONTAINS`, using the full text in `aryx_entity`.
- **Effect**: existing workspaces work again immediately, with no re-ingest. Workspaces where the script is already on the function behave exactly as before.

---

## 2. The issue

### 2.1 What users and logs see
- An Ask quote turn in ws 1126 ("I want a quote for APX Next") anchors the product but then evaluates no real rules.
- The dev API log (`aryx-api-1`, 2026-10-06) shows, for every turn:
  - about 400 warnings of the form `cpq: rule '...' references function_id=N but no BmFunction script was found`
  - `build_bml_evaluator done ... scripts=0`
  - `loaded 0 recommendation rules, 0 constraint rules`, and `149 script-condition rules skipped`
  - `loaded 0 hiding rules (0 declarative, 0 script-backed ...)`
- Downstream, model resolution falls back to the fixed pair (`ask.model.fallback_static`, APXNEXT / APXNEXT_BOM).

### 2.2 Data evidence (ws 1126, queried 2026-10-06, schema `ARYX_APP`)
- `aryx_entity`, BmFunction type: **929** entities, **0** with `script_text`.
- `aryx_graph_vertex`, ScriptText type: **666** entities. Fewer than 929 because entity resolution merges functions with identical script bodies into one ScriptText entity.
- `aryx_graph_edge`: **929** `CONTAINS` links from the BmFunction type to the ScriptText type.
- `aryx_relationship` (the source the graph is projected from): **929** `CONTAINS` links to ScriptText entities. Same as the graph.
- Conclusion: every function has exactly one link to its script.

### 2.3 How the data gets into this shape
- The XML export nests the script inside the function: `<bm_function> ... <script_text>...</script_text> ... </bm_function>`.
- The raw-graph ingest projects each element to a node. A text-only element becomes a node with a single `text` property.
- A later step, the structural-leaf fold, copies such leaf text onto the parent (so `script_text` becomes an attribute of the function) and drops the leaf node.
- With `ARYX_CSV_BML_ENABLED=true` (as on dev), the CSV BML enrichment first adds `bml_tables`, `bml_queries` and `bml_query_tables` to every `script_text` node that contains SQL. The fold then no longer sees `script_text` as a plain leaf and skips the whole tag (ingest RCA, section 3).
- The unfolded `script_text` nodes are resolved into their own entity type (`...ScriptText`), and the XML parent/child edge is saved as a `CONTAINS` relationship (`containment_relate.translate_containment_edges`, saved by `EntityStore.save_relationships` into `aryx_relationship`, then projected into `aryx_graph_edge`).

### 2.4 Why the engine cannot see them
- `PostgresCpqRdb.fetch_function_scripts` (inherited by `OracleCpqRdb`) builds the `function id -> script` map from the BmFunction entities only:
  - `script = attrs.get("script_text") or attrs.get("script")`
- It does not read `aryx_relationship`, so a script on a linked entity is invisible.
- Every rule that references a function id then finds no script and is skipped. This feeds the hiding rules (`hiding_rules/type11.py`), value rules (`value_rules/value_rules_load.py`), the BML evaluator (`recommendation_and_constraint_rules/bml_evaluator.py`) and the NL hint extraction (`nl_hint_extraction/flag_hints.py`, `unresolvable_context.py`).

---

## 3. Why it was missed

- **The engine silently assumed one data shape.** "The script is on the function" was true on the older `dev-rv-msi` ingest (one CSV per entity type, `script_text` a column of `bm_function`). The raw-graph ingest on `dev_oci` replaced that, and the guarantee became a side effect of the fold step, never written down or tested at the engine boundary.
- **Local and dev environments differ.** `ARYX_CSV_BML_ENABLED` is off on developer machines, so `script_text` stays a plain leaf and folds. Every local check (including the earlier investigation of this issue) passed. Dev has the flag on.
- **No combined test.** Fold tests ran with the enrichment off; enrichment tests did not run the fold; engine tests mock `fetch_function_scripts` or feed BmFunction rows that already carry `script_text`. No test covered "ingest with enrichment on, then load scripts".
- **The failure is silent.** The ingest reports success and plausible row counts. The engine treats "no script" as "rule not applicable", logs a per-rule warning and continues. A quote turn still completes, just without rules. Nothing raises.
- **The post-fold audit validated the fold against itself.** The audit added in PR #441 reuses the fold's own leaf test, so a tag that fails the test is never reported as an unfolded leaf (ingest RCA, section 3.3).
- **The relationship was invisible from the ADMIN login.** App tables live in schema `ARYX_APP`; unqualified queries as `ADMIN` return `ORA-00942`, which made the link look absent until the schema was found.

---

## 4. Solution

### 4.1 Two complementary fixes
- **Ingest side (fold fix, commit `740d4c13`, separate branch)**: the fold ignores the BML list properties and carries them onto the parent, so new ingests put `script_text` back on the function. It does not repair data that is already stored.
- **Engine side (this branch, the fallback)**: the engine follows the existing `CONTAINS` link when a function has no script of its own. It repairs every already-ingested workspace immediately and keeps working whatever the ingest shape.
- Both should ship. The fallback removes the dependence on one ingest shape; the fold fix keeps new data in the expected shape.

### 4.2 How the fallback works
1. Read all BmFunction entities, as before (`fetch_entities_by_type(ws, "bmfunction", catalog_prefix)`).
2. Split them (`own_function_scripts`):
   - functions with their own `script_text` (or `script`): use it, unchanged behaviour;
   - functions with a BM id but no script: remember `entity_id -> BM function id`.
3. If no function is missing a script, return immediately. **No extra query** runs for healthy workspaces.
4. Otherwise run one query (`fetch_contained_entities`) that returns every `CONTAINS` link to a ScriptText entity in the workspace, with the target's full attributes:
   - `aryx_relationship r JOIN aryx_entity t ON t.id = r.target_entity_id`
   - filtered by workspace, `r.name = 'CONTAINS'`, and the ScriptText type (normalized suffix `scripttext`, restricted to the same `catalog_prefix` as the functions)
   - ordered by source then target id, so the pick is deterministic.
5. For each missing function (`add_linked_scripts`), take the first non-blank text from its linked rows, looking at `text` (the raw XML element text key), then `script_text`, then `script`.
6. Log one Raven record (`cpq.rdb.function_scripts_linked`, INFO) with counts only: functions, without own script, filled from link, still missing. No script text is logged.

### 4.3 Design decisions
- **Read from `aryx_entity`, never from the graph tables.** `aryx_graph_vertex` clips every string attribute to 200 characters (`_GRAPH_ATTR_STR_MAX`), which would hand the engine truncated scripts. The fallback reads the stored entity attributes, which hold the full text.
- **Own script always wins.** A function that already has `script_text` is never overridden by a link, so workspaces ingested after the fold fix are unaffected.
- **One query per call, no IN lists.** The link query filters by type, not by a list of function ids. This avoids Oracle bind-list limits on workspaces with thousands of functions; links from non-function sources are discarded in Python.
- **Same catalog scoping as functions.** BM function ids are unique only within one XML export, so the ScriptText type is matched with the same `catalog_prefix` as the functions.
- **Shared ScriptText entities are fine.** Two functions with identical scripts point at the same entity; each gets the same text.
- **Failure is non-fatal.** If the link query fails, it logs `ask.rdb.read_failed` and returns no rows; the result is the same as today (scripts missing), never worse.
- **Small, isolated code.** The selection logic is a new module (`cpq/rdb/rdb_function_scripts.py`, 91 lines) with pure functions; each dialect only adds the one SQL query.

### 4.4 Files changed
- `src/aryx/cpq/rdb/rdb_function_scripts.py` (new): `own_function_scripts`, `add_linked_scripts`, constants.
- `src/aryx/cpq/rdb/rdb_postgres.py`: `fetch_function_scripts` uses the fallback; new `fetch_contained_entities` (Postgres SQL).
- `src/aryx/cpq/rdb/rdb_oracle.py`: `fetch_contained_entities` (Oracle SQL, `:n` binds).
- `tests/test_cpq_function_scripts_contains_link_2026_10_06.py` (new, 11 tests).

### 4.5 Tests
- Own script wins, and the link query is not run at all.
- Missing script is read from the linked ScriptText (catalog prefix passed through).
- Two functions sharing one merged ScriptText entity both get the script.
- A function with no link stays missing, and the log counts say so.
- An own script is not overridden by a link.
- Blank linked text is skipped; the first non-blank linked row wins.
- Links whose source is not a function are ignored.
- The log record has counts and no script text (sentinel check).
- Postgres and Oracle `fetch_contained_entities`: correct tables, binds, parameters, and JSON-to-dict coercion.
- A failed link query returns an empty list.

---

## 5. Risks and limits

- **Large scripts**: the fallback returns whatever `aryx_entity` stored. Whether very large scripts (around 129 KB seen on the older line) store intact on Oracle is still unverified (ingest RCA risk R1).
- **Extra query cost**: only for workspaces with missing scripts; one join filtered by workspace, relationship name and type. Callers already invoke `fetch_function_scripts` several times per turn; if the cost shows up, cache per workspace and re-ingest marker.
- **Text key assumption**: an unfolded ScriptText entity is expected to keep the raw element text under `text`. The fallback also accepts `script_text` and `script`. Verify on ws 1126 after deploy (section 6).
- **Not a substitute for the fold fix**: other leaf tags that failed to fold for the same reason are not covered by this fallback.

---

## 6. How to verify after deploy

1. Run one quote turn in ws 1126 ("I want a quote for APX Next").
2. In the API log, expect `cpq.rdb.function_scripts_linked` with `filled_from_link` near 929 and `still_missing` near 0.
3. Expect the `no BmFunction script was found` warnings to disappear, `build_bml_evaluator ... scripts=` to be non-zero, and non-zero recommendation or constraint rules.
4. Optional DB check of the text key (run as ADMIN):
   - `SELECT JSON_QUERY(attributes, '$' RETURNING VARCHAR2(4000) TRUNCATE) FROM ARYX_APP.aryx_entity WHERE workspace_id = 1126 AND LOWER(ontology_type) LIKE '%scripttext%' FETCH FIRST 1 ROWS ONLY;`
   - expect a `text` key holding the script.

---

## 7. Audit line

`[2026-10-06] FIX | aryx-oci | cpq/rdb | Root: fetch_function_scripts read only BmFunction.script_text; unfolded scripts sit on CONTAINS-linked ScriptText entities (ws 1126: 929 functions, 0 own scripts, 929 links) | Fix: fallback reads the linked ScriptText from aryx_entity when a function has no script of its own`
