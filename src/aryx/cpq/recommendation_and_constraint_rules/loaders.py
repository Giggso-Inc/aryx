"""The four thin ``_load_value_rules`` projections -- recommendation,
constraint, validation, and the both-at-once pass (Phase 4 step 6
extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Each one is a single projection of ``CpqEngine._load_value_rules``' 4-tuple,
so all four take the ``engine`` instance and call it back through the
instance -- ``_load_value_rules`` is itself deliberately still on
``CpqEngine`` (oversized, awaiting its own decomposition) and several
tests replace it per-instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.state import ConstraintRule, RecommendationRule, ValidationRule

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.engine import CpqEngine


def load_recommendation_and_constraint_rules(
    engine: CpqEngine, workspace_id: int, catalog_prefix: str = "",
) -> tuple[list[RecommendationRule], list[ConstraintRule]]:
    """Both rule sets in a single pass — the call callers wanting BOTH
    should use. load_recommendation_rules()/load_constraint_rules() each
    independently call _load_value_rules(), which repeats the same 4
    join-table queries plus a full function-script scan; calling both
    back-to-back (as every CPQ turn does) doubles that DB work for no
    reason. Prefer this method whenever both lists are needed.

    Return arity deliberately unchanged (still a 2-tuple) — widely
    monkeypatched across the test suite with a bare `(rec, con)` stub;
    the value-less-action hiding rule subset (docs/CPQ_VALUELESS_HIDE_
    ACTION_LOADING_GAP_PLAN_2026_08_05.md) is folded into
    load_hiding_rules() instead, so every existing caller/mock of
    EITHER method keeps working unchanged."""
    rec_rules, con_rules, _validation_rules, _extra_hiding_rules = (
        engine._load_value_rules(workspace_id, catalog_prefix))
    return rec_rules, con_rules


def load_validation_rules(
    engine: CpqEngine, workspace_id: int, catalog_prefix: str = "",
) -> list[ValidationRule]:
    """Warning-message rules (Amendment 12) for this catalog — see
    ValidationRule's own docstring and _load_value_rules for how these
    are distinguished from Hiding/Recommendation/Constraint rules.
    Shares _load_value_rules' fetch with load_recommendation_and_
    constraint_rules — call both only when genuinely needed, same
    double-fetch caveat as load_recommendation_rules."""
    _rec_rules, _con_rules, validation_rules, _extra_hiding_rules = (
        engine._load_value_rules(workspace_id, catalog_prefix))
    return validation_rules


def load_recommendation_rules(
    engine: CpqEngine, workspace_id: int, catalog_prefix: str = "",
) -> list[RecommendationRule]:
    """Recommendation rules for this catalog — see _load_value_rules for
    how rule semantics are classified (NOT by rule_type/action_type).
    If you also need constraint rules, call
    load_recommendation_and_constraint_rules() instead to avoid fetching
    the same rule data twice."""
    rec_rules, _con_rules, _validation_rules, _extra_hiding_rules = (
        engine._load_value_rules(workspace_id, catalog_prefix))
    return rec_rules


def load_constraint_rules(
    engine: CpqEngine, workspace_id: int, catalog_prefix: str = "",
) -> list[ConstraintRule]:
    """Constraint rules for this catalog — declarative AND script.

    See _load_value_rules for how rule semantics are classified (by
    each action's set_type, NOT by rule_type/action_type — neither
    matches real data in either ingested catalog). Script-form actions
    (function_id != -1) get the raw BML script attached; allowed values
    are derived at apply time by the BML evaluator from the current
    filled variables. If you also need recommendation rules, call
    load_recommendation_and_constraint_rules() instead to avoid
    fetching the same rule data twice.
    """
    _rec_rules, con_rules, _validation_rules, _extra_hiding_rules = (
        engine._load_value_rules(workspace_id, catalog_prefix))
    return con_rules
