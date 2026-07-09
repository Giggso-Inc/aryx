# CPQ Cascade Conversation Plan — Seed → Cascade → Change → Re-cascade

**Status:** Design complete (Andie Drama session), pending implementation
**Date:** 2026-07-09
**Depends on:** `docs/CPQ_GRAPH_FIX_PLAN.md` (all 4 phases landed on `fix/cpq-graph-rag-issues`) — this plan extends the same engine, it does not replace it.

---

## 1. Requirement (client language)

> The client selects the product and one independent variable. From that seed,
> the system cascades: hidden rules reveal dependent variables; constraint and
> recommendation rules are checked; each newly resolved dependent variable is
> fed back through the same rule checks — looping until nothing new appears.
> Then the JSON payload is generated. The client can change any value
> afterwards; the system re-cascades from that change and updates the JSON.
> The whole exchange is a conversational chain with maintained history.
> Dependent variables auto-select their default value, or the first value if
> no default exists. Some dependents are single-select (radio); some are
> multi-select (checkbox), selected based on rules. The conversation is
> verbose by default; JSON is only shown when the client asks for it.

## 2. Resolved decisions (HITL, this session)

**D1 — Seed/anchor model.** Today's `validate_anchors` (`engine.py:209-232`) hard-blocks
until product + product-line + country are *all* present in one message.
**Resolved:** replace with a **sequential** prompt — product first (if
missing), then country (if missing) — not a single blocking error. Hardware
version (`hwVersion`) **moves from anchor to dependent**: it is resolved
through the normal cascade like any other rule-governed variable, not
required up front.

**D2 — Auto-fill eligibility.** The engine deliberately never auto-picks a
first option for multi-option attrs today (`auto_fill`, `engine.py:1001-1016`,
the Issue-6 "Stop and Wait" safeguard). **Resolved:** eligibility for
default-or-first auto-fill is **rule-outcome driven** — an attribute is a
"dependent variable" in this spec's sense only if it is referenced as a
`target_attr_id` by at least one loaded `HidingRule`, `RecommendationRule`,
or `ConstraintRule` (resolvable via the existing `_attr_index` ID bridge,
`engine.py`). Attributes with no rule coverage, and the two anchors
(product/country), always keep the existing ask-the-user behavior.

## 3. Auto-fill policy (per rule type, in priority order)

For a rule-governed dependent, once revealed/visible:

1. **Recommendation rule fires** (condition met) → use `recommended_value`
   directly. *(No change — `apply_recommendation_rules` already does this.)*
2. **Constraint rule(s) active** (condition met, `allowed_values` computed) →
   - Single-select: pick `default_value` if it's in the allowed set, else the
     first allowed value by menu order.
   - Multi-select: the **allowed set itself is the auto-selected set** — this
     is what "select multiple based on rules" means; it is not a single
     default-or-first pick.
3. **No recommendation/constraint active, but attr is hiding-rule-governed
   (just revealed)**:
   - Single-select: `default_value` if present, else first option by `order_number`.
   - Boolean: `default_value` if present (coerced to true/false), else default
     to `false` (unchecked) — a boolean's "first value" is well-defined and
     low-risk since there are only two states.
   - Multi-select: `default_value` if present (a default is inherently a
     single item — pre-select just that one), **else leave unselected and ask
     the user**. Auto-selecting multiple options with no rule or default to
     justify the choice is exactly the guessing risk D2's eligibility test
     exists to prevent — "rule-governed" makes an attr *eligible* for
     auto-fill, it doesn't mean every branch of every select_type gets one.
4. **Not rule-governed and not an anchor** → unchanged: ask the user
   (existing Stop-and-Wait path, `auto_fill` pending logic).

This is layered on top of the existing loop — `evaluate_rules_loop`
(`engine.py`) already runs hide → recommend → constrain → auto-fill to a
fixpoint; only the auto-fill step's *eligibility test* changes.

## 4. Single-select vs multi-select

- New `ConfigAttr.select_type: Literal["single", "multi", "boolean"]`
  (`cpq/state.py`), derived from BM attribute metadata at load time
  (`load_product_config`, `engine.py:266-407`). **Derivation rule (confirmed):**

  ```python
  def classify_select_type(attrs: dict) -> Literal["single", "multi", "boolean"]:
      if str(attrs.get("is_array_control_attr", "")).strip() == "1":
          return "multi"
      if (str(attrs.get("display_type", "")).strip() == "10"
              or str(attrs.get("data_type", "")).strip() == "4"):
          return "boolean"
      return "single"  # covers display_type == "3" (dropdown) and free-text/other
  ```

  Priority order matters: check `is_array_control_attr` first, then the
  boolean pair, else default to `"single"` — dropdowns (`display_type=="3"`)
  and any other field shape (free-text, etc.) both fall through to `"single"`
  safely, since the existing free-text path (`attr.options == []`) is
  unaffected by `select_type`.
- **`"boolean"` is a distinct third case, not folded into `"single"`.** A
  boolean checkbox has exactly one value like radio/dropdown selection, but
  it has **no `BmMenuItem` options** to prompt from (`load_product_config`'s
  menu-item join, `engine.py:320-362`, will find none) — its prompt is a
  fixed Yes/No, not a numbered list. `next_question_prompt` (`engine.py`)
  needs a `select_type=="boolean"` branch alongside its options-based path.
- **Verified against the full sample population** (all 15 config attrs, not
  a partial sample): `is_array_control_attr` is `"0"` for every attr,
  `data_type` is `"1"` for every attr, `display_type` never equals `"10"`.
  This export contains **6 dropdowns, 9 free-text/other, 0 multi-select,
  0 boolean** — the derivation rule is confirmed, but this sample cannot
  exercise the `"multi"` or `"boolean"` branches end-to-end (see §9, S14a/S14b).
- **No change to `CpqSession.filled`'s existing type** (`dict[str, str]`) —
  the panel rejected a blanket `str | list[str]` rewrite as touching every
  call site for a minority case. Add a **new** field instead:
  `CpqSession.filled_multi: dict[str, list[str]]` (`cpq/state.py`).
  `build_payload` merges both into the final JSON (multi-select values as
  JSON arrays). `apply_answer` gains a multi-select path (parse
  comma/numbered multi-pick input) alongside the existing single-answer path.

## 5. Change → re-cascade, with explicit invalidation

`_handle_cascade` (`ask_api.py:269-353`) and `find_cascade_dependents`
(`engine.py`) already implement "change → invalidate dependents → re-run
loop" for single-select. Extend, do not replace:

- When a re-cascade narrows a multi-select attr's allowed set and one or more
  previously-selected members fall outside it, **do not silently drop them**
  (same bug class as the Region=NA payload-drop fix). Extend the cascade
  notice to name the dropped values explicitly:
  `"Removed **X, Y** from **{label}** — no longer valid after this change."`
- `filled_multi` participates in the same dependent-invalidation walk as
  `filled`.

## 6. Response mode: two independent "rich-by-default, opt-in-only" toggles

Clarified this session: there are **two separate axes**, both governed by the
same principle — *the richer/verbose form is always the default; the terser
form (raw JSON, or a batched question list) is shown only when the client
explicitly asks for it.* Both toggles share one detector pattern so this
isn't built twice.

### 6.1 Content axis: verbose narrative vs JSON

- New `CpqSession.mode: Literal["verbose", "json_only"]` (default
  `"verbose"`), plus a new intent detector alongside `detect_approval`
  (`engine.py:1102-1104`) for "show me the json" / "what's the payload so
  far" phrasing. **If the client does not specifically ask for JSON, JSON is
  never shown** — the response is always the verbose narrative form instead.
- **Verbose = a status report, not just the bare next question.** Reuse and
  extend `render_filled_summary` (`engine.py:1386-1409`, already produces
  "**Configured so far:** ...") so every turn's response is: what's been
  decided so far (+ why, from `cascade_log`, §7) followed by the pending
  question(s) — not a bare one-line prompt with no context.
- **Preview vs final distinction, not currently in the engine.** Today FORMAT
  B (JSON block) only appears at completion (`status="awaiting_approval"`) or
  turn-cap. This spec wants JSON **on request, mid-conversation, without**
  forcing approval status. Implementation: a preview branch that calls
  `build_payload(filled, filled_source)` and renders it read-only, tagged
  `"preview": true`, leaving `session.status` untouched — the existing
  approval gate (Step 8) remains the only path to `cpq_payload` being set.

### 6.2 Delivery axis: question-by-question vs batched pending list

- **Default: sequential, one pending attribute per turn** — unchanged from
  today's FORMAT A (`next_question_prompt`, one attr at a time).
- **On explicit request only** (interpretation — confirm if this reads
  differently than intended): phrasing like "what else do you need", "show
  me all the remaining questions", "what's left" triggers a **batched**
  response instead — every currently-pending attribute listed together in
  one message, each with its own short "why" line from `cascade_log`/
  `build_context_sentence`, rather than doled out one per turn.
- New `CpqSession.question_mode: Literal["sequential", "batched"]` (default
  `"sequential"`) — a per-turn choice, not sticky: the client can ask for the
  batched view once and the next turn still answers one-at-a-time unless
  asked again. Mirrors the JSON toggle in 6.1 exactly.
- **Shared detector infrastructure:** both 6.1's JSON-request and 6.2's
  batch-request are the same UX pattern — "client explicitly asked for a
  different presentation of the same underlying state." Implement as one
  intent-detection helper parameterized by target presentation, not two
  separate regex sets, to avoid the drift `detect_approval`/
  `detect_qa_question`/`detect_change_request` already show from growing
  independently.

## 7. History for coherent re-explanation

`AskRequest.history` today is plain Q&A text pairs (`ask_api.py:58`), used
only for the standard Ask LLM path — the CPQ turn loop doesn't consume it.
Add a lightweight **cascade delta log** to `CpqSession`
(`cascade_log: list[dict]`, e.g. `{"var": ..., "old": ..., "new": ...,
"rule": ..., "turn": ...}`), appended whenever `_handle_cascade` or the main
loop changes a value. `build_context_sentence` (`engine.py:857-901`) and the
cascade notice both read from this log instead of re-deriving "why" from the
current rule set alone — keeps multi-turn explanations coherent as the
conversation grows past turn 5.

## 8. Phased implementation

```
Phase A — Seed/anchor rework (D1)         — ask_api.validate_anchors path
Phase B — Rule-governed auto-fill (D2/§3) — engine.auto_fill, evaluate_rules_loop
Phase C — Multi-select schema (§4)        — state.py, engine.py, ask_api.py
Phase D — Cascade invalidation (§5)       — ask_api._handle_cascade
Phase E — Response-mode toggles (§6): verbose/JSON + sequential/batched — shared detector, engine.py, ask_api.py
Phase F — Cascade history log (§7)        — state.py, engine.py
Phase G — Testing (§9): automated scenarios + live verification on workspace 12
```

A and B are independent and can start in parallel. C is now **unblocked** —
the `select_type` derivation rule is confirmed (§4) — and can start alongside
A/B. D depends on C for the multi-select invalidation path but the
single-select notice-naming improvement can land without C. E and F are
independent of the others.

**Cross-plan dependency, found via live audit (2026-07-09):** Phase B's
eligibility test (D2 — "is this attr a `target_attr_id` of some loaded rule")
is only as complete as `load_hiding_rules`/`load_recommendation_rules`/
`load_constraint_rules`'s ability to actually resolve rule targets. A live
audit against workspace 12 found these loaders miss rules that target an
attribute via `bm_config_layout_attr_assoc`, `bm_config_rule_layout_assoc`,
or `bm_config_rule_assoc` chaining, rather than a simple `BmConfigRuleAction`
row — see `CPQ_GRAPH_FIX_PLAN.md` §6a for the full finding. **Phase B's code
can be written in parallel with Phase A**, but its *results* — how many
attrs actually get auto-filled — will stay artificially low, reproducing
the exact "asked for 85 attributes" symptom this plan exists to fix, until
§6a lands. Land §6a before validating Phase B against real data (§9.2 step 2
in particular depends on it directly).

## 9. Testing Plan

Two tracks, same discipline as `CPQ_GRAPH_FIX_PLAN.md`: automated scenarios
carry **zero hardcoded values** (everything derived from whatever export
`ARYX_CPQ_SAMPLE` points at); the **live track reuses workspace 12**
(`aryx_ws_12` — created for the graph-fix validation, still live: verified
this session at **15,334 entities / 15,744 relationships**, unchanged) as the
concrete manual/integration vehicle — no re-ingestion needed for Phases A/B/D/E/F,
since none of them touch ingestion or projection.

### 9.1 Automated — extend `tests/test_cpq_e2e.py` / `cpq_fixtures.py`

| # | Scenario | Ground truth derivation | Asserts |
|---|---|---|---|
| S8 | Sequential anchor prompting (D1) | Drive `_run_cpq_turn` with a question containing neither product nor country | Turn 1 prompts for product only (not a 3-anchor block); turn 2 (product given) prompts for country; hwVersion is NOT demanded before cascade starts |
| S9 | Rule-governed auto-fill (D2/§3) | From the sample's real hiding/recommendation/constraint rules, pick a target attr with a `default_value` and one without | Attr with `default_value` auto-fills to it; attr without auto-fills to first option by `order_number`; an attr with **no** rule reference of any kind still goes to `pending` (regression guard against re-introducing Issue 6) |
| S10 | Constraint-driven value set | A constraint-governed attr under an active rule | Auto-filled value is a member of the rule's `allowed_values`, never a value the rule excludes |
| S11 | Re-cascade invalidation naming (§5) | Change an already-filled attr that is a hiding-rule condition for others | Cascade notice names every invalidated dependent; none silently vanish from `session.filled` |
| S12 | Verbose default, JSON on explicit request only (§6.1) | Drive two turns: one plain config-answer turn, one turn asking "show me the json" | Plain turn's response contains **no** JSON — narrative status report (decisions so far + why + next question) instead; JSON-request turn returns a `"preview": true` block; `session.status` stays `"configuring"`; `cpq_payload` stays `None` either way |
| S12b | Sequential default, batched pending list on explicit request (§6.2) | Drive to a point with ≥2 pending attrs, then ask "what else do you need" | Default turns show exactly one pending attribute; the explicit-request turn lists **all** currently-pending attrs together, each with its own reason line; the following turn (no repeat request) reverts to one-at-a-time |
| S13 | Cascade history coherence (§7) | Multi-turn driven conversation with ≥2 value changes | `cascade_log` records each change with its firing rule; `build_context_sentence` output for a later turn references the correct prior change, not just the current rule set |
| S14a | `classify_select_type` unit test — **pure function, no sample needed** | Synthetic input dicts covering each branch: `is_array_control_attr="1"` (→multi); `display_type="10"` and, separately, `data_type="4"` (→boolean); `display_type="3"` (→single/dropdown); an empty/unknown shape (→single, the safe default) | Each synthetic input classifies correctly; priority order holds — an attr with BOTH `is_array_control_attr="1"` and `display_type="10"` classifies as `"multi"` (checked first) |
| S14b | Multi-select / boolean on real data — **fixture-gated for the default sample** | Run `classify_select_type` over every `truth.config_attrs()` row from the resolved `ARYX_CPQ_SAMPLE`. Re-confirmed this session: the default sample yields 6 dropdown, 9 single/other, **0 multi, 0 boolean** — the classifier is proven correct, but this export cannot exercise the `"multi"`/`"boolean"` cascade paths end-to-end | Assert the classification counts are internally consistent (every attr gets exactly one class); explicitly skip the end-to-end multi/boolean cascade assertions with a reason naming the zero-count, rather than silently passing on an empty set |

S8–S13 and S14a follow the existing `FakeCpqRdb`/`FakeReader` pattern (no
database required) — S14a needs no sample file at all, it is a pure
unit test of the confirmed classifier. The end-to-end multi-select cascade
behavior (§3 point 2 — allowed-set-as-selected-set) still needs either a
second real export with a genuine `is_array_control_attr="1"` attribute, or
a hand-built `ConfigAttr(select_type="multi", ...)` integration fixture —
**do not fabricate a fake multi-select flag on real single-select sample
data**, that would be the exact hardcoding this project's test discipline
forbids.

### 9.2 Live — manual verification on workspace 12

Same call pattern already used for the graph-fix validation
(`POST /ask`, `workspace_id: 12`), now targeting the new behaviors:

1. **D1 sequential prompting** — send a question with no product/country
   mentioned at all; confirm the response asks for product only, then a
   follow-up asks for country, before any config attrs load.
2. **D2/§3 auto-fill** — drive a full conversation and inspect
   `session_data.filled_source` per turn; every value whose source is
   `"rule"` or `"default"`/`"auto"` must correspond to an attr this plan's
   eligibility test would classify as rule-governed — cross-check against
   `aryx_ws_12`'s real hiding/recommendation/constraint rules via the same
   Cypher used in the graph-fix validation (`MATCH (r:Entity {type:
   'Sl3500EDummyConfigBmConfigRule'})...`).
3. **§5 re-cascade** — after reaching `awaiting_approval`, send a change
   request for an attr that conditions a hiding rule; confirm the response
   names every invalidated dependent attr by label, and the follow-up
   question set matches the newly-visible attrs.
4. **§6.1 preview** — mid-conversation (before `awaiting_approval`), ask "what
   does the json look like so far"; confirm a tagged preview appears and
   `status` does not change to `awaiting_approval`; confirm the very next
   ordinary turn goes back to verbose narrative, no JSON, unprompted.
5. **§6.2 batched pending list** — once ≥2 attrs are pending, ask "what else
   do you need from me"; confirm every pending attr is listed in one message
   with its own reason; confirm the following turn (a normal answer, no
   repeat request) returns to one-question-per-turn.
6. **§4 multi-select — explicitly OUT of scope for workspace 12.** Log this
   gap rather than skip it silently: this workspace's data cannot exercise
   multi-select at all. A second live workspace (ingested from an export
   confirmed to contain a checkbox-style attribute) is required before this
   behavior can be manually verified end-to-end.

Workspace 12 stays reusable across A/B/D/E/F testing rounds; only re-ingest
if Phase C's `select_type` derivation requires re-running projection against
a *different* sample export for §4 / S14a / S14b / step 6 above.

## 10. Risks

- **§4 derivation rule is confirmed but untested against a real `"multi"` or
  `"boolean"` example** — the classifier logic itself is locked in and unit-
  testable now (S14a), but end-to-end behavior for those two branches (cascade,
  payload serialization, prompt rendering) has never run against real data.
  Land S14a first; treat the multi/boolean cascade paths as higher-risk until
  a qualifying export or integration fixture exercises them (S14b, §3 point 2).
  Watch also for non-`"0"`/`"1"` values of `is_array_control_attr` in other
  exports (e.g. `null`, `"true"`) — the classifier's `.strip() == "1"` check
  must not silently misclassify those; confirm the exact string form BM emits
  across more than one customer export before relying on it in production.
- **Phase B's benefit is capped by `CPQ_GRAPH_FIX_PLAN.md` §6a** (cross-plan
  dependency, §8) — without that fix landing first, Phase B will look
  implemented but auto-fill far fewer attrs than it should, because the rule
  loaders it depends on miss chained/layout-targeted rules. Don't validate
  Phase B's "how many attrs got auto-filled" numbers against real data until
  §6a is in.
- **D1 changes existing behavior** for any caller relying on the current
  single-shot 3-anchor block — audit `validate_anchors` callers before
  removing hwVersion from the gate.
- **§6.1 preview JSON** must never be mistaken for the approved payload by a
  downstream consumer — the `"preview": true` tag is load-bearing; don't drop
  it in a later refactor.
- **§6.2 shared detector** (verbose/JSON request vs batch-questions request)
  must disambiguate correctly when a message could plausibly trigger either —
  e.g. "what's left" leans batch-questions, "show me what you have" is
  ambiguous between a verbose recap (already the default) and a JSON ask.
  Bias the detector toward the existing rich default on ambiguity, never
  toward JSON — false-negative (stays verbose) is safe, false-positive
  (leaks JSON unasked) violates the requirement directly.

## 11. Out of scope (this plan)

- Changing the BML evaluator (Phase 2 of `CPQ_GRAPH_FIX_PLAN.md`) — reused as-is.
- Oracle ADB test execution — same deferral as the parent plan.
