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
