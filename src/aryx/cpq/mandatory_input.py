"""``_is_mandatory_input_attr`` (Phase 4, one of the 8 previously-
deferred oversized `CpqEngine` methods, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). `_ATTRSEQ_CONFIRMED_REQUIRED_VNS`/
`_DECISION_REQUIRED_KEYS` are read off the engine MODULE object.
"""

from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.cpq import engine as _engine_module


def is_mandatory_input_attr(
    engine: Any, vn: str, attr: "Any | None", source: str | None,
    active_sources: frozenset[str] | None = None,
    required_vns: frozenset[str] | None = None,
    exclude_anchor_vns: frozenset[str] | None = None,
    gate_attrseq_confirmed_to_active_source: bool = False,
    rule_forced_active_vns: frozenset[str] | None = None,
    data_table_forced_vns: frozenset[str] | None = None,
    hint_text: str | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    _dt_cache: dict[tuple[int, str], tuple] | None = None,
) -> bool:
    """Tier A/B/C scoping key (docs/CPQ_GOVERNED_BLINDPICK_AND_CONFIGDATA_
    BEAUTIFY_FIX_PLAN_2026_08_14.md Fix 2, extended for beautify's
    Mandatory/System split, further extended 2026-08-19 with Tier C —
    docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md)
    — True for structurally-required decision anchors (Hardware
    Version, exact productSelectionProduct_all match, "basemodel"/
    "selectmodel"-named attrs), the small named set of attrs
    individually live-verified Required via the real per-base-model
    Attrsequence Data Table (`_ATTRSEQ_CONFIRMED_REQUIRED_VNS`),
    attributes the customer directly answered (source=="user"), and
    (Tier C, opt-in via `required_vns`) AttrSequence-Required attrs
    genuinely unresolved by any Whitelist/Defaultinattr row. Shared by
    `build_payload` (scopes `config_data` to this set — Tier C is
    NEVER passed there, see docs/CPQ_ConfigData_Payload_Mandatory_
    Fix_Scope_2026_08_19.md), `beautify_rows`/`beautify_text` (splits
    their output into a "Mandatory User Input" section vs. "System-
    Configured / Recommended"), and the conversational summary
    (`_filled_summary_triples`) — one scoping key, three consumers, so
    none can silently drift apart on what counts as "genuinely
    required" within their own intended scope.

    Deliberately does NOT read `ConfigAttr.required` (bm_config_attr.
    required) — PR #220 review: that field is confirmed live 0/
    unreliable for essentially every attribute in this catalog (a flat,
    catalog-wide column, not real per-base-model requiredness); an
    earlier version keying off it directly silently no-opped for exactly
    the attrs it was meant to fix (e.g. baselineReleaseSW_astro, 448/449
    real Attrsequence rows Required despite bm_config_attr.required==0).

    `_ATTRSEQ_CONFIRMED_REQUIRED_VNS` is a hand-verified, stopgap
    allowlist (cheap, no DB round-trip) covering only attrs someone has
    live-verified so far. `required_vns` (Tier C) generalizes the same
    idea via a live per-(cpq_model, base_model) AttrSequence query,
    automatically covering fields the named set explicitly doesn't
    (Configuration Type, Solution Type, Duration, Battery Type, Include
    a Spare, per-item Application Services checkboxes) with no manual
    verification — see `mandatory_tier_c_vns`. Both stay, deliberately:
    Tier C is never passed to `build_payload` (unlike the named set).

    `attr` may be `None` (no ConfigAttr resolved for this key) — such a
    key can never be a structural anchor, so only the `source=="user"`
    fallback (or Tier C, which needs no `attr`) can include it.

    All params below default to a no-op that preserves every existing
    caller's prior behavior byte-for-byte; only `build_payload` (config_
    data scoping) opts into most of them, and beautify/the summary opt
    into `required_vns` only, exactly as noted per param.

    `active_sources` — `build_payload` passes `_CONFIG_DATA_ACTIVE_
    SOURCES` (default `None` == literal `source == "user"`) so a genuine
    decision tagged "hint"/"cascade"/"cascade-dependent"/"country_derived"/
    "product_anchor" also qualifies for `config_data`, without touching
    beautify's/the summary's own behavior.

    `required_vns` — Tier C opt-in via `mandatory_tier_c_vns`'s result;
    beautify and the summary pass this, `build_payload` never does.

    `exclude_anchor_vns` — `build_payload` passes `_data_table_resolved_
    anchor_vns`'s result so a `config_data`-only exception (an anchor-
    named attribute that's actually 100% data-table-resolved, e.g.
    modelSelectionbaseModel_astro via NewCountryRegMapping, rather than
    a genuine customer decision) is excluded from `config_data`
    specifically (docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_
    2026_08_19.md), without changing beautify's/the summary's own Tier A
    behavior.

    `gate_attrseq_confirmed_to_active_source` — PR #220's named set
    (`_ATTRSEQ_CONFIRMED_REQUIRED_VNS`) has no per-consumer gate the way
    `exclude_anchor_vns`/`required_vns` do — membership alone (e.g.
    baselineReleaseSW_astro, applicationServicesSelection_astro) was
    leaking genuinely catalog-defaulted (never customer-decided) values
    into `config_data`, contradicting `scope_required_and_edited`'s own
    "blind-picked defaults excluded" contract. `build_payload` passes
    `True` so a named-set member only counts toward Tier A for
    `config_data` when it's ALSO actively sourced; beautify's/the
    summary's calls are unaffected — still land in Mandatory/the summary
    regardless of source, matching PR #220's original intent there.

    `rule_forced_active_vns` — a `source=="rule"` value isn't always the
    "blind-picked default" `gate_attrseq_confirmed_to_active_source` was
    built to exclude — confirmed live (workspace 93, wirelessCarrier_
    astro forced to "LTE CAPABILITY NO SERVICE" by the real rule "Force
    Set Wireless Carrier... when ATAK is enabled") a RecommendationRule
    can deterministically force a value as the direct, causal consequence
    of a decision the CUSTOMER already made — no less genuine than a
    "cascade" copy. `build_payload` passes `_rule_forced_from_active_
    decision_vns`'s result: variable_names whose single declarative-
    condition RecommendationRule was triggered by an actively-sourced
    attr, counting as actively sourced too, on top of (never instead of)
    the plain `active_sources` check.

    `data_table_forced_vns` — same spirit, different resolution path: an
    `_ATTRSEQ_CONFIRMED_REQUIRED_VNS` member whose value the real
    ingested Whitelist/Defaultinattr Data Table confirms as ANY genuine
    legal option (deliberately not requiring it be the only one — live
    data proved "exactly one" too strict: wirelessCarrier_astro genuinely
    has 2 legal values, "ATT/FIRSTNET" and "VERIZON", for base model
    H55TGT9PW8AN + Country=US). A catalog-proven answer isn't a blind-
    picked default — `build_payload` passes `_data_table_forced_vns`'s
    result so it counts as actively sourced too.

    `hint_text`/`workspace_id`/`catalog_prefix`/`_dt_cache` — docs/
    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3: Tier A's Hardware
    Version branch used to mark ANY Hardware Version attr structurally
    mandatory with no applicability check. These four (all `None`/``""``
    by default) feed `CpqEngine._hardware_version_confirmed_not_
    applicable` — the same real, already-wired-in applicability check
    `auto_fill_hw_order`/`governance_flags` already consult — so Tier A
    stops forcing Hardware Version when the customer's own wording
    already confidently resolves to a device whose real attrSequence
    data proves Hardware Version is never governed for it. One-sided
    (see that method's own docstring): with no hint/workspace_id (every
    existing caller that doesn't opt in), it always returns `False`, so
    `not False` is `True` and this branch is byte-for-byte identical to
    before.
    """
    vn_flat = vn.lower().replace("_", "")
    _excluded_anchors = exclude_anchor_vns or frozenset()
    is_active_source = (
        source in active_sources if active_sources is not None
        else source == "user"
    ) or (rule_forced_active_vns is not None and vn in rule_forced_active_vns) or (
        data_table_forced_vns is not None and vn in data_table_forced_vns
    )
    # plan F6: with the derived required set driving, the hand-listed names are not consulted
    attrseq_confirmed = (
        vn in _engine_module._ATTRSEQ_CONFIRMED_REQUIRED_VNS
        and not get_settings().cpq_required_set_enabled
    )
    if gate_attrseq_confirmed_to_active_source:
        attrseq_confirmed = attrseq_confirmed and is_active_source
    tier_a = attr is not None and (
        vn == "productSelectionProduct_all"
        or (
            engine._is_hardware_version_attr(attr)
            and not engine._hardware_version_confirmed_not_applicable(
                hint_text, workspace_id, catalog_prefix, _dt_cache)
        )
        or ("basemodel" in vn_flat and vn not in _excluded_anchors)
        or ("selectmodel" in vn_flat and vn not in _excluded_anchors)
        or attrseq_confirmed
    )
    tier_b = (
        any(dk in vn_flat for dk in _engine_module._DECISION_REQUIRED_KEYS)
        and is_active_source
    )
    tier_c = required_vns is not None and vn in required_vns
    return tier_a or tier_b or tier_c or is_active_source
