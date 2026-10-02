"""CPQ LLM-first intent classifier settings — a Settings mixin.

Split out of `config.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `config_core.py`'s docstring for the mixin-composition
rationale.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class CpqIntentSettingsMixin(BaseSettings):
    cpq_off_topic_veto_shadow_enabled: bool = Field(
        default=False,
        description=(
            "CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T8: shadow-log-only "
            "measurement phase for the hard off-topic veto (_OFF_TOPIC_HARD "
            "in intent_gateway.py) -- the audit's own fix proposal is to "
            "split the veto into strong/weak terms and never let a weak "
            "term override a confident LLM 'quote'/'qa' verdict, but that "
            "is a live customer-facing routing change and was deliberately "
            "NOT shipped without first measuring how often it would even "
            "matter on real traffic. When on, classify_ask_route's pre-LLM "
            "hard_off_topic veto additionally logs (never changes routing) "
            "whether the matched term is in the provisional "
            "_OFF_TOPIC_WEAK_TERMS set -- this is the ONLY reachable veto "
            "site (see intent_gateway.py's own comment on the separate "
            "'N10 post-LLM' block: that second check is dead code, "
            "confirmed unreachable, since the pre-LLM veto already returns "
            "whenever its identical condition is true); no LLM verdict is "
            "available to compare against at this site, since the veto's "
            "whole purpose is to skip the LLM call. The weak/strong split "
            "itself is provisional -- seeded from the audit's own explicit "
            "example ('real quotes mentioning weather can still be "
            "silently rejected') -- and exists to be validated or revised "
            "by this shadow data, not treated as already-correct. Off by "
            "default, zero behavioral change when on (log-only). Override "
            "with ARYX_CPQ_OFF_TOPIC_VETO_SHADOW_ENABLED=true to collect "
            "real shadow-mode data against live traffic."
        ),
    )
    cpq_shadow_intent_enabled: bool = Field(
        default=False,
        description=(
            "Phase 1, docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md: run the "
            "shadow-mode universal intent classifier (_shadow_classify_cpq_"
            "turn in ask_api.py) alongside the real deterministic dispatch "
            "on every CPQ turn, logging its classification for later "
            "comparison. Off by default: live-confirmed this added an extra "
            "unconditional LLM call to every single test invoking "
            "_run_cpq_turn, taking the CPQ/BML suite from ~10s to ~128s with "
            "zero behavioral change (the shadow call is try/except-wrapped "
            "and never affects a turn's real answer) -- purely a test-speed "
            "and CI-cost concern, same class of always-on-cost issue "
            "bml_use_llm above already guards against. Override with "
            "ARYX_CPQ_SHADOW_INTENT_ENABLED=true to collect real shadow-mode "
            "data against live traffic."
        ),
    )
    cpq_qa_ambiguity_check_enabled: bool = Field(
        default=False,
        description=(
            "Phase 3, docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md: before "
            "answering a generic graph Q&A question, classify whether the "
            "question is itself ambiguous (2+ plausible distinct meanings) "
            "and ask a clarifying question instead of committing to one "
            "interpretation. Off by default for the same test-speed/CI-cost "
            "reason as cpq_shadow_intent_enabled -- an unconditional extra "
            "LLM call on every Q&A turn. Override with "
            "ARYX_CPQ_QA_AMBIGUITY_CHECK_ENABLED=true."
        ),
    )
    cpq_llm_first_enabled: bool = Field(
        default=True,
        description=(
            "Phase 2 (PARTIAL), docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md: "
            "let the universal intent classifier dispatch directly to "
            "_handle_cascade/_handle_cascade_multi/_build_no_value_response "
            "(bypassing the regex detectors) for CHANGE_REQUEST/"
            "CHANGE_REQUESTS_MULTI/CHANGE_TARGET_WITHOUT_VALUE/AMBIGUOUS/"
            "OUT_OF_SCOPE only -- every other category still falls through "
            "to the unchanged deterministic path (see "
            "_dispatch_intent_result's docstring for the full category "
            "list this initial landing does not yet cover). On by default "
            "(2026-07-28) for local/dev testing of the LLM-first flow -- "
            "note this carries the same extra-LLM-call cost as "
            "cpq_shadow_intent_enabled on every STEP 6 turn, and has NOT "
            "been validated against real Phase 1 shadow-mode disagreement/"
            "resolution-failure data yet -- the plan doc's own Phase 2 "
            "criteria ('once shadow mode shows the deterministic "
            "resolution step reliably resolves what the LLM names') has "
            "not actually been met. Set ARYX_CPQ_LLM_FIRST_ENABLED=false "
            "to fall back to the pure deterministic path (e.g. for a fast "
            "CI run) or before considering this validated for production."
        ),
    )
    cpq_llm_first_universal_enabled: bool = Field(
        default=True,
        description=(
            "Phase 4 (docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md §8): "
            "runs the LLM-first dispatcher (_dispatch_intent_result, gated "
            "above by cpq_llm_first_enabled) on EVERY turn regardless of "
            "session.status -- previously it only ran inside the "
            "awaiting_approval/post_approval block, so it never fired "
            "during the actual configuring-stage conversation, which is "
            "most real traffic. Also enables the 6 new dispatch branches "
            "(PRODUCT_QUANTITY_CHANGE, COUNTRY_CHANGE, "
            "BULK_QUANTITY_CHANGE, RESPONSE_MODE_REQUEST, APPROVAL) that "
            "Phase 2's initial landing deliberately deferred. Off by "
            "default -- ships behind this flag for shadow/staging "
            "validation first, per the plan doc's own rollout discipline, "
            "since these are real mutating actions during active "
            "configuration, not just post-review edits. Requires "
            "cpq_llm_first_enabled=True to have any effect at all -- this "
            "flag only widens WHEN/WHAT that mechanism covers, it doesn't "
            "replace it. Override with "
            "ARYX_CPQ_LLM_FIRST_UNIVERSAL_ENABLED=true."
        ),
    )
    cpq_intent_gemini_model: str = Field(
        default="gemini-2.5-pro",
        description=(
            "Pinned model id for the CPQ intent gateway (cpq/intent_gateway.py). "
            "One structured call per turn; logged with session run_id. "
            "Override with ARYX_CPQ_INTENT_GEMINI_MODEL."
        ),
    )
    catalog_profile_shadow_check_enabled: bool = Field(
        default=False,
        description=(
            "CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3: run "
            "CatalogProfile.shadow_check (via catalog_profile.shadow_check_"
            "role_vn) alongside three real hardcoded-literal sites -- "
            "_invalidate_stale_base_model's Base-Model-clear (\"Base Model\" "
            "role, every Hardware Version/Product/Country/Region change), "
            "_data_table_resolved_anchor_vns's Region read (\"Region\" role), "
            "and run_early_pass's hidden-master-string refresh (\"Hidden "
            "Master String\" role, unverified label -- unlike the other two, "
            "no live confirmation this label exists in any real catalog's "
            "attrToVarMapping table; shadow mode is how that gets found "
            "out) -- comparing each hardcoded literal against what the real "
            "attrToVarMapping-Data-Table-driven resolver (resolve_variable_"
            "name_for_role) gives for the session's actual CPQ model, "
            "logging any disagreement. Off by default for the same reason "
            "as cpq_shadow_intent_enabled above -- this adds a real RDB "
            "round trip (module-level 300s-TTL cached, but still an "
            "unconditional extra call on the first hit and every TTL "
            "expiry) to every one of these files' own unit tests and to "
            "real hot paths (the hidden-master-string site runs on EVERY "
            "rules-loop pass, potentially several per turn), and has not "
            "yet been validated against live traffic. Override with "
            "ARYX_CATALOG_PROFILE_SHADOW_CHECK_ENABLED=true to collect real "
            "shadow-mode disagreement data before ever switching a literal "
            "over to the resolved value."
        ),
    )
    model_policy_shadow_check_enabled: bool = Field(
        default=False,
        description=(
            "CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T6 Phase 3 follow-up: "
            "run model_policy.shadow_check_optional_empty_fill_vns alongside "
            "try_multi_optional_empty's real _OPTIONAL_EMPTY_FILL_ACCEPTED_"
            "VNS membership check (every multi-select, non-required, "
            "non-grid-selector auto_fill attr), comparing today's hardcoded "
            "constant's answer against what the new model_policy legacy "
            "table gives for the session's actual CPQ model(s), logging any "
            "disagreement. Off by default, same reason and same shape as "
            "catalog_profile_shadow_check_enabled above -- this is the "
            "'shadow' phase of T6's own proposed legacy-→shadow-→scoped-"
            "→remove rollout: proves real-traffic agreement before "
            "try_multi_optional_empty is ever switched to read from "
            "model_policy instead of the hardcoded constant. Override with "
            "ARYX_MODEL_POLICY_SHADOW_CHECK_ENABLED=true to collect real "
            "shadow-mode disagreement data."
        ),
    )
    catalog_profile_scoped_resolution_enabled: bool = Field(
        default=False,
        description=(
            "CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3 'scoped' "
            "rollout: makes resolve_base_model_vn() (and, if added later, "
            "any sibling resolve_<role>_vn() function) actually GOVERN the "
            "real key modelSelectionbaseModel_astro's value is read/popped "
            "under, across all ~16 of that literal's real call sites, "
            "instead of only shadow-logging. Off by default -- checked "
            "FIRST, before any other work, in every one of those functions: "
            "live-confirmed (a hung unit test caught this before it "
            "shipped) that an ungated version pays a real, uncached "
            "~265s-class RDB round trip on its first call in any 300s "
            "window, and this is now called from ~16 sites, several in hot "
            "loops (one per rules-loop pass) -- unconditionally live would "
            "have been a severe latency regression on the very first turn "
            "to reach any of them. When off, every one of those ~16 sites "
            "behaves byte-identically to before this rollout (returns the "
            "hardcoded literal immediately, no RDB call at all). Override "
            "with ARYX_CATALOG_PROFILE_SCOPED_RESOLUTION_ENABLED=true only "
            "for a deployment/workspace confirmed to have real "
            "attrToVarMapping coverage -- as of 2026-09-25, live-checked: "
            "none of the 24 real workspaces in this session's dev_oci "
            "environment do."
        ),
    )
    model_policy_scoped_resolution_enabled: bool = Field(
        default=False,
        description=(
            "CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T6 Phase 3 'scoped' "
            "rollout: makes resolve_optional_empty_fill_membership() "
            "actually GOVERN try_multi_optional_empty's real fill decision "
            "(across its one real call site), instead of only shadow-"
            "logging via model_policy_shadow_check_enabled above. Off by "
            "default -- checked FIRST, before any other work, same safety "
            "rationale as catalog_profile_scoped_resolution_enabled: model-"
            "candidate resolution touches the same RDB-backed data source "
            "that already caused one hung test this session. When off, "
            "the real call site behaves byte-identically to before this "
            "rollout (reads the hardcoded _OPTIONAL_EMPTY_FILL_ACCEPTED_"
            "VNS constant directly, no RDB call at all). Live-checked "
            "2026-09-25: every real product string tried against workspace "
            "704 resolves through the T2 APX-NEXT-fallback bug to "
            "candidates including 'APXNEXT', and model_policy's APXNEXT "
            "entry is byte-identical to the legacy constant -- so turning "
            "this on today would currently still be a no-op, for a "
            "different reason than catalog_profile_scoped_resolution_"
            "enabled's inertness (T2's fallback behavior, not empty "
            "attrToVarMapping data). Override with "
            "ARYX_MODEL_POLICY_SCOPED_RESOLUTION_ENABLED=true once a "
            "catalog/model has its own real, distinct model_policy entry."
        ),
    )
    data_table_candidates_empty_on_no_match_enabled: bool = Field(
        default=False,
        description=(
            "CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T2 Phase 4: makes "
            "_cpq_model_candidates() (data_table_bridge/candidates.py) "
            "return an empty tuple, plus a logged data gap, instead of the "
            "hardcoded _DEFAULT_CPQ_MODEL_CANDIDATES = ('APXNEXT', "
            "'APXNEXT_BOM') fallback, whenever neither the row-level nor "
            "family-level Data Table resolution finds a real match for the "
            "product. Off by default -- when off, this function behaves "
            "byte-identically to before this flag existed (unmapped "
            "products still silently default to APX NEXT candidates, "
            "exactly as documented in T2's own 'Problem' finding). All "
            "~22 real call sites were spot-checked before this flag was "
            "added: every one either iterates the returned tuple or "
            "explicitly guards on 'if not candidates/models', never "
            "indexes it directly -- an empty tuple is safe everywhere it "
            "was sampled, but this has NOT been verified against a real "
            "non-APX-NEXT catalog's actual behavior end-to-end (T2's own "
            "'Impact' section: no real workspace in this dev_oci "
            "environment has attrToVarMapping/Data Table coverage for any "
            "product other than APX NEXT, so there is nothing here to "
            "prove this against yet). Override with "
            "ARYX_DATA_TABLE_CANDIDATES_EMPTY_ON_NO_MATCH_ENABLED=true "
            "only once a real non-APX-NEXT catalog's behavior under this "
            "flag has actually been observed, not merely code-reviewed."
        ),
    )
    cpq_intent_mode: str = Field(
        default="llm_first",
        description=(
            "Top-level /ask intent router mode (Prompt 3). "
            "'llm_first' (default) — gateway classifies every cold-start "
            "turn; handlers only execute. Required for route_meta.quantity/"
            "route_meta.country (docs/CPQ_TURN1_COUNTRY_EXTRACTION_DEFECT_"
            "PLAN_2026_08_13.md) to ever reach the actual turn at all -- "
            "'shadow' strips both before the turn runs (observe-only), so "
            "a turn-1 message stating the country/quantity is left entirely "
            "to the deterministic regex extractor with no LLM fallback, "
            "even when the regex mis-parses it. "
            "'deterministic_first' — legacy is_cpq_question regex/alias gate "
            "(no gateway). "
            "'shadow' — deterministic path decides; gateway classifies in "
            "parallel for agreement logs only (grep by run_id). "
            "Rollback = set ARYX_CPQ_INTENT_MODE=shadow or "
            "=deterministic_first."
        ),
    )
    cpq_intent_timeout_s: float = Field(
        default=120.0,
        description=(
            "Hard timeout (seconds) for the top-level intent gateway call "
            "(classify_ask_route). On timeout/error, escape hatch falls "
            "back to the deterministic is_cpq_question path -- but as of "
            "docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_13.md, a turn-1 "
            "timeout ALSO means route_meta.quantity/.country are "
            "unavailable, surfacing an explicit \"classifier call failed\" "
            "message rather than a silent regex fallback for those two "
            "fields specifically -- raised from the original 10s default "
            "(too tight, live-verified timing out during normal, non-bulk "
            "traffic) to match cpq_intent_classify_timeout_s below. "
            "OPERATIONAL WARNING (review finding, 2026-08-13): this is a "
            "hard timeout on a SYNCHRONOUS, user-facing HTTP request -- "
            "before this value elapses, a slow/degraded LLM backend holds "
            "the /ask request open. If any upstream reverse proxy, load "
            "balancer, or API gateway in front of this service has a "
            "shorter idle/request timeout than this value (many common "
            "defaults are 30-60s), the CUSTOMER will see a generic "
            "502/504 from that layer instead of the graceful \"classifier "
            "call failed, try again\" message this design is meant to "
            "guarantee -- the reject-on-failure UX this PR ships can only "
            "ever fire if this value is reached before any shorter upstream "
            "timeout is. Confirm the deployment's full upstream timeout "
            "chain comfortably exceeds this value before relying on the "
            "default; lower it here if it doesn't, accepting the original "
            "too-tight-for-normal-traffic tradeoff at a smaller scale "
            "instead. Override with ARYX_CPQ_INTENT_TIMEOUT_S."
        ),
    )
    cpq_intent_classify_timeout_s: float = Field(
        default=120.0,
        description=(
            "Hard timeout (seconds) for classify_intent (intent_gateway.py) "
            "-- the mid-session LLM-first classifier, distinct from "
            "cpq_intent_timeout_s (the turn-1 top-level router's own "
            "timeout). Added docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md "
            "§8 Phase 4: classify_intent had no timeout wrapper at all "
            "before this, unlike classify_ask_route -- broadening how "
            "often it's called (every turn, not just post-approval) made "
            "an unbounded hang a bigger exposure than it was before. On "
            "timeout, returns action='fallback' -- callers already treat "
            "that as 'proceed to the deterministic path', so no new "
            "caller-side branch is needed. Override with "
            "ARYX_CPQ_INTENT_CLASSIFY_TIMEOUT_S."
        ),
    )

    cpq_bml_tilde_split_enabled: bool = Field(
        default=False,
        description=(
            "Port of the aryxent PR 12 fix (aryxent_bug_cpq-blind-pick-"
            "unscoped-menu.md): also split a BML script's quoted return "
            "value on '~' (e.g. \"A~B~C\"), the catalog's second real "
            "multi-value packing convention besides '|^|'. Off by default "
            "-- when off, only '|^|' is split, exactly as before. Override "
            "with ARYX_CPQ_BML_TILDE_SPLIT_ENABLED=true."
        ),
    )
    cpq_base_model_placeholder_guard_enabled: bool = Field(
        default=False,
        description=(
            "Port of the aryxent PR 4 fix: reject the placeholder value '*' "
            "(see cpq/base_model_placeholder.py) when a recommendation rule "
            "tries to write it into a base-model attribute, at the three "
            "write sites (apply_recommendation_rules, "
            "resync_stale_recommendations, tier2_satisfied_rec). Off by "
            "default -- when off, behaviour is byte-identical to before. "
            "Override with ARYX_CPQ_BASE_MODEL_PLACEHOLDER_GUARD_ENABLED=true."
        ),
    )
    cpq_generic_candidate_exclusion_enabled: bool = Field(
        default=False,
        description=(
            "Port of the aryxent PR 13/14 fixes: in "
            "data_table_bridge/conflicts.py, (a) _resolve_via_data_tables "
            "skips the generic ('APXNEXT','APXNEXT_BOM') fallback pair when "
            "it is not the primary candidate, (b) "
            "_invalidate_inconsistent_paired_values leaves it out of the "
            "per-model intersection, and (c) "
            "find_confirmed_data_table_conflicts ignores it as a non-primary "
            "candidate. Off by default -- when off, both "
            "behave exactly as before. Override with "
            "ARYX_CPQ_GENERIC_CANDIDATE_EXCLUSION_ENABLED=true."
        ),
    )
    cpq_candidates_real_models_first_enabled: bool = Field(
        default=False,
        description=(
            "Partial port of the aryxent PR 3/10 candidate-order fix: in "
            "data_table_bridge/candidates.py, when the primary candidates "
            "are the generic ('APXNEXT','APXNEXT_BOM') fallback and real "
            "CPQModels were discovered for the known base model, put the "
            "real models FIRST so callers (which stop at the first single "
            "value) no longer answer for APX NEXT. Does not add a "
            "resolved-model object (dev_oci has no model_resolution). Off "
            "by default -- when off, order is unchanged. Override with "
            "ARYX_CPQ_CANDIDATES_REAL_MODELS_FIRST_ENABLED=true."
        ),
    )
    cpq_model_resolution_enabled: bool = Field(
        default=False,
        description=(
            "Port of aryxent PR 1 (model_resolution). When on, the ask flow "
            "resolves, once per turn, which catalog model the customer's "
            "wording refers to (Basemodeltoconfig + BmCatalog tree + "
            "Flagsforflashport) and binds it to the turn via a contextvar "
            "(cpq/model_resolution.py). Binding alone changes nothing; it is "
            "what the cpq_model_context_seed_enabled, "
            "cpq_model_scope_lookups_enabled and cpq_model_leaf_pick_top_"
            "enabled flags read. Off by default -- when off no resolution "
            "runs and behaviour is unchanged. Override with "
            "ARYX_CPQ_MODEL_RESOLUTION_ENABLED=true."
        ),
    )
    cpq_model_leaf_pick_top_enabled: bool = Field(
        default=False,
        description=(
            "Needs cpq_model_resolution_enabled. In the ask flow's model-leaf "
            "disambiguation (ask_model_leaf_resolve.py), when the customer's "
            "wording matches 2+ catalog model leaves, pick the resolver's "
            "top match (deterministic ranking) and log that it did so, "
            "instead of asking which model was meant (aryxent behaviour). "
            "Off by default -- when off, the existing question is asked. "
            "Override with ARYX_CPQ_MODEL_LEAF_PICK_TOP_ENABLED=true."
        ),
    )
    cpq_model_context_seed_enabled: bool = Field(
        default=False,
        description=(
            "Port of aryxent PR 2. Needs cpq_model_resolution_enabled. When "
            "single_model_variable_name finds nothing (multi-leaf catalog), "
            "seed _bm_model_variable_name from the turn's resolved model "
            "node so model-guarded rule scripts can evaluate. Never "
            "overrides the single-leaf mechanism. Off by default. Override "
            "with ARYX_CPQ_MODEL_CONTEXT_SEED_ENABLED=true."
        ),
    )
    cpq_model_scope_lookups_enabled: bool = Field(
        default=False,
        description=(
            "Port of aryxent PR 3. Needs cpq_model_resolution_enabled. When "
            "on: (a) _cpq_model_candidates prepends the resolved model's "
            "cpqModel when missing; (b) the blind first-available picks "
            "(tier6_single_b, ask_data_gap, ask_rule_governed_blind) take "
            "the first option the resolved model's own Whitelist allows "
            "(cpq/model_scope_pick.py). Off by default -- when off, "
            "behaviour is byte-identical. Override with "
            "ARYX_CPQ_MODEL_SCOPE_LOOKUPS_ENABLED=true."
        ),
    )
    cpq_rule_scope_filter_enabled: bool = Field(
        default=False,
        description=(
            "Port of aryxent PR 6. Needs cpq_model_resolution_enabled. When "
            "on, loaded hiding/recommendation/constraint/validation rules "
            "are kept only if their catalog-node ref_id is the resolved "
            "model's node, one of its ancestors, or unbound (empty). Off by "
            "default -- when off, rule loading is byte-identical. Override "
            "with ARYX_CPQ_RULE_SCOPE_FILTER_ENABLED=true."
        ),
    )
    cpq_defaultinattr_shape_enabled: bool = Field(
        default=False,
        description=(
            "Port of aryxent D7 (Defaultinattr; aryxent only planned it, so "
            "this is a minimal new implementation). When on, a Defaultinattr-"
            "shaped Data Table (BaseModel + attrN/valN, no CPQModel) is read "
            "(cpq/data_table/data_table_defaultinattr.py) and "
            "_resolve_via_data_tables falls back to its default for the "
            "known base model when Whitelist gave no single legal value and "
            "the default is a real option. Off by default -- when off, "
            "behaviour is unchanged. Override with "
            "ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED=true."
        ),
    )
    cpq_infer_legal_values_enabled: bool = Field(
        default=False,
        description=(
            "Port of aryxent D8 (PR 7/15). When on, the blind first-available "
            "picks (tier6_single_b, ask_data_gap, ask_rule_governed_blind) "
            "that found no Whitelist-scoped option infer a legal set from "
            "the Whitelist condition columns (cpq/inferred_legal_pick.py) before "
            "falling back to raw catalog order. With a known base model its "
            "own rows win; if it has rows but none match the filled "
            "conditions nothing is inferred, and if it has no rows at all "
            "(sparse data) the model tier is used. Off by default. Override "
            "with ARYX_CPQ_INFER_LEGAL_VALUES_ENABLED=true."
        ),
    )
    cpq_derive_base_model_enabled: bool = Field(
        default=False,
        description=(
            "Port of aryxent D10 (PR 8). When on, the Base Model auto_fill "
            "stage narrows the model's real base models to exactly one using "
            "already-known attribute values (Whitelist evidence) and fills "
            "it (source 'derived_from_known_attrs') instead of leaving the "
            "full raw list to be asked. Off by default. Override with "
            "ARYX_CPQ_DERIVE_BASE_MODEL_ENABLED=true."
        ),
    )
    cpq_whitelist_narrow_questions_enabled: bool = Field(
        default=False,
        description=(
            "Port of aryxent D13/D17 (PR 11). When on, (a) the in-loop "
            "apply_constraint_rules also intersects the Whitelist-narrowed "
            "legal set (_resolve_narrowed_legal_values, 2+ values) for "
            "unanswered attrs into constrained_opts, so question option "
            "lists are narrowed; (b) resolve_pending_grid_quantities, when "
            "given a workspace, uses the same narrowed set for a selector "
            "with no constraint result. Off by default. Override with "
            "ARYX_CPQ_WHITELIST_NARROW_QUESTIONS_ENABLED=true."
        ),
    )
    cpq_product_match_exact_first_enabled: bool = Field(
        default=False,
        description=(
            "Port of aryxent D11 (PR 9). When on, Product seeding/matching "
            "tries the turn's resolved model's exact name first, and the "
            "bidirectional-substring Product match prefers an exact name "
            "over a longer name that merely contains it. Off by default. "
            "Override with ARYX_CPQ_PRODUCT_MATCH_EXACT_FIRST_ENABLED=true."
        ),
    )
    cpq_free_text_presentable_enabled: bool = Field(
        default=False,
        description=(
            "Port of dev-rv-msi #370 (bug 2). When on, apply_answer's "
            "free-text fallback for an optionless attribute accepts a "
            "customer's typed answer if it is _presentable() rather than "
            "_valid(), so a real catalog code such as 'NA' is no longer "
            "rejected in an endless re-ask loop. Off by default. Override "
            "with ARYX_CPQ_FREE_TEXT_PRESENTABLE_ENABLED=true."
        ),
    )
