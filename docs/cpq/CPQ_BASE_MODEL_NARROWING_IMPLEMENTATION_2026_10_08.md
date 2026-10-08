# Base model narrowing, both directions — implementation

Date: 2026-10-08. Workspace 1267 (Astro25), catalog prefix `Astro25Configdata`.
Flag: `cpq_base_model_narrowing_enabled` (`ARYX_CPQ_BASE_MODEL_NARROWING_ENABLED`), **off by default**.
The fill-pass behaviours run only when `ARYX_CPQ_DERIVE_BASE_MODEL_ENABLED=true` is on as well (without the existing
derivation the base model would wait for the answers and then be asked from the full list anyway). The typed-phrase
hint tie-break needs only the narrowing flag.

## 1. The problem

"I want a quote for APX 900 for US" is the main flow. The real CPQ screen asks Frequency Band and Keypad Type and never
shows a base model. Ask asked "Since we locked in United States, please choose the Base Model" with **660 options**
(`HK2072A`, `M36KSS9PW1AN`, …), and a message that did contain "700/800 MHz, Limited Keypad" still ended in the same
question.

## 2. What the logs and data showed (not assumed)

| Finding | Evidence |
|---|---|
| The model and its base models are found | `ask.base_model.not_derived`: `product_filled: true`, candidates `["APX900", …]`, `base_models_per_candidate: {"APX900": 10}` |
| Only the country narrowed anything | `known_attr_match`: one entry, `ultimateDestinationCountry`, `remaining_before: 10 → remaining_after: 8` |
| The 10 base models are exactly 5 frequency bands × 2 keypad types | `WS1267_WHITELIST`, APX 900: `modelSelectionFrequencyBands_astro` (10 base models, 5 values), `modelSelectionKeypadType_astro` (10 base models, 2 values) |
| Typed answers were not recognised | `ask.preamble.hints`: `hint_names: ["country"]` only |
| The two attributes were then **guessed** | `ask.fill.attribute decided`: `source` = `default_first_available` / `blind_pick_rule_governed` (stage trail: `tier1_hint_match: no_op`, `tier4_options: value_chosen`). The derivation ignores guessed values on purpose |
| Why the typed phrases were dropped | `extract_catalog_hints` never guesses when an option's text belongs to 2+ attributes. "Limited Keypad" is an option of `modelSelectionKeypadType_astro` and `modelSelectionDisplayType_astro`; "700/800 MHz" of the frequency band and several antenna and radio-option attributes |
| `BaseModelToConfig.csv` does not help narrow | `attr1`/`val1` are empty for APX 900, N30, 4500, 8500, 1500; 195 of 826 models have a single base model, and only 4 split by product name |

Root causes, in order of effect:

1. **The customer's frequency band and keypad never count as answers** (never-guess rule on a multi-owner phrase).
2. **The discriminating attributes are guessed, not asked** (`tier4_options` blind pick).
3. **The base model is a decision attribute asked immediately** while nothing separates its base models yet.

## 3. The mapping works both ways

A base model such as `H92UDH9PW7AN` and its (frequency band, keypad) pair identify each other. Reverse
(attributes → base model) is what a customer can answer. Forward (base model → attributes) is useful when a base model
is given. Both are implemented.

## 4. Design

Everything is read from the model's own whitelist rows; no model or attribute name is in the code.

### 4.1 Which attributes separate a model's base models (`base_model_narrowing.single_valued_discriminators`)

An attribute separates the base models still **in play** when:
- **every** one of them (blank and `ALL` excluded) has rows for it,
- each base model holds **exactly one** value for it, and
- at least **two different** values exist.

"In play" means the base models the known answers (the country, ...) have not already excluded, using the same
narrowing as the derivation (`narrowed_base_models`, shared so the two cannot drift). An attribute whose value is
already decided is therefore not asked. For APX 900 with nothing known that gives the frequency band and the keypad
type. Left out on purpose: the country (several values per
base model), housing (only some base models), and `productSelectionProduct_all` (the same value everywhere).

### 4.2 Per fill pass (`build_base_model_narrowing`, called from `auto_fill_setup` only when the flag is on)

The first candidate model with two or more base models is used (candidates come from the existing
`resolved_model_first_candidates`). The result, `BaseModelNarrowing`, is attached to `FillScope.base_model_narrowing`:

| Field | Meaning |
|---|---|
| `ask_first` | visible, unanswered separating attributes with options, excluding the country and region keys (they have their own path) and any base model / part-number attribute (`basemodel` in the name). A guessed value counts as unanswered |
| `forward` | when the customer already has a base model, `{attribute: value}` read off that base model for the unanswered separating attributes |
| `base_model_codes` | the model's base model codes, to tell a base model attribute from a part-number one |

It is `None` when there is no product, the model has fewer than two base models, nothing separates them, or the known
answers already leave a single base model (the derivation fills it).

**Earlier guesses are reopened** (`reopen_guessed_values`, in the same setup): a guessed value of an attribute the
narrowing asks or forward-fills is forgotten (value, display and source), because the "already filled" stage keeps a
`blind_pick_rule_governed` value and the attribute would never be asked while the base model waits for it. Only
guesses are reopened, never an answer. Any error while building the narrowing is caught and logged at debug level, and
the pass fills exactly as it does with the flag off.

### 4.3 The four behaviours

| # | Where | What |
|---|---|---|
| 1 | `governance_flags` | an attribute in `ask_first` becomes a **decision attribute**: asked, never guessed (the engine's existing "always ask" state) |
| 2 | `region_and_base_model` (`_defer_base_model_question`) | after the existing derivation returns nothing, a base model attribute **waits** (`state.done`, not pending) while `ask_first` is non-empty. When the customer has answered, the existing `derive_base_model_from_known_attrs` fills it |
| 3 | same stage | a **part-number** base model attribute (its options are not base model codes, e.g. `modelSelectionBaseModelMsl_astro`) that the layout hides (`display_order` loaded and the attribute absent) is not asked |
| 4 | new stage `tier0_forward_fill` | a known base model fills its unanswered separating attributes (source `derived_from_base_model`) |

### 4.4 Typed answers (`catalog_hints_product.product_selector_entries`)

When a typed phrase is owned by several attributes and none is the product selector, the owner whose value for that
phrase is one of the model's discriminator values is preferred — **only if exactly one owner qualifies**; otherwise it
stays never-guess. The discriminator values come from `discriminator_values(...)`, computed in
`ask_step2_catalog_hints._model_discriminators` only when the flag is on. With the flag off, or no discriminators, the
call to `extract_catalog_hints` is the same two-argument call as before.

## 5. The flows

```
A. bare "I want a quote for APX 900 for US"
   country known (10 -> 8 base models) -> ask Frequency Band -> ask Keypad Type
   -> existing derivation fills the base model -> the base model question never appears

B. "…for US, 700/800 MHz, Limited Keypad"
   hints recognised for the one owner the rows use -> real (non-guess) sources
   -> derivation fills the base model -> no questions about them

C. the customer gives a base model
   forward fill sets Frequency Band and Keypad Type (only if unanswered)

D. a model with exactly one base model (195 of 826): unchanged, derived immediately
```

## 6. Files

| File | Change |
|---|---|
| `cpq/base_model_narrowing.py` (new) | discriminators, `BaseModelNarrowing`, `build_base_model_narrowing`, `discriminator_values` |
| `cpq/auto_fill_stages/tier0_forward_fill.py` (new) | forward fill stage, placed after `tier0_hidden` |
| `cpq/auto_fill_stages/governance_flags.py` | decision-attribute rule |
| `cpq/auto_fill_stages/region_and_base_model.py` | defer / skip part-number attribute |
| `cpq/auto_fill_stages/coordinator.py` | registers the new stage |
| `cpq/auto_fill/auto_fill_setup.py`, `cpq/engine.py` (`FillScope`) | builds and carries the narrowing (new field has a default) |
| `cpq/catalog_hints.py`, `cpq/catalog_hints_product.py`, `cpq/engine.py` | optional `discriminators` argument |
| `api/ask_turn_steps/ask_step2_catalog_hints.py` | computes the discriminators (flag-gated, failure-safe) |
| `cpq/data_table/data_table_derive_base_model.py` | `model_rows_and_base_models`, `row_attr_values` |
| `config/config_cpq_intent.py` | the flag |

The derivation (`derive_base_model_from_known_attrs`) and the whitelist data are unchanged.

## 7. Safety

- **Flag off:** `scope.base_model_narrowing` is `None`, the hint call is the same two-argument call, and no stage changes
  an outcome (pinned by tests, including an end-to-end flag-off case that still asks the base model).
- **One-sided:** it only changes order and fills from the model's own rows; it never overrides an answered attribute
  (user or hint source). A guessed value is never treated as an answer: a guess made earlier (an earlier turn, or an
  earlier pass before the product was known) is reopened so the attribute is asked.
- **Fallback:** if the answers still leave two or more base models, the existing always-ask base model question
  applies. Nothing is guessed.
- **No customer text** is added to any log.

## 8. Known limits (not fixed here)

- `modelSelectionBaseModelMsl_astro` (part numbers such as `T7766A`) is not derivable from the whitelist: its options
  are a different identifier space. It is only skipped when the layout hides it.
- The derivation depends on the order of the known attributes; two contradictory separating attributes give an
  order-dependent result (`explain_known_attrs` in the diagnostics shows it). Separate ticket.
- A separating attribute that is **hidden** (APX 900's `modelSelectionRegion_astro`) is not asked and cannot count as
  evidence unless something fills it.
- A multi-owner phrase whose owners are *both* used by the model's rows stays never-guess.
- The layout variant (portable vs mobile) used for the "layout hides it" check depends on the layout being uploaded
  per variant under one prefix; with only the portable layout loaded, a mobile model's `display_order` is the
  portable one. See `docs/oci-oracle/LAYOUT_UPLOAD_AND_MAPPING_ASTRO25_2026-10-06.md`.

## 9. Tests

`tests/test_cpq_base_model_narrowing_2026_10_08.py` (44), built from the real shapes: the 10 APX 900 base models
(5 bands × 2 keypads), the multi-owner phrases "700/800 MHz" and "Limited Keypad", and the real `auto_fill` pipeline with
only the RDB faked.

| Area | Cases |
|---|---|
| Discriminators | only separating attributes found; 5 × 2 identifies all 10 |
| Build | bare quote; hidden / optionless attributes; answered; guess is not an answer; nothing to narrow |
| Forward | known base model fills; never overrides; a guessed base model is not known |
| Stages | decision attribute; defer and resume; part-number attribute (layout hides / places / no layout); flag off |
| Hints | dropped today; hinted with the discriminators (by item value or display name, the rule the forward fill uses); exactly-one-owner rule; single owner and product selector unchanged; flag-gated and failure-safe |
| Reopening | a `blind_pick_rule_governed` or `default_first_available` guess is reopened and asked (red without the fix); only the guessed attribute; answers untouched; a build failure leaves the fill as it was; needs the derivation flag |
| Remaining base models | an attribute decided by the country is not asked; a guessed country does not narrow; a part-number attribute is never asked |
| End to end | bare quote asks both and not the base model; flag off asks as before; answers derive the base model; typed hints derive it; a given base model fills the two; one answer leaves the other |

## 10. Rollout and verification on dev

1. Deploy with the flag off (no change).
2. Set `ARYX_CPQ_BASE_MODEL_NARROWING_ENABLED=true` and `ARYX_CPQ_DERIVE_BASE_MODEL_ENABLED=true`; recreate the container
   and confirm with `docker inspect aryx-api-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E "NARROWING|DERIVE_BASE"`.
3. New chat **"I want a quote for APX 900 for US"**. Expect: Frequency Band, then Keypad Type, then no base model
   question. Check:
   ```bash
   docker logs aryx-api-1 --since 10m 2>&1 | grep -E "ask.base_model.(derived|not_derived)|BASE_MODEL_DEFERRED|ask.catalog_hint.multi_owner" | cut -c1-300
   ```
4. New chat **"…for US, 700/800 MHz, Limited Keypad"**. Expect no questions about those, `ask.base_model.derived`, and
   `reason_code: MODEL_DISCRIMINATOR_OWNER` on the hints.
5. Check N30 (3 base models, frequency band only), APX 4500 and a single-base-model product (unchanged).
6. Compare with the real screens. If a question the real UI asks is missing, turn the flag off and report the attribute.

## 11. Open follow-ups

- Hide / ask order of the remaining Msl and regional attributes (see the layout doc).
- The order dependence of the derivation.
- Forward-filling from a part number typed in the message (needs a mapping from part number to base model; the
  `BaseModelToConfig` table has `pvPartNumber` for only 9 rows).

## Follow-up (2026-10-08): the question lists only the model's own values

Live run after #473: the bot asked Keypad Type and Frequency Bands (not the 660-option base model), but listed the
catalog's full lists (4 keypads, 20 bands) although APX 900's base models hold 2 keypads and 5 bands.

`discriminator_option_limits` (`base_model_narrowing.py`) returns, per separating attribute still to ask, the item values
the base models still in play hold. `_with_model_option_limits` (`ask_step11_build_response.py`) merges them into
`constrained_opts` before the question is built (flag `cpq_base_model_narrowing_enabled`; only tightens an existing
rule constraint; failure leaves the list as it was). An attribute whose options all belong to the model keeps its list.
The shortened list is also what the next reply is matched against (`_remember_attr_scope` builds the pending scope from it), so a
typed value that was left out gets the scoped "did you mean" re-ask from the shown list, not a silent accept. Each limited question
logs `ask.options.model_limits` (DEBUG: offered vs catalog option count) so an over-trim is visible.

## Combined PR (2026-10-08): what it contains and what to set

Replaces #474 (option limits) and #477 (grid quantities) and adds the fixes found while replaying APX 900 on dev.

| Change | Flag (all off by default) | Evidence |
|---|---|---|
| Frequency / keypad lists show only the model's own values | `ARYX_CPQ_BASE_MODEL_NARROWING_ENABLED` | 20 bands / 4 keypads shown, whitelist holds 5 / 2 |
| Narrowing questions follow the model's AttrSequence `Seq` (frequency 33, keypad 39) | same | keypad was asked before frequency |
| Derivation applies the separating attributes first and ignores an attribute the rows only use as a condition | `ARYX_CPQ_DERIVE_DISCRIMINATORS_FIRST_ENABLED` | country US dropped the two 700/800 MHz base models (10 -> 8): `ask.base_model.not_derived`, `known_attr_match` |
| "700/800 MHz" typed in the first message is hinted: the model is read from the wording, the Product is not filled yet | `ARYX_CPQ_BASE_MODEL_NARROWING_ENABLED` + `ARYX_CPQ_MODEL_RESOLUTION_ENABLED` | hints run before the turn's model is bound |
| Grid quantity questions only for a selector the pass left pending | `ARYX_CPQ_GRID_QUANTITY_PENDING_SELECTORS_ONLY_ENABLED` | APX N30 asked 7 holders after 0 pending |

Environment (dev): set `ARYX_CPQ_BASE_MODEL_NARROWING_ENABLED`, `ARYX_CPQ_DERIVE_DISCRIMINATORS_FIRST_ENABLED`,
`ARYX_CPQ_GRID_QUANTITY_PENDING_SELECTORS_ONLY_ENABLED` to `true`. Already on and required: `ARYX_CPQ_DERIVE_BASE_MODEL_ENABLED`,
`ARYX_CPQ_MODEL_RESOLUTION_ENABLED`, `ARYX_CPQ_RULE_SCOPE_FILTER_ENABLED`, `ARYX_CPQ_BASE_MODEL_PLACEHOLDER_GUARD_ENABLED`,
`ARYX_CPQ_MODEL_SCOPED_QUESTIONS_ENABLED`. Recreate the container (a restart does not read new variables).

Replay on dev after deploy: "I want a quote for APX 900 in the US" -> frequency (5 options) then keypad (2 options) -> base model
derived, no 660-option question; "I want a quote for APX 900 with 700/800 MHz in the US" -> only the keypad is asked.
Also quote APX 8000H (check the derived base model is never `H91TGD9PW4AN`, which belongs to the SRX / XE models only).

Not in this PR: the Product being stored as `APX900FLASHPORT` (the catalog's only "APX 900" Product item is the upgrade series).

### Defaults from the Defaultinattr table (existing flag, no code change in this PR)

Live run (ws 1267, APX 900, 700/800 MHz, Full Keypad, US, base model `H92UCH9PW7AN`): three "System-Configured / Recommended"
values were first-option guesses (`blind_pick_rule_governed`, `default_first_available`) although `WS1267_DEFAULTINATTR` holds
the real default for that base model:

| Attribute | Table default | Quote showed |
|---|---|---|
| `antennasType_astro` | WHIP (STANDARD) | STUBBY |
| `modelSelectionHazardousLocation_astro` | N/A | TIA4950(UL) |
| `packingPackageType_astro` | BULK | SINGLE |

The table is read only with `ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED=true` (`cpq_defaultinattr_shape_enabled`, off by default). With
it on, the default of the known base model is used when the whitelist gave no single legal value and the default is a real option.
Set it with the other flags and recreate the container. Replay "APX 900 in the US" (700/800 MHz, Full Keypad) and confirm the three
values above; the table also holds defaults for about 15 more attributes of this base model (submersible NO, belt clip
2.0 INCH (STANDARD), manual NO, operation mode DIGITAL TRUNKING (P25 PHASE I), multikey NO MULTIKEY, housing BLACK, service type
ESSENTIAL, service duration 7 YEAR, ...). Not verified live yet: whether the flag was already on, and whether the defaults are applied
in the same turn the base model is derived.
