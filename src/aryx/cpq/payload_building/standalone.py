"""Standalone (non-conversational) BOM payload assembly (Phase 4 step 8
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Pure orchestration over ``CpqEngine``'s own loaders/`evaluate_rules_loop`
/`build_payload`, so every collaborator is reached through the passed-in
`engine` instance exactly as the original ``self.<name>(...)`` calls did
-- instance-level and class-level patches both stay honored, and
`build_payload` (deliberately deferred for its own decomposition) is
left entirely untouched.
"""

from __future__ import annotations

from typing import Any


def build_standalone_payload(
    engine: Any,
    reader: Any,
    workspace_id: int,
    product_hint: str,
    filled: dict[str, str],
    filled_multi: dict[str, list[str]] | None = None,
    hints: dict[str, str] | None = None,
    country: str | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Assemble a correct BOM payload OUTSIDE a live conversational
    turn, with the SAME defaulting and ordering guarantees a live turn
    gets — the structural fix for docs/APX_Next_RootCause_And_Fix_
    Report Issue 1 ("no path sets a rule-driven attr when a payload is
    assembled directly") and Issue 2 (payload key ordering).

    A live conversational turn (ask_api.py's per-turn handler) already
    calls evaluate_rules_loop (hide -> recommend -> constrain -> auto-
    fill until stable) before build_payload — that loop is what
    actually populates rule-driven attrs like a recommendation-rule
    target. A payload assembled directly by a script has historically
    skipped straight to something payload-shaped without ever running
    it, silently missing every attr only that loop can fill. This
    method runs the identical loop (empty `hints={}` is a valid,
    supported input — hints normally come from conversational text via
    extract_flag_hints/extract_catalog_hints, but evaluate_rules_loop
    itself has no dependency on conversation state) then calls
    build_payload with `rules` populated for dependency-aware ordering,
    so both issues are fixed by one call for any standalone caller.

    Returns (payload, unresolved). `unresolved` is
    find_unresolvable_context_attrs' output: every attr still missing
    that NO rule could ever fill (the genuine customerType-class gap —
    never guessed, always surfaced instead of silently omitted). An
    empty `unresolved` list does not guarantee the payload is complete
    against every catalog requirement — only that nothing MORE could
    have been resolved automatically without guessing.

    Catalog-agnostic: attrs/rules/scripts are all loaded fresh from
    `reader`/`workspace_id` via the same generic loaders every other
    catalog-facing method here uses — no attribute or rule name is
    hardcoded, and this works identically for any ingested BM export.
    """
    attrs, resolved_product_name = engine.load_product_config(
        reader, workspace_id, product_hint)
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    hiding_rules = engine.load_hiding_rules(workspace_id, catalog_prefix, resolved_product_name)
    rec_rules, con_rules = engine.load_recommendation_and_constraint_rules(
        workspace_id, catalog_prefix)
    bml_eval = engine.build_bml_evaluator(workspace_id, catalog_prefix)

    working_filled = dict(filled)
    working_multi = dict(filled_multi or {})
    visible_attrs, working_filled, _display_filled, _constrained_opts = engine.evaluate_rules_loop(
        attrs, hints or {}, working_filled, hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_multi=working_multi, country=country,
    )

    payload = engine.build_payload(
        working_filled, None, working_multi, visible_attrs,
        rules=[*hiding_rules, *rec_rules, *con_rules],
    )
    unresolved = engine.find_unresolvable_context_attrs(
        visible_attrs, working_filled, workspace_id, catalog_prefix,
        rec_rules, con_rules,
    )
    return payload, unresolved
