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
    cpq_attr_search_enabled: bool = Field(
        default=False,
        description=(
            "Attribute-first product discovery, phase 1: lets the turn-1 "
            "top-level router (classify_ask_route) return route="
            "'attribute_search' for a cold-start message that names an "
            "attribute/value but no product (e.g. 'I want a product that "
            "has ATT as a carrier'), with the raw attribute_label/"
            "attribute_value. Off by default -- the router's prompt and "
            "schema are unchanged when off. When on, run_ask lists the "
            "products whose Data Table rows offer that value "
            "(api/ask_attribute_search.py), falling back to the normal "
            "quote path when the attribute can't be grounded. "
            "Override with ARYX_CPQ_ATTR_SEARCH_ENABLED."
        ),
    )
    cpq_attr_search_max_choices: int = Field(
        default=5,
        description=(
            "Attribute-first discovery, phase 4: the most product families "
            "offered as a numbered choice when an attribute search matches "
            "several. 1 match starts the quote directly; 2..N are offered as "
            "choices; more than N gets a 'which product family?' question "
            "instead of a long list. Override with "
            "ARYX_CPQ_ATTR_SEARCH_MAX_CHOICES."
        ),
    )
