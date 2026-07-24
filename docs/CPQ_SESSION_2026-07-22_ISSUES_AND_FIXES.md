# CPQ Session Issues & Fixes — 2026-07-22

Live-verified issue log from cross-validating real APX NEXT Enhanced, SVX Video Remote
Speaker Mic, and DM4400 quote flows against workspace 19 catalog data, plus PR #111 review
follow-ups. Each entry: **Problem statement** (what was observed), **Where in the ARYX flow**
(exact file/function), **Root cause**, **Fix**.

---

## 1. Recommendation rules losing to a generic catalog default

**Problem statement:** Quoting APX NEXT Enhanced with base model `H45TGU9PW8AN` should force
`solutionTypeDevices_astro` (Solution Type) to `CLOUD RC` ("RadioCentral with CPS") per the
real rule "Set CLOUD RC as default value." Instead it always resolved to the attribute's
generic XML default, `RADIOCENTRAL PLUS CPS PROGRAMMING`.

**Where in the flow:** `src/aryx/cpq/engine.py` — `CpqEngine.auto_fill()`, the fill-priority
chain (hint → default_value → rule-governed default-or-first).

**Root cause:** Step 3 (a non-empty XML `default_value`) ran and locked the attribute into
`filled` *before* step 4 ever checked whether a targeted recommendation rule's condition was
already satisfied. `apply_recommendation_rules()` never revisits an attribute already in
`filled`, so any attribute with both a real rule *and* a non-empty default silently favored
the default, every time.

**Fix:** Added `_satisfied_recommendation()` and inserted it as a new step *before* the
default_value fallback — a condition-matched recommendation now wins over a generic default,
since it's more specific. Reused the same helper to de-duplicate the existing step-4 check.
(commit `0f6f059`)

---

## 2. `detect_change_request` never disambiguated identical-label collisions

**Problem statement:** PR #111 review flagged that a request like "change service type to
Premier" against 3 attributes all displayed as **"Service Type"** would silently resolve to
whichever one is first in catalog order — `detect_attr_query` already had a collision check,
but `detect_change_request` never did.

**Where in the flow:** `src/aryx/api/ask_api.py` — the "STEP 6: change request → cascade"
branch, immediately before calling `_cpq_engine.detect_change_request()`.
`src/aryx/cpq/engine.py` — new method `detect_change_request_collision()`.

**Root cause:** `detect_label_collision()` (used elsewhere) gates on options-query keywords
("what options...") that never appear in a change request, so it could not be reused
directly. `detect_change_request`'s own fix for a *related* problem (a generic label like
"Quantity" losing to a more specific one that subsumes it, e.g. "mounting type Locking Molle
Mount Quantity") only handles **subsumption**, not attrs sharing the exact **same** label.

**Fix:** Added `detect_change_request_collision()` — gated on the same change-verb/arrow
signal `detect_change_request` uses, restricted to attrs already in `filled`/`filled_multi`,
grouped by *exact* label text (not the options-query keyword gate). Wired into `ask_api.py`
ahead of the change-request handler so an identical-label tie now prompts for
disambiguation. (commit `01edd68`)

**Follow-up bug this introduced:** the message *"change mounting type Shirt Magnetic Mount
Quantity to 88"* itself starts with the generic **"Mounting Type"** text, so the new collision
check false-positived a collision between the two "Mounting Type" selectors even though the
user clearly named the specific quantity attribute. Fixed by adding the same
"more-specific-match-supersedes" narrowing `detect_change_request` already used for the
subsumption case. (commit `8370739`)

---

## 3. Tier-1 BML evaluator reading `//`-commented-out code as live

**Problem statement:** After changing Hardware Version (which invalidates and re-derives
`Product`), `productSelectionProduct_all.value` flipped from the correct `"APX NEXT ENHANCED"`
to the wrong, title-cased `"APX NEXT Enhanced"` — a live comparison of two JSON payload
snapshots from the same conversation caught the discrepancy.

**Where in the flow:** `src/aryx/cpq/bml.py` — `_parse_branches()` / `_branch_values()` /
`_BOOL_RETURN_RE`, the Tier-1 deterministic script evaluator used by
`apply_recommendation_rules()` for script-backed recommendations.

**Root cause:** The real script "Default APX Next Enhanced based on HW version" is:
```
if (hWVersion_astro == "NEXT ENHANCED LTE PLUS 5G") {
    //returnVal = "APX NEXT Enhanced";
    returnVal = "APX NEXT ENHANCED";
}
```
Every Tier-1 regex scanner searched the **raw** script text, comments included — so the
commented-out (wrong-cased) line matched *before* the real, live statement right after it.
Not specific to this attribute: any script with a commented-out scratch line ahead of its
real statement hit the same bug.

**Fix:** Added `_strip_line_comments()` — strips `//` to end-of-line while respecting quoted
string literals (so a `"http://..."` value survives) — applied once at `_parse_branches`'
entry so every downstream scan (bodies/conditions sliced from that same text) sees
comment-free source. (commit `0464d19`)

---

## 4. Tier-1 silently truncating a string-concatenation script to garbage

**Problem statement:** SVX's `sVXTAAKitHelpText_viSoln` ("SVX TAA Kit Help Text") always
showed the same broken value: `<model style=` — clearly truncated HTML, not real help text.

**Where in the flow:** `src/aryx/cpq/bml.py` — `_branch_values()`, `_ASSIGN_RE`.

**Root cause:** The real script builds its HTML via string concatenation:
```
returnval ="<model style="+"\""+"color:#2B8838; font-size:9pt;"+"\""+">"+"<b>"+link+"</b></model>";
```
`_ASSIGN_RE`'s alternation only accepts `"literal"|"literal"` segments joined by `|` — it
silently stopped matching at the first `+` and returned just the first quoted fragment as if
it were the complete, intentional value.

**Fix:** `_branch_values()` now checks whether the right-hand side continues past the
matched literal list (i.e. the next non-whitespace character is `+`) and bails to `None`
(unparseable → falls through to Tier-2/unknown) instead of returning the truncated fragment.
Logs a `WARNING` (not `INFO` — this deployment's root logger is configured at `WARNING`,
confirmed live, so `INFO` was silently dropped) so this class of script shows up in
production logs going forward. (commit `c94b718`)

---

## 5. Cascade notice read as internal shorthand, not plain English

**Problem statement:** After a change that invalidates dependents, the notice read:
*"This invalidated: Product — re-evaluating."* — mechanical, not something a sales rep could
act on or necessarily understand.

**Where in the flow:** `src/aryx/api/ask_api.py` — `_handle_cascade()`, the `cascade_note`
construction.

**Root cause:** `cascade_note` was built by directly joining raw `display_label`s with no
natural-language framing at all — `f" This invalidated: *{', '.join(dependent_labels)}* —
re-evaluating."`.

**Fix:** Rewrote as a plain-English sentence naming WHY (the change just made) and WHAT is
happening (dependents recalculating), singular/plural phrased so one dependent doesn't read
oddly as a list: *"Because **Hardware Version** changed, **Product** depends on it and needs
a fresh value — recalculating now."* (commit `c94b718`)

---

## 6. "Associated Options" summary showing too many, low-value attributes

**Problem statement:** As more real rules got correctly wired up this session (items 1–4
above, plus earlier array-set/dedup fixes), the "Associated Options" section of the chat
summary grew to ~24–32 items per quote — many of them internal/administrative fields
(Order Type, Validation Org, Software Release) nobody would read out loud to a customer.
Product decision (confirmed via user feedback after observing the growth live): narrow this
to genuinely business-relevant, customer-facing configuration choices only.

**Where in the flow:** `src/aryx/cpq/engine.py` — `CpqEngine._filled_summary_triples()`
(feeds `filled_summary_pairs()`, `categorized_summary_groups()`, and the narrated summary
built in `ask_api.py::_cpq_summary_text()`).

**Root cause / iteration:**
- **First pass:** `rule_governed_ids()` is a *static* set — "this attribute is targeted by
  at least one loaded rule anywhere in the catalog" — regardless of whether that rule's
  condition actually held this turn. Narrowed to `filled_source` values that represent a
  genuine per-turn decision (`rule`, `country_derived`, `user`, `hint`, `cascade`,
  `cascade-dependent`), excluding bland `default`/`optional`/`auto` fills.
- **Still too broad:** this APX NEXT catalog has hundreds of real rules, so *most* of its
  catalog-wide defaults (Region, Housing, Battery Type, Wireless Carrier, ...) genuinely do
  have a rule targeting them and passed the new filter — "rule fired" and "worth telling a
  sales rep about" turned out not to be the same thing for this catalog.

**Fix:** Added a curated `_ASSOCIATED_OPTIONS_KEY_FRAGMENTS` allowlist (frequency, band,
antenna, battery, carrier, keypad, housing, channel, hardware, video, mount, training,
wireless, display, knob, packaging, spare, end-user-type, coverage, accidental-damage, RSM,
region, color, voltage, certification, connector, cable, earpiece, case, bracket,
screen-protector, manual, charger, power) applied *only* to the catch-all "Associated
Options" fallback category — Product Name/Service Plan/Quantity & Duration stay unaffected
(already narrow by category definition), and the full-detail `beautify_rows`/`beautify_text`
table view (`rule_governed_ids=None`) is untouched, still shows every filled attribute.
(commit `c94b718`, extended same-session)

---

## Verification discipline

Every fix above was: (1) reproduced live against real workspace-19 Postgres/FalkorDB data
before writing any code, (2) covered by new unit tests (`test_cpq_bml_comments.py`,
`test_cpq_label_collision.py`, `test_cpq_summary_active_sources.py`), (3) re-verified live
by rebuilding the Docker container (`docker compose build api && up -d --force-recreate api`)
and replaying the exact failing conversation turns against `POST /ask`, never assumed correct
from code reading alone.
