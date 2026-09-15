"""CPQ session state — serialisable so the UI can echo it back each turn.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), the 4 rule
dataclasses live in `cpq.state_rules` and MenuOption/ConfigAttr live in
`cpq.state_config_attr` — re-exported below so every existing `from
aryx.cpq.state import X` caller (134 files) keeps working unchanged.
`CpqSession` stays here: it is a single dataclass whose fields serialize
flat to JSON via `to_dict()`/`from_dict()` for the API's session-echo
contract — splitting its field *declarations* across files would not
create real modularity (a dataclass's fields must live in one class body),
only move code around while risking that flat-serialization contract, so
it is kept whole here as a deliberate exception, not a missed split.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from aryx.cpq.state.state_config_attr import ConfigAttr, MenuOption
from aryx.cpq.state.state_rules import (
    ConstraintRule,
    HidingRule,
    RecommendationRule,
    ValidationRule,
)

__all__ = [
    "ConfigAttr",
    "ConstraintRule",
    "CpqSession",
    "HidingRule",
    "INTENT_QUEUE_CAP",
    "MenuOption",
    "RecommendationRule",
    "ValidationRule",
]

# Max variable_names held in CpqSession.pending_intent_queue. Overflow is
# reported to the user (never silently dropped).
INTENT_QUEUE_CAP = 10


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
    # How many units of the product the customer wants -- a session-level
    # concept, deliberately separate from any catalog attribute (docs/
    # CPQ_QUANTITY_SLOTFILLING_AND_UI_ISSUES_PLAN_2026_08_11.md). Kept
    # OUTSIDE `filled`/`filled_multi` on purpose: build_payload only ever
    # iterates those two dicts, so this can never leak into the final
    # configData JSON without any special-case exclusion code. Defaults to
    # 1 (one unit) until the customer says otherwise.
    product_quantity: int = 1
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

    # Grid-selector attrs (a select_type=="multi" attr driving a per-row
    # quantity grid, e.g. SVX's mountingTypeArray_viSoln) the customer has
    # explicitly said they're done adding rows to (docs/CPQ_SVX_MOUNTING_
    # TYPE_ARRAY_GRID_MULTI_SELECT_PLAN_2026_08_25.md). auto_fill keeps a
    # grid selector in `pending` as long as any currently-valid option
    # hasn't been picked yet -- this is the customer's own override so a
    # catalog that legitimately narrows to 5-6 options doesn't get asked
    # forever once they've picked the ones they want. Never touched for
    # any other attr shape; empty by default (no-op for every session
    # that never reaches this path).
    pending_grid_declined_vns: list[str] = field(default_factory=list)

    # Gateway clarify memory (live-verified gap, 2026-07-28): "change
    # hardware" is too vague to pin one attr → gateway action=clarify asks
    # "Hardware Version or System Key?" but historically saved NO pending
    # state. The bare reply "Hardware Version" then arrived with no memory
    # of the question, classified blind as ATTR_QUERY/QA, fell through
    # partial dispatch, and hit the generic "I didn't quite catch that"
    # nudge.
    #
    # Conceptual shape (serialized flat, same pattern as
    # pending_change_collision_vns):
    #   { candidate_vns, original_question, clarifying_question, asked_turn }
    pending_clarify_vns: list[str] = field(default_factory=list)  # candidate_vns
    pending_clarify_question: str = ""  # original_question (vague utterance)
    # Grounded clarifying_question we showed (catalog labels only — never
    # free-form LLM prose that may invent non-catalog examples).
    pending_clarify_prompt: str = ""
    # session.turn when the clarify was issued (for audit / loop detection).
    pending_clarify_asked_turn: int = 0
    # Consecutive unresolved replies to this clarify. After 2 misses,
    # force a numbered pick list (loop-exit guard).
    pending_clarify_misses: int = 0

    # variable_name of the attribute the CUSTOMER most recently asked a
    # question about (e.g. "what are the other options for Wireless
    # Carrier"), set by _handle_cpq_qa's attr-query fast path. Deliberately
    # separate from pending_variables (which tracks what the SYSTEM is
    # still waiting on an answer for, and is wiped the moment an attribute
    # is filled) — this tracks conversational recency instead, and stays
    # set even for an already-filled attribute the customer is revisiting.
    # docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §8: without
    # this, "make it ATT/FirstNet" right after asking about Wireless
    # Carrier had no way to prefer that attr over a genuinely-ambiguous
    # sibling (Carrier Selection) that also accepts the same value.
    #
    # A list, not a single string (docs/config_consistency_issues_2026-
    # 07-30.md Issue 12): a compound options query ("what are the
    # Frequency Bands and Wireless Carrier available?") asks about
    # MULTIPLE attributes in one turn. A single-string field can only
    # remember the last one processed, silently losing the others as
    # a follow-up-resolution hint for the LLM classifier — live-confirmed
    # as the reason a two-attribute follow-up ("Add Frequency Bands as
    # VHF and Wireless Carrier as ATT/FirstNet") resolved inconsistently.
    last_qa_variables: list[str] = field(default_factory=list)

    # variable_name of the attribute a gateway clarify ("which attribute
    # did you mean?") was most recently RESOLVED to, and the turn it was
    # resolved on. docs/config_consistency_issues_2026-07-30.md issue 4:
    # once the customer explicitly names one candidate (e.g. "Frequency
    # Bands" out of a 7-way clarify), a LATER bare value reply ("VHF") can
    # be a legal option on several OTHER candidates too (Frequency Band/
    # Msl, Primary/Secondary Frequency all also accept "VHF" — confirmed
    # live) and re-triggers a fresh clarify with no memory of the earlier
    # answer, forever (the LLM fallback has no per-candidate option
    # visibility to break the tie either). Reused as a tie-breaker in
    # `_set_pending_clarify_and_answer`/`_match_pending_clarify_reply`:
    # if this attr is among the fresh candidates and the reply is one of
    # ITS real option values, resolve straight to it instead of re-asking.
    last_clarified_attr_vn: str = ""
    last_clarified_turn: int = 0

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

    # Ordered queue of variable_names still to ask after a multi-target
    # change utterance ("change hardware version, service type and
    # activation delay"). Replaces the single-string
    # pending_multi_intent_vn slot (which only ever held one secondary
    # target and was filled in only two branches). Deduped, FIFO, cap 10
    # (INTENT_QUEUE_CAP). Old session_data payloads with
    # pending_multi_intent_vn still migrate via from_dict / the
    # pending_multi_intent_vn property.
    pending_intent_queue: list[str] = field(default_factory=list)

    # Overflow variable_names from a queue that hit the cap — surfaced
    # once in the reply so the customer can re-ask; never silently dropped.
    pending_intent_overflow: list[str] = field(default_factory=list)

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

    # PROMPT 7 — durable candidate-list scope (flat, session-echoed).
    # When the engine shows a constrained option list / family
    # disambiguation / "did you mean" set, the NEXT reply is matched
    # against pending_scope_candidates FIRST (exact → partial → fuzzy).
    # Without this, a mismatch re-prompt called next_question_prompt
    # unconstrained and dumped the catalog-wide 325-option Product list
    # (live: "sl3500e" → 70 codes → "r7ex" → full catalog). Mirrors
    # pending_clarify / pending_change_collision memory patterns.
    # kind: family_disambiguation | product_options | attr_options |
    #       product_suggestions | ""
    pending_scope_kind: str = ""
    pending_scope_candidates: list[str] = field(default_factory=list)
    pending_scope_origin_question: str = ""
    pending_scope_asked_turn: int = 0
    pending_scope_misses: int = 0
    # variable_name when scope is attr/product options; else ""
    pending_scope_attr_vn: str = ""
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

    # Post-failure prevention (session_guard): deep-copied CpqSession
    # dicts taken BEFORE each mutating intent. Cap 10 (evict oldest).
    # Nested history is stripped on push so snapshots stay bounded.
    # Restored by the first-class "undo" intent.
    history: list[dict[str, Any]] = field(default_factory=list)

    # Consecutive clarification prompts for the same variable_name.
    # After 2, the orchestrator presents numbered options instead of
    # another free-form clarify (loop-exit guard).
    clarify_streak_by_vn: dict[str, int] = field(default_factory=dict)

    # Turns that ended unresolved (clarify / unparseable / no progress).
    # After 5, offer deterministic guided mode.
    unresolved_turns: int = 0

    # When True, skip LLM-first gateway and force the deterministic
    # detector waterfall (user accepted guided mode, or loop-exit
    # automatic offer was taken).
    guided_mode: bool = False

    # Recent user utterance snippets (capped) for BOM provenance —
    # "trace to a user utterance" without re-scanning ask history store.
    recent_utterances: list[str] = field(default_factory=list)

    @property
    def pending_multi_intent_vn(self) -> str:
        """Compat for pre-queue session_data / callers.

        Returns the head of pending_intent_queue, or "" when empty.
        """
        return self.pending_intent_queue[0] if self.pending_intent_queue else ""

    @pending_multi_intent_vn.setter
    def pending_multi_intent_vn(self, value: str) -> None:
        """Compat setter: assign/clear maps onto the queue head.

        - Empty / None → pop head (legacy clear pattern).
        - Non-empty → ensure vn is at the front of the queue (deduped).
        """
        vn = (value or "").strip()
        if not vn:
            if self.pending_intent_queue:
                self.pending_intent_queue.pop(0)
            return
        q = [v for v in self.pending_intent_queue if v != vn]
        self.pending_intent_queue = [vn] + q
        while len(self.pending_intent_queue) > INTENT_QUEUE_CAP:
            self.pending_intent_queue.pop()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CpqSession":
        raw = dict(d or {})
        # Migrate legacy single-string multi-intent into the queue.
        legacy = raw.pop("pending_multi_intent_vn", None)
        init_fields = {
            k for k, f in cls.__dataclass_fields__.items()
            if f.init
        }
        obj = cls(**{k: v for k, v in raw.items() if k in init_fields})
        if legacy and isinstance(legacy, str) and legacy.strip():
            if legacy not in obj.pending_intent_queue:
                obj.pending_intent_queue = [legacy] + list(obj.pending_intent_queue)
                while len(obj.pending_intent_queue) > INTENT_QUEUE_CAP:
                    obj.pending_intent_queue.pop()
        return obj
