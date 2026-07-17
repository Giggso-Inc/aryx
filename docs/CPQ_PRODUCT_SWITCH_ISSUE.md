# CPQ Issues — live-testing findings (workspace 14)

Workspace: 14 (real multi-catalog data — APX Next + SVX Video RSM)

Issues found via live testing, all fully root-caused:

| # | Issue | Status |
|---|---|---|
| 1 | Product list not narrowed by product family | **FIXED (mitigated)** — oversized lists now ask for the exact name instead of dumping; underlying narrowing still impossible (data gap) |
| 2 | Summarizer shows raw "Key decisions" list with `(none)` lines | Root-caused — env issue (403) + small fixable filter gap |
| 3 | "SVX video body camera" doesn't trigger a product switch | Root-caused — data gap (no marketing-name aliases), documented limitation |
| 4 | Mid-session switch not detected for family mentions ("Quote APX Next…") | **FIXED** — alias-map detection over each catalog's own `bm_catalog` tree |
| 5 | Real CPQ API rejects SVX payload: 5 attrs "invalid payload" | **FIXED (locally verified)** — `set_type=2` excluded from payload + menu shape for menu-backed numerics; real-API re-submission pending |
| 6 | Menu answer resembling another family's tree name hijacked by "did you mean" (e.g. "APX 6500" while Product is pending) | **FIXED** — answer-over-switch precedence; switch detection moved after attrs load, defers to a valid pending-attr answer |
| 7 | "yes" to a stateless "did you mean…?" hint approved/submitted the current quote | **FIXED** — suggestion prompt now arms a pending state (single candidate → `confirm_switch`; several → new `suggest_switch`) |
| 8 | Payload root key was `configAttributes`; integration contract expects `configData` | **FIXED** — root key renamed in `build_payload`, tests/docs updated, live-verified (84-attr APX payload now under `configData`) |
| 9 | "Bill Country" (`CRM_BILL_COUNTRY`, a CRM-integration field) asked as a question after a product switch | **FIXED** — noise vars never pend; plus follow-up: a preserved country now carries over as a hint, so UDC isn't re-asked after a switch |

---

# Issue 1 — Product list not narrowed by product family (`videoSolutions_BOM`)

Status: **FIXED (mitigated).** The user-facing symptom — a ~380-line
unusable dump — is resolved: `next_question_prompt` now caps enumeration at
`_MAX_ENUMERATED_OPTIONS` (25); an oversized attr asks for the exact name
with 3 examples instead ("**Product** has 325 available options — too many
to list here. Please provide the exact name…"). Threshold-based and
attr-agnostic — it also fixed the ~250-entry country dump. Verified live
(workspace 14) and covered by `tests/test_cpq_prompt_cap.py` (5 tests).
The UNDERLYING narrowing (restricting those 325 to family-relevant models)
remains impossible with current data — see the analysis below; the product
list in each catalog genuinely contains zero SVX items, so for SVX quotes
the Product attr has no correct answer (cross-attribute redirect + optional
"skip" were proposed as a follow-up and are not yet built).

## 1. Reported symptom

After selecting product family `videoSolutions_BOM` and country `United
States`, the "Product — choose one" list shows ~380 models spanning every
Motorola product family in the tenant (APX, XiR, DGP, SLR, MTP, VZ, TLKR,
etc.) instead of only SVX-relevant models.

Reproduction (workspace 14):

```
quote me a videoSolution
> To start the configuration I need the product family (e.g., aSTRO25_bom, videoSolutions_BOM). Could you provide that?
videoSolutions_BOM
> Thanks — and what's the destination country for this quote?
United States
> Product — choose one:
  1. APX 6500
  2. APX 6500Li
  3. APX 5500
  4. VX-451
  ... (~380 total, every family mixed together)
```

## 2. First hypothesis (ruled out) — cross-catalog graph leak

Initial suspicion: `reader.neighbors()` has no catalog-prefix awareness,
and `productSelectionProduct_all` (native id `39427019`) has separate
`BmMenuItem` sets per catalog sharing that native id — a workspace with
2+ catalogs could merge neighbor lists across them.

This is a **real, separately-confirmed bug** (see
`docs/CPQ_MULTI_CATALOG_ASK_FLOW_BUGS_PLAN.md` Bug 1/3b), and a fix was
applied in `src/aryx/cpq/engine.py` (catalog-prefix filter on the
menu-item neighbor loop, commit `50ad047`), with its own regression test
in `tests/test_cpq_engine_catalog_scope.py`.

**Live re-test after deploying the fix showed the symptom above is
unchanged** — direct graph inspection confirmed `productSelectionProduct_all`'s
328 neighbors in workspace 14 were already all correctly typed to the SVX
catalog prefix. There was no cross-catalog leak for this attribute in this
workspace. The fix is valid and kept, but it is not the cause of this
symptom.

## 3. Actual root cause — a BML dependency chain with no source data

The only rule capable of narrowing `productSelectionProduct_all`'s options
is a 3-step chain:

1. **Constraint script** — `"Restrict Product Selection Based on Package
   Choice String"` narrows the Product options based on a computed
   variable `packageChoiceString`.
2. **Recommendation script** — `"Set Package Choice String"` computes
   `packageChoiceString` by splitting `packageNumber` (delimiter
   `^:1:^`) into `packageIDNumber_contracts`, `packageRevision`,
   `packageRegion` — but only runs `if(not isnull(packageNumber) and
   packageNumber <> "")`.
3. **`packageNumber`** (order 3, required=False) has **zero menu-item
   options anywhere in the ingested XML** — its only graph neighbor is a
   `BmConfigZipCache` metadata entity, not a picklist.

The variable names in step 2 (`REGION`, `PACKAGE ID`, `REVISION`) indicate
`packageNumber` is a **contract/price-book package identifier**, not a
product/family selector — i.e. the source catalog narrows this Product
list by *which pricing package/contract the quote is under*, not by which
product family the customer asked for. That data lives in BigMachines'
account/contract layer and is never present in the ingested product-catalog
XML, so Aryx has no way to fill it.

Since `packageNumber` can never be filled from the data Aryx has, the
whole chain stays empty end to end, and `apply_constraint_rules` correctly
reports "no active constraint" on the Product attribute — the engine is
behaving correctly given its inputs; the input needed to narrow this list
does not exist in the ingested catalog.

## 4. Why this can't be fixed as-is

There is no hardcode-free way to narrow the Product list for this catalog:

- Fabricating a value for `packageNumber`, or a hand-picked options list
  for it, would require data Aryx doesn't have and would be exactly the
  kind of hardcoding this project has consistently avoided.
- The narrowing signal genuinely isn't "product family" in this catalog's
  own design — choosing `videoSolutions_BOM` was never going to narrow
  this attribute, because the source rule never keys off family at all.

## 5. Options going forward (undecided)

- **A.** Accept as a known, documented limitation — no further action.
- **B.** Model `packageNumber` as a new user-facing input, which first
  requires sourcing what its legitimate values actually are (outside this
  catalog's own XML export — likely account/contract data Aryx doesn't
  currently ingest).
- **C.** Investigate whether a different, catalog-agnostic signal (e.g.
  the already-resolved `resolved_catalog_prefix`) could substitute for
  family-based narrowing specifically for this attribute — would need
  confirmation this doesn't contradict the source catalog's own intended
  behavior (contract-based, not family-based, narrowing).

No option has been selected yet.

## 6. References

- Full investigation trace and test results: `docs/CPQ_PRODUCT_SWITCH_TESTING_REPORT.md` §7/§7.1
- Related, previously-deferred cross-catalog bugs: `docs/CPQ_MULTI_CATALOG_ASK_FLOW_BUGS_PLAN.md`
- Fix commit: `50ad047` on `fix/cpq-implicit-product-switch-detection`
- New regression test: `tests/test_cpq_engine_catalog_scope.py`

---

# Issue 2 — Summarizer shows raw "Key decisions" bullet list with `(none)` lines

Status: **root-caused — primary cause is a local-environment LLM auth failure
(403), not a code defect; a secondary, genuinely fixable filter gap lets
`(none)` placeholder lines through**

## 1. Reported symptom

After "Quote APX Next Enhanced radios for a US customer" completes, the
completion message shows a long raw list:

```
Configuration complete for aPXNext_BOM.

Key decisions:
Region → NA
Frequency Bands → 700/800 MHz
...
promotionArrayController → (none)
promotionId → (none)
Frequency Band → (none)
Promotion → (none)
...  (~70 lines, ~25 of them "(none)")
```

instead of the expected short prose summary.

## 2. Root cause (a) — narrator LLM call fails with HTTP 403 locally

The prose summarizer IS present in this build (`_cpq_summary_text` in
`src/aryx/api/ask_api.py`, from commit `8238e93` — contained in this
branch). It narrates via `llm_runtime.chat("menial", ...)` and, **by
design**, catches any failure and falls back to the deterministic bullet
list `render_filled_summary()` — the `**Key decisions:**` format — so the
CPQ flow never blocks on the narrator.

Reproduced directly inside the running local container: the "menial" LLM
call fails with **HTTP Error 403: Forbidden** (same auth failure previously
observed on the Q&A synthesis path in this environment). So the raw list is
the designed fallback firing on every completion in this environment. In an
environment with working LLM credentials the prose summary is produced.
The failure is only logged at DEBUG level, which is why nothing appears in
default container logs — worth raising to WARNING so this is visible.

## 3. Root cause (b) — `(none)` placeholder lines survive the low-signal filter

The `(none)` values come from optional, unconstrained multi-selects that
`auto_fill` legitimately auto-assigns as empty (`display_filled[vn] =
"(none)"`, `src/aryx/cpq/engine.py` ~line 3032 — mirrors real Oracle CPQ
behavior for optional checkbox lists). The summary filter
`_is_summary_excluded` drops booleans, warranty lines, durations,
secondary/product attrs — but has **no rule for the `(none)` placeholder**,
so ~25 empty lines survive into both the narrator's input and the fallback
bullet list.

## 4. Fix

- **(a) 403:** environment/credentials issue, not code — fix the LLM
  provider configuration for the local deployment. Optionally raise the
  narration-failure log from DEBUG to WARNING so the fallback is visible.
- **(b) `(none)` filter:** one-line addition to `_is_summary_excluded`
  (exclude values equal to the empty-multi-select placeholder). Small,
  safe, testable. **Not yet applied — pending decision.**

---

# Issue 3 — "Quote a SVX video body camera" does not trigger a product switch

Status: **root-caused — data gap (no marketing-name aliases in the ingested
XML); same class of limitation as Issue 1, already documented in the
testing report §6**

## 1. Reported symptom

With a completed `aPXNext_BOM` session (`awaiting_approval`), the message
"Quote a SVX video body camera for a US customer" did NOT offer a switch to
`videoSolutions_BOM`. Instead the engine replied "I couldn't match that to
a valid option for Ultimate Destination Country" with the full country
list; after answering "United states", it re-opened Product with the full
unconstrained ~380-item list.

## 2. Root cause — phrasing shares almost nothing with any ingested name

Measured with the real fuzzy scorer (`CpqEngine._fuzzy_score_candidates`)
against the real ingested names:

| Candidate | Score | Threshold needed |
|---|---|---|
| `videoSolutions_BOM` | **0.485** | 0.82 confirm / 0.65 suggest |
| `aSTRO25_bom` | 0.421 | — |
| "Svx Video Remote Speaker Microphone" (catalog display name) | **0.400** | — |

"SVX video body camera" is a marketing/colloquial description: the only
overlapping tokens with ANY ingested name are "svx video". "Body camera"
appears nowhere in the ingested XML — not in the BOM identifier, not in the
BmPrdFamily display name. No matcher (fuzzy or otherwise) can bridge that
without an external alias source. Even alias-matching against the catalog
display name (a plausible enhancement) would NOT have caught this phrasing
(0.400).

## 3. Cascade — what the miss caused downstream

1. No switch detected → message fell through to the awaiting-approval
   "describe any changes" path.
2. That path extracted "US" as a country hint, tried to apply the whole
   sentence as an Ultimate Destination Country answer, failed → re-showed
   the full country options list.
3. "United states" was then accepted as a country **change** → rules
   re-evaluated → Product re-opened, showing the full unconstrained list —
   which is **Issue 1's root cause again**, this time in the APX catalog
   (each catalog carries the identical full-portfolio master list on
   `productSelectionProduct_all`, and the `packageNumber` narrowing chain
   never resolves there either).

## 4. Why this can't be fixed as-is

Bridging "SVX video body camera" → `videoSolutions_BOM` requires a
marketing-name/alias mapping that does not exist anywhere in the ingested
catalog XML — the same class of data gap as Issue 1's `packageNumber`.
Hardcoding an alias list would violate the project's no-hardcoding rule.
Possible future directions (undecided): ingest an external product-alias
source, or add a token-level overlap heuristic ("svx" appears in exactly
one catalog's display name) — the latter needs careful false-positive
analysis before being considered.

Note: Issue 4's alias map (below) narrows this gap but does not close it —
the tree names it adds ("SVX Video Remote Speaker Microphone", "vX650_BOM",
"mobile_BOM") still score only ~0.4 against "SVX video body camera";
"body camera" appears nowhere in the ingested names.

---

# Issue 4 — Mid-session switch not detected for family mentions ("Quote APX Next Enhanced radios")

Status: **FIXED** — verified live (workspace 14) and unit-tested.

## 1. Reported symptom

With an SVX (`videoSolutions_BOM`) session in progress, the message
"Quote APX Next Enhanced radios for a US customer" did NOT offer a switch.
It fell through to the change-request path, was misread as an Ultimate
Destination Country answer ("I couldn't match that…"), and the follow-up
"United States" landed back in the same SVX configuration — the switch to
APX never happened.

## 2. Root cause

`detect_product_mention` matched only against `_ingested_product_names` —
the two `BmPrdFamily` identifiers (`aSTRO25_bom`, `videoSolutions_BOM`),
internal BOM names a client rarely types. "APX Next" scores ~0.42 against
`aSTRO25_bom`, below every threshold. And a raw PRODUCT mention can never
discriminate the catalog anyway, because both XMLs carry the identical
flat product list (Issue 1's finding — "Both the xml have the same
product"). The signal that CAN discriminate is the `bm_catalog` tree:
confirmed live that each export carries ONLY its own tree —
`ApxNextConfigBmCatalog` holds `aSTRODevices_BOM` / `aPXNext_BOM`
("APX™ NEXT") / `aPXN70_BOM` ("APX™ N70"); the SVX export holds only
`mobile_BOM` / `vX650_BOM` ("SVX Video Remote Speaker Microphone").

## 3. Fix (shipped)

New `CpqEngine.ingested_product_alias_map(reader, workspace_id)` — builds
{alias → owning family} from each catalog's own `BmPrdFamily` +
`BmCatalog` tree (variable names AND display names). An alias appearing
under more than one family is dropped entirely (ambiguous — never guess).
`detect_product_mention` and `suggest_product_candidates` now match over
these aliases and resolve to the FAMILY name, which the existing
confirm-switch flow anchors on. Fully data-driven — a newly ingested
catalog's tree names are recognised with no code change.

Live verification (workspace 14): mid-SVX-session, "Quote APX Next
Enhanced radios for a US customer" → "It looks like you're asking about
**aSTRO25_bom** … Switch? (yes/no)" → "yes" → switch completed, country
United States preserved (re-validated against the APX catalog via the real
rule cascade), APX config loaded.

Tests: `test_tree_product_line_mention_triggers_family_switch`,
`test_tree_name_of_current_family_is_not_a_switch`,
`test_shared_tree_alias_is_dropped_never_guessed`,
`test_alias_map_maps_tree_names_to_family` (tests/test_cpq_product_switch.py).

---

# Issue 5 — Real CPQ API rejects SVX payload: 5 attrs "invalid payload"

Status: **FIXED — implemented and locally verified against both catalogs;
real-API re-submission still pending.**

Local verification (containerized service, workspace 14):
- **APX Next**: full quote re-run pre/post fix — generated payload
  **byte-identical** (84 attrs, zero change), confirming no APX impact.
- **videoSolutions_BOM**: full quote re-run — payload diff shows EXACTLY
  the intended change and nothing else: the 4 `set_type=2` attrs removed
  (21 → 17 attrs), `bWCNumberOfRefreshes_viSoln` reshaped `1` →
  `{"value": "1", "displayValue": "1"}`.
- Unit coverage: `tests/test_cpq_payload_shapes.py` (5 tests — set_type=2
  excluded for single AND multi, menu-backed integer uses menu shape,
  non-menu integer stays bare, set_type 1/3/"" menus unchanged).

## 1. Reported symptom

Submitting a completed `videoSolutions_BOM` configuration to the real CPQ
BOM API returned:

```
"o:errorDetails": [
  {"title": "Attribute modelSelectionSelectModel_viSoln has an invalid payload."},
  {"title": "Attribute archeType_viSoln has an invalid payload."},
  {"title": "Attribute serviceType_viSoln has an invalid payload."},
  {"title": "Attribute dMSDuration_viSoln has an invalid payload."},
  {"title": "Attribute bWCNumberOfRefreshes_viSoln has an invalid payload."}
],
"title": "Invalid payload."
```

APX Next submissions with the same serializer had previously been accepted.

## 2. Root cause — two distinct defects (confirmed against live DB metadata)

**(a) `set_type=2` transient attrs included in the payload (4 of the 5).**
Every ACCEPTED menu attr in that payload (`validationOrg`,
`ultimateDestinationCountry`, `mountType_viSoln`, `billingOptions_viSoln`)
is `set_type=1`; all four rejected menu attrs are `set_type=2`. The values
sent were verified as exact matches of real menu `item_value`s, and the
wrapper shape (`{"value","displayValue"}`) is identical to the accepted
attrs — so content and shape are fine; INCLUSION is the defect. What
`set_type=2` means is visible in the APX catalog's own data: its 15 such
attrs are transient UI/action-layer fields (`_price_book_var_name`,
`testPager2`, `mergePackage`, `update`, `clearPackageJson`,
`saveChanges_RecommendedConfiguration_astro`, …) — not transaction-line
attributes. APX never tripped this because its `set_type=2` attrs are
noise-shaped and never reach the payload; SVX places real menus
(model-selection panel: Select Model, Solution Type, Service Type, DMS
Duration) on that layer, so they landed in the payload and were rejected.

**(b) Menu-backed numeric misserialized (the 5th).**
`bWCNumberOfRefreshes_viSoln` has real menu items (`"1"`, `"2"`, `"3"`)
but `data_type=3`; `classify_select_type` lets `data_type=3 → integer`
win before considering options, so `build_payload` sent bare `1` instead
of the menu shape `{"value":"1","displayValue":"1"}`.

## 3. Fix (approved, pending implementation)

1. `ConfigAttr` carries `set_type`; `build_payload` excludes `set_type=2`
   attrs from `configAttributes` (same treatment as `hide_in_trans` —
   keyed on BM's own per-attribute metadata, no attribute names in code).
   They still drive rules and conversation; they just aren't POSTed.
2. Menu shape wins over numeric `data_type` when the attr has menu
   options.

## 4. APX Next impact — verified none

- APX has **zero** menu-backed `data_type=3` attrs, so fix (b) cannot
  change any APX payload (`dmsDuration_astro` is `data_type=3` with NO
  menu — stays a bare number, as already accepted live).
- APX's 15 `set_type=2` attrs are transient fields already excluded by
  the existing noise filters or never filled — fix (a) is a no-op or a
  correct removal of a stray transient for APX.
- Verification plan includes an APX payload diff (before/after fix,
  expected identical) plus a real re-submission of the SVX quote.
- **Verified**: APX diff came back byte-identical (see status block above).

---

# Issue 6 — Menu answer hijacked by "did you mean" when it resembles another family's tree name

Status: **FIXED — implemented, unit-tested, live-verified.**

Shipped fix: switch/suggest detection moved from Step 1 to AFTER Step 2
loads the catalog's attrs, gated by answer-over-switch precedence — if the
message matches one of the currently-pending attribute's OPTIONS
(`apply_answer`, options-backed tiers only; the free-text tier is
deliberately not consulted, since it would classify any text as an answer
while a free-text attr is pending), it is treated as an answer and switch
detection is skipped entirely. Side benefit: ordinary answer turns now
skip the alias-inventory fetch completely (extends the P2 optimization).
The country anchor prompt moved with it, so a switch mention sent while
the country is still unanswered is detected rather than swallowed.

Live verification (workspace 14): "APX 6500" with Product pending now
locks `APX6500` and completes the configuration (previously returned "did
you mean **aSTRO25_bom**?"); immediately after, "Quote APX Next Enhanced
radios for a US customer" on the same session still correctly triggers the
confirm-switch prompt — Issue 4's behavior is intact.

Tests (tests/test_cpq_product_switch.py, Scenario 12):
`test_menu_answer_resembling_other_family_alias_is_not_hijacked`,
`test_menu_answer_containing_alias_substring_still_locks` (the stronger
exact-substring tier: "APX NEXT Single Band" is a real option containing
the alias "APX NEXT"),
`test_non_answer_switch_mention_still_detected_with_pending_menu`.

---

# Issue 7 — "yes" to a stateless "did you mean…?" hint approved the current quote

Status: **FIXED — implemented, unit-tested, live-verified.**

## 1. Reported symptom (live transcript)

With a completed `aSTRO25_bom` session (`awaiting_approval`), "quote me a
videoSolution" produced the mid-band hint "did you mean one of:
**videoSolutions_BOM**?". Replying **"yes"** did NOT switch — it emitted
the full aSTRO25_bom BOM payload: the reply was consumed by the
awaiting-approval handler as quote **approval**. The user asked about
switching products; the system responded by approving the very quote they
were trying to leave. Accidental-submission hazard, not just UX confusion.

## 2. Root cause

The suggestion prompt was **stateless** — unlike the confirm-switch
prompt, it set no `pending_anchor`, so the next turn's reply fell through
to whatever handler matched first. In `awaiting_approval`, an affirmative
matches the approval gate. (Related: replying `aSTRO25_bom` to the hint
got the generic "didn't quite catch that" nudge — same statelessness.)

## 3. Fix (shipped)

- **One candidate** (the overwhelmingly common case): the hint now arms
  the EXISTING `confirm_switch` state — "did you mean **X**? Switching
  would discard the current configuration. (yes/no)" — so yes/no (and the
  country re-validation) flow through the proven gate.
- **Several candidates**: new `suggest_switch` pending state +
  `CpqSession.pending_switch_candidates`; a bare "yes" re-prompts with the
  list (can't guess between 2+), "no" continues with the current product,
  and a name reply falls through to normal detection → `confirm_switch`.
- Bonus: replying to a confirm prompt with the offered product's own name
  now counts as affirmative (previously it counted as a decline).

Live verification (workspace 14, exact transcript replay): completed APX
quote → "quote me a videoSolution" → confirm prompt armed
(`pending_switch_product=videoSolutions_BOM`) → "yes" → switched to
`videoSolutions_BOM`, country preserved, **no payload emitted**, config
continues.

Tests (Scenario 13):
`test_single_suggestion_sets_confirm_state_so_yes_switches_not_approves`,
`test_multi_suggestion_yes_reprompts_instead_of_guessing`,
`test_multi_suggestion_no_continues_with_current_product`,
`test_multi_suggestion_name_reply_routes_into_confirm_flow`,
`test_confirm_switch_accepts_the_product_name_as_affirmative`.

---

# Issue 8 — Payload root key: `configAttributes` vs `configData`

Status: **FIXED — user confirmed the actual integration contract expects
`configData`; root key renamed in `build_payload` (the single source of
the literal), all test/doc references updated, and live-verified: the
84-attribute APX payload now renders under `configData`. §3's open
question (why per-attribute errors came back despite the old key) remains
unanswered but moot — the next real submission will validate the new
envelope directly.**

## 1. Question raised

Generated payloads are wrapped as `{"configAttributes": {...}}`; the
integration contract for the real CPQ endpoint reportedly expects
`{"configData": {...}}`.

## 2. Root cause of the current key

- The key exists in exactly ONE place: `build_payload`'s final
  `return {"configAttributes": out}` (`src/aryx/cpq/engine.py`).
- It was adopted from the internal payload-contract analysis
  (`docs/CPQ_RULE_TOOL_FLOW_PLAN.md` §8/§15b), which validated the
  per-attribute SHAPES (menu wrapper, bare booleans, multi-select items,
  hide_in_trans exclusions) against real API behavior — but the ENVELOPE
  key itself was an assumption. `configData` appears nowhere in the repo.
- Nothing in this repo submits to Oracle CPQ (the web app passes
  `cpq_payload` through opaquely) — external submissions are the first
  true end-to-end test the envelope has had.

## 3. Contradicting evidence to resolve before renaming

The live SVX rejection (Issue 5) returned **per-attribute** errors
("Attribute modelSelectionSelectModel_viSoln has an invalid payload"),
meaning that endpoint parsed the submitted envelope and located our
attributes. Consistent with any of: (a) the endpoint accepting both keys,
(b) the submission tooling re-wrapping our JSON into the real envelope
before POSTing, (c) per-attribute validation running regardless of the
envelope key. Which one it is determines whether the rename is required,
optional, or a no-op.

## 4. Fix (pending confirmation)

One-line change in `build_payload` (plus tests/docs referencing the key).
To be applied once the real integration spec / submission path confirms
`configData` is the required root — then re-verify both catalogs' payloads
and a real submission.

---

# Issue 9 — CRM-integration field ("Bill Country") asked as a question

Status: **FIXED — implemented, unit-tested, live-verified (including a
follow-up gap the fix uncovered).**

Shipped:
1. **Noise vars never pend** — `auto_fill`'s pending gate now requires
   `not _is_noise_var(vn)` even for decision-promoted attrs. Tests:
   `tests/test_cpq_noise_pending.py` (CRM_BILL_COUNTRY/CRM_SHIP_COUNTRY
   never asked; `ultimateDestinationCountry` still asked).
2. **Follow-up found the moment Bill Country stopped masking it:** the
   switch-preserved, re-validated country never re-entered the hint
   stream, so the new catalog's `ultimateDestinationCountry` was re-asked
   anyway. `_run_cpq_turn` now injects `hints["country"] =
   session.country` on any turn where a country is already confirmed and
   the message carries none — the preserved country fills country-shaped
   attrs exactly as the original hint did on its own turn.

Live verification (workspace 14, full replay): completed APX quote →
"quote me a videoSolution" → confirm → switch completes; the next
question is the genuine Product attr — no "Bill Country", and
`ultimateDestinationCountry` auto-filled `US` from the preserved country
without re-asking.

## 1. Reported symptom

Immediately after a confirmed product switch to `videoSolutions_BOM`, the
first question asked was "**Bill Country** — Please provide a value."
The user's expectation was that bill country should follow the destination
country; the real answer is stronger — it should never be asked at all.

## 2. Root cause

"Bill Country" is `CRM_BILL_COUNTRY` — a CRM-integration field (billing
address from the account system), not a quote input. `build_payload`
already excludes it (`_is_noise_var`: fully-uppercase `CRM_` head), so any
answer the user gives is silently dropped — the question is pure waste.

It gets asked because of two stacked conditions in `auto_fill`'s pending
gate (`engine.py` ~3181, `elif attr.options or is_decision_attr:`):

1. The decision-required promotion matches the "country" fragment inside
   `CRM_BILL_COUNTRY`, overriding the very next comment's intent ("CRM/
   system fields with no options ... are skipped — filled by integration").
   Noise vars WITH menus already have a no-ask guard (auto-default);
   noise vars WITHOUT menus slip through when decision-promoted.
2. It never surfaced on normal first turns because a country hint in the
   opening message ("...for a US customer") fills it before the gate. A
   switch turn's message ("videoSolutions_BOM") carries no country hint,
   so the field survives to the gate and, with a low order number, becomes
   the first question.

## 3. Fix (designed, not yet applied)

One condition: noise vars never pend —
`elif not self._is_noise_var(vn) and (attr.options or is_decision_attr):`.
Consistent with the payload exclusion and the existing menu-backed
noise-var guard (Bug 2 precedent).

## 4. Impact analysis

- **Payload: zero change.** Noise vars are already excluded from
  `configData` unconditionally — filled or not, they never appear.
- **Rule evaluation: zero change, verified.** No BML function script in
  either catalog references `CRM_BILL_*` or `CRM_SHIP_*` (checked live:
  0 matches in workspace 14's BmFunction entities), so leaving them
  unfilled cannot alter any hiding/recommendation/constraint outcome.
- **Conversation: strictly fewer bogus questions.** Any
  integration-shaped field with a decision-key fragment in its name
  (`CRM_BILL_COUNTRY`, `CRM_SHIP_COUNTRY`, equivalents in future
  catalogs) stops being asked. Turns that fill them via a country hint
  (normal first turns) are unchanged — the hint path runs before the gate
  and stays as-is.
- **Blast radius:** the guard keys on the existing `_is_noise_var`
  convention (underscore-prefixed or fully-uppercase integration prefix),
  the same predicate the payload builder trusts — no new classification
  logic, no attribute names in code. A genuine ask-able attr like
  `ultimateDestinationCountry` (lowercase head) is untouched.
- **Risk:** if some future catalog had a REAL user-input attr whose name
  matches the noise convention AND has no menu options, it would stop
  being asked — but such an attr would already be excluded from the
  payload today, so it was already broken in a worse way (asked, then
  answer dropped).
