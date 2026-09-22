"""Feature-aware graph search — Phase 1 of the feature/region search plan.

find_entities(attrs=...) (see reader.py) finds candidates by static
attribute value alone. That's not the whole picture: a candidate can match
on paper and still be one CpqEngine's hiding rules would suppress for a
given product (confirmed live: 62% of real hiding rules in a real catalog
are script-backed BML conditions, not simple declarative ones -- see
CpqEngine.load_hiding_rules' own docstring). search_by_feature() composes
the two: find candidates, then check each product-configurable candidate
against its own hiding rules with an empty/caller-supplied `filled` dict,
so a caller can tell "matches, and visible by default" apart from
"matches, but a rule would hide it."

Verified session-free (2026-09-15): CpqEngine.load_product_config,
load_hiding_rules, build_bml_evaluator, and apply_hiding_rules all accept
plain (reader, workspace_id, ...) arguments -- no live configuration
session/transaction object anywhere in the chain. build_bml_evaluator's
Tier-2 LLM fallback is gated by settings.bml_use_llm (default False), so
calling it here does not introduce unexpected LLM cost by default.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.data_table.data_table_resolver import (
    search_products_by_feature,
    search_products_by_region,
)
from aryx.cpq.engine import CpqEngine


def search_by_feature(
    reader: Any,
    engine: CpqEngine,
    workspace_id: int,
    ontology_type: str | None = None,
    name: str | None = None,
    attrs: dict[str, str] | None = None,
    filled: dict[str, str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find entities by type/name/attribute, annotated with hiding-rule status.

    filled -- optional {variable_name: value} of hypothetical prior answers
    to evaluate hiding rules against (e.g. {"customerType": "Federal"} to
    answer "would this be hidden for a federal customer"). Defaults to {},
    which evaluates every rule's safe default ("not enough info -> don't
    hide") -- a legitimate but weaker answer ("hidden by default"), not an
    error.

    Returns each matched entity's normal find_entities() fields plus:
      hidden_by_rule: bool -- True if a hiding rule fires against `filled`
        for this entity's own product context, False otherwise, None if
        this entity isn't part of a CPQ-configurable product (no
        product-level rules apply -- most graph entities aren't).
      hiding_rule_names: list[str] -- names of rules that fired, if any.
    """
    candidates = reader.find_entities(
        ontology_type=ontology_type, name=name, attrs=attrs, limit=limit,
    )
    filled = filled or {}
    results: list[dict[str, Any]] = []

    for entity in candidates:
        product_hint = entity.get("name") or ""
        annotated = dict(entity, hidden_by_rule=None, hiding_rule_names=[])
        if not product_hint:
            results.append(annotated)
            continue
        try:
            product_attrs, resolved_name = engine.load_product_config(
                reader, workspace_id, product_hint,
            )
        except Exception:
            # Not every matched entity is a configurable product (could be
            # a bare attribute, a data-table row, etc.) -- that's expected,
            # not a failure to surface to the caller.
            results.append(annotated)
            continue
        if not product_attrs:
            results.append(annotated)
            continue

        catalog_prefix = product_attrs[0].catalog_prefix or ""
        hiding_rules = engine.load_hiding_rules(workspace_id, catalog_prefix)
        if not hiding_rules:
            # Confirmed configurable product, just zero hiding rules apply
            # to it -- definitively "not hidden" (False), distinct from
            # "not a configurable product at all" (None) above.
            annotated["hidden_by_rule"] = False
            results.append(annotated)
            continue

        bml_eval = engine.build_bml_evaluator(workspace_id, catalog_prefix)
        _visible_attrs, rule_messages, hidden_vns = engine.apply_hiding_rules(
            product_attrs, filled, hiding_rules, bml_eval=bml_eval,
        )
        target_vn = None
        for a in product_attrs:
            if a.variable_name == product_hint or a.display_label == product_hint:
                target_vn = a.variable_name
                break
        annotated["hidden_by_rule"] = bool(target_vn and target_vn in hidden_vns)
        annotated["hiding_rule_names"] = rule_messages
        annotated["resolved_product_name"] = resolved_name
        results.append(annotated)

    return results


def _join_key(raw: Any) -> str | None:
    """Normalize a model/product name for cross-source matching -- the
    same string, case/whitespace-insensitive, joining a graph entity's
    `name` (search_by_feature's own product_hint) against a Data Table
    row's `model` column. Returns None for anything that isn't a
    non-empty string, so callers never join on an empty/garbage key."""
    text = str(raw or "").strip()
    return text.upper() if text else None


def search_products_combined(
    reader: Any,
    engine: CpqEngine,
    workspace_id: int,
    *,
    region: str | None = None,
    feature_label: str | None = None,
    feature_value: str | None = None,
    ontology_type: str | None = None,
    name: str | None = None,
    attrs: dict[str, str] | None = None,
    cpq_model: str | None = None,
    filled: dict[str, str] | None = None,
    limit: int = 50,
    catalog_prefix: str = "",
) -> list[dict[str, Any]]:
    """Phase 2 merge: combine Phase 1 (graph) and Phase 2 (Postgres Data
    Table) search results on a shared model-name join key.

    Per Phase2_DataTable_Schema_Audit.md §4 step 4: the two searches key on
    different identifiers (graph entity `name` vs. Data Table `model`), so
    this joins on that name/model string (case/whitespace-insensitive via
    _join_key) rather than assuming either side's identifier scheme.

    Pass `region` and/or (`feature_label` + `feature_value`) to run the
    Postgres-side search (search_products_by_region / search_products_by_
    feature) -- these are the whole reason this merge exists, since Data
    Tables never reach FalkorDB and Phase 1 alone cannot see them. Pass
    `ontology_type`/`name`/`attrs` to ALSO run Phase 1's graph search
    (search_by_feature) and merge its hits in by the same key.

    Every Postgres-side match is additionally cross-referenced against the
    graph by name (a single search_by_feature(name=...) lookup per distinct
    model) so a caller gets graph context (hidden_by_rule, etc.) on a
    Data-Table-only hit without needing to run Phase 1 separately -- this
    is a real N+1 pattern (one extra graph lookup per distinct matched
    model), the same shape search_by_feature's own per-candidate
    load_product_config calls already accept for Phase 1.

    Returns one dict per distinct model, each with:
      model: str -- the join key's original-cased form (first value seen).
      source: list[str] -- any of "graph", "data_table", sorted.
      data_table_matches: list[dict] -- every search_products_by_region/
        search_products_by_feature row for this model, [] if none.
      graph_entity: dict | None -- the matching search_by_feature() result
        for this model, if the model exists in the graph at all.
    """
    filled = filled or {}
    merged: dict[str, dict[str, Any]] = {}

    def _entry(key: str, display_name: Any) -> dict[str, Any]:
        return merged.setdefault(key, {
            "model": display_name, "data_table_matches": [], "source": set(),
        })

    # Phase 2 side first -- the reason this function exists: constraints
    # Phase 1's graph search can never see at all.
    dt_rows: list[dict[str, Any]] = []
    if region:
        dt_rows.extend(
            dict(row, _dt_kind="region")
            for row in search_products_by_region(region, workspace_id, catalog_prefix)
        )
    if feature_label and feature_value:
        dt_rows.extend(
            dict(row, _dt_kind="feature")
            for row in search_products_by_feature(
                feature_label, feature_value, workspace_id,
                cpq_model=cpq_model, catalog_prefix=catalog_prefix,
            )
        )
    for row in dt_rows:
        key = _join_key(row.get("model"))
        if key is None:
            continue
        entry = _entry(key, row.get("model"))
        entry["data_table_matches"].append(row)
        entry["source"].add("data_table")

    # Phase 1 side -- only run when a graph-specific filter is actually
    # given, so a caller who only wants a Postgres-side region/feature
    # search doesn't pay for an unbounded "browse everything" graph scan.
    if ontology_type or name or attrs:
        for candidate in search_by_feature(
            reader, engine, workspace_id, ontology_type=ontology_type,
            name=name, attrs=attrs, filled=filled, limit=limit,
        ):
            key = _join_key(candidate.get("name"))
            if key is None:
                continue
            entry = _entry(key, candidate.get("name"))
            entry["graph_entity"] = candidate
            entry["source"].add("graph")

    # Apply `limit` BEFORE the per-model enrichment loop below, not just to
    # the final return value (PR #331 review, M2): search_products_by_region/
    # search_products_by_feature take no limit of their own and scan their
    # full row set, so without this a broad match (e.g. a common region)
    # against hundreds of models would issue hundreds of synchronous graph
    # round-trips -- one per distinct model -- before any truncation ever
    # happened. dict preserves insertion order (Python 3.7+), so this keeps
    # the first `limit` distinct models encountered across both phases.
    merged = dict(list(merged.items())[:limit])

    # Enrich every Data-Table-only match with graph context, when the
    # model also happens to exist in the graph, so the caller gets one
    # merged view without needing a separate Phase 1 call.
    #
    # name=entry["model"] goes into find_entities' CONTAINS predicate, not
    # an equality match -- candidates[0] under limit=1 used to be accepted
    # unconditionally, meaning a query for "APX1" could silently attach an
    # unrelated entity like "APX100-Pro"'s hidden_by_rule (PR #331 review,
    # M1). Fetch a few CONTAINS candidates instead and only accept the one
    # whose OWN join key matches this entry's key exactly; drop to None
    # (no graph context, source stays data_table-only) if none do.
    for key, entry in merged.items():
        if "graph_entity" in entry:
            continue
        candidates = search_by_feature(
            reader, engine, workspace_id, name=entry["model"], filled=filled, limit=5,
        )
        exact = next(
            (c for c in candidates if _join_key(c.get("name")) == key), None,
        )
        if exact is not None:
            entry["graph_entity"] = exact
            entry["source"].add("graph")

    results = []
    for entry in merged.values():
        entry["source"] = sorted(entry["source"])
        entry.setdefault("graph_entity", None)
        results.append(entry)
    return results
