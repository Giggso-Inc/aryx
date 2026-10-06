# script_text not on BmFunction: issue, RCA, risks and fixes, 2026-10-06

> **DOC CONTRACT**
>
> - **Purpose**: one complete record of the "function script text missing after XML ingest" issue: what was seen, the root cause, why it was missed, the fixes, the risks that remain, and how to prove it is fixed.
> - **Status**: LIVING. Fix branch committed locally (`740d4c13`), **not pushed, no PR yet**. Nothing is deployed for the fix itself.
> - **Last updated**: 2026-10-06.
> - **Basis**: ingest logs from the dev container `aryx-api-1`, DB counts pasted by the team for workspaces 1126, 1147, 1150 and 1166, and the code on `origin/dev_oci`. No production data was touched. Where something was not verified it says "not verified".
> - **Formatting**: bullets only.

---

## 1. Summary (read this first)

- **Issue**: after an XML ingest on dev, `BmFunction` rows have no `script_text`. The script text lands as a separate `...ScriptText` entity type instead.
- **Impact**: the CPQ engine reads function scripts only from `BmFunction.attributes.script_text`. With it empty, rules, recommendations, region lookups and data-table scripts cannot be evaluated, and Ask cannot resolve the region.
- **Root cause**: `ARYX_CSV_BML_ENABLED=true` on dev. With it on, the CSV BML enrichment adds three list properties to every `script_text` node that holds SQL. The structural-leaf fold only folds a tag when every node of it has no properties other than `text`, so the whole `script_text` tag stopped folding.
- **Why it was not seen locally**: the flag is off on developer machines, so `script_text` stayed a plain leaf and folded.
- **Fix**: let the fold ignore the BML lists, carry them onto the parent function with the text, and make CSV BML describe a function that carries its own script. Branch `fix/cpq-fold-script-text-with-bml-props-2026-10-06`, commit `740d4c13`.
- **Env change needed**: none.

---

## 2. What was observed

### 2.1 Symptoms
- Workspaces 1126, 1147, 1150 and 1166 (all Astro or SVX XML ingests) show functions without script text.
- Workspace 1166 (the small `Video Solutions-SVX.xml`, 6,441,003 bytes, 199 functions):
  - DB count: `FUNCTIONS 199 | WITH_SCRIPT 0`.
  - 32 entity types, which are the 31 types the code normally produces plus `Video SolutionSvxScriptText` (169 rows). 169 rows from 199 records is the entity resolution merging duplicate script bodies.
- Data tables and layout files were also missing in 1126, 1147 and 1150. That is a separate upload gap (section 8), not part of this issue.

### 2.2 Log evidence (dev container, ingest of 2026-10-06 13:11 UTC)
- The folds ran. The log has about 190 lines of `structural leaf fold: tag=... folded N node(s) onto their parents`, and the closing line `raw_graph folds ... structural_leaf=True locale_wrapper=True`.
- Sibling tags in the same function block folded with 199 each: `java_class_name`, `child_class_names`, `script_size`.
- `script_text` is absent from the folded list, and the pipeline then ran it as its own tag: `raw graph nodes extracted tag=script_text records=199`, `199 records landed - 4 field profiles saved`, `Registering ontology type Video SolutionSvxScriptText`.
- **4 field profiles** for `script_text` is the key clue. A plain-text leaf has one field (`text`). The other three are the BML lists.
- No `ARYX_ING_LEAF_UNFOLDED` audit line was logged, because the audit uses the same leaf test as the fold (section 4.4).
- Container environment: `ARYX_CSV_BML_ENABLED=true` and `ARYX_WORKER_BACKEND=oci_functions`. The streaming and fold flags are not set, so defaults apply (fold on, streaming off).

### 2.3 Reproduction
- Real `resolve_and_relate_raw_graph` on `Video Solutions-SVX.xml` with the database mocked:
  - BML flag **off**: 31 types, no `ScriptText`. This is why every earlier local check looked fine.
  - BML flag **on**, before the fix: 32 types including `ScriptText`. This matches dev exactly.
  - BML flag **on**, after the fix: 31 types, no `ScriptText`.

---

## 3. Root cause (RCA)

### 3.1 Mechanism, step by step
1. `resolve_and_relate_raw_graph` projects the XML into raw nodes (`xml_projector.py`). A text-only element becomes a node with a single `text` property.
2. Before folding, `resolve_relate.py` calls `with_query_tables()`, which calls `enrich_projection()` (`csv_bml_ingestion/bml_graph.py`) when `ARYX_CSV_BML_ENABLED` is on.
3. `enrich_projection` gives every node whose text holds SQL three list properties: `bml_tables`, `bml_queries`, `bml_query_tables`. In these exports that is the `script_text` nodes that contain queries.
4. `fold_structural_leaf_tags` then classifies each tag with `is_structural_leaf_tag`: every node of the tag must have no property other than `text`, and no children. The test is per tag, not per node.
5. A single enriched `script_text` node therefore made all 199 non-leaf. The tag was left in the per-tag resolve path and became its own `ScriptText` entity type.
6. The `BmFunction` entities never received `script_text`. The engine (`fetch_function_scripts`) reads `attrs["script_text"]` from the function entity, so it found nothing.

### 3.2 Why locally it worked
- `ARYX_CSV_BML_ENABLED` is off locally, so step 3 never ran and the nodes stayed plain leaves.
- Every earlier check on this issue (the check script, the slice runs, the real-file runs) was done with the flag off, which hid the cause.

### 3.3 Why the audit did not catch it
- The post-fold audit added in PR #441 (`leaf_audit.py`) reuses `is_structural_leaf_tag`. A tag that fails the test is, by definition, not reported as an unfolded leaf. The audit validated the fold against itself.

### 3.4 Design tension behind it
- CSV BML intentionally works on the entities the resolve step builds. Its lookup (`stored_graph.py`) reads `aryx_graph_vertex` rows whose attributes contain `bml_tables`, and describes each match through the vertex's neighbours in `aryx_graph_edge`.
- So that feature wanted script text on its own entity, while the engine wants it on the function. Nobody had written down that the two must coexist.

---

## 4. How it was missed

### 4.1 Comparison with dev-rv-msi
- **dev-rv-msi** (the older line) ingested XML with `_xml_to_csvs` in `pipeline/doc_discovery.py`: one CSV per entity type, with `script_text` as a column of the `bm_function` rows. Scalar leaf elements were never separate entities. Verified: `origin/dev-rv-msi` has 0 files under `cpq_ingestion/raw_graph` and 0 under `csv_bml_ingestion`.
- **dev_oci** replaced that with the raw-graph ingest on 2026-09-30 (`c97d236b`). Folding scalar leaves back onto their parent became an explicit step, added later (2026-10-04, `74899ec7` and follow-ups).
- CSV BML enrichment landed in between (2026-10-02, `029a5feb`) and rewrites node properties before the folds.
- In dev-rv-msi "script on the function" was a side effect of the flattening, not a rule, so nobody wrote a test for it. The re-architecture lost the guarantee silently. The port analysis (`DEV_RV_MSI_PORT_ANALYSIS_2026-10-02.md`) lists CPQ fixes to port, but none covers "script text must reach BmFunction through the new ingest".

### 4.2 Contributing causes
- **No combined test**: fold tests ran with enrichment off, enrichment tests did not run the folds, and every fixture was a pure leaf.
- **Environment difference**: dev has the BML flag on, laptops do not. I (the investigating assistant) cannot read `.env`, so the flag was invisible until `docker exec ... env` was run.
- **Silent failure**: the ingest reported success, row counts looked plausible, and the damage only showed when the engine looked for scripts.
- **Wrong early suspects**: stale deploy, projector differences, text length and the streaming path were all examined first and ruled out. Time was lost there.
- **Self-referential audit**: see 3.3.

---

## 5. Fixes

### 5.1 Fix for the root cause (branch, not yet pushed)
- Branch `fix/cpq-fold-script-text-with-bml-props-2026-10-06`, commit `740d4c13`, off `origin/dev_oci`.
- `src/aryx/cpq_ingestion/raw_graph/structural_leaf.py`:
  - `is_structural_leaf_tag` ignores `bml_tables`, `bml_queries`, `bml_query_tables`. The key names are imported lazily from `csv_bml_ingestion.bml_graph`, nothing is hardcoded. A real XML attribute still blocks the fold.
  - The fold carries those lists onto the parent. It extends (never nests), de-duplicates `bml_tables`, and keeps `bml_queries` and `bml_query_tables` parallel.
- `src/aryx/csv_bml_ingestion/stored_graph.py`: when a match vertex carries its own script (folded onto a function), the match uses the vertex's own short values (name, id) as identity and reports the real script property name instead of `text`. A plain `ScriptText` vertex behaves as before.
- Tests:
  - New `tests/cpq_ingestion/test_fold_script_text_with_bml_props_2026_10_06.py` (6 tests): enrichment adds the properties; one enriched script among plain ones still folds; a real attribute still blocks; text and lists land on the function; two scripts under one function extend, not nest; no change without enrichment.
  - New lookup test in `tests/csv_bml_ingestion/test_stored_graph.py`: a folded function is found and described by its own name.
  - One existing assertion updated, which encoded the old shape (the clipped text key is now `script_text` on the function).
- Result: `tests/cpq_ingestion`, `tests/csv_bml_ingestion` and `tests/test_raven_log_ask_response_qa.py`: 541 passed, 3 skipped.

### 5.2 Guards already merged
- PR #441 (merged): post-fold leaf audit (`ARYX_ING_LEAF_UNFOLDED`), the workspace health check (`scripts/check_cpq_ingest_health.py`, `ingest_health.py`) and the offline check `scripts/check_cpq_xml_fold.py`.
- Limit: the audit shares the fold's predicate (3.3). The health check is the real outcome test (functions with script text), so it must be run after each XML ingest.

### 5.3 Proposed follow-ups (not implemented)
- Add a length check to `ingest_health`: stored `script_text` length against the `script_size` field the XML carries per function (allow a tolerance, since it may count bytes).
- Make the audit outcome-based (functions in the landed entities with and without script text) instead of predicate-based.
- Optional engine fallback: if a function has no `script_text`, read the linked `ScriptText` entity. Deferred, because the ingest fix makes it unnecessary for new ingests.
- Optional backfill for already-ingested workspaces. Deferred: re-ingest is simpler and safer.

### 5.4 Workaround without a code change
- Unset `ARYX_CSV_BML_ENABLED`, restart, and re-ingest. This loses the query-table links CSV BML builds, so it is only for when the team is blocked.

---

## 6. Environment and deployment

- **Env changes**: none. `ARYX_CSV_BML_ENABLED=true` stays on, `ARYX_WORKER_BACKEND=oci_functions` is unchanged, and the fold flags keep their defaults.
- **Deploy the code to every process that runs the ingest.** The API container did the 1166 ingest (the fold logs were in `aryx-api-1`). If any upload is sent to the OCI Function `aryx-ingest-fn`, its image bakes `src/` at build time and must be rebuilt and redeployed too.
- **Existing workspaces** (1126, 1147, 1150, 1166) keep the old shape until their XML is re-ingested.

---

## 7. Risks

- **R1, large scripts on Oracle (open, highest)**: every function entity now carries its full script. The port analysis records a `bm_function` with a 129 KB `script_text` that silently dropped the whole `BmFunction` type on the older line. Whether a 129 KB attribute stores correctly on the Oracle path is **not verified**. Mitigation: run the Astro25 ingest (large scripts) on a test workspace and use the length check in 5.3.
- **R2, graph clip (low)**: the graph store clips string attributes to 200 characters (`_GRAPH_ATTR_STR_MAX` in `oracle_graph_store_helpers.py`). The engine does not read the graph for scripts (`fetch_function_scripts` documents "read from the RDB, never the graph"), and the `bml_*` lists are not clipped. Anything that reads `BmFunction` text from the graph sees 200 characters. The Postgres accessor was verified. The Oracle accessor was **not read**.
- **R3, CSV BML identity**: matches on a function use the function's own name and id. This is tested against a fake graph database only, not against Oracle. Verify with one real CSV upload after deploy.
- **R4, entity size**: function entities are larger (full script plus up to 8 queries of up to 2,000 characters each). Expected to be acceptable.
- **R5, stale deployment**: if the OCI Function image is not rebuilt, uploads routed there keep the bug. Check the function image date.
- **R6, existing data**: workspaces ingested before the fix stay broken until re-ingested. The health check will report them as FAIL.
- **R7, regression of the fix**: the fold now depends on the BML key names. Renaming them in `bml_graph.py` updates both places automatically (the import), but a new enrichment property would block the fold again. The new tests cover the three current keys.

---

## 8. Related gaps found along the way (not this issue)

- Data-table CSVs (whitelist, attrSequence, defaultInAttr, newCountryRegMapping, seriesModelsMapping) are missing in 1126, 1147 and 1150. Without `newCountryRegMapping` rows the region stays unresolved.
- No Active layout file for the Astro and APX Next workspaces. The layout must have `status: "Active"` and be uploaded with the exact catalog prefix.
- 14-product config_data audit never reported results. APX NEXT config_data is not derived. APX 4500 and 6500 provisioning and Solution Type whitelist rows are missing.

---

## 9. How to verify (after deploy)

1. Re-ingest `Video Solutions-SVX.xml` into a fresh workspace.
2. Ingest log: `docker logs aryx-api-1 --since 30m | grep -E "ARYX_ING_LEAF_UNFOLDED|structural leaf fold: tag=script_text"`. Expect a `tag=script_text folded 199` line and no audit warning.
3. Types: no `...ScriptText` type for the new workspace (31 types).
4. Count: functions with script text equals the function count (199 of 199).
5. Health: `python scripts/check_cpq_ingest_health.py --workspace-id <ws> --catalog-prefix <prefix>`. The function check passes.
6. Upload one CSV that a script queries (for example `attrSequence.csv`) and confirm CSV BML still finds the script and labels it with the function's name.
7. Ingest the Astro25 file on a test workspace and re-run steps 3 to 5 to cover large scripts (R1).
8. Then re-ingest 1126, 1147, 1150 and 1166 as needed.

---

## 10. Timeline

- 2026-09-30: raw-graph ingest added on dev_oci (`c97d236b`).
- 2026-10-02: CSV BML enrichment added (`029a5feb`).
- 2026-10-04: structural-leaf fold added (`74899ec7` and follow-ups).
- 2026-10-06: PR #441 merged and deployed (audit, health check). Dev re-ingest of the SVX file showed `script_text` still unfolded.
- 2026-10-06: `ARYX_CSV_BML_ENABLED=true` found on dev, root cause confirmed, fix committed locally (`740d4c13`).

---

## 11. Audit line

`[2026-10-06] RCA | aryx-oci | cpq_ingestion | Root: ARYX_CSV_BML_ENABLED enrichment adds bml_* lists to script_text so the per-tag leaf fold skips it; audit shares the predicate; no combined test | Fix: fold ignores BML keys, carries them to the parent, CSV BML identity fallback (740d4c13, unpushed) | Open: R1 large scripts on Oracle`

---

## 12. Evidence from workspace 1188 (SVX file, ingested after PR #445 was deployed)

- **Ingest shape unchanged**: 199 functions, 0 with their own `script_text`, 169 `...ScriptText` entities, 199 `CONTAINS` links. Log: `raw_graph folds ... structural_leaf=True`, no `tag=script_text` fold line, `Registering ontology type Video SolutionSvxScriptText`.
- **PR #445 fallback result** (engine log `cpq.rdb.function_scripts_linked`): `filled_from_link 162, still_missing 37, mixed_entities 12, skipped_links 37, verified 1`. So **37 of 199 functions get no script** through the read-side fallback.
- **Cause of the 37**: resolution merges `ScriptText` records that are not the same text. 16 entities are linked to more than one function (46 links). In 11 of them every member has a different length (the largest merged 7 different scripts into one entity, the next 5). The fallback correctly refuses those links, so the original per-function text is only in the landed records, not in the entity.
- **Consequence**: the read-side fallback cannot recover those scripts. Keeping each script on its own function at ingest (this fix) can: the `ScriptText` entities are never created, so nothing is merged.
- **Query lists survive**: CSV BML found scripts through the curated graph on this shape (`newCountryRegion.csv` loaded into `ws1188_newcountryregion`), which this fix has to preserve (the lists are carried onto the function; covered by a lookup test).
- **Data tables** land in `ws1188_*` workspace tables, not `aryx_entity`: `attrsequence` 47,332, `defaultinattr` 6,187, `whitelist` 49,986, `newcountryregion` 253, `cpqmodelhierarchy` 2. `BaseModelToConfig`, `UserGroupMapping` and `rtteTAReference` were skipped (`CBI_BML_NOT_FOUND`: no ingested script reads them). Model resolution then fell back to the static `APXNEXT` pair (`ARYX_ASK_MODEL_FALLBACK_STATIC`). Hypothesis, not verified: the scripts that read those tables are in an XML (for example the APX util library) not yet ingested into 1188.
- **Correction to section 8**: data-table CSVs are not stored in `aryx_entity`, so an `aryx_entity` type count cannot show whether they were ingested. Check `ws<id>_*` tables instead.
