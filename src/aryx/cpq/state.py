"""CPQ session state — serialisable so the UI can echo it back each turn."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class HidingRule:
    """One declarative hiding rule from the graph (rule_type=11, condition_type=1).

    condition_attr_id  — entity_id of the BmConfigAttr whose value is checked.
    condition_value    — the value that triggers this rule (from BmConfigRuleInput.value1).
    target_attr_id     — entity_id of the BmConfigAttr to hide/show.
    hide               — True = hide the target when condition is met; False = show.
    rule_name          — human-readable rule name for reporting.
    """
    rule_name: str
    condition_attr_id: int
    condition_value: str
    target_attr_id: int
    hide: bool = True


@dataclass
class RecommendationRule:
    """One declarative recommendation rule (rule_type=10, condition_type=1).

    When condition_attr equals condition_value, the engine auto-selects
    recommended_value for target_attr (if target is not already filled).
    Only declarative rules (condition_function_id=-1) are loaded.
    """
    rule_name: str
    condition_attr_id: int
    condition_value: str
    target_attr_id: int
    recommended_value: str  # item_value to auto-select on the target attr


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
    """
    rule_name: str
    condition_attr_id: int
    condition_value: str
    target_attr_id: int
    allowed_values: list[str]  # item_values that remain valid when condition fires
    script: str | None = None  # raw BML — evaluated dynamically when set


@dataclass
class MenuOption:
    """One selectable value for a configuration attribute."""

    item_value: str    # API backend code sent to CPQ BOM API (e.g. "US")
    display_name: str  # Friendly label shown to the sales rep (e.g. "United States")
    order: int = 999


@dataclass
class ConfigAttr:
    """One configuration attribute extracted from the knowledge graph."""

    entity_id: int
    variable_name: str   # CPQ backend key (e.g. "hWVersion_astro")
    display_label: str   # Human label shown in conversation
    required: bool
    default_value: str
    options: list[MenuOption]  # empty → free-text input
    order: int = 999
    tier: str = "independent"  # "independent" | "dependent"
    # Source-native id (e.g. BigMachines attribute id from the ingested XML).
    # Rule inputs/actions reference attributes by THIS id, not by the aryx
    # entity_id — rule joins must resolve through both.
    source_id: int | None = None
    # "single" (dropdown/radio, one value) | "multi" (checkbox, allowed set
    # from rules) | "boolean" (fixed Yes/No, no menu options at all).
    # Derived from BM attribute metadata — see classify_select_type() in
    # engine.py (CPQ_CASCADE_CONVERSATION_PLAN.md §4).
    select_type: str = "single"
    # Source-derived catalog prefix (see engine._catalog_prefix), e.g.
    # "ApxNextConfig" or "Sl3500EConfig" — "" when unresolved. Lets rule
    # loaders scope to the same ingested catalog this attr came from, so a
    # workspace holding more than one product's XML export never lets one
    # catalog's rules act on another's attributes.
    catalog_prefix: str = ""
    # True for BM attrs flagged hidden=1 in the source XML — never shown to
    # the customer or added to `pending`, but still eligible for its own
    # default_value (BML scripts elsewhere may reference it) instead of
    # being dropped from the graph entirely.
    hidden: bool = False


@dataclass
class CpqSession:
    """Accumulated state across all conversation turns.

    Serialised as JSON in the API response so the client can echo it back
    on the next turn — no server-side session store required.
    """

    mode: str = "cpq"
    product_name: str = ""
    product_entity_id: int = 0
    # variable_name → item_value (API code stored, never display label)
    filled: dict[str, str] = field(default_factory=dict)
    # variable_name → list of item_values, for select_type=="multi" attrs.
    # Kept separate from `filled` (str-only) rather than widening its type —
    # multi-select is a minority case; touching every _valid()/apply_answer()/
    # build_payload() call site for it was rejected (CPQ_CASCADE_CONVERSATION_PLAN.md §4).
    filled_multi: dict[str, list[str]] = field(default_factory=dict)
    # variable_name → friendly display label (shown to user in summary)
    display_filled: dict[str, str] = field(default_factory=dict)
    # variable_name → how the value was obtained:
    # "user" (explicit answer) | "hint" (stated in NL) | "cascade" (copied from
    # a validated sibling) | "rule" (recommendation rule) | "default" |
    # "auto" (single-remaining-option). build_payload keeps none-like codes
    # (e.g. Region="NA") for user-confirmed sources instead of dropping them.
    filled_source: dict[str, str] = field(default_factory=dict)
    # variable_names not yet answered
    pending_variables: list[str] = field(default_factory=list)
    turn: int = 0
    complete: bool = False
    # "configuring" → active guided flow
    # "awaiting_approval" → all attrs filled; showing Step 6 review; user must confirm or change
    # "approved" → user confirmed; BOM payload generated (Step 8)
    status: str = "configuring"
    # "" | "product" | "country" — which anchor Step 1 is currently waiting
    # on, so the NEXT turn's raw reply can be treated as a direct answer for
    # that anchor even when it doesn't match the general NL hint patterns
    # (e.g. a bare "United States" with no "customer in ..." wrapper).
    pending_anchor: str = ""
    # Resolved destination country (anchor). Persisted separately from
    # `filled` because it's needed for the anchor gate itself, before any
    # config attrs are even loaded.
    country: str = ""
    # "verbose" (default) | "json_only" — content axis: JSON is shown ONLY
    # when the client explicitly asks for it; verbose is always the default,
    # never inferred the other way (CPQ_CASCADE_CONVERSATION_PLAN.md §6.1).
    response_mode: str = "verbose"
    # "sequential" (default) | "batched" — delivery axis: pending questions
    # are shown one at a time unless the client explicitly asks to see all
    # of them at once. Per-turn, not sticky (§6.2).
    question_mode: str = "sequential"
    # Cascade delta log — one entry per value change, so later turns can
    # explain "why" from what actually happened rather than re-deriving it
    # from the current rule set alone (§7). Each entry:
    # {"var": ..., "old": ..., "new": ..., "rule": ..., "turn": ...}.
    cascade_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CpqSession":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
