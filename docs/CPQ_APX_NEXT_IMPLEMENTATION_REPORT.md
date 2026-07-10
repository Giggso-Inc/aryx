# CPQ APX Next — Implementation Report

**Date:** 2026-07-10
**Branch:** `feat/falkordb-cypher-logging`
**Scope:** Phases G–N of `docs/CPQ_APX_NEXT_ISSUES_PLAN.md` — the ETL/conversational fixes
and the widened auto-fill eligibility change (≤2–3-prompt client requirement).
**Companion doc:** `docs/CPQ_APX_NEXT_TESTING_REPORT.md` (test evidence for every phase below).

---

## 1. Status at a glance

| Phase | Description | Status | Files |
|---|---|---|---|
| G | FK-detection compound-column fix | ✅ Implemented | `src/aryx/pipeline/doc_discovery.py` |
| H | Dangling-FK `-1` sentinel exclusion | ✅ Implemented | `src/aryx/pipeline/ingest_validation.py` |
| I | `apply_answer` constraint validation | ✅ Implemented | `src/aryx/cpq/engine.py`, `src/aryx/api/ask_api.py` |
| J | Single-select re-validation on cascade | ✅ Implemented | `src/aryx/cpq/engine.py` |
| K | Verbose summary noise filter + Key-decisions grouping | ✅ Implemented | `src/aryx/cpq/engine.py`, `src/aryx/api/ask_api.py` |
| L | Live audit against workspace 13 | ✅ Complete (done earlier this session, unchanged) | — |
| M | Surveillance/carrier mutex decision (HITL) | ⏸ **Skipped for now**, per explicit user instruction (2026-07-10) | — |
| N | Widened auto-fill eligibility (≤2–3-prompt target) | ✅ Implemented | `src/aryx/cpq/engine.py`, `src/aryx/api/ask_api.py` |

Net diff for this pass: **6 files changed, 675 insertions(+), 43 deletions(-)**
(`src/aryx/cpq/engine.py`, `src/aryx/api/ask_api.py`, `src/aryx/pipeline/doc_discovery.py`,
`src/aryx/pipeline/ingest_validation.py`, `tests/test_cpq_e2e.py`,
`docs/CPQ_CASCADE_CONVERSATION_PLAN.md`), plus the new
`docs/CPQ_APX_NEXT_ISSUES_PLAN.md` planning doc itself. None of these changes have
been committed yet — they are in the working tree only.

---

## 2. Phase-by-phase detail

### Phase G — FK-detection compound-column fix

**Problem:** `_detect_fk_links` (`doc_discovery.py`) matched a column's FK prefix against
only the **last** CamelCase word of the target ontology type (`tag_word`). Real BM columns
like `attr_set_id` (target `BmConfigAttrSet`) carry more context than the last word alone —
`"attr_set"` never matched `tag_word="set"`. Confirmed live: 3 columns
(`attr_set_id`, `page_template_id`, `config_attr_id`) had nonzero *expected* edges but zero
*actual* edges written.

**Fix:** Candidate stems are now generated from **every trailing-word-run** of the target
type's de-camelCased name (not just the last word), in both `snake_case` and joined form,
singular and plural — e.g. for `BmConfigAttrSet`: `set`, `attrset`/`attr_set`,
`configattrset`/`config_attr_set`. Purely derived from the type name; no hardcoded column
or prefix list.

```python
# doc_discovery.py — _detect_fk_links, per (source, target) pair
_words = re.findall(r'[A-Z][a-z0-9]*', type_b)
tag_candidates: set[str] = {type_b_l, singular_b}
for k in range(1, len(_words) + 1):
    suffix_words = _words[-k:]
    for form in ("_".join(w.lower() for w in suffix_words),
                 "".join(w.lower() for w in suffix_words)):
        tag_candidates.add(form)
        tag_candidates.add(_singular(form))
```

Matching changed from an exact 4-way `in (...)` tuple check to `col_l[:-3] in tag_candidates`
(and the `_name` equivalent) — same call site, wider candidate set.

**Verified:** all 3 live-failing columns resolve to a candidate stem (checked by direct
script execution against the real type names — see Testing Report S15).

### Phase H — dangling-FK sentinel exclusion

**Problem:** `ground_truth_from_tabular` (`ingest_validation.py`) counted BigMachines'
universal `-1` "not set" convention as a broken/dangling FK reference, inflating the
apparent problem count with a false signal (`dangling_fk_values=1 sample=['-1']` in the
live ingestion log).

**Fix:** one-line guard, mirroring the same sentinel-awareness already used elsewhere in
the codebase (`condition_function_id == -1` checks):

```python
for r in rows:
    val = str(r.get(col, "")).strip()
    if not val or val == "-1":
        continue   # BM's own "not set" convention — not a broken reference
    ...
```

### Phase I — `apply_answer` constraint validation

**Problem:** `apply_answer` had no way to reject an answer matching an option that an
*active* constraint rule had just eliminated — a user could still "select" a value the
menu no longer offered.

**Fix:**
- `apply_answer(attr, user_answer, constrained_item_values=None)` — when supplied, every
  matching strategy (numeric position, exact item_value, exact display name, prefix,
  word-boundary) is pre-filtered to that set; free-text fallback is disabled when a
  constraint is active (there's nothing free-text to validate against).
- **Call-site change in `ask_api.py`:** Step 5 (the answer-lock step) previously had no
  constraint context available at all — `constrained_opts` wasn't computed until Step 3,
  *after* Step 5 already ran. Fixed by hoisting `bml_eval = build_bml_evaluator(...)`
  earlier in `_run_cpq_turn` (right after rule loading) and computing
  `apply_constraint_rules(attrs, con_rules, session.filled, bml_eval=bml_eval)` at Step 5
  time — `session.filled` hasn't changed since the prompt was shown last turn, so this
  reflects exactly what the user was offered.

### Phase J — single-select re-validation on cascade

**Problem:** `auto_fill`'s multi-select path already re-validated an existing selection
against a newly-active constraint (dropping members no longer allowed, per §5's
Region=NA fix). The single-select path had no equivalent — a stale, now-invalid answer
would silently survive a cascade.

**Fix:** the `if vn in filled:` branch now checks `constrained_opts.get(attr.entity_id)`
before short-circuiting. If the locked value is no longer in the allowed set: it's popped
from `filled`/`display_filled`/`sources`, recorded in the same `dropped` dict the
multi-select path already uses (so the cascade notice reads "Carrier was reset — no longer
valid after deleting LTE" via the existing rendering path), and falls through to normal
re-resolution instead of `continue`-ing past it.

**Cascade re-fill inherits Phase N automatically** — re-resolution uses the same
`governed_ids` set passed into this same `auto_fill` call, so a dependent that was
eligible for auto-fill on first pass is equally eligible on re-fill. No separate change
was needed in the cascade path itself (see also §Phase N below, and Testing Report S26).

### Phase K — verbose summary noise filter + Key-decisions grouping

**Problem, two parts:**
1. `render_filled_summary` only filtered HTML-template values. Live query #9 showed
   `CRM_BILL_COUNTRY`, `CRM_CUSTOMER_ID`, etc. at the top of the "clean" summary —
   integration/system fields cluttering a sales-rep-facing narrative.
2. The new client spec (§3g) asks for verbose mode to surface only rule-*decided*
   "important" attrs, not a flat list where a rule-driven Region choice and an
   arbitrarily-defaulted cosmetic toggle read as equally significant.

**Fix:**
```python
@staticmethod
def _is_noise_var(variable_name: str) -> bool:
    """Underscore prefix, or a leading `_`-delimited segment that is fully
    uppercase (e.g. CRM_BILL_COUNTRY) — structural, not a hardcoded prefix list."""
    if variable_name.startswith("_"):
        return True
    head = variable_name.split("_", 1)[0]
    return len(head) >= 2 and head.isalpha() and head.isupper()
```
`render_filled_summary` now takes an optional `rule_governed_ids` set (the strict subset
from `rule_governed_ids()` — see Phase N). When supplied, output splits into a
**"Key decisions"** block (attrs a hiding/recommendation/constraint rule actually reasoned
about) and a terse `"+N other field(s) auto-configured"` count for the rest. Without it,
behavior is unchanged (flat list) — fully backward compatible for any caller not yet
updated.

### Phase N — widened auto-fill eligibility (the ≤2–3-prompt fix)

**Problem:** D2 (`CPQ_CASCADE_CONVERSATION_PLAN.md`) deliberately restricted default-or-first
auto-fill to attrs targeted by a loaded hiding/recommendation/constraint rule — a safeguard
against Issue 6's eager guessing. On APX Next's richer catalog (427 attrs, 688 rules), this
left **29 attrs pending** after both anchors resolve — only 1 of those 29 was actually
rule-governed; the other 28 simply carry no rule at all in the source data. Nowhere close
to the client's ≤2–3-prompt requirement.

**Decision (approved via HITL, "go"):** widen eligibility to a second, independent path —
attrs marked `required=False` in the source (excluding decision-required keys
country/region, which always ask regardless of governance):

```python
eligible = governed_ids ∪ {
    a.entity_id for a in attrs
    if not a.required
    and not any(dk in a.variable_name.lower().replace("_","") for dk in _DECISION_REQUIRED_KEYS)
}
```

**Implementation:**
- `governed_target_ids()` (the function every call site already used) now returns this
  widened union.
- The **original strict logic was extracted**, unchanged, into a new
  `rule_governed_ids()` — needed because `filled_source` must still distinguish *why* an
  attr got a value: `"rule"` (an actual rule reasoned about it) vs. a new `"optional"` tag
  (admitted only via the `required=False` path). Phase K's Key-decisions grouping and any
  future audit depend on this distinction surviving the widening.
- `auto_fill()` gained an optional `rule_governed_ids` parameter (defaults to
  `governed_ids` itself when omitted — i.e. every step-4 fill tags `"rule"`, the exact
  pre-Phase-N behavior for any caller not yet passing it — fully backward compatible).
  Both the multi-select and single/boolean governed branches now tag `source` via
  `"rule" if attr.entity_id in rule_governed else "optional"`.
- All 3 real call sites (`engine.py`'s `evaluate_rules_loop`, and both turn-handlers in
  `ask_api.py`) updated to compute and thread `rule_governed_ids` alongside the existing
  `governed_ids`.

**Cross-doc consistency:** `CPQ_CASCADE_CONVERSATION_PLAN.md`'s D2 section now carries an
explicit amendment note pointing here, so a reader of that doc alone isn't left with a
stale eligibility rule.

**Live-equivalent result (confirmed by automated test, not just live trace):** on
`APX_Next_config.xml`, a conversation seeded with product+country in message 1 now reaches
`awaiting_approval` in **≤3 user turns** — see Testing Report S23.

---

## 3. Files touched (this pass)

| File | Nature of change |
|---|---|
| `src/aryx/cpq/engine.py` | `governed_target_ids` widened; new `rule_governed_ids()`; `auto_fill` gains `rule_governed_ids` param + single-select re-validation branch; `apply_answer` gains `constrained_item_values`; `render_filled_summary` gains `_is_noise_var` + `rule_governed_ids` grouping |
| `src/aryx/api/ask_api.py` | `bml_eval` hoisted earlier in `_run_cpq_turn`; Step 5 recomputes pre-answer constraints and passes them to `apply_answer`; `rule_governed_ids` threaded to `auto_fill`/`render_filled_summary` call sites |
| `src/aryx/pipeline/doc_discovery.py` | `_detect_fk_links` Pass 1 candidate-stem generation widened to all trailing-word-runs |
| `src/aryx/pipeline/ingest_validation.py` | `-1` sentinel excluded from dangling-FK classification |
| `tests/test_cpq_e2e.py` | `test_s9` updated for Phase N semantics; S15–S26 added (see Testing Report) |
| `docs/CPQ_CASCADE_CONVERSATION_PLAN.md` | D2 amendment note added, pointing to this plan's Phase N |
| `docs/CPQ_APX_NEXT_ISSUES_PLAN.md` | Full planning doc (findings, phases, tests, risks) — the source of truth this report summarizes |

---

## 4. What is explicitly NOT implemented

- **Phase M (surveillance/carrier mutex)** — skipped for now per explicit instruction. No
  code was written for either option (i) (flag to catalog owner) or (ii) (build an
  Aryx-side mutex heuristic). The two underlying bugs (surveillance double-charge,
  LTE/Carrier state conflict) remain live and unfixed in the source catalog. Nothing else
  in Phases G–N depends on this decision.
- **A duplicate-concept-attr detector (Phase M's option ii, and Phase N/M's data-health
  feeder S21)** — deliberately not built; building it now would presuppose option (ii)
  before the catalog-owner conversation in option (i) even happens.
- **S20a as an automated regression** — the 10-query live audit against workspace 13 was
  done manually this session (Phase L, complete); formalizing it as an automated FalkorDB
  test remains optional future work, not required for Phases G–N.

## 5. Not yet committed

All changes described above are in the working tree, uncommitted. No branch, commit, or PR
has been created for this pass — confirm before any `git add`/`commit`/push.
