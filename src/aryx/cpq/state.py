"""CPQ session state — serialisable so the UI can echo it back each turn."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    target_attr_id     — entity_id of the BmConfigAttr to hide/show.
    hide               — True = hide the target when condition is met; False = show (declarative only).
    rule_name          — human-readable rule name for reporting.
    conditions         — ALL of this rule's real bm_config_rule_input rows, as
        [(attr_id, value), ...] — same attr_id repeated means OR (any of
        those values matches for that attribute); different attr_ids are
        ANDed together. None/empty falls back to the single
        condition_attr_id/condition_value pair (backward compatible with
        rules that only ever had one input). Confirmed live: 445/688 rules
        in a real catalog carry 2+ input rows that the old single-pair
        shape silently collapsed to just the last one — see
        docs/CPQ_APX_NEXT_RULE_CATALOG.md "Gap Deep-Dive & Impact Analysis".
    """
    rule_name: str
    condition_attr_id: int
    condition_value: str
    target_attr_id: int
    hide: bool = True
    script: str | None = None
    conditions: list[tuple[int, str]] | None = None


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
    for declarative multi-input rules.
    """
    rule_name: str
    condition_attr_id: int
    condition_value: str
    target_attr_id: int
    recommended_value: str = ""  # item_value to auto-select on the target attr
    script: str | None = None
    conditions: list[tuple[int, str]] | None = None
    condition_script: str | None = None


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
    conditions: list[tuple[int, str]] | None = None  # see HidingRule.conditions
    condition_script: str | None = None


@dataclass
class ValidationRule:
    """A warning-message rule with no value action at all (Amendment 12,
    docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md) — a genuinely distinct
    fourth rule shape from Hiding/Recommendation/Constraint, never modeled
    before this. Its BmConfigRuleAction has function_id=-1 (not
    script-backed) AND an empty value1 — it neither hides, sets, nor
    restricts anything; its only content is a human-readable `message`
    attached to `target_attr_id`, to be shown when `condition_script`
    (a BML boolean) evaluates True.

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

    Same D2 "never guess" discipline as every other script-backed rule
    here: an unknown/unresolvable condition never fires.
    """
    rule_name: str
    target_attr_id: int
    condition_script: str
    message: str


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
    # Raw BM set_type code from the source XML ("1" transaction-line,
    # "2" transient UI/action-layer, "3" other). set_type=2 attrs must be
    # EXCLUDED from the BOM API payload — confirmed live: the real CPQ API
    # rejected every set_type=2 attr sent ("has an invalid payload") while
    # accepting identically-shaped set_type=1 menus, and the APX catalog's
    # own set_type=2 population (_price_book_var_name, mergePackage,
    # update, clearPackageJson, ...) shows the layer is transient fields,
    # not transaction attributes. Distinct from select_type (UI shape).
    set_type: str = ""
    # True for BM attrs flagged hidden=1 in the source XML — never shown to
    # the customer or added to `pending`, but still eligible for its own
    # default_value (BML scripts elsewhere may reference it) instead of
    # being dropped from the graph entirely.
    hidden: bool = False
    # True for BM attrs flagged hide_in_trans=1 — the source system's own
    # "don't submit this at transaction/order time" marker (confirmed live
    # against the real CPQ API: productInformationText_astro and
    # productSelectionHelptext_astro both carry this flag and both got
    # "cannot be modified" from the real API when included in a submission
    # payload). Distinct from `hidden` (never shown in the UI) — a field can
    # be visible/computed for display but still excluded from the BOM
    # submission itself; see CpqEngine.build_payload.
    hide_in_trans: bool = False
    # True for BM attrs flagged is_array_control_attr=1 — the source
    # system's own marker that this attr drives a native-UI grid editor
    # (e.g. a mounting-type quantity table), not a plain scalar/menu
    # question. Its real target quantity attrs are typically hidden=1 and
    # sized/populated by a rec/constraint rule conditioned on this control
    # (see docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5 Change B).
    is_array_control: bool = False
    # True for BM attrs flagged auto_lock=1 — confirmed live (docs/
    # CPQ_SESSION_2_OPEN_ISSUES.md, auto_lock double-wrap finding) this
    # overrides the set_type=="2" exclusion in build_payload: a set_type=="2"
    # attr with auto_lock=1 (e.g. archeType_viSoln, modelSelectionSelectModel_
    # viSoln) is a real, includable value that ships double-wrapped
    # ({"value": {"value":..,"displayValue":..}}), not dropped like the
    # genuinely transient set_type=="2"/auto_lock=0 attrs.
    auto_lock: bool = False
    # BigMachines composite "array set" membership (docs/
    # CPQ_ARRAY_SET_PAYLOAD_PLAN.md) — a driver/control attr (already
    # flagged is_array_control above) plus ordered member columns (e.g.
    # Mounting Type's selector + its own per-row quantity), grouped by a
    # shared bm_config_attr_set id and serialized as one _index-keyed row
    # per selection rather than flat per-column lists. None/"" = not part
    # of any array-set.
    array_set_id: int | None = None
    array_set_role: str = ""              # "driver" | "member" | ""
    array_col_order: int = 999            # member ordinal within the set's row
    # DRIVER attrs only — the set's own variable_name (from the
    # bm_config_attr_set driver row, a distinct, never-ConfigAttr-ingested
    # entity) precomputed into the real wire-format top-level key, e.g.
    # "_setmountingTypeArrayset_viSoln". Members leave this "" — the
    # wrapper key is looked up via the driver, never reconstructed by
    # build_payload from a template.
    array_set_wrapper_key: str = ""


@dataclass
class CpqSession:
    """Accumulated state across all conversation turns.

    Serialised as JSON in the API response so the client can echo it back
    on the next turn — no server-side session store required.
    """

    mode: str = "cpq"
    # Minted once when a session is first created (ask_api.py, on the
    # `CpqSession()` fresh-session fallback) and echoed back every turn
    # like every other field — traces one quote's ENTIRE lifecycle (anchor
    # gate -> rule cascade -> cascades -> approval -> payload) across every
    # turn in every "cpq: ..." log line, via
    # aryx.cpq.logging_context.set_run_id(). Empty for any session that
    # predates this field (from_dict() below simply won't find the key).
    run_id: str = ""
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
    # variable_names extract_catalog_hints() flagged as negated in ANY past
    # turn's question text (e.g. "no multikey"). Accumulated across turns,
    # not recomputed per-turn like `hints` — a negation stated on turn 1
    # must still suppress auto_fill's blind fallback on turn 3 even though
    # turn 3's own question ("No Surveillance Kit") carries no negation
    # signal itself (confirmed live: without this, multikeyType_astro was
    # protected on the turn "no multikey" was typed, then silently filled
    # "MULTIKEY" on the next turn once that turn's fresh, negation-free
    # question overwrote the (until-then not persisted) suppression).
    negated_vns: list[str] = field(default_factory=list)
    # Set when a LATER turn mentions a different product than product_name
    # while a configuration is already in progress. The next turn's reply is
    # then treated as a yes/no answer to the switch-confirmation prompt
    # instead of a normal CPQ hint (see _run_cpq_turn's confirm_switch gate).
    # Empty string when no switch is pending — old session_data payloads that
    # predate this field simply default to "" via CpqSession.from_dict.
    pending_switch_product: str = ""
    # The raw question text that TRIGGERED the switch detection (e.g. "Quote
    # APX Next Enhanced radios for a US customer"). detect_product_mention
    # resolves switches at the FAMILY/catalog level (pending_switch_product
    # is "aSTRO25_bom", not "APX NEXT Enhanced" — the family can host 300+
    # distinct products, see its own docstring) — the specific product the
    # user actually named lives only in this original text. Carried through
    # so the confirmed switch can seed productSelectionProduct_all directly
    # from it instead of re-asking a question the user's own trigger message
    # already answered. Empty when no switch is pending, same convention as
    # pending_switch_product.
    pending_switch_question: str = ""
    # Set when the mid-band "did you mean one of: ...?" hint offered MORE
    # THAN ONE family (pending_anchor == "suggest_switch") — the candidates
    # the next turn's reply picks from. A bare "yes" is ambiguous against
    # 2+ names, so the suggest_switch gate re-prompts with this list instead
    # of guessing (Issue 7, docs/CPQ_PRODUCT_SWITCH_ISSUE.md: the stateless
    # version of this prompt let "yes" fall through to the approval handler,
    # which SUBMITTED the current quote). Old payloads default to [] via
    # from_dict, same as every other newer field.
    pending_switch_candidates: list[str] = field(default_factory=list)
    # Per-product snapshot of config-scoped state, keyed by product_name (the
    # FAMILY/catalog key detect_product_mention resolves to -- same identity
    # that already gates a switch). Captured on switch-AWAY (before the reset
    # below wipes it) and restored on switch-TO when the target was visited
    # earlier this session, so A -> B -> A no longer discards A's answers by
    # design (see docs/CPQ_MULTI_PRODUCT_SESSION_SNAPSHOT_PLAN.md). Restored
    # values are seeded back in as auto_fill's already_filled -- the SAME
    # re-validation every normal turn already relies on, so a value that's no
    # longer valid under current rules is naturally dropped/re-asked, never
    # blindly trusted. Capped at 5 entries (evict-oldest) to bound payload
    # growth. Each snapshot dict has keys: filled, filled_multi,
    # display_filled, filled_source, country, negated_vns, product_entity_id.
    product_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Set when a change request's target attr was ambiguous (two attrs share
    # a display_label — see detect_change_request_collision) and the
    # "which one did you mean?" prompt was shown. The candidate
    # variable_names and the ORIGINAL question (which carries the intended
    # new value) so the NEXT turn's reply — a bare variable_name or a list
    # index, not a fresh CPQ hint — can resolve the collision and still
    # apply the original value, instead of being read as an unrelated
    # message (live-verified gap, 2026-07-22: the collision prompt had no
    # memory at all, so answering it did nothing). Empty when no collision
    # is pending, same convention as pending_switch_product.
    pending_change_collision_vns: list[str] = field(default_factory=list)
    pending_change_collision_question: str = ""

    # Same convention as pending_change_collision_vns/_question above, but
    # for the OPTIONS-QUERY collision prompt (detect_label_collision inside
    # _handle_cpq_qa — "what are the mounting types available?" when 2+
    # attrs share a display_label) — a separate code path from the
    # change-request collision, never given the same memory when that one
    # was fixed (live-verified gap, 2026-07-23: replying with the exact
    # variable_name shown in the prompt fell through to a generic nudge).
    pending_label_collision_vns: list[str] = field(default_factory=list)
    pending_label_collision_question: str = ""

    # Set when detect_change_target_without_value recognized a change-verb
    # naming an already-filled attr but no resolvable new value ("change
    # hardware version") and asked which value instead of guessing
    # (docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md Related finding 1). The
    # NEXT turn's reply IS the new value directly (not a fresh CPQ hint),
    # so it must be captured and applied via _handle_cascade before falling
    # through to ordinary detection again — same "remember what prompt is
    # pending" convention as pending_change_collision_vns above, just for a
    # single target attr rather than a disambiguation list. Empty string
    # when no such prompt is pending.
    pending_change_no_value_vn: str = ""

    # Set when a message named a label-collision target ("change service
    # type...") AND a second, distinct, already-filled attr with no given
    # value in the same message ("...and solution type") -- confirmed live
    # (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 4): a message naming 2+
    # distinct intents only ever got the FIRST one addressed, the rest
    # silently dropped once the collision detector's own caller returned.
    # The collision must be resolved first (its own reply format is a
    # number/variable_name, not a value), so this stashes the second
    # target's variable_name to continue to automatically once the
    # collision resolves, rather than losing it. Empty string when none
    # is pending.
    pending_multi_intent_vn: str = ""

    # Set when a catalog's own bm_catalog tree has 2+ model leaves (so
    # single_model_variable_name can't auto-seed _bm_model_variable_name
    # unambiguously — Amendment 10, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_
    # PLAN.md) and the customer's own text didn't already name one. The
    # candidate leaf names shown, so the NEXT turn's reply (exact name or
    # a looser phrasing an LLM fallback resolves) answers THIS prompt
    # instead of falling through to the unrelated "Product" attrs, which
    # were never the right place to resolve this.
    pending_model_leaf_candidates: list[str] = field(default_factory=list)
    # True once _bm_model_variable_name was resolved via the model-leaf
    # disambiguation mechanism above (multi-leaf catalog, proven-ambiguous
    # tree) — distinct from any other, less certain way that field might
    # end up filled. Gates skipping the catalog's "Product"-labeled attrs
    # (Amendment 10 follow-up): once the real identity is known through
    # the bm_catalog tree, those attrs are proven irrelevant/generic for
    # THIS catalog (Amendment 5 Finding 3) and asking for them is pure
    # noise — but only when resolved through THIS specific, verified path.
    model_leaf_resolved: bool = False
    # The ORIGINAL message that first anchored session.product_name (e.g.
    # "I want to configure CommandCentral Aware 2024 for a customer in
    # the United States") — captured once, on the anchoring turn, so
    # later turns (which only ever see their own short reply, "United
    # States"/"NA"/...) can still auto-resolve an ambiguous model-leaf
    # choice (Amendment 10) from what the customer originally said,
    # instead of losing that context the moment the country/region
    # anchor questions consume the conversation. Never cleared —
    # harmless to keep once the product is set, same convention as
    # product_name itself.
    product_anchor_question: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CpqSession":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
