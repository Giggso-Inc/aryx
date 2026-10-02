"""`auto_fill`'s real implementation (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md): builds the P0 `FillContext`/`FillScope` pair, runs
`auto_fill_resolve.resolve_one_attr` over every attr, then the P2/P3
post-passes. `CpqEngine.auto_fill` is a one-line delegating wrapper; this
docstring is the full caller-facing contract. Logic unchanged from the
original inline body.
"""

from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.cpq.auto_fill import auto_fill_resolve, auto_fill_setup


def run_auto_fill(
    engine: Any,
    attrs: list[Any],
    hints: dict[str, str],
    already_filled: dict[str, str] | None = None,
    constrained_opts: dict[int, list[str]] | None = None,
    filled_source: dict[str, str] | None = None,
    governed_ids: set[int] | None = None,
    already_filled_multi: dict[str, list[str]] | None = None,
    dropped_multi: dict[str, list[str]] | None = None,
    rule_governed_ids: set[int] | None = None,
    country: str | None = None,
    rec_rules: list[Any] | None = None,
    negated_vns: set[str] | None = None,
    skip_always_ask: set[str] | None = None,
    bml_eval: Any | None = None,
    validation_rules: list[Any] | None = None,
    display_order: dict[str, int] | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    _dt_cache: dict[tuple[int, str], tuple] | None = None,
    hiding_rules: list[Any] | None = None,
    _default_fill_signatures: dict[str, tuple] | None = None,
    _signature_exclude_vns: frozenset[str] | None = None,
    grid_declined_vns: frozenset[str] | None = None,
    product_anchor_hint: str | None = None,
) -> tuple[dict[str, str], dict[str, str], list[Any]]:
    """Auto-fill attributes. Never assigns None/null/empty values.

    grid_declined_vns — optional (default None, no-op for every
    existing caller). docs/CPQ_SVX_MOUNTING_TYPE_ARRAY_GRID_MULTI_
    SELECT_PLAN_2026_08_25.md: a grid-selector attr (one of
    `resolve_array_grid_links`' keys — a select_type=="multi" attr
    driving per-row quantity companions, e.g. SVX's mountingTypeArray_
    viSoln or APX Next's itemTypeVX650_astro) that already has 1+
    picks is kept in `pending` for another round as long as any
    currently-valid (constraint/rec-rule-narrowed) option remains
    unpicked — so a customer can add several rows across turns, not
    just the first one they name. `grid_declined_vns` is the
    customer's own escape hatch: once they explicitly decline further
    picks (session-level, set by the caller), that vn is treated as
    settled regardless of how many valid options remain unpicked.
    Structural — keyed only on `resolve_array_grid_links`' own output
    and `filled_multi`/`constrained_opts` state, no attribute or
    catalog name anywhere in the check.

    _default_fill_signatures — docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_
    2026_08_19.md: optional, mutated in place. When supplied, a
    "default_first_available"-sourced attribute is only re-derived when
    `_fill_signature(...)` has changed since it was last (re)derived --
    `None` (the default) is a complete no-op, identical to every caller
    that doesn't pass it (every existing direct test call site included).
    Owned by `evaluate_rules_loop`, which declares one fresh dict per
    turn and threads it through every pass, so the gate only ever
    suppresses redundant re-derivation WITHIN one turn's passes, never
    across turns (pass 0 of a new turn always has an empty dict to
    compare against, so it always re-attempts derivation).

    _signature_exclude_vns — docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_
    2026_08_19.md (RC3, 2026-08-24): optional; variable names to leave
    out of `_fill_signature(...)`'s snapshot of `filled`/`filled_multi`.
    `None` (the default) is a complete no-op. Exists because a small,
    provably non-converging subset of attributes (e.g. a real Data-Table
    pairing conflict that `_invalidate_inconsistent_paired_values`
    re-evicts every single pass without ever resolving) would otherwise
    change the WHOLE-dict signature every pass for every OTHER
    `default_first_available` attribute too, defeating
    `_default_fill_signatures`'s gate for the entire turn even though
    only a handful of attributes are actually still in flux. Owned by
    `evaluate_rules_loop`, which grows this set only once the SAME
    invalidated set repeats across two consecutive passes -- a genuinely
    still-narrowing attribute (a different set pass over pass) is never
    added, so it keeps getting a fresh signature every pass as before.

    hiding_rules — docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_
    PLAN_2026_08_10.md: optional; when supplied, a pending-bound attr
    whose ONLY hiding rule structurally depends on a confirmed-absent
    data table (`_KNOWN_MISSING_DATA_TABLES`) is warned-and-skipped
    instead of asked forever. `None` (the default) is a complete no-op,
    identical to every caller that doesn't pass it.

    product_anchor_hint — the customer's own original wording (e.g.
    "I want APX 3000 for United States", CpqSession.product_anchor_
    question) — optional, `None` (default) keeps every existing
    caller's behavior unchanged. Only consulted by the Hardware
    Version decision-attr check below (see _hardware_version_
    confirmed_not_applicable's own docstring); a device this hint
    can't confidently resolve, or one where real attrSequence data
    doesn't rule it out, leaves Hardware Version exactly as mandatory
    as it always was.

    workspace_id — optional; when supplied, an attribute whose only
    governing rule is script-based and failed to resolve
    (`_NEVER_GUESS_SCRIPT_GOVERNED`) gets one more real-data attempt via
    `data_table_resolver.py` before falling through to pending
    (docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md
    §11-§12) — real ingested Oracle CPQ Data Table rows, not a guess.
    `None` (the default) skips this tier entirely, identical to
    pre-existing behavior for every caller that doesn't pass it.
    catalog_prefix — forwarded to the same lookup for workspaces
    holding more than one ingested catalog (see `_catalog_prefix`).

    display_order — optional {variable_name: rank} from
    `load_layout_display_order` (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_
    PLAN.md §2c). When supplied: (a) the returned `pending` list is
    sorted by rank instead of catalog/discovery order, so questions
    get asked in the same sequence the real native UI shows them; (b)
    only `is_decision_attr` anchors (Country/Region/Hardware
    Version/Product) and grid-linked selectors reach `pending` at all
    — every other attr the final ask-branch would otherwise have
    asked about is instead SKIPPED (left entirely unfilled, not
    defaulted-empty) when nothing upstream (hint/recommendation/
    default) resolved it. Sibling-forced re-asks
    (`enforce_exclusive_sibling_families`) are a separate code path
    and are unaffected either way. `None` (the default) keeps today's
    "ask everything with options" behavior completely unchanged.

    Priority order (first match wins):
      1. Already filled in a prior turn.
      2. User-stated value matched from NL hints.
      3. A `rec_rules` recommendation targeting this exact attr whose
         condition is ALREADY satisfied by the current `filled` state
         (via `_satisfied_recommendation`) — checked BEFORE the generic
         XML default_value below, because a targeted, condition-matched
         recommendation is more specific than a catalog-wide default and
         must win over it. Without this, an attr with a non-empty
         default_value got locked in by step 4 unconditionally, before
         `apply_recommendation_rules()` (which runs later in
         `evaluate_rules_loop` and never revisits an attr already in
         `filled`) ever got a chance to apply (confirmed live:
         solutionTypeDevices_astro's own default_value silently beat
         the "Set CLOUD RC as default value" rule this way).
      4. Valid default_value from XML (not None/null/0).
      5. Rule-governed default-or-first (D2/§3) — only for attrs in
         `governed_ids`; everything else falls through to (6). Before
         falling to "first by order", re-checks `_satisfied_recommendation`
         (same helper as step 3, needed here for attrs with NO
         default_value at all, which skip step 3's `attr.options` guard
         only when they still lack a value) — if so, uses that value
         instead. Without this check, a rule-governed attr whose real
         recommendation condition happens to already be true this same
         pass still got the blind first-option pick here (this method
         runs before `apply_recommendation_rules()` in
         `evaluate_rules_loop`), permanently locking in the wrong value
         since neither mechanism revisits an attr already in `filled`
         (confirmed live: hWVersion_astro's region=NA recommendation
         never fired because first-by-order claimed it first).
      6. First eligible item_value by order_number, but ONLY when exactly
         one option remains after constraint filtering (NO EAGER
         EVALUATION — Issue 6's "Stop and Wait" safeguard for anything
         not rule-governed).

    constrained_opts — {entity_id: [allowed_item_values]} from active
      ConstraintRules. When set, first-option fallback only picks from the
      allowed set; hint/default paths ignore constraints (they were validated
      by the rule that produced the recommendation).
    governed_ids — entity_ids eligible for step 4 (see governed_target_ids).
    rule_governed_ids — the strict rule-only subset of governed_ids (see
      rule_governed_ids()); used only to tag filled_source as "rule" vs
      "optional" (Phase N/K) for step-4 fills. Defaults to governed_ids
      itself when omitted, i.e. every step-4 fill is tagged "rule" —
      the pre-Phase-N behavior for callers not yet passing it.
    country — confirmed country text (session.country), used ONLY to
      derive region-pattern decision-key attrs via `derive_region()`
      before they fall to the normal "always ask" path. "country"
      itself is unaffected — it's still asked as before (D1). No match
      (unmapped country, or catalog offers no matching code) falls
      through to asking, same as if `country` were omitted.
    negated_vns — variable_names from extract_catalog_hints() whose
      concept was explicitly negated in the question (see that method's
      docstring). Step 4's blind first-by-order fallback is skipped for
      these — ask instead of risking the literal opposite of what was
      requested.

    select_type handling within step 4:
      - single/boolean: default_value if present, else first option by
        order (boolean's "first option" is well-defined — only two states).
      - multi, non-required: an active constraint narrowing to EXACTLY
        ONE remaining option is auto-filled (written to filled_multi),
        same certainty threshold as single-select's "exactly one
        choice" case (confirmed live, docs/CPQ_MULTISELECT_AUTOFILL_
        OVERSELECTION_PLAN_2026_08_05.md: a near-universally-true
        constraint narrowing a menu to 9 of 11 options is not a
        recommendation to select all 9 — auto-selecting all 9 there
        was the original bug). Narrowing to SEVERAL remaining options
        (still ambiguous) prefers the XML default_value when it's
        still one of the currently-valid options; with no matching
        default, defaults to empty rather than asking — an explicit
        product decision (same plan doc's "explicit product decision"
        addendum) to favor fewer conversational questions over asking
        about every unresolved optional multi-select, accepting the
        known, documented risk that a sibling rule keyed on "does NOT
        contain value X" may treat that default-empty as a genuine
        confirmed answer.

    Returns:
      filled         — {variable_name: item_value} for API payload
      display_filled — {variable_name: display_name} shown to sales rep
      pending        — attrs that still need a human answer

    filled_multi is updated in place (via the `filled_source` pattern) if
    `already_filled_multi` is supplied; otherwise multi-select governed
    auto-fills are silently skipped (caller opted out of multi-select).
    An existing multi-selection is re-validated against a NEW active
    constraint each call — members no longer allowed are dropped and
    named in `dropped_multi` (in place) rather than silently vanishing
    (§5 — same bug class as the Region=NA payload-drop fix).

    skip_always_ask — variable_names whose normal always-ask override
    (e.g. productSelectionProduct_all, §3c) should NOT force a question
    this call, because the caller already confirmed via
    resolve_ui_layout_scope() that the real native UI never shows this
    field for the active configuration flow (exactly one active
    rule_type=6 flow resolved, and this attr isn't in it — see
    docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5). Empty/None
    changes nothing — every catalog where the flow is ambiguous (e.g.
    APX Next, 2 active flows) keeps today's unchanged always-ask
    behavior.
    """
    ctx, scope = auto_fill_setup.build_fill_context_and_scope(
        engine, attrs, hints, already_filled, constrained_opts, filled_source,
        governed_ids, already_filled_multi, dropped_multi, rule_governed_ids,
        country, rec_rules, negated_vns, skip_always_ask, bml_eval,
        validation_rules, display_order, workspace_id, catalog_prefix,
        _dt_cache, hiding_rules, _default_fill_signatures, _signature_exclude_vns,
        grid_declined_vns, product_anchor_hint,
    )

    for attr in attrs:
        auto_fill_resolve.resolve_one_attr(engine, attr, ctx, scope)

    engine._resolve_pointer_defaults(attrs, ctx.filled, ctx.display_filled, ctx.sources)
    pending = engine._cascade_fill_pending(ctx.pending, ctx.filled, ctx.display_filled, ctx.sources)

    # Hardware-based catalogs: country/region -> Hardware (mandatory) ->
    # other attrs -> Product last; Product deferred until Hardware filled.
    pending = engine._order_pending_hardware_before_product(
        pending, ctx.filled, attrs, display_order=display_order,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix,
        cache=_dt_cache, product_anchor_hint=product_anchor_hint,
    )

    # dev-rv-msi #362: drop attrs confirmed never-applicable to the device
    # resolved from the customer's wording (one-sided; flagged).
    if get_settings().cpq_not_applicable_guard_enabled:
        pending = engine._attrs_confirmed_not_applicable_for_hint(
            pending, product_anchor_hint, workspace_id, catalog_prefix, _dt_cache,
        )

    return ctx.filled, ctx.display_filled, pending
