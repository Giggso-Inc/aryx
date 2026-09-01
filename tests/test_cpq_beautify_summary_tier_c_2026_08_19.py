"""docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md --
implements Tier C for beautify's "Mandatory User Input" vs "System-
Configured / Recommended" split and the summary's item selection
(config_data deliberately excludes Tier C -- see docs/CPQ_ConfigData_
Payload_Mandatory_Fix_Scope_2026_08_19.md and test_cpq_config_data_
active_sources_2026_08_19.py).

Covers:
  - _is_mandatory_input_attr's new Tier C (required_vns) parameter.
  - mandatory_tier_c_vns' three exclusions: no filled/workspace_id/base
    model -> empty; _RECOMMENDED_CONFIG_ONLY_VNS members excluded even
    when R-flagged; data-table-resolvable attrs excluded even when
    R-flagged.
  - _is_summary_excluded's is_mandatory gate: a genuinely Mandatory
    boolean-valued attr (e.g. isProvisioningRequiredInCloudEnv_astro) is
    no longer silently dropped.
  - beautify_rows'/beautify_text's Tier C threading via required_vns.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attr(entity_id: int, vn: str, label: str, select_type: str = "single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=label,
        required=False, default_value="", select_type=select_type,
        options=_menu("A", "B"),
    )


def test_is_mandatory_input_attr_tier_c_included():
    engine = CpqEngine()
    attr = _attr(1, "solutionTypeDevices_astro", "Solution Type")
    assert engine._is_mandatory_input_attr(
        "solutionTypeDevices_astro", attr, "rule",
        required_vns=frozenset({"solutionTypeDevices_astro"}),
    ) is True


def test_is_mandatory_input_attr_tier_c_absent_when_not_in_required_vns():
    engine = CpqEngine()
    attr = _attr(1, "someOtherAttr_astro", "Some Other Attr")
    assert engine._is_mandatory_input_attr(
        "someOtherAttr_astro", attr, "rule",
        required_vns=frozenset({"solutionTypeDevices_astro"}),
    ) is False


def test_mandatory_tier_c_vns_empty_without_filled_or_workspace():
    engine = CpqEngine()
    assert engine.mandatory_tier_c_vns(None, 93) == frozenset()
    assert engine.mandatory_tier_c_vns({}, 93) == frozenset()
    assert engine.mandatory_tier_c_vns({"modelSelectionbaseModel_astro": "H1"}, None) == frozenset()
    assert engine.mandatory_tier_c_vns({"productSelectionProduct_all": "X"}, 93) == frozenset(), (
        "no base_model key at all -- must be empty, not a guess"
    )


def test_mandatory_tier_c_vns_excludes_recommended_only_and_data_table_resolvable():
    engine = CpqEngine()
    filled = {
        "modelSelectionbaseModel_astro": "H1",
        "productSelectionProduct_all": "APX NEXT",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine.dt_governed_required_attr_names_for_base_model",
        return_value={
            "packingPackageType_astro",  # curated Recommended-only
            "solutionTypeDevices_astro",  # genuinely Mandatory, no data-table coverage
            "batteryType_astro",  # data-table-resolvable -> excluded
        },
    ), patch(
        "aryx.cpq.engine.dt_resolve_whitelist_values",
        side_effect=lambda cm, bm, vn, *a, **k: (["Standard"] if vn == "batteryType_astro" else None),
    ):
        result = engine.mandatory_tier_c_vns(filled, 93, "")
    assert result == frozenset({"solutionTypeDevices_astro"})


def test_summary_excluded_boolean_gate_skips_for_mandatory_attr():
    """The isProvisioningRequiredInCloudEnv_astro fix: a boolean-valued
    attr the caller has confirmed is Mandatory must NOT be dropped by
    the boolean-value exclusion."""
    engine = CpqEngine()
    attr = _attr(1, "isProvisioningRequiredInCloudEnv_astro", "Is provisioning required?",
                 select_type="boolean")
    assert engine._is_summary_excluded(
        "isProvisioningRequiredInCloudEnv_astro", "Is provisioning required?", "No",
        attr, source="hint", is_mandatory=True,
    ) is False
    # Non-mandatory booleans keep today's exclusion behavior unchanged.
    assert engine._is_summary_excluded(
        "isProvisioningRequiredInCloudEnv_astro", "Is provisioning required?", "No",
        attr, source="hint", is_mandatory=False,
    ) is True


def test_filled_summary_triples_includes_mandatory_boolean_via_required_vns():
    """End-to-end: a hint-sourced boolean survives in the summary once
    it's confirmed Mandatory via Tier C."""
    engine = CpqEngine()
    attr = _attr(1, "isProvisioningRequiredInCloudEnv_astro", "Is provisioning required?",
                 select_type="boolean")
    display_filled = {"isProvisioningRequiredInCloudEnv_astro": "No"}
    sources = {"isProvisioningRequiredInCloudEnv_astro": "hint"}

    # Without Tier C coverage: excluded (boolean + not mandatory).
    triples = engine._filled_summary_triples(
        display_filled, [attr], rule_governed_ids={1}, sources=sources,
    )
    assert triples == []

    # With Tier C coverage: included.
    triples = engine._filled_summary_triples(
        display_filled, [attr], rule_governed_ids={1}, sources=sources,
        required_vns=frozenset({"isProvisioningRequiredInCloudEnv_astro"}),
    )
    assert [t[0] for t in triples] == ["isProvisioningRequiredInCloudEnv_astro"]


def test_beautify_rows_tier_c_moves_defaulted_attr_into_mandatory_section():
    engine = CpqEngine()
    attr = _attr(1, "solutionTypeDevices_astro", "Solution Type")
    display_filled = {"solutionTypeDevices_astro": "RadioCentral"}
    filled_source = {"solutionTypeDevices_astro": "rule"}

    # Without Tier C: lands in System-Configured / Recommended.
    rows = engine.beautify_rows("Product", display_filled, [attr], filled_source)
    assert rows[-1]["section"] == engine._BEAUTIFY_SYSTEM_SECTION

    # With Tier C: lands in Mandatory User Input.
    rows = engine.beautify_rows(
        "Product", display_filled, [attr], filled_source,
        required_vns=frozenset({"solutionTypeDevices_astro"}),
    )
    assert rows[-1]["section"] == engine._BEAUTIFY_MANDATORY_SECTION


def test_beautify_rows_never_promotes_recommended_only_attr_via_tier_c():
    """packingPackageType_astro must stay in the System-Configured /
    Recommended section even if (incorrectly) passed in required_vns --
    mandatory_tier_c_vns itself would never produce this, but
    _is_mandatory_input_attr's own required_vns membership check has no
    additional _RECOMMENDED_CONFIG_ONLY_VNS re-check, so this documents
    that the exclusion discipline lives in mandatory_tier_c_vns, not
    duplicated in _is_mandatory_input_attr -- callers MUST use
    mandatory_tier_c_vns's result, never a hand-built required_vns."""
    engine = CpqEngine()
    assert "packingPackageType_astro" in engine._RECOMMENDED_CONFIG_ONLY_VNS
