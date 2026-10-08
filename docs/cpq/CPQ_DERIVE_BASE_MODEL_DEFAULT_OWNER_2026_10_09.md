# N70 (and N50 on dev): the base model is not derived, so band / flashcode questions are asked

Date: 2026-10-09. Flag (off by default): `cpq_derive_base_model_default_owner_enabled`
(`ARYX_CPQ_DERIVE_BASE_MODEL_DEFAULT_OWNER_ENABLED`). Needs `cpq_derive_base_model_enabled`.

## 1. Problem

* Dev, "I want to quote for APX N70 for United States": "This configuration is missing required data: Is FLASHcode Available?,
  Quantity, Power Adapter." (locally: "Number of Flashcode Digits?").
* Dev, "... APX N50 ...": the customer is asked "Frequency Bands (model Selection)".
* Wanted: N30 and N50 ask the country only; N70 asks the country and its own mandatory attributes, not base-model noise.

## 2. Cause (ws 281, DEBUG fill log; the same tables as ws 1267)

`ask.base_model.not_derived`, `NOT_NARROWED_TO_ONE`: N70 has 3 base models (VHF, 700/800 MHz, UHF). The base model is derived from
Whitelist evidence of the known attribute values. For N30 / N50 each base model's Whitelist row holds ONE band (VHF / 700/800 / UHF), so
the first-option band pick (700/800) narrows to one base model. For N70 every base model's Whitelist rows list ALL three bands
(`single_valued_discriminators` finds no separating attribute), so no known value narrows anything: the base model stays unknown,
everything that depends on it (flashcode, scoped questions, defaults) is asked or reported missing. On dev N50 the band was not picked
first, so the engine asked it.

The Defaultinattr table does separate them: the 700/800 MHz base model of each model defines the band default and the most defaults
(N70: 32 rows for `H35UCT9PW8AN` against 3 for the VHF and 5 for the UHF one; N30 24/23/23; N50 23/22/22).

## 3. Change (generic; no model, attribute or value name)

| File | What |
|---|---|
| `cpq/base_model_defaults.py` | `base_model_own_defaults(base_model, ...)`: {attribute: default values} of the rows naming that base model itself (`ALL` excluded), cached per turn |
| `cpq/derive_base_model_default_owner.py` (new) | `default_owner_base_model(...)`: runs only on the base models the Whitelist narrowing leaves (never overrides it). With 2+ left, every one having Defaultinattr rows, it returns the one whose defined attributes are a strict superset of each other's. Not used when a value the customer gave (source `user` / `hint`) differs from that base model's default for the same attribute |
| `cpq/derive_base_model_pick.py` | calls it when the Whitelist derivation returns None; logs `DERIVED_FROM_DEFAULT_OWNER` |
| `config/config_cpq_intent.py` | the flag |

## 4. Result (local, ws 281, dev's flags + `ARYX_CPQ_BASE_MODEL_DEFAULTS_ENABLED`)

| | before | after |
|---|---|---|
| N30 | complete, country only | unchanged |
| N50 | complete, country only | unchanged |
| N70 | asks "Number of Flashcode Digits?" | complete, base model `H35UCT9PW8AN` (700/800 MHz) |

## 5. Limits (read before enabling)

* N70's two sheet-mandatory attributes (Qty of SVX remote speaker mic, Wireless Carrier) are `O` (optional) rows in AttrSequence; the
  sheet's "mandatory" comes from conditional rules. The engine fills Wireless Carrier with its first-option pick (`FIRST_BY_ORDER_GOVERNED`,
  source `rule`), which the required-set treats as catalog-filled, so they are not asked. Not changed here.
* A band typed by the customer for a model whose Whitelist does not separate bands (N70 "... VHF ...") is not recognised from the
  wording today (the band stays the first-option pick); the guard above only protects values the customer gave. Not changed here.
* Models whose base models have no Defaultinattr rows, or no strict superset, behave as before.
* Replay one quote per model flag off / on.
* Tests: `tests/test_cpq_derive_base_model_default_owner_2026_10_09.py` (8).
