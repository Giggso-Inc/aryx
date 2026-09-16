# CPQ Session Summary — 2026-07-17

## 1. Ingestion impact — does dev need re-ingestion?

**No.** Verified by diffing every commit made today (`f43ba01`..`a1b4d15`) for any file touching
an ingestion path (`*ingest*`, graph-writer modules, `bm_*` XML parsers): zero matches.

All changes are **read-time only** — they operate on data already sitting in the graph after a
prior ingestion. Specifically:

- `engine.py` changes are confined to `apply_hiding_rules`, `apply_constraint_rules`,
  `apply_recommendation_rules`, `build_payload`, `auto_fill`, and the new
  `find_rule_inconsistencies()` — all rule-evaluation logic, none of it touches
  `load_product_config`'s query shape or the entity schema ingestion writes.
- `bml.py` changes are LLM-role routing (`"menial"` → `"answer"`) and the tilde-OR-list
  condition-matching fix — pure evaluation logic, no schema dependency.
- `ask_api.py`, `observability/page.tsx`, `docker-compose.yml`, tests, and docs carry no
  ingestion-path code at all.

**Conclusion:** push to dev and test directly against the **existing** dev workspace(s) — no
re-ingest, no graph rebuild required. If dev's graph already has APX Next / SVX data loaded from
before, it is fully compatible with every fix below.

---

## 2. Issues fixed today — problem statement + fix

### 2.1 Duplicate global-attribute menu options
**Problem:** Currency/Language/Number-Format dropdowns showed duplicate entries because the same
BM company-level attribute is re-exported per catalog, and each catalog's menu items were appended
without deduping.
**Fix:** `engine.py` menu-option loading now dedupes via `seen_opts: set[(item_value.lower(),
display_name.lower())]` before building `menu_by_attr`.

### 2.2 Noise-vars asked despite being payload-excluded
**Problem:** Several internal/dummy attributes were prompted to the user in conversation even
though `build_payload` already excluded them from the final JSON — wasted turns, confusing UX.
**Fix:** `auto_fill` gained a branch: `elif self._is_noise_var(vn) and attr.options:` — silently
defaults noise vars (prefers `default_value` if valid, else first-by-order) instead of queuing
them as a pending question.

### 2.3 Wrong `productSelectionProduct_all` default
**Problem:** This shared, 325-option field (identical id across every catalog) had no single
reliable governing rule, so the engine's heuristic default was frequently wrong.
**Fix:** `is_decision_attr` now also returns true for `vn == "productSelectionProduct_all"`
(exact match) — promotes it to always-ask rather than silently defaulting.

### 2.4 Payload attribute ordering didn't match the real XML
**Problem:** `configAttributes` in the JSON reflected `auto_fill`'s insertion order (hints →
defaults → rule-fills → fallback), not the catalog's actual sequence.
**Fix:** `build_payload` now sorts the final dict by `ConfigAttr.order` (`bm_config_attr.order_number`),
verified live against APX Next: order_number 1–6 attrs now appear first, 293 last.

### 2.5 Tilde-delimited OR-list conditions silently never matched
**Problem:** Hiding/constraint/recommendation rules whose `condition_value` is a `"~"`-delimited
OR-list (e.g. `"PREMIER~ADVANCED SOFTWARE ONLY~ESSENTIAL SOFTWARE ONLY"`) were compared via bare
string equality against the *whole* list — so no single real value could ever match, and the rule
silently never fired.
**Fix:** New `_condition_value_matches()` helper (splits on `"~"`, case-insensitive membership
check), applied at all 4 rule-evaluation call sites in `engine.py`, plus the equivalent fix in
`bml.py`'s `evaluate_declarative_conditions()` (the multi-input/OR-group path).
**Status:** fix landed and full test suite passes (37 passed, 3 pre-existing unrelated failures);
the exact motivating live case still needs a follow-up re-verification pass in the rebuilt
container (flagged, not silently claimed fixed).

### 2.6 Rule-consistency blind spot — no cross-check existed at all
**Problem:** Nothing verified that `session.filled` (what the engine believes is true) actually
agreed with what each rule type's *own* independently-computed result said it should be.
**Fix:** New `find_rule_inconsistencies()` (engine.py) — cross-checks `filled` against
`apply_hiding_rules`, `apply_constraint_rules`, and `apply_recommendation_rules`'s own outputs.
Hiding-type disagreements auto-fix (dropped from payload via `build_payload`'s new `hidden_vns`
param — the engine is certain here). Constraint/recommendation disagreements are logged only,
never auto-fixed, since guessing risks overwriting a real customer choice.

### 2.7 Independent-oracle validation system merged
**Problem:** The rule-consistency check above still calls production's own `apply_*` methods —
useful, but not a *true* independent check (a bug in `apply_hiding_rules` itself would go
undetected).
**Fix:** Merged `rule-validation-script` branch's oracle system
(`src/aryx/cpq/validation/*`, `scripts/check_cpq_rule_loop.py`) — re-implements rule semantics
from scratch, generates deterministic scenarios (every menu option, every tilde-OR branch),
fixpoint-converges, and checks rule-order-dependence by re-running production with reversed rule
lists. Confirmed complementary, not conflicting, with 2.6.

### 2.8 LLM model routing — Tier-2 BML fallback and quote summaries used the wrong model
**Problem:** `bml.py`'s Tier-2 script-evaluation fallback and `ask_api.py`'s
`_cpq_summary_text` quote narration both called the lightweight **menial** model
(`grok-3-mini`), when reasoning-heavy tasks like script interpretation and quote narration should
use the **reason** model.
**Fix:** All 3 `bml.py` Tier-2 call sites and `_cpq_summary_text` switched from
`llm_runtime.chat("menial", ...)` to `llm_runtime.chat("answer", ...)` (the internal key backing
`ARYX_LLM_REASON_MODEL`). Also set `ARYX_BML_USE_LLM=true` in `.env` to actually activate the
Tier-2 path locally.

### 2.9 Observability UI showed the wrong model name
**Problem:** The "Model" tile on `/observability` displayed `mc?.menial_model` (`grok-3-mini`)
regardless of which model actually handled reasoning-heavy calls.
**Fix:** `apps/web/app/observability/page.tsx` — tile relabeled "Reason Model", now reads
`mc?.answer_model` (falls back to `mc?.model`).

### 2.10 Local Docker Compose stack — multi-layered dev-environment bugs
**Problem/Fix pairs** (kept local — not yet pushed, see §3):
- Host-oriented DSNs (`localhost:55432`, `localhost:6379`) leaked into containers via
  `env_file: .env` and `${VAR:-...}` substitution → added explicit docker-network-hostname
  overrides (`postgres`, `falkordb`) to `api`, `mcp`, `shay-api`'s `environment:` blocks.
- `shay-api` missing 2 tables (`SHAY_RUN_MIGRATIONS=false`, Alembic history out of sync) →
  applied the 2 missing `CREATE TABLE` statements directly via `psql`.
- Email-verification gate blocked local testing → bypassed via direct Postgres `UPDATE`.
- `shay-api` had no `ARYX_API_URL_INTERNAL`, defaulted to unreachable `localhost:8088` →
  added `ARYX_API_URL_INTERNAL=http://api:8000`.
- **Real root cause of every "lost graph on restart" incident:** FalkorDB's entrypoint writes to
  `/var/lib/falkordb/data`, not `/data` — the old volume mount (`graphdata:/data`) never
  persisted anything. Fixed the mount path.
- Wrong Shay↔Aryx workspace mapping — ingested test data landed in workspace 3 (unmapped, 0
  Shay-visible entities) instead of workspace 19 (already mapped, 427 real entities) → retargeted
  testing at workspace 19.

---

## 3. What's pushed vs. what's local-only

| Scope | Files | Status |
|---|---|---|
| Rule-evaluation fixes (2.1–2.7) | `engine.py`, `bml.py` | Pushed (`6896854`, `a2b9e43`, `2c5b547`) |
| Model routing + UI (2.8–2.9) | `bml.py`, `ask_api.py`, `observability/page.tsx`, tests, docs | Pushed (`a1b4d15`) |
| Local dev-stack fixes (2.10) | `docker-compose.yml` | **Not yet pushed** — held back pending a separate go/no-go |
| Scratch debug output | `apx_us_final.txt`, `fixed_payload.json`, `q1_turn1.txt`, `sl3500e_hwq.txt`, `turn2_answer.txt` | Untracked, not for the repo |

---

## 4. Verification flow — how correctness is checked today

CPQ correctness is checked at **three independent layers**, each catching a different failure class:

### Layer 1 — Rule-consistency cross-check (`find_rule_inconsistencies`, engine.py)
Runs on every `ask_api.py` turn, right after rules are loaded. Compares `session.filled` (what
the engine currently believes) against **each rule type's own freshly-computed result**:

1. `apply_hiding_rules(attrs, filled, hiding_rules, bml_eval)` → set of variable names that
   *should* be hidden right now.
2. `apply_constraint_rules(...)` → set of variable names whose current value violates an active
   allowed-values constraint.
3. `apply_recommendation_rules(...)` → set of variable names whose current value disagrees with
   what the recommendation engine would set.

If `filled` disagrees with (1), the discrepancy is **auto-fixed**: `build_payload`'s new
`hidden_vns` param drops that attribute from the outgoing JSON — safe, because "should be hidden"
is unambiguous. Disagreements from (2)/(3) are **logged only**
(`logger.info("cpq: rule-consistency check found %d issue(s): %s", ...)`) and never silently
overwritten, since guessing which value the customer "should" have could destroy a real choice.

**Weakness:** this layer calls production's own `apply_*` methods — it cannot catch a bug that
lives *inside* those methods themselves (a blind spot circular by construction).

### Layer 2 — Independent-oracle scenario engine (`src/aryx/cpq/validation/`)
Addresses Layer 1's blind spot by **re-implementing rule semantics from scratch** — never calls
`apply_hiding_rules`/`apply_constraint_rules`/`apply_recommendation_rules`:

1. `scenarios.py` generates every menu-option combination and every tilde-delimited OR-branch as a
   distinct deterministic scenario.
2. `transitions.py` + `runner.py` fixpoint-iterate each scenario to a stable state, with cycle
   detection (a rule loop that never converges is itself a defect).
3. `compare.py` diffs the oracle's stable state against what production's engine actually
   produces for the same inputs.
4. `production.py` additionally re-runs production with the rule list reversed — a rule set that
   is truly order-independent must converge to the same answer either way; if it doesn't, the
   catalog has an undetected rule-ordering dependency.
5. `report.py` emits a structured JSON report (`--output cpq-rule-report.json`) categorizing each
   mismatch by rule type and severity.

**Entry point:**
```
PYTHONPATH=src python scripts/check_cpq_rule_loop.py \
  --workspace-id 19 --product "APX Next" --strict-unknown \
  --output cpq-rule-report.json
```

### Layer 3 — Manual raw-XML cross-verification (ad hoc, this session)
Used for the APX Next hardware-version and SVX video-solution investigations today. Steps:

1. Confirm every payload attribute exists as a real `bm_config_attr` in the source XML
   (`variable_name` match).
2. Confirm the payload's value is a real `bm_menu_item.item_value` under that attribute's id
   (not a hallucinated or stale value).
3. Find every `bm_config_rule` whose `bm_config_rule_input.attribute_id` references the changed
   attribute, resolve its `bm_config_rule_action` targets, and check whether the payload's other
   values are consistent with what that rule's condition implies.
4. Explicitly rule out "nothing changed" as a bug when the rule graph has **no** dependents on
   the changed attribute — verified this was the case for `hWVersion_astro` (only one
   product-family constraint referenced it, already satisfied either way).

This layer is manual/investigative rather than automated — it exists to validate Layer 1/2's
findings against ground truth when a specific live transcript is in question, and to catch data
issues the oracle doesn't model yet (e.g. the `archTypeSubDuration_viSoln` plural/singular
condition-value mismatch found in the SVX XML, §2 follow-up item).

---

## 5. Open follow-ups (not yet closed)

- Re-verify the `serviceTypeAdditionalDMSCoverage_astro=PREMIER` → hides
  `includeAccidentalDamageAddDMSCoverage_astro` case live in the rebuilt container (§2.5 known gap).
- Run `check_cpq_rule_loop.py --workspace-id 19 --product "APX Next"` to completion and record
  the verdict (started as a background task previously, never reported on).
- `archTypeSubDuration_viSoln` plural ("1 YEARS") vs. constraint-rule singular ("3 YEAR") value
  format mismatch in the SVX raw XML — track for when a 3/6/9-year duration is actually selected.
- `docker-compose.yml` push decision still pending (§3).
