# Base model defaults: N30 / N50 get their own defaults, not the first menu option

Date: 2026-10-08. Flag (off by default): `cpq_base_model_defaults_enabled` (`ARYX_CPQ_BASE_MODEL_DEFAULTS_ENABLED`).
Follow-up to #475 / #480 (those make the quote finish with the country only; this makes the rest of the values the right ones).

## 1. Problem

After "i want to quote APX N30 for US" dev shows "Configuration complete" with country, product and base model (`H15UCF9PW6AN`).
The other attributes were filled, but not with N30's defaults (ws 281, same flags as dev):

| Attribute | `Defaultinattr` for `H15UCF9PW6AN` (and the real CPQ screen) | engine |
|---|---|---|
| Antenna | WHIP | STANDARD |
| Keypad | LIMITED KEYPAD | NO KEYPAD |
| Belt clip | 2.0 INCH / 5.08 CM (STANDARD) | COVERT CARRY HOLSTER |
| Package | BULK | SINGLE |
| Data cable / user guide / DLM CD / system key | NO | YES |
| Hazardous location | N/A | ISA-12.12.01-2015 (UL) |
| Battery | BATT LIION IMPRES 2 IP68 2850T | STANDARD |
| Solution type / DMS service / DMS duration / billing | CPS-EXISTING RM / ESSENTIAL / 7 YEARS / IMMEDIATE | RADIO MANAGEMENT (MSI HOSTED) / PREMIER / 1 YEAR / UPFRONT |

Only 10-11 of the 24 default rows of the base model matched.

## 2. Cause (fill log, `antennasType_astro`)

Pass 0 fills the attribute before the base model exists: `tier4_options value_chosen`, source `rule` (the first or only option of
a rule-governed attribute). Passes 1+ find a value with a non-guess source and stop at `tier0_already_filled`. The base model's
`Defaultinattr` row is only read by `_resolve_via_data_tables` for an attribute that is still empty, so it was never reached.
The existing `ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED=true` was tried on its own: no change, for the same reason.

## 3. Change (generic; no model or attribute name)

| File | What |
|---|---|
| `cpq/base_model_defaults.py` (new) | `base_model_defaults(base_model, ...)`: the `{attribute: default}` map of one base model, built in one walk and cached in the per-turn cache (the existing `resolve_defaultinattr_value` walks the whole table per attribute; ~3,000 attributes per pass is too slow). Same rules: exact base model beats `ALL`; two distinct defaults in the winning tier = none |
| `auto_fill_stages/tier0_base_model_default.py` (new) | two stages. `stage_base_model_default_clear` (right after the not-applicable guard, before `tier0_already_filled`): with a real (non-guessed) base model, empties an attribute whose earlier pick has source `rule`, a guess or `defaultinattr` and differs from the base model's default. `stage_base_model_default_fill` (after `tier2_satisfied_rec`, before `tier3_default_value`): writes the default only if the hint stage and the recommendation stage left the attribute empty. The default must be an option (matched by item value or display name) that the active constraints still allow. Values from the customer / their wording / the session (`user`, `hint`, `auto`, `data_table`) stay. Hidden attributes, multi-selects (their own flag), the decision anchors and the attributes the governance stage always asks (country, region, hardware version, select-model, base model) are not touched. The value written has the source `defaultinattr`; it is replaced when the base model changes and its default differs |
| `auto_fill_stages/coordinator.py` | registers the two stages |
| `config/config_cpq_intent.py`, `cpq/model_scoping_flags.py` | the flag and its one reader |

## 4. Result (local, ws 281, dev's flag set + this flag; "i want to quote APX N30 / N50 for US")

| | rows of the base model's `Defaultinattr` matched | status |
|---|---|---|
| N30, before | ~10 of 24 | complete |
| N30, after | **22 of 24** | complete, 0 pending |
| N50, after | **21 of 23** | complete, 0 pending |

The two not matched, for both products:

* `modelSelectionRegion_astro` (default NA): hidden, so the stage does not touch it (a hidden attribute only takes its own XML
  default). Region is derived from the country elsewhere; not changed here.
* `documentationTestResultsRatedAudioPrintoutLabel_astro` (default NO): visible and in the data (status 1, not hidden), but the
  engine never evaluates it: zero fill records at DEBUG, so it is not in the attribute list the fill receives. A loader question
  (why this attribute is not loaded for the product), not a defaults question; not changed here.

## 5. Rollout and limits

* Flag off: the stage returns at its first line (a settings read); nothing changes. Tests pin it.
* Needs the base model to be derived first (the flags of #475 / #480 and `cpq_derive_base_model_enabled`).
* Precedence with the flag on: the customer's words, then a recommendation rule that applies now, then the base model's default, then
  the generic default. This is why the work is split in two stages (review of #481: a single early stage wiped a typed hint and a
  satisfied recommendation).
* The base model code is compared case-insensitively, like `ALL`.
* Replay one quote per model with the flag off and on and compare the values (a model with a `Defaultinattr` row for an attribute
  now gets that value instead of the first option).
* Tests: `tests/test_cpq_base_model_defaults_2026_10_08.py` (16, through the real `CpqEngine.auto_fill`): the map (exact over ALL,
  ambiguous = none, case-insensitive, built once); default fill and replacement of a rule pick / a guess; a typed hint wins; a satisfied
  recommendation wins; a base-model change replaces the old default; customer / hint / auto / data-table values stay; always-asked
  attributes get no default; display-name defaults; not-an-option defaults unused; guessed base model; flag off; stage order.

Existing tests: 45 files that mention auto_fill / the stage pipeline (755 tests, flag off): 698 pass, 47 skipped, 9 fail; the 9 are in the
list that also fails on untouched `dev_oci` (they need the Docker-internal Oracle host name from the machine running pytest).
