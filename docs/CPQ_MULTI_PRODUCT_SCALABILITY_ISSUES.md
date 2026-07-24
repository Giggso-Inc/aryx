# CPQ Multi-Product Scalability — Issues & Fix Plan

Goal being evaluated: ingest 5+ product catalogs into one workspace, quote any of
them via natural language, and switch between products within a single
conversation session. This document is an analysis only — nothing here has
been implemented yet.

All findings below were verified live against the running engine and the
real ingested graph/Postgres data (workspace 1, `ApxNextConfig`/ASTRO +
`Sl3500EConfig`/PCR catalogs), not inferred from code reading alone.

---

## 1. Product/family detection is a hardcoded whitelist

**Where:** `_HINT_PATTERNS` and `_PRODUCT_PATTERNS` in
[`src/aryx/cpq/engine.py`](../src/aryx/cpq/engine.py) (lines ~126-153 and
~308-316), plus `_CPQ_TRIGGER` (lines ~117-123).

**Problem:** these are literal regex lists naming `APX NEXT` (+XE/XN/Enhanced),
`SL3500e`, `DPX`, `XPR`, `MOTOTRBO`. A product whose name isn't in the list
gets **zero** detection, regardless of whether the underlying catalog data
actually supports it.

**Proof:** `detect_product_mention("I need to quote DGM 8500e radios for a US
customer.", {})` returns `""` — even though `DGM 8500e` is a real, ingested
product (see §3). Every one of the 5 target products needs a hand-added
regex entry under the current design. This does not scale past 2-3 products
without ongoing code edits.

**Already generic (no fix needed):**
- `_catalog_prefix()` — derives the ingested-source prefix from the ontology
  type name via regex, not a hardcoded list. Works for any Nth product.
- `_scope_to_catalog()` — matches against real `BmPrdFamily`/`BmCatalog`
  entity data fetched at runtime. Proven live: `load_product_config(reader,
  1, "DGM 8500e")` resolves cleanly to the right catalog with **no code
  change**, because the matching logic itself is already data-driven.
- `_COUNTRY_TO_REGION` / `derive_region()` — a universal geography table
  (country → NA/LA/EMEA/ME/APAC), not product-specific at all. Confirmed
  intentional and out of scope for this fix.

**Fix direction:** replace the two hardcoded pattern lists with a runtime
lookup against the same data `_scope_to_catalog()` already fetches —
`BmPrdFamily`/`BmCatalog` names plus each catalog's `productSelectionProduct_all`-
equivalent option list. This is the same technique already proven this
session for `extract_catalog_hints()` (mid-conversation NL hints), just
applied one stage earlier, at first-message product detection and at the
anchor-answer validation step.

---

## 2. Product-family anchor answer is accepted with zero validation

**Where:** [`src/aryx/api/ask_api.py:538-555`](../src/aryx/api/ask_api.py).

```python
if not session.product_name:
    detected = _cpq_engine.detect_product_mention(req.question, hints)
    if not detected and session.pending_anchor == "product":
        detected = req.question.strip()   # <-- accepted with NO validation
    ...
    session.product_name = detected
```

**Problem:** once the engine asks "what's the product family?", **any**
text typed in reply is accepted verbatim as the product name — never
checked against real catalog/product data.

**Proof (reproduced live):** asked "I need to quote DGM 8500e radios for a
US customer." → engine asked for product family (since §1's detector
missed "DGM 8500e") → replying **"US"** (a country, not a family) was
silently accepted as `session.product_name = "US"`. Downstream,
`productSelectionProduct_all` had no way to match "US" against any of its
325 options, so it fell back to blind first-by-order and produced
`APX6500` — a completely unrelated model nobody asked for. Every field
downstream (Euro plug, China bracket, ATEX cert, Arabic keypad) was just
that phantom model's own default profile, not independent bugs.

**Fix direction:** validate the anchor answer against the same real
family/catalog/product-option data described in §1 before accepting it. If
no match, re-ask instead of silently locking in unvalidated text. This
closes the failure mode for any number of ingested products, not just two.

---

## 3. DGM 8500e already exists in the ingested data — it's just mis-surfaced

**Verified:** the `Sl3500EConfig` ingestion is not really "SL3500e-only" —
it's a 73-model "PCR Business Light Devices" portfolio that includes real
`BmCatalog` entities `autoDGM5000E_BOM`, `autoDGM5500E_BOM`,
`autoDGM8000E_BOM`, `autoDGM8500E_BOM`, plus genuine `mOTOTRBO_BOM` /
`mOTOTRBOR3_BOM` entries, and a matching `'DGM8500' | 'DGM 8500'` option in
`productSelectionProduct_all`.

**Minor data inconsistency:** the catalog entity name has a trailing "E"
(`autoDGM8500E_BOM`) but the product option text does not (`DGM8500`, no
"e"). Worth knowing if any future logic does exact- rather than
substring-matching against that field.

**Implication for 5-product ingestion:** before ingesting new XML files,
check whether the "5 products" are actually already present as sub-entries
inside an existing ingestion (as DGM/MOTOTRBO are inside SL3500e) — the
product catalog here is not 1:1 with ingested XML files.

---

## 4. Two products cannot be quoted in one session — confirmed, reproduced live

**Where:** `session.product_name` is write-once
([`ask_api.py:538`](../src/aryx/api/ask_api.py) gates the whole detection
block on `if not session.product_name`), and is never re-evaluated or reset
anywhere else in the file (`grep` confirms only two assignment sites, both
inside that same gated block or its `load_product_config` follow-up).

**Proof (reproduced live) — the Q&A path specifically:**

```
Q: what are values available for the hardware versions for APX NEXT?
A: 1. APX NEXT (4G LTE+5G)  2. APX NEXT (4G LTE Only)
   session.product_name: APX NEXT

Q: what are values available for the hardware versions for SL3500e
A: 1. APX NEXT (4G LTE+5G)  2. APX NEXT (4G LTE Only)   <-- WRONG, same answer
   session.product_name: APX NEXT   <-- never changed
```

**Root cause:** `_handle_cpq_qa()` (Step 7, contextual Q&A) receives
`attrs` as a parameter — already loaded by the caller using the
**already-locked** `session.product_name`. Its fast path,
`detect_attr_query(req.question, attrs)`, only ever searches within those
already-loaded attrs. It never re-checks whether the *current* question
names a different product. So once a session locks onto "APX NEXT",
every subsequent question — even one explicitly naming "SL3500e" — is
answered using APX NEXT's attribute list.

This is not a "run two products in parallel" ask; today there is **no path
at all** for a mid-session product switch, not even for a pure read-only
Q&A question naming a different product.

**Fix direction (two parts):**
1. **Q&A path:** before falling back to the locked `attrs`, check whether
   the current question's text matches a *different* product than
   `session.product_name` (via the same generic lookup as §1). If so,
   answer using that product's freshly-loaded attrs without touching
   session state — a read-only "tell me about X" shouldn't require
   abandoning the in-progress quote.
2. **Configuration path:** detect an explicit "start a new quote for
   \<product\>" / "actually I need \<other product\>" signal mid-session,
   and if the resolved product differs from `session.product_name`, reset
   the session's `filled`/`display_filled`/`filled_source`/`filled_multi`/
   `pending_variables`/`status`/`cascade_log` and re-anchor on the new
   product — rather than mixing state from two different catalogs into one
   `filled` dict. This is the safer of the two options given 91 confirmed
   `variable_name` collisions between the two currently-ingested catalogs
   (mostly generic CRM/system fields) — carrying stale values across a
   product switch risks contaminating the new quote even where names
   collide only accidentally.

---

## 5. "Why does it ask instead of using a default?" — confirmed working as designed

Looked at the two "Surveillance" questions from the pasted transcript:

| Attribute | entity_id | default_value | Options |
|---|---|---|---|
| `spSurveillancePackagesType_astro` | 9113 | `""` (empty) | Beige, Black, No Surveillance Kit |
| `spSurveillancePackagesTypes_astro` | 8702 | `""` (empty) | Black, MCW Bundle Pack 1/2/3, No Surveillance Kit |

Both have a genuinely empty `default_value` in the raw XML, and both offer
multiple real options with no rule dictating which one applies. Per this
engine's explicit design principle (D2 — "never guess"), an attribute with
no default and no governing rule is asked, not silently defaulted. That is
intentional, not a bug.

**What is worth flagging:** these are two *different, real* attributes in
the source data (different entity ids) that happen to overlap on one shared
option ("Impress 3-Wire Surveillance Kit - Black"). The earlier
`conflicted_optional_ids` fix (this session, for the "double-fill" bug)
specifically prevents the engine from *silently* picking different values
for both — it correctly asks for both instead, which is what happened here.
The customer experience of being asked what reads as "the same question"
twice is a genuine UX rough edge, but it is the designed, safer behavior,
not a regression.

---

## 6. Hardware Version default — CORRECTED after checking raw rule tables

**Original claim in this section (now known wrong):** "zero rules target
hWVersion_astro, this is a pre-existing data gap." That was based on the
already-*parsed* `HidingRule`/`RecommendationRule` lists only. Checking the
raw `BmConfigRuleInput`/`BmConfigRuleAction` tables by BM-native id turned
up **three** real rules targeting `hWVersion_astro`:

| Rule (raw data) | Type | Condition | Effect | Backing |
|---|---|---|---|---|
| "Associated recommendation Hide HW Version unless APX Next NA or APX Next fed model (portables)" | hiding | Country + Region + CustomerType + Model | hides Hardware Version unless matched | **script (BML)** |
| "Constrain None for Hardware version" | constraint | Region = `NA` | constrains the option set | declarative |
| "Default hardware version for APX Next" | recommendation | Region = `NA` | recommends `NEXT STANDARD LTE ONLY` | declarative |

**Corrected conclusion:** `NEXT STANDARD LTE ONLY` was not a blind guess —
it is the *correct* output of the third (declarative, real) rule for a
US/NA customer. There is no data gap here; the engine got the right answer
for the right reason. What actually needs fixing is §8 below — the first
rule (the hiding one) never gets a chance to run in our engine at all.

---

## 8. Script-backed hiding rules are silently skipped — confirmed at scale (119/191)

This directly answers the question raised this round from the real Oracle
CPQ UI screenshots: after filling in Destination Country, Hardware Version
appeared in the UI where it hadn't been shown before — a real
dependent-attribute reveal, driven by rules, exactly like the engine here
is supposed to reproduce.

**Confirmed the dependency chain is real, in our own ingested data:** the
first rule in the table above ("Hide HW Version unless...") is precisely
that Country/Region-gated visibility rule. But it's **script-backed**
(its logic lives in a BML function, not a plain condition/value row), and:

- `load_hiding_rules()` explicitly **skips** script-backed rules — they are
  counted and logged ("script-backed, not evaluated") but never become an
  active hide/show rule.
- `apply_hiding_rules()` takes **no BML evaluator parameter at all** —
  unlike `apply_constraint_rules()`, which already accepts one and does
  evaluate script-backed constraints.

**Scale, measured directly:** of the 191 hiding rules ingested for the APX
Next catalog, **119 (62%) are script-backed** and therefore never take
effect in this engine today. Only 72 (38%) are declarative and actually
apply. So for roughly 6 out of 10 real "show/hide this field based on that
prior answer" dependencies in the source data, this engine currently does
**not** validate or apply them at all — not because the data lacks them,
but because BML-driven hide/show logic isn't wired up, only BML-driven
constraints are.

**This is very likely also why** Hardware Version → Product →
Configuration Type → Software Bundles (the further cascade visible in the
second screenshot) doesn't reveal progressively the way the real UI does —
the same script-backed-hiding gap plausibly governs those transitions too;
not independently verified per-field here, but the mechanism and the 62%
figure make it the leading explanation.

**Fix direction:** thread a `bml_eval` parameter through
`load_hiding_rules()`/`apply_hiding_rules()`, the same pattern already
proven for constraints — keep script-backed hiding rules instead of
discarding them, and evaluate their condition via the existing BML
evaluator (Tier 1 deterministic parser, Tier 2 LLM fallback) each pass.

---

## 9. Design proposal from this session: hierarchical fallback when detection is vague

Proposed by the user this round: if product detection can't confidently
resolve to one product, ask for the **family** first, then narrow through
whatever real sub-hierarchy the catalog actually has (family → model →
config), rather than either guessing or asking one flat "which product"
question.

This composes cleanly with §1/§2's fix direction, because the real data
already has that hierarchy: `BmPrdFamily` (1 per ingested source) →
`BmCatalog` (many models per source, e.g. the 73 under `Sl3500EConfig`) →
`productSelectionProduct_all` option (the customer-facing model name).
Concretely:

1. Try direct detection (§1's generalized version) against all 3 levels at
   once — most messages will resolve here (e.g. "DGM 8500e" matches
   `autoDGM8500E_BOM` directly, no extra questions needed, proven live).
2. If nothing matches uniquely, ask for the **family** (dynamically listing
   the real ingested family names — not the static "APX Next, MOTOTRBO,
   SL3500e" string currently hardcoded at
   [`ask_api.py:546`](../src/aryx/api/ask_api.py)).
3. Once family is confirmed, if it still doesn't uniquely resolve to one
   model (e.g. a family with 73 catalogs like PCR), ask for the specific
   model next, listing only that family's real catalog names.
4. Only then call `load_product_config` with the fully-resolved,
   validated product/catalog.

This also directly satisfies §2's fix (every step validates against real
data before advancing) and scales to 5+ products without new hardcoding —
the question list at each step is generated from whatever is actually
ingested, not a fixed regex list.

---

## Summary table

| # | Issue | Status | Blocks 5-product goal? |
|---|---|---|---|
| 1 | `_HINT_PATTERNS`/`_PRODUCT_PATTERNS`/`_CPQ_TRIGGER` hardcode product names | Confirmed | Yes — hard blocker |
| 2 | Anchor answer accepted with no validation | Confirmed, reproduced live | Yes — hard blocker |
| 3 | DGM 8500e exists but mis-surfaced; minor name inconsistency | Confirmed | No — informational |
| 4 | No mid-session product switch (Q&A and config both) | Confirmed, reproduced live | Yes — hard blocker |
| 5 | Double "surveillance" question | Working as designed | No — UX polish only |
| 6 | hWVersion "no rule" claim | **Retracted** — a real rule explains the value correctly | N/A |
| 7 | apply_hiding_rules() ignores script-backed rules (119/191 = 62% of hiding rules never apply) | **Confirmed, measured live** | Yes — this is why dependent-field reveal (seen in the real Oracle UI) doesn't happen here |
| 8 | Hierarchical family→model fallback | Design proposal, not yet built | Enables the fix for #1/#2 |

**Recommended fix order:** §7 (wire BML evaluation into hiding rules — the
single highest-leverage fix; it's the actual mechanism behind the real
UI's progressive field reveal and is currently silently dropping 62% of
hide/show rules) alongside §1 + §2 + §8 (generalize product detection,
validate the anchor answer, add the hierarchical fallback), then §4
(mid-session product switch), in that order. §3 is informational only.
§5 needs no code change. §6 was retracted after checking the raw rule
tables — no fix needed there.

No code has been changed as part of this analysis.