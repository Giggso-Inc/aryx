"""CPQ rule dataclasses — Hiding, Recommendation, Constraint, and Validation
rules loaded from the graph's BmConfigRuleInput/Action rows.

Split out of `cpq/state.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class HidingRule:
    """One hiding rule from the graph (rule_type=11).

    Declarative form: condition_attr_id/condition_value/hide describe a
    simple equality check (from BmConfigRuleInput.value1).

    Script form (BML): ``script`` holds the raw BML body from the referenced
    BmFunction — confirmed live that ~62% of real hiding rules in this
    catalog are script-backed (their hide/show logic depends on more than
    one variable, e.g. "hide unless region=NA OR country=KY OR
    customerType=FEDERAL"), not the single condition_attr/condition_value
    pair the declarative form can express. At apply time the evaluator
    derives a bool from the current filled variables (see
    BmlEvaluator.should_hide); condition_attr_id/condition_value are unused
    when script is set (the script embeds its own conditions).

    condition_attr_id  — entity_id of the BmConfigAttr whose value is checked (declarative only).
    condition_value    — the value that triggers this rule (declarative only).
    condition_operator — the raw BM-native operator code for the
        condition_attr_id/condition_value pair above ("4" = "=", the
        default/majority code — see conditions' docstring below for the
        full mapping). Only meaningful when conditions is None/empty.
    target_attr_id     — entity_id of the BmConfigAttr to hide/show.
    hide               — True = hide the target when condition is met; False = show (declarative only).
    rule_name          — human-readable rule name for reporting.
    conditions         — ALL of this rule's real bm_config_rule_input rows, as
        [(attr_id, value, operator), ...] — same attr_id repeated means OR
        (any of those values matches for that attribute); different
        attr_ids are ANDed together. None/empty falls back to the single
        condition_attr_id/condition_value/condition_operator triple
        (backward compatible with rules that only ever had one input).
        Confirmed live: 445/688 rules in a real catalog carry 2+ input
        rows that the old single-pair shape silently collapsed to just
        the last one — see docs/CPQ_APX_NEXT_RULE_CATALOG.md "Gap
        Deep-Dive & Impact Analysis".

        operator is the raw BM-native comparison-operator code, confirmed
        (docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md) via
        cross-referencing 31 independently-authored rule names against
        their raw operator1 values: "4"="=" (74.5% of real rows, the
        previously-assumed default), "3"="<>" (18%, confirmed 31/31),
        "1"="<", "2"="<=", "5"=">" (all high-confidence, low-volume).
        "7"="intersects"/"8"="disjoint from" (Phase 2, confirmed via
        104/110 real rows targeting a select_type=="multi" attribute plus
        4 independently-authored rule-name cross-checks with zero
        contradictions — see bml._operator_hit's docstring for the
        confirmed rule examples). For "7"/"8" the attribute's current
        value is itself allowed to be a "~"-joined set (a multi-select
        attr's current selections), checked via set intersection rather
        than scalar equality. Before the Phase 1 fix, every operator was
        silently treated as "=" — e.g. a real rule named "...For Non
        Federal" with operator "3" (<>) against "FEDERAL" was being
        evaluated as customerType=="FEDERAL" instead of
        customerType<>"FEDERAL", inverting its intent.
    """
    rule_name: str
    condition_attr_id: int
    condition_value: str
    target_attr_id: int
    hide: bool = True
    script: str | None = None
    conditions: list[tuple[int, str, str]] | None = None
    condition_operator: str = "4"
    dt_whitelist_substitute: bool = False
    """True for a narrow, explicitly-named set of "...If No Value(s)
    Available"-shaped hiding rules whose BmFunction script is missing from
    ingestion (docs/APX900_Hybrid_Combiner_Missing_Script_Issue.md) --
    substitutes a real Data Table whitelist check (resolve_whitelist_values)
    for the missing script's condition, rather than dropping the rule
    entirely (see CpqEngine.load_hiding_rules/apply_hiding_rules). Never set
    generically -- only for rule names this codebase has individually
    confirmed follow the "hide when no legal value is available right now"
    semantics via live evidence, the same discipline _CONFIRMED_DEAD_ATTRS
    and similar named carve-outs elsewhere in engine.py already use."""
    ref_id: str = ""  # BmCatalog node this rule is scoped to ("" = unbound/unknown); cpq/rule_scope.py
    always: bool = False
    """True for a declarative rule that has NO condition rows at all: Oracle
    treats it as always true (plan F10, flag `cpq_empty_condition_rule_true_
    enabled`). Never set for scripted rules or rules that have inputs."""
    master_writers: list[Any] | None = None
    """Plan F9 (flag `cpq_master_string_hide_enabled`): the recommendation
    rules whose action WRITES a master string this script reads, attached at
    load time. None (always, flag off) = old behaviour."""


@dataclass
class RecommendationRule:
    """One declarative recommendation rule (rule_type=10, condition_type=1).

    When condition_attr equals condition_value, the engine auto-selects
    recommended_value for target_attr (if target is not already filled).

    Script form (BML): ``script`` holds the raw BML body from the referenced
    BmFunction. At apply time the evaluator derives the recommended value
    from the current filled variables (Tier-1 if/else `returnVal="X"` idiom,
    same evaluator ConstraintRule uses); condition fields are unused (the
    script embeds its own conditions on variable names). Gated identically
    to ConstraintRule's script form: an unknown/unresolvable script outcome
    never fills anything (D2 "never guess").

    condition_script — distinct from ``script`` above. This rule's own
    condition_function_id is a BML boolean script (not the single
    condition_attr_id/condition_value pair) while the ACTION is declarative
    (recommended_value is a plain value, not derived from a script). At
    apply time the evaluator runs this through the same boolean Tier-1/
    Tier-2 machinery apply_hiding_rules already uses via
    BmlEvaluator.hide_for_script (True = rule fires, unknown = never guess,
    doesn't fire). Mutually exclusive with ``script`` in practice — a rule
    with both a script condition AND a script action is handled by
    ``script`` alone (see CpqEngine._load_value_rules).

    conditions — see HidingRule.conditions; same AND-of-OR-groups semantics
    and same operator mapping for declarative multi-input rules.
    """
    rule_name: str
    condition_attr_id: int
    condition_value: str
    target_attr_id: int
    recommended_value: str = ""  # item_value to auto-select on the target attr
    script: str | None = None
    conditions: list[tuple[int, str, str]] | None = None
    condition_script: str | None = None
    writer_conditions: list[tuple[int, str, str]] | None = None
    """A script-backed rule's own declarative inputs (flag `cpq_script_rec_rule_conditions_enabled`). Read ONLY by the
    master-string writer test; kept apart from `conditions` so rule ranking and the dependency graph, which read
    `conditions`, see the same rule as before."""
    condition_operator: str = "4"
    ref_id: str = ""  # BmCatalog node this rule is scoped to ("" = unbound/unknown); cpq/rule_scope.py


@dataclass
class ConstraintRule:
    """One constraint rule (rule_type=5).

    Declarative form: when condition_attr equals condition_value, only
    allowed_values remain valid item_values for target_attr. Multiple
    ConstraintRules for the same target are intersected (AND semantics).

    Script form (BML): ``script`` holds the raw BML body from the referenced
    BmFunction. At apply time the evaluator derives allowed_values from the
    current filled variables; condition fields are unused (the script embeds
    its own conditions on variable names).

    condition_script — see RecommendationRule.condition_script: the rule's
    own condition is a BML boolean script while allowed_values is a plain
    declarative list. Evaluated via BmlEvaluator.hide_for_script the same way.
    """
    rule_name: str
    condition_attr_id: int
    condition_value: str
    target_attr_id: int
    allowed_values: list[str]  # item_values that remain valid when condition fires
    script: str | None = None  # raw BML — evaluated dynamically when set
    conditions: list[tuple[int, str, str]] | None = None  # see HidingRule.conditions
    condition_script: str | None = None
    condition_operator: str = "4"
    mode: str = ""
    """"" = `allowed_values` is the allow-list (legacy). "ALLOW" / "DISALLOW" come
    from a `setConstraintValuesInSession` action (plan F2, flag `cpq_constraint_
    mode_enabled`); for "DISALLOW" the listed values are removed from the options."""
    guard_attr: str = ""
    """Variable that must hold a value for a mode-carrying action to run at all."""
    blank: bool = False
    """The action's literal list contains the empty string: with mode "DISALLOW" the
    blank value itself is not allowed, i.e. the attribute is required (plan F6)."""
    ref_id: str = ""  # BmCatalog node this rule is scoped to ("" = unbound/unknown); cpq/rule_scope.py


@dataclass
class ValidationRule:
    """A warning-message rule with no value action at all (Amendment 12,
    docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md) — a genuinely distinct
    fourth rule shape from Hiding/Recommendation/Constraint, never modeled
    before this. Its BmConfigRuleAction has function_id=-1 (not
    script-backed) AND an empty value1 — it neither hides, sets, nor
    restricts anything; its only content is a human-readable `message`
    attached to `target_attr_id`, to be shown when its condition
    (`condition_script` OR `conditions`) evaluates True.

    Confirmed live: CommandCentral Aware's "Constrain video devices" rule
    (target OfVideoStreamingDevices_3_swSoln) checks
    `fmod(value, 25) <> 0` and attaches "Please enter a qty in multiple of
    25. Eg. 25...50...75..125.." — a real, catalog-authored validation
    message that existed in the source data but was silently dropped by
    every existing rule loader (Hiding requires rule_type=11 exclusively;
    Recommendation/Constraint's declarative-action branch requires a
    non-empty value1 to bucket by set_type — this rule's action has
    neither), because none of them model "condition true -> show this
    message, no value change" at all.

    docs/CPQ_CONDITIONAL_REQUIRED_RULE_PLAN_2026_08_05.md — the same
    message-only shape also occurs with a purely DECLARATIVE condition
    (no condition_function_id at all), e.g. "Restrict Number Of Seats
    between 1 and 12" -> message "Number Of Seats must be between 1 and
    12", gated on numberOfSeats_astro < 1 OR > 12 (operators "1"/"5",
    confirmed docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md).
    Confirmed via a 4-catalog audit: 138/150 real "set_type=-1, no value1"
    action rows carry a genuine, non-boilerplate message — this was
    explicitly anticipated but deferred in the loader (see
    _load_value_rules's own historical comment) pending exactly this
    confirmation. condition_attr_id/condition_value/condition_operator/
    conditions mirror HidingRule's identically-named fields; exactly one
    of condition_script / conditions is set per instance, same convention
    as HidingRule/ConstraintRule/RecommendationRule.

    Same D2 "never guess" discipline as every other rule here: an
    unknown/unresolvable condition (script OR declarative) never fires.
    """
    rule_name: str
    target_attr_id: int
    message: str
    condition_script: str | None = None
    condition_attr_id: int = 0
    condition_value: str = ""
    condition_operator: str = "4"
    conditions: list[tuple[int, str, str]] | None = None
    ref_id: str = ""  # BmCatalog node this rule is scoped to ("" = unbound/unknown); cpq/rule_scope.py
