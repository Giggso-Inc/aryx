# CPQ Carrier Attrs Missing from `config_data` / Beautify — RCA & Fix (2026-08-20)

**Status:** Fixed — PR #237 (merged), PR #239 (merged, includes the docstring correction below)
**Attrs affected:** `wirelessCarrier_astro` ("Wireless Carrier", 4G-only base models),
`carrierSelectionMultiSelect_astro` ("Carrier Selection", 5G-capable base models)

## Symptom

Live testing on workspace 93 repeatedly showed the carrier attribute missing from the
final `config_data` JSON payload, and — in a later, distinct incident — missing from
Beautify's "Mandatory User Input" section too, for the 4G-only flow specifically
(base model `H55TGT9PW8AN`, product `APX NEXT All Band`).

`wirelessCarrier_astro` and `carrierSelectionMultiSelect_astro` are mutually exclusive
per-base-model siblings for the same real-world concept — zero base models require both.
4G-only base models resolve carrier via the single-select `wirelessCarrier_astro`; 5G-capable
base models resolve it via the multi-select `carrierSelectionMultiSelect_astro`.

There were **two independent, unrelated gaps**, found and fixed in sequence.

## Gap 1 — `build_payload` never counted a catalog-resolved carrier as "active" (PR #237)

`build_payload`'s `_is_mandatory_input_attr` scoping (Tier A/B/C, see
`docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_2026_08_19.md`) only ships an attribute into
`config_data` when it is a structural anchor, or is tagged one of a small set of "active"
sources (`user`, `hint`, `cascade`, `cascade-dependent`, `country_derived`, `product_anchor`).
A value resolved via a `RecommendationRule` (source `"rule"`) or a genuine Data-Table lookup
was excluded even when it was a real, catalog-authored answer rather than a blind pick.

Live-confirmed on workspace 93:
- `wirelessCarrier_astro` can be forced by the real rule *"Force Set Wireless Carrier... when
  ATAK is enabled"* — a deterministic, causal consequence of a decision the customer already
  made (ATAK enabled), no less genuine than a `"cascade"` copy.
- For base model `H55TGT9PW8AN` + `Country=US`, the real ingested Whitelist Data Table
  narrows `wirelessCarrier_astro` to two legal values (`ATT/FIRSTNET`, `VERIZON`) — a
  catalog-proven choice among real alternatives, not a made-up value.

### Fix

Two new generic (catalog-agnostic, no attribute names hardcoded) helpers in `engine.py`:

- **`_rule_forced_from_active_decision_vns`** — a `RecommendationRule` with a single
  declarative condition (no script, no multi-input `conditions`) whose trigger attribute is
  itself actively sourced makes its target attribute count as actively sourced too.
- **`_data_table_forced_vns`** — a `_ATTRSEQ_CONFIRMED_REQUIRED_VNS` member whose filled
  value the real Whitelist/Defaultinattr Data Table confirms as **any** genuine legal option
  for the active `(cpq_model, base_model)` counts as actively sourced. Deliberately does
  **not** require the value be the *only* legal option — an earlier, stricter
  "exactly one" version was live-DB-proven too strict (the `H55TGT9PW8AN` + `US` case above
  has two legal carriers, and a real choice among 2+ legitimate options is still genuine).

Both frozensets are computed once per `build_payload` call (gated on
`scope_required_and_edited`) and OR'd into `_is_mandatory_input_attr`'s active-source check
via its `rule_forced_active_vns` / `data_table_forced_vns` params.

## Gap 2 — sibling-exclusion logic stripped the catalog-proven value anyway (PR #239)

Gap 1 fixed *inclusion in `config_data`* for an already-filled value. It did not explain why,
for the 4G-only flow specifically, the value sometimes never made it into **Beautify** either
— a stricter symptom, since Beautify's own Tier A check has no active-source gate at all and
should show a `_ATTRSEQ_CONFIRMED_REQUIRED_VNS` member unconditionally once filled.

Root cause: a separate mechanism, `exclusive_sibling_family_exclusions` (added earlier to fix
a different bug — two siblings both getting filled when no hiding rule actually excluded
either one), treats `wirelessCarrier_astro`/`carrierSelectionMultiSelect_astro` as a named
exception pair (`_KNOWN_SIBLING_PAIRS` — their display labels share no common stem, so the
generic label-similarity detector can't find them on its own). Whenever the single-select
sibling has a "weakly sourced" value (`source` in `{"default", "rule", "auto"}`) and the
multi-select sibling is still empty, it **strips** the single-select's value from `filled` and
queues the multi-select to be asked instead — on the assumption that the multi-select is
always the "real" governing attribute once both are visible.

That assumption breaks for the 4G-only flow: `carrierSelectionMultiSelect_astro` has **zero**
legal Data Table rows for a 4G base model, so asking for it can never produce an answer.
The result: `wirelessCarrier_astro`'s genuine, catalog-proven value gets stripped, its
multi-select sibling gets queued but can never be filled, and **both** carrier attrs end up
empty — missing from `config_data` *and* Beautify.

### Fix

Added a `catalog_confirmed_vns` exemption parameter to `exclusive_sibling_family_exclusions`
/ `enforce_exclusive_sibling_families`: a single-select value already vouched for by
`_rule_forced_from_active_decision_vns` or `_data_table_forced_vns` (the same two mechanisms
from Gap 1) is never stripped. Wired at the `ask_api.py` call site, which computes the union
of both mechanisms before calling `enforce_exclusive_sibling_families`.

This is additive and scoped to the single-select side of the pair only — it does not change
the strip logic for any other sibling pair, and does not affect the 5G flow at all (there,
`carrierSelectionMultiSelect_astro` genuinely is the governing attribute and fills normally
through its own path).

## Why two separate fixes were needed

| | Gap 1 (`_data_table_forced_vns` / `_rule_forced_from_active_decision_vns`) | Gap 2 (`catalog_confirmed_vns` exemption) |
|---|---|---|
| Consumer affected | `config_data` only | `filled` itself (upstream of `config_data` *and* Beautify) |
| Failure mode | Value present in `filled`, excluded from payload by scoping | Value deleted from `filled` entirely by the sibling-exclusion pass |
| Symptom | Beautify showed it, `config_data` didn't | Neither showed it |

Gap 1 alone was sufficient for cases where the sibling-exclusion pass never fired (e.g. the
value was sourced `"user"`/`"hint"`, outside `_WEAK_SOURCES`). Gap 2 was needed for the
specific 4G-only case where the value's source was `"rule"`/`"default"` — weak enough to
trigger the sibling strip even after Gap 1 made it "active" for `config_data` purposes,
since the strip runs earlier in the turn, on `filled` directly, before `build_payload` or
Beautify ever see it.

## Verification

- Live turn-by-turn against workspace 93, both 4G (`wirelessCarrier_astro`,
  `H55TGT9PW8AN`) and 5G (`carrierSelectionMultiSelect_astro`, `H55TGT9PW8BN`) flows.
- `tests/test_cpq_config_data_attrseq_confirmed_gate_2026_08_19.py` — 12 tests covering Gap 1
  (rule-forced and data-table-forced inclusion, plus abstention on script/multi-input rules).
- `tests/test_cpq_frequency_band_family_exclusions.py` — 14 tests covering Gap 2, including
  a dedicated check that the exemption never leaks into an unrelated sibling pair.
- Full CPQ+BML suite: 1303 passed, 16 failed — matches the established pre-existing failure
  baseline exactly (unrelated to this change), 47 skipped.

## Related docs

- `docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_2026_08_19.md` — the original Tier A/B/C
  scoping design this fix extends.
- `docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md` — Beautify's own
  Mandatory/System split, the shared scoping key both this fix and that one build on.
