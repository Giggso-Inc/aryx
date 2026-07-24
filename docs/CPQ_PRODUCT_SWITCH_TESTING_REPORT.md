# CPQ Mid-Session Product-Switch Detection — Testing Report

Branch: `fix/cpq-implicit-product-switch-detection`

## 1. Original problem

In a workspace holding more than one ingested product catalog, a client
mid-conversation about Product A who then asks something about Product B
kept getting answers scoped to Product A — the session silently never
recognized the switch. Root cause: `detect_product_mention` only matched
when the OTHER product's exact name appeared verbatim in the message; any
partial, misspelled, or implicit reference was silently ignored, so the
`confirm_switch` safety gate (which already existed) never had a chance to
fire.

## 2. Design iterations and problems caught along the way

Three real design flaws were caught and corrected before landing on the
shipped approach — each one is a genuine bug this session found in its own
prior fix, not just the original report:

| # | Problem found | How it was caught | Fix |
|---|---|---|---|
| 1 | First attempt (LLM-based Tier 2) added an LLM call to **every** plain config answer ("black", "yes", "core bundle"), not just ambiguous ones — Tier 1 never matches a name-free answer, so Tier 2 fired every time. | Self-review, re-reading the diff after shipping | Added a 5-word gate — later found to be structurally unworkable (see #2) |
| 2 | The word-count gate lived in `ask_api.py`, before `Step 2` loads the actual `ConfigAttr` list — there was no per-attribute option data available yet to compare against, so the "smarter" gate was never reachable as designed. | Re-tracing the actual code path | Abandoned the LLM approach entirely |
| 3 | LLM classifier risked false-triggering a confirm prompt on ordinary questions ("does it support dual SIM too") because it had no visibility into conversation context — same input could plausibly classify either way. | User's own review of the design | **Replaced LLM entirely** with a deterministic fuzzy-substring match (`aryx.resolution.classical.string_score`, already used elsewhere for entity-resolution) — zero cost, zero non-determinism, empirically validated: true near-misses score 0.86–0.88, unrelated questions cap at 0.50 |
| 4 | `ultimateDestinationCountry` turned out to be a shared, tenant-wide global attribute — the *same native id* across every catalog checked. Comparing menu-option lists per catalog can't tell you anything about country availability. | Checking real Postgres data before designing the country-availability feature | Availability must come from rule evaluation, not attribute comparison |
| 5 | The actual constraint on product availability by country is **BML-script-based** (`"Constraint Product based on region and Customer Type"`), not a simple declarative country → allowed-list rule. 5 of 6 constraint rules targeting the product selector in APX Next are script-form; a hand-rolled declarative-only check silently reported "always available" for all of them. | Querying real constraint-rule data for the product-selector attribute | Reused `apply_constraint_rules`/`BmlEvaluator` (the same machinery already used for every other constraint in the engine) instead of reading rule conditions directly |
| 6 | Listing "which other countries ARE available" was in scope originally, but would require re-running the same script evaluation once per candidate country — up to ~249 evaluations for one failed check. | Cost/feasibility analysis before building it | Scope cut: just ask for a different country, no enumerated list |
| 7 | Preserving a valid country across a switch (new, correct behavior) broke 2 pre-existing tests that incidentally relied on the old "always reset country" behavior. | Full regression suite after implementation | Updated both tests to explicitly set `country=""`, restoring their real original intent (verify reset-and-reanchor from a clean slate) |

## 3. What shipped

1. **Fuzzy-match fallback** in `detect_product_mention` — deterministic
   `string_score` sliding-window match, threshold `0.82`, no LLM.
2. **Mid-band "did you mean...?" suggestions** — `suggest_product_candidates`,
   threshold band `0.65–0.82`, capped at 5 real candidates.
3. **Country re-validation on confirmed switch** — `check_country_availability`,
   reuses `apply_constraint_rules`/`BmlEvaluator`. New `switch_country`
   pending-anchor state asks for a different country instead of silently
   resetting or blocking. A country already validated for the new product
   is now **preserved**, not reset.

## 4. Live testing (real data, workspace 14 — 2 ingested catalogs)

Real ingested family names in this workspace: `aSTRO25_bom` (APX Next),
`videoSolutions_BOM` (SVX Video RSM) — internal BOM identifiers, not
customer-friendly names. Worth noting as a **separate, pre-existing**
characteristic of `_ingested_product_names` that limits how naturally any
detection (old or new) matches casual phrasing — not something this
session introduced or fixed.

| Test | Input | Result |
|---|---|---|
| Baseline single-query | "Quote APX Next Enhanced radios for a US customer." | Resolves fully in one turn — `aPXNext_BOM`, unaffected by this change |
| Mid-band suggestion | "quote me a videoSolution" | `cpq_switch_ambiguous()` → "did you mean **videoSolutions_BOM**?" |
| Confident fuzzy match | "what about video solutions instead" | `cpq_switch_candidate()` → yes/no confirm prompt |
| Confirmed switch, country available | "yes" | Real BML-script evaluation ran (~7.4s) against SVX's actual constraint rule → US confirmed available → country **preserved** → old config discarded, 43 new attrs auto-resolved for `videoSolutions_BOM` |
| Country-unavailable path | *(not exercised live)* | Only unit/mock-tested — constructing a real blocked-country case would require reverse-engineering the BML script's internal logic; the plumbing itself is proven correct via the "available" path and direct unit tests |

No errors in container logs from the feature itself; two unrelated `403`
errors appeared from an earlier mis-scoped test that accidentally routed
into the separate Q&A synthesis path (pre-existing auth issue there, out of
scope for this branch).

## 5. Automated test results

- `tests/test_cpq_product_switch.py`: **23/23 passed** (16 pre-existing +
  new coverage for fuzzy match, mid-band suggestions, country
  re-validation, and the switch_country loop).
- `tests/test_cpq_e2e.py`: 5 failed, 35 passed, 6 skipped — failures are
  the same pre-existing, unrelated set (`s1`, `s15` `ImportError`; `s38`,
  `s39`, `s42` anchor/logging gaps) present before this branch's work
  started. Zero new regressions.

## 6. Known, honest limitations

- No "available in these countries" hint list — confirmed impractical
  (§2.6). Client is asked for a different country with no suggestions.
- Country availability check only covers the product-selector attribute
  (`productSelectionProduct_all`) being constrained to zero options — a
  narrower, SKU-specific restriction that doesn't empty the whole selector
  won't be caught by this check.
- Detection quality is bounded by how closely a client's natural phrasing
  matches the real ingested family name, which — per §4 — can be an
  internal BOM identifier rather than a marketing name.

## 7. New issue found via live testing (post-ship) — cross-catalog menu-item bleed

While live-testing the switch flow above (step 4 of §4: switch to
`videoSolutions_BOM`, country `United States`), the resulting "Product —
choose one" list showed hundreds of models from *every* product family in
the workspace (APX, XiR, DGP, SLR, MTP, VZ, etc.), not just SVX-relevant
models — even though the correct catalog (`videoSolutions_BOM`) had already
been resolved.

**Root cause (confirmed against real Postgres data):** the attribute
`productSelectionProduct_all` (native id `39427019`) has its own
catalog-prefixed `BmMenuItem` entities in *each* catalog
(`ApxNextConfigBmMenuItem`: 325 rows; `"Svx Video Remote Speaker
Microphone"BmMenuItem`: 325 rows), all pointing at the same shared native
id. `reader.neighbors()` (`src/aryx/graph/reader.py`) has no catalog
scoping — it returns neighbors from both catalogs, and
`load_product_config`'s menu-item collection loop merges them without
filtering. This is the same root cause as the already-known, previously
deferred "Bug 1"/"Bug 3b" in
`docs/CPQ_MULTI_CATALOG_ASK_FLOW_BUGS_PLAN.md`, now confirmed live for a
third attribute.

**Fix plan (not yet applied):**

1. In `load_product_config`'s menu-item collection loop (`engine.py`), add
   one filter clause to the existing `menu_ids` list comprehension: keep a
   neighbor only if `_catalog_prefix(n.get("type") or "") ==
   resolved_catalog_prefix`. `resolved_catalog_prefix` is already computed
   earlier in the same function via the existing `_scope_to_catalog`
   pattern — nothing new to derive, and the same scoping convention already
   used by `_load_rule_join_data` / `fetch_rules` / `_scope_to_catalog`
   elsewhere in this engine. Reviewed and confirmed not to be hardcoding:
   both `resolved_catalog_prefix` and `_catalog_prefix()` are computed
   dynamically per call, not literal catalog/product names baked into
   code. (The adjacent, unchanged `"menuitem" in type.lower()` check is a
   BigMachines schema-level constant, verified stable across multiple
   independent catalogs this session — a different, stronger category than
   a tenant-specific variable name like `productSelectionProduct_all`.)
2. Add a regression test: two fake catalogs sharing a
   `productSelectionProduct_all`-style attribute and `BmMenuItem` neighbors
   with the same variable name but different catalog prefixes — assert only
   the resolved catalog's menu items are returned.
3. Live-verify against workspace 14: reload `videoSolutions_BOM` + `United
   States`, confirm the "Product — choose one" list only contains
   SVX-relevant models.
4. Run `test_cpq_product_switch.py` + `test_cpq_e2e.py` — confirm the same
   5 known pre-existing baseline failures, zero new regressions.
5. Commit/push/PR only once explicitly requested, on a new branch off
   `dev`.

**Status:** fix applied to `engine.py`. New regression coverage added in
`tests/test_cpq_engine_catalog_scope.py` (2/2 passed): one test asserts a
neighbor from a different catalog prefix sharing the same native id is
filtered out; a second asserts the common single-catalog case is
unaffected. Full regression run after the fix: `test_cpq_product_switch.py`
23/23 passed; `test_cpq_e2e.py` 5 failed / 35 passed / 6 skipped — the same
pre-existing, unrelated baseline failures (`s1`, `s15` `ImportError`; `s38`,
`s39`, `s42` anchor/logging gaps). Zero new regressions.

### 7.1 Live re-test — fix confirmed NOT sufficient; deeper root cause found

Replayed the exact reported sequence against workspace 14 with the fix
deployed: "quote me a videoSolution" → `videoSolutions_BOM` → `United
States`. The Product list still showed all ~380 models across every
family — unchanged from the original report.

Direct investigation of the live graph confirmed **this specific bug was
never a cross-catalog graph leak in the first place**:
`productSelectionProduct_all`'s 328 neighbors in workspace 14 were already
all correctly typed to the SVX catalog prefix (`Svx Video Remote Speaker
Microphone...`) — zero neighbors from any other catalog. The §7 fix is
still correct and kept (real, verified via its own regression test), but
it had nothing to filter in this case.

**Real root cause — a 3-step BML dependency chain that never resolves:**

1. The *only* rule that narrows `productSelectionProduct_all`'s options is
   a constraint script, "Restrict Product Selection Based on Package
   Choice String," which reads a computed variable `packageChoiceString`.
2. `packageChoiceString` is itself computed by a recommendation-rule
   script, "Set Package Choice String," which requires `packageNumber` to
   be non-empty (`if(not isnull(packageNumber) and packageNumber <> "")`).
3. `packageNumber` (order 3, required=False) has **zero menu-item options**
   anywhere in the ingested XML — its only graph neighbor is a
   `BmConfigZipCache` metadata entity, not a picklist. In real
   BigMachines this value almost certainly comes from an account/contract
   "Package" selection made outside this catalog's configuration export
   (pricing/package data) — Aryx never receives it.

Since `packageNumber` can never be filled from the data Aryx has, the
whole chain stays empty end to end, and `apply_constraint_rules` correctly
reports "no active constraint" — the engine isn't misbehaving; the input
needed to narrow this list simply doesn't exist in the ingested catalog.

**Conclusion:** this specific manifestation is **not fixable within the
current data model** — there's no hardcode-free way to narrow the list,
since the narrowing input doesn't exist anywhere in the ingested catalog.
Fabricating a value or an options list for `packageNumber` would itself be
the kind of hardcoding this project has consistently avoided. Documented
here as a known, root-caused limitation pending a decision on whether to
pursue modeling `packageNumber` as a new user-facing input (which would
first require sourcing what its legitimate values actually are — outside
this catalog's own export).
