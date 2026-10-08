# N70 mandatory attributes, and what `ARYX_CPQ_NO_BLIND_FILL_OPTIONAL_ENABLED` (#486) does to N30 / N50 / N70

Date: 2026-10-09. Documentation only: no code change. Local replay on ws 281 (the same tables as ws 1267), `dev_oci` at #487, dev's
other flags, `ARYX_CPQ_DERIVE_BASE_MODEL_DEFAULT_OWNER_ENABLED` (#488) and `ARYX_CPQ_BASE_MODEL_DEFAULTS_ENABLED` (#481) on.

## 1. The question

The mandatory-attribute sheet marks, for APX N70, `Qty of SVX Remote Speaker Mic` and `Wireless Carrier` (and nothing for N30 / N50
besides the country). Should a quote for "APX N70 for United States" ask them?

## 2. What the data says

* Both are `O` (optional) rows in AttrSequence for every N70 base model. The sheet shows them after "Add SVX Video Wireless Remote
  Speaker Mic: Checked", so they are required only once that add-on is chosen (a conditional rule), not always.
* Without any flag, N70 fills Wireless Carrier with its first option (`FIRST_BY_ORDER_GOVERNED`, source `rule`), so it is never asked.

## 3. Replay (local)

| Flags | N70 | N30 | N50 |
|---|---|---|---|
| none of the below | complete; Wireless Carrier = first option, silently | complete | complete |
| `REQUIRED_SET_ENABLED`, `REQUIRED_SET_ASKS_ENABLED`, `REQUIRED_SET_RULE_GUARDS_ASSUMED_OPEN` | complete; the silent pick is gone; the "Mandatory User Input" list grows with attributes filled from Defaultinattr (antenna, housing, battery, ...), not asked | same | not run |
| `NO_BLIND_FILL_OPTIONAL_ENABLED` (#486) | complete; Wireless Carrier and Application Services no longer silently picked; list = country-only shape | complete | **asks "Number of Flashcode Digits?"** |

## 4. The N50 regression with #486 (found here, not fixed here)

With the flag on, N50's frequency band is optional, has no basis and is left empty (`OPTIONAL_NO_BASIS`). Today the first-option band
pick (700/800 MHz) is what lets the Whitelist narrow N50's three base models to one (each base model holds one band). Without the pick
the base model stays unknown (`NOT_NARROWED_TO_ONE`), and everything that depends on it, Flashcode digits first, is asked. #488's default
owner correctly stays out of it: the band still separates the base models, so it must be asked, not picked.

Consequence: do not enable `ARYX_CPQ_NO_BLIND_FILL_OPTIONAL_ENABLED` on a workspace where N50 must complete with the country only,
until the band of a model whose Defaultinattr names one default base model is taken from that default (the same idea as #481 /
#488, applied to a separating attribute that has exactly one Defaultinattr owner). That is a code change and needs a decision.

## 5. Recommendation

1. N70 sheet-mandatory attributes: no always-ask code change; they are conditional on the remote speaker mic. If the real screen
   asks them when the add-on is chosen, that path needs its own test (the wording "with the video wireless remote speaker mic" did
   not set the add-on locally).
2. `ARYX_CPQ_NO_BLIND_FILL_OPTIONAL_ENABLED` removes the silent N70 pick but breaks N50 (section 4): hold it until the band default
   is handled.
3. The required-set flags change the summary of every model (longer list of defaulted attributes); replay a few models first.
