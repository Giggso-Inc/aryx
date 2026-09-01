"""_ATTRSEQ_CONFIRMED_REQUIRED_VNS (PR #220) has no per-consumer gate --
baselineReleaseSW_astro/applicationServicesSelection_astro/
carrierSelectionMultiSelect_astro land in beautify's "Mandatory User
Input" section unconditionally (PR #220's intent), but that same
unconditional membership was also leaking genuinely catalog-defaulted
(never customer-decided) values into config_data, contradicting
scope_required_and_edited's own contract ("blind-picked defaults" must
be excluded) -- live-confirmed via a real config_data sample containing
baselineReleaseSW_astro/applicationServicesSelection_astro despite
neither being customer-answered.

Fix: gate_attrseq_confirmed_to_active_source (default False, beautify/
summary unaffected) -- when True (build_payload's own two call sites),
a named-set member only counts toward Tier A if it's ALSO actively
sourced.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption, RecommendationRule


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attr(entity_id: int, vn: str, label: str, select_type: str = "single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=label,
        required=False, default_value="", select_type=select_type,
        options=_menu("A", "B"),
    )


def test_beautify_and_summary_default_unaffected_by_gate():
    """No gate_attrseq_confirmed_to_active_source passed (beautify's/the
    summary's own call shape) -- unconditional inclusion, exactly PR
    #220's original intent, regardless of source."""
    engine = CpqEngine()
    attr = _attr(1, "baselineReleaseSW_astro", "Software Release")
    assert engine._is_mandatory_input_attr(
        "baselineReleaseSW_astro", attr, "rule",
    ) is True
    assert engine._is_mandatory_input_attr(
        "baselineReleaseSW_astro", attr, "default",
    ) is True


def test_config_data_gate_excludes_passively_sourced_attrseq_confirmed_attr():
    engine = CpqEngine()
    attr = _attr(1, "baselineReleaseSW_astro", "Software Release")
    assert engine._is_mandatory_input_attr(
        "baselineReleaseSW_astro", attr, "rule",
        gate_attrseq_confirmed_to_active_source=True,
    ) is False
    assert engine._is_mandatory_input_attr(
        "baselineReleaseSW_astro", attr, "default",
        gate_attrseq_confirmed_to_active_source=True,
    ) is False


def test_config_data_gate_still_includes_actively_sourced_attrseq_confirmed_attr():
    engine = CpqEngine()
    attr = _attr(1, "applicationServicesSelection_astro", "Application Services Selection")
    assert engine._is_mandatory_input_attr(
        "applicationServicesSelection_astro", attr, "user",
        gate_attrseq_confirmed_to_active_source=True,
    ) is True
    # Also honors the widened _CONFIG_DATA_ACTIVE_SOURCES set, not just "user".
    assert engine._is_mandatory_input_attr(
        "applicationServicesSelection_astro", attr, "hint",
        active_sources=engine._CONFIG_DATA_ACTIVE_SOURCES,
        gate_attrseq_confirmed_to_active_source=True,
    ) is True


def test_build_payload_config_data_excludes_passively_filled_software_release():
    """End-to-end: build_payload(scope_required_and_edited=True) drops
    Software Release from config_data when it's a passive catalog
    default, matching the live-observed sample."""
    engine = CpqEngine()
    sw_release_attr = _attr(1, "baselineReleaseSW_astro", "Software Release")
    carrier_attr = _attr(2, "carrierSelectionMultiSelect_astro", "Carrier Selection")
    filled = {
        "baselineReleaseSW_astro": "BASELINE RELEASE",
        "carrierSelectionMultiSelect_astro": "ATT/FIRSTNET",
    }
    sources = {
        "baselineReleaseSW_astro": "rule",
        "carrierSelectionMultiSelect_astro": "user",
    }

    payload = engine.build_payload(
        filled, sources, {}, [sw_release_attr, carrier_attr],
        scope_required_and_edited=True,
    )
    assert "baselineReleaseSW_astro" not in payload["configData"]
    assert "carrierSelectionMultiSelect_astro" in payload["configData"]


def test_config_data_includes_wireless_carrier_when_actively_sourced():
    """2026-08-20: wirelessCarrier_astro (single-select, 4G-only base
    models e.g. H45TGT9PW8AN/H55TGT9RW8AN) and carrierSelectionMultiSelect_
    astro (multi-select, 5G base model H55TGT9PW8BN) are confirmed-live
    mutually-exclusive per-base-model siblings for the same "carrier"
    concept -- Attrsequence optionOrReqFlag=="R" for real APX NEXT
    CPQModels, zero shared base models between the two. Both belong in
    _ATTRSEQ_CONFIRMED_REQUIRED_VNS, gated the same way, so the 4G base
    model gets its own Carrier attribute in config_data exactly like the
    5G base model already does."""
    engine = CpqEngine()
    attr = _attr(1, "wirelessCarrier_astro", "Wireless Carrier")
    assert engine._is_mandatory_input_attr(
        "wirelessCarrier_astro", attr, "user",
        gate_attrseq_confirmed_to_active_source=True,
    ) is True
    assert engine._is_mandatory_input_attr(
        "wirelessCarrier_astro", attr, "rule",
        gate_attrseq_confirmed_to_active_source=True,
    ) is False


def test_build_payload_config_data_includes_actively_sourced_wireless_carrier():
    engine = CpqEngine()
    carrier_attr = _attr(1, "wirelessCarrier_astro", "Wireless Carrier")
    filled = {"wirelessCarrier_astro": "ATT/FIRSTNET"}
    sources = {"wirelessCarrier_astro": "user"}

    payload = engine.build_payload(
        filled, sources, {}, [carrier_attr],
        scope_required_and_edited=True,
    )
    assert "wirelessCarrier_astro" in payload["configData"]


def test_config_data_includes_rule_forced_carrier_when_trigger_is_active_sourced():
    """2026-08-20 live logs (workspace 93): wirelessCarrier_astro gets
    force-set to "LTE CAPABILITY NO SERVICE" by the real rule "Force Set
    Wireless Carrier... when ATAK is enabled" (source="rule") -- not a
    blind catalog default, but the deterministic consequence of the
    customer's own ATAK selection. _rule_forced_from_active_decision_vns
    detects this generically (RecommendationRule.condition_attr_id ->
    trigger variable_name -> is ITS source active) with no attribute or
    rule name hardcoded, and build_payload wires it into config_data."""
    engine = CpqEngine()
    atak_attr = _attr(1, "aTAKEnabledPackage_astro", "ATAK Enabled Package")
    carrier_attr = _attr(2, "wirelessCarrier_astro", "Wireless Carrier")
    rule = RecommendationRule(
        rule_name='Force Set Wireless Carrier="LTE CAPABILITY NO SERVICE" when ATAK is enabled',
        condition_attr_id=1, condition_value="YES", target_attr_id=2,
        recommended_value="LTE CAPABILITY NO SERVICE",
    )
    filled = {
        "aTAKEnabledPackage_astro": "YES",
        "wirelessCarrier_astro": "LTE CAPABILITY NO SERVICE",
    }

    payload = engine.build_payload(
        filled, {"aTAKEnabledPackage_astro": "user", "wirelessCarrier_astro": "rule"},
        {}, [atak_attr, carrier_attr], rules=[rule], scope_required_and_edited=True,
    )
    assert "wirelessCarrier_astro" in payload["configData"]

    payload_inactive_trigger = engine.build_payload(
        filled, {"aTAKEnabledPackage_astro": "default", "wirelessCarrier_astro": "rule"},
        {}, [atak_attr, carrier_attr], rules=[rule], scope_required_and_edited=True,
    )
    assert "wirelessCarrier_astro" not in payload_inactive_trigger["configData"]


def test_rule_forced_active_vns_abstains_on_script_and_multi_input_rules():
    """Script-backed and multi-input (conditions=) rules have no single
    extractable trigger attr -- must abstain (empty result), never guess
    which leg to trust."""
    engine = CpqEngine()
    attrs = [
        _attr(1, "aTAKEnabledPackage_astro", "ATAK Enabled Package"),
        _attr(2, "wirelessCarrier_astro", "Wireless Carrier"),
    ]
    script_rule = RecommendationRule(
        rule_name="script rule", condition_attr_id=1, condition_value="YES",
        target_attr_id=2, recommended_value="X", script="returnVal='X'",
    )
    multi_input_rule = RecommendationRule(
        rule_name="multi input rule", condition_attr_id=1, condition_value="YES",
        target_attr_id=2, recommended_value="X",
        conditions=[(1, "YES", "4")],
    )
    sources = {"aTAKEnabledPackage_astro": "user"}
    assert engine._rule_forced_from_active_decision_vns(
        [script_rule], attrs, sources, engine._CONFIG_DATA_ACTIVE_SOURCES,
    ) == frozenset()
    assert engine._rule_forced_from_active_decision_vns(
        [multi_input_rule], attrs, sources, engine._CONFIG_DATA_ACTIVE_SOURCES,
    ) == frozenset()


def test_data_table_forced_vns_includes_any_real_legal_value_not_just_singleton():
    """2026-08-20 live data (workspace 93): wirelessCarrier_astro has TWO
    real legal values (ATT/FIRSTNET, VERIZON) for base model
    H55TGT9PW8AN + Country=US -- a real catalog choice among legitimate
    carriers, not a made-up value. `_data_table_forced_vns` must include
    it once `resolve_whitelist_values` proves the filled value is among
    the real legal options, regardless of how many alternatives exist."""
    from unittest.mock import patch

    engine = CpqEngine()
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
        "wirelessCarrier_astro": "ATT/FIRSTNET",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ):
        result = engine._data_table_forced_vns(filled, 93, "")
    assert result == frozenset({"wirelessCarrier_astro"})


def test_data_table_forced_vns_excludes_value_not_among_real_legal_options():
    """A filled value that ISN'T among the real Whitelist-confirmed legal
    options for this context must never be treated as data-table-forced
    -- this only vouches for real, catalog-proven answers."""
    from unittest.mock import patch

    engine = CpqEngine()
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
        "wirelessCarrier_astro": "SOME MADE UP VALUE",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ):
        result = engine._data_table_forced_vns(filled, 93, "")
    assert result == frozenset()


def test_build_payload_config_data_includes_data_table_forced_carrier():
    """End-to-end: build_payload(scope_required_and_edited=True) includes
    a rule-sourced carrier value once the Data Table proves it's a real
    legal option, even though it's not exactly the only one."""
    from unittest.mock import patch

    engine = CpqEngine()
    carrier_attr = _attr(1, "wirelessCarrier_astro", "Wireless Carrier")
    base_model_attr = _attr(2, "modelSelectionbaseModel_astro", "Base Model")
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "wirelessCarrier_astro": "ATT/FIRSTNET",
    }
    sources = {
        "modelSelectionbaseModel_astro": "rule",
        "wirelessCarrier_astro": "rule",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ), patch(
        "aryx.cpq.engine.dt_resolve_region_allow_value", return_value=None,
    ):
        payload = engine.build_payload(
            filled, sources, {}, [carrier_attr, base_model_attr],
            scope_required_and_edited=True, workspace_id=93,
        )
    assert "wirelessCarrier_astro" in payload["configData"]


def test_data_table_forced_vns_checks_filled_multi_for_multiselect_members():
    """2026-08-20 live incident: carrierSelectionMultiSelect_astro (the
    5G-capable sibling of wirelessCarrier_astro) is select_type=="multi"
    -- its real answer lives in `filled_multi`, never in `filled`. The
    original implementation only ever checked `filled.get(vn)`, so this
    member could never be widened to "active" for config_data even
    though the exact same Data Table narrowing already proven for its
    single-select sibling applies to it too. Every value selected must
    be a real legal option (not just one) for the multi-select case."""
    from unittest.mock import patch

    engine = CpqEngine()
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8BN",
        "productSelectionProduct_all": "APX NEXT ENHANCED",
    }
    filled_multi = {"carrierSelectionMultiSelect_astro": ["ATT/FIRSTNET"]}
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ):
        result = engine._data_table_forced_vns(
            filled, 93, "", filled_multi=filled_multi,
        )
    assert result == frozenset({"carrierSelectionMultiSelect_astro"})


def test_data_table_forced_vns_multiselect_requires_every_selected_value_legal():
    """A multi-select selection with even one value NOT among the real
    legal options must never be treated as data-table-forced -- unlike
    the single-select "any real legal option" check, every selected
    value must be individually catalog-proven."""
    from unittest.mock import patch

    engine = CpqEngine()
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8BN",
        "productSelectionProduct_all": "APX NEXT ENHANCED",
    }
    filled_multi = {
        "carrierSelectionMultiSelect_astro": ["ATT/FIRSTNET", "SOME MADE UP VALUE"],
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ):
        result = engine._data_table_forced_vns(
            filled, 93, "", filled_multi=filled_multi,
        )
    assert result == frozenset()


def test_build_payload_config_data_includes_data_table_forced_multiselect_carrier():
    """End-to-end: build_payload includes a multi-select carrier value
    once the Data Table proves every selected option is a real legal
    value -- the 5G analogue of test_build_payload_config_data_includes_
    data_table_forced_carrier (which covers the 4G single-select case)."""
    from unittest.mock import patch

    engine = CpqEngine()
    carrier_attr = _attr(
        1, "carrierSelectionMultiSelect_astro", "Carrier Selection", select_type="multi",
    )
    base_model_attr = _attr(2, "modelSelectionbaseModel_astro", "Base Model")
    filled = {"modelSelectionbaseModel_astro": "H55TGT9PW8BN"}
    filled_multi = {"carrierSelectionMultiSelect_astro": ["ATT/FIRSTNET"]}
    sources = {
        "modelSelectionbaseModel_astro": "rule",
        "carrierSelectionMultiSelect_astro": "rule",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        return_value=["ATT/FIRSTNET", "VERIZON"],
    ), patch(
        "aryx.cpq.engine.dt_resolve_region_allow_value", return_value=None,
    ):
        payload = engine.build_payload(
            filled, sources, filled_multi, [carrier_attr, base_model_attr],
            scope_required_and_edited=True, workspace_id=93,
        )
    assert "carrierSelectionMultiSelect_astro" in payload["configData"]


def test_beautify_rows_keeps_attrseq_confirmed_attr_mandatory_regardless_of_source():
    """Regression guard: this gate must never reach beautify_rows/
    beautify_text -- PR #220's own test coverage (test_cpq_beautify_
    table.py) depends on unconditional inclusion staying intact."""
    engine = CpqEngine()
    attr = _attr(1, "baselineReleaseSW_astro", "Software Release")
    display_filled = {"baselineReleaseSW_astro": "Baseline Release"}
    filled_source = {"baselineReleaseSW_astro": "system"}

    rows = engine.beautify_rows("Product", display_filled, [attr], filled_source)
    assert rows[-1]["section"] == engine._BEAUTIFY_MANDATORY_SECTION
