# CPQ XML ingestion — display names (locale-wrapper folding) — plan

Date: 2026-10-05 · Branch: `fix/cpq-xml-locale-wrapper-names-2026-10-05` (from `origin/dev_oci` @ `8bdb1c8e`)
Status: **plan only — no code yet**

## Problem

On the raw-graph CPQ XML path (`cpq_ingestion_raw_graph`), Oracle CPQ display
names never reach the entity that owns them. Ask therefore shows numeric CPQ
ids / placeholder values instead of names.

Confirmed live on workspace 1126 (`shay::APX_NEXT`, ingested 2026-10-05 20:21 UTC
by the deployed `origin/dev_oci` build, i.e. *after* PR #435):

| Entity | `name` attr | Graph vertex name (what Ask shows) | Where the real name lives |
|---|---|---|---|
| `…BmPrdFamily` | — | `17691416877` | child `…Label` → `{"en": "ASTRO®25_BOM"}`; own `variable_name: aSTRO25_bom` |
| `…BmCatalog` (model) | — | `17691417058` | child `…BmName` → `{"en": "APX™ NEXT"}`; own `bm_variable_name: aPXNext_BOM` |
| `…BmCatalog` (model) | — | `18282054621` | child `…BmName` → `{"en": "APX™ N70"}`; own `bm_variable_name: aPXN70_BOM` |
| `…BmConfigAttr` (×430) | — (0 of 430) | `0` — only **2 distinct names across 430 attrs** | child `…Name` → `{"en": "BoolContinue1"}` |

Also left as separate child entities instead of attributes: `…Description`
(798 nodes, mixed `{"text": …}` / `{"en": …}` shapes) and `…DefaultValue`.

User-visible symptoms (Ask, workspace 1126):
- "pick a product family: 1. **17691416877**"
- "did you want the **17691417058** or **18282054621** model?"
- "Which attribute did you mean? 1. **0 (bool Continue1)** 2. **0 (bool Continue2)** …"

## Root cause — and was it intentional? (PR archaeology)

Not a deliberate design choice; a capability the old path had was never ported.

- **Old path `_xml_to_csvs`** (`pipeline/doc_discovery/doc_discovery_xml.py`)
  explicitly treats locale wrappers (`<name><en>…</en></name>`) as *values*,
  never entity types (`_LOCALE_TAGS`, `_extract_field`: prefer `<en>`, else
  first non-empty locale) and flattens them onto the parent row.
- **PR #400** (raw graph → curated graph bridge, 2026-09-30) is deliberately
  "one node per element, no classification". It does not mention multilingual
  fields or display names, and did not port the locale rule.
- **Structural-leaf fold** (PR #429 follow-ups / `CPQ_XML_CONFIRM_RESOLVE_PERFORMANCE_ISSUES_2026-10-04.md` §1 Tier 1)
  was a **performance** change, validated on `<Record><id/><Name/></Record>`.
  It folds only one level: `<en>` (a true leaf) folds onto `<label>`, but
  `<label>` itself had a child so it is never classified as a leaf and stays
  an entity. It also requires *every* node of a tag to be leaf-shaped, so a
  mixed tag like `<description>` (sometimes text, sometimes `<en>`) never folds.
- **PR #435** (type-prefix fix) lists "family display name being a numeric ID"
  as explicitly **out of scope**, pre-existing in both pipelines — true for
  Ask's `name`-only read, but the old path at least kept the value on the parent.

Why the vertex name is a number / `0`: with no name-ish key on the entity,
`oracle_graph_store_helpers._display_name` falls through `_NAME_KEYS`
(`name`, `full_name`, `title`, `label`, …) to the first short string property
(`id` → `17691416877`; `qty_attr_id` → `0`).

## Decision (Andie 🎭 Drama session, 2026-10-05)

Fix at ingestion (one place, every consumer benefits) + backfill already-ingested
workspaces. Read-time-only fallback rejected (would need fallbacks in 14+
`_catalog_prefix` / name consumers and hides the data defect).

User decision: **Ask shows the human label** (e.g. "APX™ NEXT"); matching keeps
working on the variable name too.

## Design

### 1. Locale-wrapper fold — second pass in `raw_graph/structural_leaf.py`

After the existing `fold_structural_leaf_tags` pass, run
`fold_value_wrapper_tags(edges, by_tag, …)`:

- A node is **value-shaped** when (after pass 1) it has no remaining children in
  `by_tag` and every property key is `text` or a locale key.
- A tag folds when **all** its nodes are value-shaped (same all-or-nothing rule
  as pass 1, so a tag that is sometimes a real record is never half-folded).
- Folded value = `en`, else first non-empty locale (in `_LOCALE_TAGS` order),
  else `text` — identical precedence to `_xml_to_csvs._extract_field`.
- Stored on the parent under the wrapper's own tag (`label`, `bm_name`, `name`,
  `description`, `default_value`) — same column names the old path produced,
  same list-accumulation rule as pass 1 for repeated tags.
- Move `_LOCALE_TAGS` to `cpq_ingestion/constants.py` (or a shared module) and
  import it from both paths so they can't drift.
- Ships under the existing `ARYX_CPQ_STRUCTURAL_LEAF_FOLD_ENABLED` opt-out, plus
  its own `ARYX_CPQ_LOCALE_WRAPPER_FOLD_ENABLED` (default true) per PR #429 N1.

Effect: `BmConfigAttr.name = "BoolContinue1"`, `BmPrdFamily.label = "ASTRO®25_BOM"`,
`BmCatalog.bm_name = "APX™ NEXT"`. `_display_name` already prefers `name`/`label`
so the graph vertex name becomes human-readable with no graph-layer change
(`bm_name` is **not** in `_NAME_KEYS` — see §2).

### 2. Display label + match name for families / models

In `resolve_relate.py` (or the fold, post-pass), for CPQ entities:
- `display_label` ← `label` → `bm_name` → `name` → `variable_name` / `bm_variable_name`.
- `name` ← `variable_name` / `bm_variable_name` **only when `name` is empty** —
  `catalog_naming.py` matching was built around `aPXNext_BOM`-shaped names.
- Add `display_label` (and `bm_name`) to `_NAME_KEYS` *after* `name`/`label` —
  low risk, ordering-only.

### 3. Ask prompts show `display_label`

`nl_hint_extraction/families.py`, `entity_fetch._match_family_name`,
`catalog_scoping`, the model-choice prompt and the attribute "did you mean"
list: render `display_label` when present; match on **both** `display_label`
and `name`, with ™/®/© stripped in normalization (`"APX NEXT"` must match
`"APX™ NEXT"`).

### 4. Backfill existing workspaces

`scripts/backfill_cpq_locale_wrapper_names.py`, modelled on PR #435's
`backfill_raw_graph_ontology_type_naming.py`: dry-run by default, raven_log
instrumented, per workspace:
1. For each parent entity, read its `CONTAINS` children of wrapper types
   (`…Label`, `…BmName`, `…Name`, `…Description`, `…DefaultValue`), merge
   values onto the parent's attributes (same precedence as §1/§2).
2. Delete the now-redundant wrapper child entities + their relationships
   (chunked, committed per batch — undo is tight on this ADB, see ORA-30036
   incident on ws 1097 2026-10-05).
3. Rebuild the workspace graph with pre-cleared chunked deletes (the full
   `clear()` is one transaction and hit ORA-30036 on 1097).

Targets: 1097 (`OCI-MSI-6`), 1126 (`APX_NEXT`). 1090 first needs PR #435's
prefix backfill.

## Open question to verify during implementation

After picking model `17691417058`, Ask did not accept the reply as the model
and fell into the attribute "did you mean" branch. Verify whether that is the
same root cause (model names = ids colliding with numeric matching) or a
separate pending-scope bug — re-test after §1–§3.

## Tests (write first — raven-test)

- `test_structural_leaf.py`: `<label><en>X</en></label>` folds to parent
  `label="X"`; `<en>`-less `<fr>` only → first locale; mixed `<description>`
  (text + `<en>`) folds; wrapper with a real attribute or a non-locale child
  does **not** fold; repeated wrappers accumulate a list; opt-out flag restores
  current behaviour.
- Parity test: same XML through `_xml_to_csvs` and the raw-graph fold produce
  the same field values on the parent.
- `test_families.py`: family shows `display_label`, matches "APX Next" →
  `aPXNext_BOM` and "APX NEXT" → "APX™ NEXT".
- Backfill: dry-run reports counts and changes nothing; apply is idempotent.

## Rollout

1. Merge to `dev_oci`, redeploy the API (local container image is from 2026-10-02 —
   rebuild it too, or it keeps producing unprefixed, unfolded types).
2. Run backfill dry-run → apply on 1126, verify Ask end-to-end, then 1097.
3. New ingests verified on a fresh workspace with the same APX_NEXT files.
