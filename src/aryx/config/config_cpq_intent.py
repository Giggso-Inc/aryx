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
    cpq_getconstraintvals_port_enabled: bool = Field(
        default=False,
        description=(
            "docs/oci-oracle/CONFIG_DATA_REQUIRED_FIELDS_INGEST_AND_FIX_PLAN_"
            "2026-10-05.md F1: when true, the util.getConstraintVals "
            "substitution (cpq/bml/bml_util_substitution.py) uses a port of "
            "the real util function (data_table_getconstraintvals.py) -- "
            "target matched in any whitelist column, only attributes EARLIER "
            "in the UI sequence filter a row, '~'/',' multi-select values "
            "split, R flag removes the blank option -- instead of "
            "resolve_whitelist_values' plain AND-equality match. Off by "
            "default: byte-identical to before this flag existed."
        ),
    )
    cpq_country_region_table_enabled: bool = Field(
        default=True,
        description=(
            "docs/oci-oracle/CONFIG_DATA_REQUIRED_FIELDS_INGEST_AND_FIX_PLAN_"
            "2026-10-05.md F5: derive_region (and the RTTE/TA lookup) consult "
            "the ingested newCountryRegion / rtteTAReference Data Tables "
            "(data_table_geo.py) before the static _COUNTRY_TO_REGION "
            "constant. On by default, so an ingested Data Table is used "
            "without a per-table switch; with no such table nothing changes "
            "(the constant stays the fallback). Set false to skip the tables."
        ),
    )
    cpq_empty_condition_rule_true_enabled: bool = Field(
        default=False,
        description=(
            "Plan F10 (docs/oci-oracle/CONFIG_DATA_AND_BEAUTIFY_CODE_FIX_PLAN_"
            "2026-10-05.md): a declarative hiding rule with NO conditions at "
            "all is always true (Oracle semantics) instead of 'unknown'. Off "
            "by default: byte-identical to before."
        ),
    )
    cpq_condition_expression_enabled: bool = Field(
        default=False,
        description=(
            "Plan F3: evaluate a rule's `condition_expression` over its "
            "`rule_input_index` rows (AND binds tighter than OR) instead of "
            "grouping inputs by attribute. Off by default."
        ),
    )
    cpq_constraint_mode_enabled: bool = Field(
        default=False,
        description=(
            "Plan F2: read the ALLOW/DISALLOW mode of a constraint action "
            "(the third argument of setConstraintValuesInSession) and apply "
            "its literal value list accordingly. Off by default."
        ),
    )
    cpq_master_string_hide_enabled: bool = Field(
        default=False,
        description=(
            "Plan F9: evaluate hide scripts that search a master string "
            "(SPLIT/findinarray) with the master string COMPUTED from the "
            "ingested attrSequence, instead of treating an empty master as "
            "'unknown'. Off by default."
        ),
    )
    cpq_hide_index_alias_enabled: bool = Field(
        default=False,
        description=(
            "Hide scripts of the shape `idx = findinarray(arr, \"x\"); if (other == -1) {...}` test an index "
            "variable they never assign (ws 1267: 3,225 scripts assign `lindex` and test `valindex`). When on, the "
            "master-string hide evaluation (cpq_master_string_hide_enabled) treats that unassigned name as the "
            "findinarray result instead of leaving the rule undecided. Off by default. "
            "Override with ARYX_CPQ_HIDE_INDEX_ALIAS_ENABLED=true."
        ),
    )
    cpq_script_rec_rule_conditions_enabled: bool = Field(
        default=False,
        description=(
            "A script-backed recommendation rule keeps its own declarative inputs (`bm_config_rule_input`) as "
            "`conditions`. They were dropped (condition_attr_id hard-coded to 0), so a master-string WRITER such as "
            "\"Set Hidden Master String For Astro Portable\" (input: attribute not blank) had no condition and its "
            "hide rules (~340 on ws 1267) could not be decided. They are kept as `RecommendationRule.writer_conditions`, "
            "apart from `conditions`, and only the master-string writer test reads them: rule ranking, the dependency "
            "graph and when the rule fires are unchanged. Off by default. "
            "Override with ARYX_CPQ_SCRIPT_REC_RULE_CONDITIONS_ENABLED=true."
        ),
    )
    cpq_find_function_enabled: bool = Field(
        default=False,
        description=(
            "Plan F14: the value-script evaluator understands "
            "`find(attr, \"text\") > -1` style tests, so region-dependent "
            "script defaults resolve deterministically (not via the LLM tier). "
            "Off by default."
        ),
    )
    cpq_bml_nested_if_enabled: bool = Field(
        default=True,
        description=(
            "Tier-1 BML evaluates a branch body that is itself an if/else "
            "chain (a nested if), instead of reporting the whole script as "
            "unparseable. Previously only available under the broader F14 "
            "flag (cpq_find_function_enabled); split out so nesting works "
            "without the rest of F14. Live case (2026-10-07, ws 1267): the "
            "'Hide HW Version unless APX Next NA...' hiding script nests its "
            "region check inside the model check, so it evaluated to unknown "
            "-> Hardware Version stayed visible and was asked for APX 900. "
            "A missing variable inside the nested chain still reports "
            "'blocked' (never guessed). On by default; set "
            "ARYX_CPQ_BML_NESTED_IF_ENABLED=false to restore the old behavior."
        ),
    )
    cpq_multiselect_default_enabled: bool = Field(
        default=False,
        description=(
            "Plan F11: several Defaultinattr rows for one multi-select "
            "attribute are its pre-checked set (list default) instead of "
            "'ambiguous, no default'. Off by default."
        ),
    )
    cpq_required_set_enabled: bool = Field(
        default=False,
        description=(
            "Plan F6/F4/F13: config_data, beautify's Mandatory section and the "
            "summary use ONE derived required set (attrSequence R, blank-"
            "disallow and message-only rules; visible, unfilled, with legal "
            "options) instead of the hand-listed tiers. Off by default."
        ),
    )
    cpq_required_set_asks_enabled: bool = Field(
        default=False,
        description=(
            "Needs cpq_required_set_rule_guards_assumed_open (or the older cpq_required_set_guards_assumed_open). Ask asks the attributes the derived required set marks "
            "required (attrSequence R, a blank-disallow rule, a message-only rule) instead of leaving them empty or "
            "guessing them: they become 'always ask, never guess' decision attributes, after the catalog's own "
            "defaults and rules have had their say. Today only the payload and the summary read the derived set, so "
            "ws 1267, APX 900: Encryption Type (required by a blank-disallow rule, optional in attrSequence) was never "
            "asked and the quote completed without it. Off by default. Override with "
            "ARYX_CPQ_REQUIRED_SET_ASKS_ENABLED=true."
        ),
    )
    cpq_required_set_rule_guards_assumed_open: bool = Field(
        default=False,
        description=(
            "Like cpq_required_set_guards_assumed_open, but read ONLY by the derived required set (rule_required_vns): "
            "a guard variable the quote never carries (the host supplies TER in production) counts as populated, so the "
            "TER-gated blank-disallow rule for Encryption Type is in the required set. Unlike the older setting it "
            "does NOT change the constraint-rule applier, so option narrowing on every model keeps today's behaviour. "
            "Use this one with cpq_required_set_asks_enabled. Off by default. Override with "
            "ARYX_CPQ_REQUIRED_SET_RULE_GUARDS_ASSUMED_OPEN=true."
        ),
    )
    cpq_required_set_master_string_present_enabled: bool = Field(
        default=False,
        description=(
            "Required set only. A hidden, option-less attribute whose name contains 'MasterString' (hiddenConstraintMaster"
            "String_astro and the like), that the quote never fills, counts as NON-BLANK when a blank-disallow or message-"
            "only rule tests it. Real CPQ fills these strings from rules at run time; nothing in the engine does, so the "
            "'is not blank' input of 'Restrict blank value for Encryption Type for US or FED customers' (and 70+ rules like "
            "it) could never be true and Encryption Type was never required. The rule's other inputs (country, model list, "
            "bundle, product) still decide. Other hidden attributes (pdKey, Region, Customer UIN) are not assumed. Off by "
            "default. Override with ARYX_CPQ_REQUIRED_SET_MASTER_STRING_PRESENT_ENABLED=true."
        ),
    )
    cpq_required_set_guards_assumed_open: bool = Field(
        default=False,
        description=(
            "Plan F6: a blank-disallow action wrapped in `if(<variable> <> \"\")` "
            "only runs when that session variable has a value. The variable is "
            "supplied by the host, not by the quote. When true, a guard variable "
            "that is absent from the quote state is assumed to be populated (as "
            "in production); when false (default) such a rule does not fire. "
            "Applies both to the derived required set and to constraint-rule "
            "ALLOW/DISALLOW actions when options are narrowed."
        ),
    )
    cpq_series_model_narrowing_enabled: bool = Field(
        default=False,
        description=(
            "Plan F8: before attrSequence/whitelist rows are read for the "
            "derived required set, drop the CPQ models of series children that "
            "the ingested series-mapping table does not offer for the quote's "
            "country/region (an undecidable row keeps the model). Off by default."
        ),
    )
    cpq_required_set_shadow_enabled: bool = Field(
        default=False,
        description=(
            "Plan F6 shadow mode: compute the derived required set next to "
            "the current classification and LOG the difference; never changes "
            "any output. Off by default."
        ),
    )
    cpq_model_prefix_tie_ask_enabled: bool = Field(
        default=False,
        description=(
            "Plan F16: when the wording names model A in full and is a strict "
            "prefix of another sellable model B on a different catalog node, "
            "ask which one instead of silently picking A. Off by default."
        ),
    )
    cpq_model_switch_snapshot_enabled: bool = Field(
        default=False,
        description=(
            "Changing the Product (model) answer inside one family asks to confirm "
            "first, saves the old model's answers and restores the new model's "
            "saved answers (or starts clean), the same as a family switch. "
            "Off by default: the change runs today's cascade with no prompt."
        ),
    )
    cpq_blank_free_text_in_conditions_enabled: bool = Field(
        default=False,
        description=(
            "BML reads an unset text variable as an empty string. When on, constraint-rule "
            "condition scripts see every unfilled free-text attribute (no menu options) as "
            "'' instead of unknown, e.g. a customer type nobody entered counts as not federal."
        ),
    )
    cpq_layout_variants_enabled: bool = Field(
        default=False,
        description=(
            "Plan section 3: several layout exports per catalog, keyed by the "
            "layout file's own `variableName`; the one for the resolved "
            "model is chosen from the catalog's Configuration Flow rules. "
            "Off by default: one layout per catalog, as before."
        ),
    )
    cpq_layout_hidden_anchor_skip_enabled: bool = Field(
        default=True,
        description=(
            "The Product always-ask override forces a question for an attribute the native UI is "
            "assumed to show. When on, a Product attribute the catalog's layout explicitly marks "
            "`hide: true` is not force-asked (SVX hides it; every APX/Astro layout shows it). It is "
            "neither asked nor blind-filled. No layout, or no `hide: true`, changes nothing. "
            "Override with ARYX_CPQ_LAYOUT_HIDDEN_ANCHOR_SKIP_ENABLED=false."
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
    cpq_attr_search_budget_s: float = Field(
        default=25.0,
        description=(
            "Attribute-first discovery: time budget (seconds) for one "
            "attribute search. A cold catalog cache can take tens of seconds "
            "to load; past the budget the turn takes the normal quote path "
            "(never a partial result) while the lookup keeps running to warm "
            "the cache. Keep it under the deployment's proxy timeout. "
            "Override with ARYX_CPQ_ATTR_SEARCH_BUDGET_S."
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
    cpq_grid_quantity_pending_selectors_only_enabled: bool = Field(
        default=False,
        description=(
            "The upfront grid-quantity flow asks a quantity for every option of a grid selector that has no selection "
            "yet. With this flag it does that only for a selector the pass actually left pending (or one that already "
            "holds a selection): a selector the engine decided is not applicable for the model (not-applicable guard, "
            "model-scoped questions) is not resurrected as 7 quantity questions after auto-fill finished with 0 pending "
            "(ws 1267, APX N30: 'hiddenConventionalOptionsMaxQuantityAry_astro', 'backplaneQuantityHolder_astro', ...). "
            "Callers that name one selector (selector_vns) are unchanged. Off by default. Override with "
            "ARYX_CPQ_GRID_QUANTITY_PENDING_SELECTORS_ONLY_ENABLED=true."
        ),
    )
    cpq_derive_discriminators_first_enabled: bool = Field(
        default=False,
        description=(
            "Needs cpq_derive_base_model_enabled. The base model narrowing applies every known answer as a "
            "restriction, so an attribute the whitelist only uses as a CONDITION of other attributes' rows (country: "
            "'delete narrowbanding waiver when country US') excludes base models that merely have no such row. With "
            "this flag only the attributes that separate the model's base models (each holds exactly one value: "
            "frequency band, keypad type) and the attributes the rows treat as a target narrow, the separating ones "
            "first. ws 1267, APX 900: country US dropped the two 700/800 MHz base models (10 -> 8), the 700/800 MHz "
            "answer then matched nothing and the base model was asked from 660 options; the same exclusion would "
            "remove 700/800 MHz from the frequency question. Off by default. Override with "
            "ARYX_CPQ_DERIVE_DISCRIMINATORS_FIRST_ENABLED=true."
        ),
    )
    cpq_base_model_defaults_enabled: bool = Field(
        default=False,
        description=(
            "Needs the base model to be derived (cpq_derive_base_model_enabled and the flags that let it "
            "resolve). Once the base model is known, an attribute the customer did not answer gets the base "
            "model's Defaultinattr default, replacing the value an earlier pass picked before the base model "
            "existed (the first or only option, tagged 'rule'). ws 281, APX N30: antenna STANDARD instead of "
            "WHIP, keypad NO KEYPAD instead of LIMITED KEYPAD, data cable YES instead of NO, ... A value from "
            "the customer, their wording, or a recommendation rule that is satisfied now is kept; the default "
            "must be a real, currently allowed option; hidden attributes, multi-selects, the decision anchors "
            "and the attributes the engine always asks (country, region, hardware version, select-model, "
            "base model) are not touched. Off by default. Override with "
            "ARYX_CPQ_BASE_MODEL_DEFAULTS_ENABLED=true."
        ),
    )
    cpq_derive_base_model_default_owner_enabled: bool = Field(
        default=False,
        description=(
            "Needs cpq_derive_base_model_enabled. When the Whitelist leaves 2+ base models of the resolved model "
            "(every base model lists every frequency band, so a known band narrows nothing) derive the one that owns "
            "the model's default configuration: every left base model has Defaultinattr rows and exactly one defines "
            "defaults for a strict superset of the attributes of each of the others. Not used when a value the "
            "customer gave (typed or from their wording) differs from that base model's default for the same "
            "attribute. Today (APX N70) the base model stays unknown and the customer is asked flashcode digits and "
            "the band. Never overrides the Whitelist, never guesses among 2+. Off by default. Override with "
            "ARYX_CPQ_DERIVE_BASE_MODEL_DEFAULT_OWNER_ENABLED=true."
        ),
    )
    cpq_model_scoped_questions_enabled: bool = Field(
        default=False,
        description=(
            "Needs the base model to be known first: cpq_model_resolution_enabled and cpq_rule_scope_filter_enabled (so "
            "other products' rules do not fire), cpq_base_model_placeholder_guard_enabled (so a rule's '*' is not taken "
            "as the base model) and cpq_derive_base_model_enabled; with the base model empty it changes nothing. "
            "Once the base model is known and the model has AttrSequence rows for it, an attribute those rows do not "
            "list is not applicable: not asked and not filled, and a value an earlier pass only guessed for it is "
            "dropped (ws 281, APX N30: 'LORA Region', 'regionalSrvMgrName', ~600 attributes of other families asked or "
            "filled). Kept: attributes the rows list, the exact decision anchors the engine already resolves itself "
            "(country, hardware version, product, base model, region), and any attribute holding a value that came from the "
            "customer or the engine's own context (an answer, a wording match, the session variables it fills) or a "
            "hidden attribute's own default; values only a rule or a guess put there are dropped. Without it such an "
            "attribute stays visible ('silence is not a confident exclusion'), and any name containing 'region' or "
            "'product' is protected. Models with no AttrSequence rows for the base "
            "model are untouched. Also controls how a display name is compared with the customer's wording: the "
            "trademark, registered, copyright and service-mark signs are ignored, so 'APX(TM) N50' and 'APX N50' "
            "resolve to the same models (data_table_product.resolve_cpq_model_from_display_name); turning this off "
            "brings the old comparison back. Off by default. Override with ARYX_CPQ_MODEL_SCOPED_QUESTIONS_ENABLED=true."
        ),
    )
    cpq_model_resolution_tree_fallback_enabled: bool = Field(
        default=False,
        description=(
            "Needs cpq_model_resolution_enabled. When the Basemodeltoconfig rows name no model for the customer's "
            "wording (the table is missing or has no row for it), resolve the model from the BmCatalog tree itself: "
            "a LEAF catalog node whose name appears in the wording (longest name wins). The resolved node's "
            "ancestors are then the scope cpq_rule_scope_filter_enabled keeps, so recommendation / hiding / "
            "constraint rules authored under another model's node stop firing for this one (ws 281, APX N30: rules "
            "of other products filled the base model with a code of another family, then '*'). With Basemodeltoconfig "
            "rows present nothing changes. Off by default. Override with "
            "ARYX_CPQ_MODEL_RESOLUTION_TREE_FALLBACK_ENABLED=true."
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
    cpq_no_blind_fill_optional_enabled: bool = Field(
        default=False,
        description=(
            "An optional single-select attribute (not catalog-required, not a decision, forced-ask or derived-required "
            "attribute) that no earlier stage could resolve is left unanswered instead of being filled with the first "
            "option (`default_first_available`, `blind_pick_governed`, `blind_pick_rule_governed`). Today (ws 1267, "
            "APX 3000) Mission Critical Wireless Accessory Bundle went into the BOM as Pack 1 although it is optional, "
            "has no default and the real screen offers None. Can leave a rule cascade that needed the value open. Off "
            "by default. Override with ARYX_CPQ_NO_BLIND_FILL_OPTIONAL_ENABLED=true."
        ),
    )
    cpq_restrict_hide_lists_are_remove_enabled: bool = Field(
        default=False,
        description=(
            "A declarative constraint action (`set_type -1`) of a rule whose name starts with Restrict or Hide carries the "
            "values to TAKE AWAY, not the values that stay (loaded today as an allow-list). Only applied when at least one "
            "listed value is a real option of the target and something would remain; otherwise the old reading is kept "
            "(quantity limits, numbers, a list that would empty the attribute). Constrain... rules are not touched. Today "
            "(ws 1267, APX 4000) 'Restrict Frequency Band except 900MHz' (VHF, 700/800, UHF R1, UHF R2, 8/900) offered "
            "exactly those bands and left out 900 MHz, the only one the real screen offers. Off by default. Override with "
            "ARYX_CPQ_RESTRICT_HIDE_LISTS_ARE_REMOVE_ENABLED=true."
        ),
    )
    cpq_defaultinattr_resolves_ambiguity_enabled: bool = Field(
        default=False,
        description=(
            "Needs cpq_defaultinattr_shape_enabled. When the Whitelist leaves 2+ legal values for an attribute and the "
            "resolved base model's Defaultinattr default is ONE of them, take that default. It does not override the "
            "Whitelist: it breaks the tie the Whitelist leaves. Today (ws 1267, APX 900) antenna type, carry type, package "
            "type and hazardous location were AMBIGUOUS_DISCARDED on every pass and fell to a first-option guess although "
            "Defaultinattr names the real default (Whip (Standard), 2.0 inch, Bulk, N/A); a guessed battery then forced "
            "hazardous to TIA-4950 (UL) through the Whitelist. A default outside the legal values, a single legal value "
            "and an attribute without Whitelist rows behave as before. Off by default. Override with "
            "ARYX_CPQ_DEFAULTINATTR_RESOLVES_AMBIGUITY_ENABLED=true."
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
    cpq_oracle_fetch_rules_ordered_binds_enabled: bool = Field(
        default=False,
        description=(
            "OracleCpqRdb.fetch_rules named its placeholders :1, :3, :2 but passed (workspace_id, rule_type, "
            "type_pattern), so the pattern landed in the rule_type test and the rule type in the LIKE: it returned no "
            "rows and no error for every rule type (ws 1267: 3,481 active rule_type=11 hiding rules, 0 loaded; the "
            "same read serves rule_type 6 flow and 9 validation rules). When on the placeholders and values are in the "
            "same order. Loading those rules changes hiding on every product, so enable it in dev first and compare. "
            "Off by default. Override with ARYX_CPQ_ORACLE_FETCH_RULES_ORDERED_BINDS_ENABLED=true."
        ),
    )
    cpq_catalog_model_key_enabled: bool = Field(
        default=False,
        description=(
            "When a model has no rule rows under its own name, offer the data-table model key the catalog's own "
            "mapping script gives for the selected product (for example product APX8000 -> key APX8000/XE) as the "
            "first model candidate, only when the Attrsequence table has rows under it. Also turns on the "
            "punctuated-code candidates (a family whose sequence rows sit under codes such as APX8000/XE, found "
            "through the hierarchy display list). Off by default. Override with ARYX_CPQ_CATALOG_MODEL_KEY_ENABLED=true."
        ),
    )
    cpq_catalog_model_key_ttl_seconds: int = Field(
        default=900,
        description=(
            "Seconds the parsed product -> model key map is kept per workspace before the catalog scripts are "
            "read again. Override with ARYX_CPQ_CATALOG_MODEL_KEY_TTL_SECONDS."
        ),
    )
    cpq_base_model_narrowing_enabled: bool = Field(
        default=False,
        description=(
            "Base model from the model's own answers, both directions (ws 1267, 'I want a quote for APX 900': the "
            "base model was asked from 660 options and the typed frequency band and keypad were guessed). When on, "
            "(1) the attributes that separate a model's base models, read from that model's own whitelist rows "
            "(every base model has exactly one value for them and the values differ), are asked and never guessed; "
            "(2) the base model question is deferred while one is unanswered, so the existing derivation fills it; "
            "(3) a part-number base-model attribute the layout hides is not asked; (4) a known base model fills its "
            "unanswered separating attributes; (5) a typed phrase owned by several attributes is hinted for the one "
            "owner those rows use. Behaviours 1-4 also need ARYX_CPQ_DERIVE_BASE_MODEL_ENABLED (the derivation fills "
            "the base model); 5 does not. Off by default. "
            "Override with ARYX_CPQ_BASE_MODEL_NARROWING_ENABLED=true."
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
    cpq_rule_governed_hidden_attr_guard_enabled: bool = Field(
        default=False,
        description=(
            "Port of dev-rv-msi #373/#374. When on, (a) rule_target_ids "
            "also includes BmConfigMarkedAttr targets (not only "
            "BmConfigRuleAction targets), and (b) resolve_array_grid_links "
            "excludes rule-governed hidden attrs (ConfigAttr."
            "is_value_rule_target) from its name-substring 'Quantity' "
            "candidate guess, so they are never surfaced as unanswerable "
            "'Please provide a value' questions. Side effect: the wider "
            "rule_target_ids also changes which attrs build_config_attrs "
            "keeps -- hidden, no-default attrs that are marked-attr-only "
            "targets used to be dropped and are now retained (Amendment 13 "
            "rationale); confirm no other consumer surfaces them during "
            "rollout. Off by default. Override "
            "with ARYX_CPQ_RULE_GOVERNED_HIDDEN_ATTR_GUARD_ENABLED=true."
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
    cpq_not_applicable_guard_enabled: bool = Field(
        default=False,
        description=(
            "Port of dev-rv-msi #362/#364/#365. When on, (a) a new first "
            "auto-fill stage skips and clears (never a customer-confirmed "
            "'user' value) any non-anchor attribute, and Hardware "
            "Version, that real Data Table evidence confirms is never "
            "governed for the device resolved from the customer's "
            "original wording, so it is no longer blind-filled; and (b) "
            "run_auto_fill drops such attributes from the pending list so "
            "shared multi-model layouts stop asking irrelevant questions. "
            "One-sided: never adds or forces an attribute; a no-op when "
            "the device is unresolved or ambiguous. Off by default. "
            "Override with ARYX_CPQ_NOT_APPLICABLE_GUARD_ENABLED=true."
        ),
    )
    cpq_basemodel_display_name_resolution_enabled: bool = Field(
        default=False,
        description=(
            "Port of dev-rv-msi #341/#351/#365/#366. When on, a customer's "
            "free-text device mention (e.g. 'APX 900') is resolved through "
            "the Basemodeltoconfig displayModel -> cpqModel Data Table: "
            "resolve_product_cpq_models_from_hint tries it before the "
            "constraint-row scan, and resolve_product_hint gets a new "
            "first pass (graph, then the RDB when the graph is empty) "
            "that returns a unique catalog match, refuses when 2+ "
            "catalogs match, and otherwise falls to the existing passes. "
            "Off by default. Override with "
            "ARYX_CPQ_BASEMODEL_DISPLAY_NAME_RESOLUTION_ENABLED=true."
        ),
    )
    cpq_rdb_call_timeout_enabled: bool = Field(
        default=False,
        description=(
            "Port of dev-rv-msi #368 (Part A). When on, CPQ RDB reads bound "
            "each borrowed connection: Postgres issues SET statement_timeout "
            "(int literal) and resets it to DEFAULT on release; Oracle sets "
            "connection.call_timeout and restores the previous value. A "
            "timeout inside a swallowed rdb error is logged at WARNING. "
            "Off by default. Override with "
            "ARYX_CPQ_RDB_CALL_TIMEOUT_ENABLED=true."
        ),
    )
    cpq_rdb_call_timeout_ms: int = Field(
        default=60000,
        description=(
            "Per-call timeout in milliseconds for CPQ RDB reads when "
            "cpq_rdb_call_timeout_enabled is on. Override with "
            "ARYX_CPQ_RDB_CALL_TIMEOUT_MS."
        ),
    )
    cpq_rule_trace_write_timeout_enabled: bool = Field(
        default=False,
        description=(
            "Port of dev-rv-msi #363. When on, RuleTraceStore.open_session "
            "and append_entry are bounded (Postgres SET LOCAL "
            "statement_timeout; Oracle connection.call_timeout restored "
            "afterwards) and a per-run circuit breaker stops DB writes "
            "after repeated consecutive append failures. Off by default. "
            "Override with ARYX_CPQ_RULE_TRACE_WRITE_TIMEOUT_ENABLED=true."
        ),
    )
    cpq_rule_trace_write_timeout_ms: int = Field(
        default=5000,
        description=(
            "Timeout in milliseconds for rule-trace DB writes when "
            "cpq_rule_trace_write_timeout_enabled is on. Override with "
            "ARYX_CPQ_RULE_TRACE_WRITE_TIMEOUT_MS."
        ),
    )
    cpq_rule_trace_breaker_threshold: int = Field(
        default=5,
        description=(
            "Consecutive append_entry failures for one run_id after which "
            "rule-trace DB writes for that run stop (local .jsonl is "
            "unaffected). Override with ARYX_CPQ_RULE_TRACE_BREAKER_THRESHOLD."
        ),
    )
    cpq_rule_trace_flush_batch_size: int = Field(
        default=100,
        description=(
            "PR #458 review (Low finding 4): fired-rule rows buffered by "
            "record_fire() before being durably written as one "
            "append_entries_batch() round trip (one connection acquire + "
            "executemany, instead of one acquire+ping+insert per fire --"
            "confirmed live, a fresh connection acquire costs ~0.44s just "
            "for the pool's dead-connection ping on top of the insert's "
            "own round trip, and a single turn can fire 1000+ rules). "
            "100 (raised from an initial 50) roughly halves the round-trip "
            "count again on a 1000+-fire turn (~20 -> ~10 flushes), at the "
            "cost of up to 100 buffered-but-not-yet-durable rows in memory "
            "if the process crashes mid-turn before the next flush point "
            "(evaluate_rules_loop's end, ask_api._run_cpq_turn's finally, "
            "and seal() all still flush regardless of count) -- diminishing "
            "returns past this, since the fix's main win (~1000 round trips "
            "-> a handful) is already captured well before 100. Override "
            "with ARYX_CPQ_RULE_TRACE_FLUSH_BATCH_SIZE."
        ),
    )
    cpq_tables_cache_lock_enabled: bool = Field(
        default=False,
        description=(
            "Port of dev-rv-msi #368 Part B / #371. When on, "
            "_load_all_tables serialises concurrent cache-miss scans of the "
            "same (workspace_id, catalog_prefix) behind a per-key "
            "threading.Lock with a post-lock cache re-check, so a burst of "
            "concurrent requests runs one scan instead of one each. The "
            "lock wait is bounded by cpq_tables_cache_lock_timeout_s; on "
            "timeout a WARNING is logged and the scan runs unlocked. Off by "
            "default (no lock). Override with "
            "ARYX_CPQ_TABLES_CACHE_LOCK_ENABLED=true."
        ),
    )
    cpq_tables_cache_lock_timeout_s: float = Field(
        default=90.0,
        description=(
            "Maximum seconds a request waits for another thread's in-flight "
            "tables-cache scan before scanning unlocked. Only used when "
            "cpq_tables_cache_lock_enabled is on. Keep it above "
            "cpq_rdb_call_timeout_ms (so a waiter outlasts a bounded scan) "
            "and BELOW cpq_post_loop_timeout_s (so the request does not "
            "504 while its waiters are still blocked). Override with "
            "ARYX_CPQ_TABLES_CACHE_LOCK_TIMEOUT_S."
        ),
    )
    cpq_post_loop_timeout_enabled: bool = Field(
        default=False,
        description=(
            "Port of dev-rv-msi #371/#372. When on, the post-loop "
            "auto_fill in _step10_recompute_pending runs in a bounded "
            "module-level thread pool (context-copied) and raises HTTP 504 "
            "after cpq_post_loop_timeout_s; the loop and the post-loop "
            "auto_fill also share one per-turn Data Table cache. Off by "
            "default (plain synchronous call, no shared cache). Override "
            "with ARYX_CPQ_POST_LOOP_TIMEOUT_ENABLED=true."
        ),
    )
    cpq_post_loop_timeout_s: float = Field(
        default=120.0,
        description=(
            "Seconds the post-loop auto_fill may run before the request "
            "fails with HTTP 504. Only used when "
            "cpq_post_loop_timeout_enabled is on. Must be ABOVE "
            "cpq_rdb_call_timeout_ms (default 60 s) and above "
            "cpq_tables_cache_lock_timeout_s (default 90 s); a warning is "
            "logged once if the ordering is inverted. The pool has a fixed "
            "number of workers that cannot be cancelled, so when every "
            "worker is busy (including abandoned timed-out ones) new calls "
            "are rejected with HTTP 503 instead of queueing. Override with "
            "ARYX_CPQ_POST_LOOP_TIMEOUT_S."
        ),
    )
