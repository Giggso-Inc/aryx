"""docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_2026_08_19.md -- the
"Known Gap" section, implemented: modelSelectionbaseModel_astro is a
menu-type attribute at the catalog level, and _is_mandatory_input_attr's
Tier A treated any "basemodel"/"selectmodel"-fragment match as an
unconditional structural anchor -- but it is missing from BOTH the real
APX NEXT UI screenshot's "Mandatory User Input" box AND a real target
config_data payload, since its value is 100% derived from Country +
Hardware Version + Product via the ingested NewCountryRegMapping
(region-rule-shaped) Data Table, never a genuine customer decision.

_data_table_resolved_anchor_vns is the config_data-only, opt-in EXCLUDE
set (the inverse of mandatory_tier_c_vns's INCLUDE set) -- passed via
_is_mandatory_input_attr's new exclude_anchor_vns param, defaulting to
None so beautify's and the summary's own Tier A behavior is completely
unaffected (they never call build_payload's scope_required_and_edited
path at all).
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attr(entity_id: int, vn: str, label: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=label,
        required=False, default_value="", select_type="single",
        options=_menu("A", "B"),
    )


def test_is_mandatory_input_attr_excludes_anchor_when_listed():
    engine = CpqEngine()
    attr = _attr(1, "modelSelectionbaseModel_astro", "Base Model")
    assert engine._is_mandatory_input_attr(
        "modelSelectionbaseModel_astro", attr, "rule",
        exclude_anchor_vns=frozenset({"modelSelectionbaseModel_astro"}),
    ) is False


def test_is_mandatory_input_attr_keeps_anchor_by_default():
    """No exclude_anchor_vns passed (beautify's/the summary's own call
    shape) -- Base Model stays an unconditional Tier A anchor, exactly
    today's behavior."""
    engine = CpqEngine()
    attr = _attr(1, "modelSelectionbaseModel_astro", "Base Model")
    assert engine._is_mandatory_input_attr(
        "modelSelectionbaseModel_astro", attr, "rule",
    ) is True


def test_is_mandatory_input_attr_product_and_hardware_version_unaffected():
    """Product's exact-match branch and Hardware Version's separate
    helper are untouched by exclude_anchor_vns -- only the basemodel/
    selectmodel fragment branches are gated."""
    engine = CpqEngine()
    product_attr = _attr(1, "productSelectionProduct_all", "Product")
    assert engine._is_mandatory_input_attr(
        "productSelectionProduct_all", product_attr, "rule",
        exclude_anchor_vns=frozenset({"productSelectionProduct_all"}),
    ) is True


def test_data_table_resolved_anchor_vns_empty_without_inputs():
    engine = CpqEngine()
    assert engine._data_table_resolved_anchor_vns(None, [], 93) == frozenset()
    assert engine._data_table_resolved_anchor_vns({}, [_attr(1, "modelSelectionbaseModel_astro", "Base Model")], 93) == frozenset()
    assert engine._data_table_resolved_anchor_vns(
        {"productSelectionProduct_all": "APX NEXT"}, [], 93,
    ) == frozenset(), "no attrs at all -- nothing to check"
    assert engine._data_table_resolved_anchor_vns(
        {"productSelectionProduct_all": "APX NEXT"},
        [_attr(1, "modelSelectionbaseModel_astro", "Base Model")], None,
    ) == frozenset(), "no workspace_id"


def test_data_table_resolved_anchor_vns_excludes_when_region_rule_resolves():
    engine = CpqEngine()
    base_model_attr = _attr(1, "modelSelectionbaseModel_astro", "Base Model")
    other_anchor_attr = _attr(2, "modelSelectionSelectModel_astro", "Select Model")
    filled = {
        "productSelectionProduct_all": "APX NEXT ENHANCED",
        "ultimateDestinationCountry": "United States",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine._COUNTRY_TO_REGION", {"united states": "NA"},
    ), patch(
        "aryx.cpq.engine.dt_resolve_region_allow_value",
        side_effect=lambda vn, cm, region, *a, **k: (
            "H55TGT9PW8BN" if vn == "modelSelectionbaseModel_astro" else None
        ),
    ):
        result = engine._data_table_resolved_anchor_vns(
            filled, [base_model_attr, other_anchor_attr], 93, "",
        )
    assert result == frozenset({"modelSelectionbaseModel_astro"})


# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T5: an ISO country CODE (not
# just "us"/"uk"/"uae") must resolve a region too -- the map is keyed by
# name, so a bare code like "CA" used to silently fail to resolve at all.

def test_data_table_resolved_anchor_vns_resolves_a_country_code_not_just_a_name():
    engine = CpqEngine()
    base_model_attr = _attr(1, "modelSelectionbaseModel_astro", "Base Model")
    filled = {
        "productSelectionProduct_all": "APX NEXT ENHANCED",
        "ultimateDestinationCountry": "CA",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine._COUNTRY_TO_REGION", {"canada": "NA"},
    ), patch(
        "aryx.cpq.engine.dt_resolve_region_allow_value",
        side_effect=lambda vn, cm, region, *a, **k: (
            "H55TGT9PW8BN" if vn == "modelSelectionbaseModel_astro" and region == "NA" else None
        ),
    ):
        result = engine._data_table_resolved_anchor_vns(
            filled, [base_model_attr], 93, "",
        )
    assert result == frozenset({"modelSelectionbaseModel_astro"}), (
        "country code 'CA' must resolve to region NA via 'canada', "
        "not silently fail because the map is keyed by name"
    )


def test_build_payload_config_data_excludes_data_table_resolved_base_model():
    """End-to-end: build_payload(scope_required_and_edited=True) drops
    Base Model from config_data when it's confirmed region-rule-resolved,
    while a genuinely user-answered attribute stays in."""
    engine = CpqEngine()
    base_model_attr = _attr(1, "modelSelectionbaseModel_astro", "Base Model")
    country_attr = _attr(2, "ultimateDestinationCountry", "Country")
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8BN",
        "ultimateDestinationCountry": "United States",
        "productSelectionProduct_all": "APX NEXT ENHANCED",
    }
    sources = {
        "modelSelectionbaseModel_astro": "rule",
        "ultimateDestinationCountry": "hint",
    }
    with patch(
        "aryx.cpq.engine._cpq_model_candidates", return_value=("APXNEXT",),
    ), patch(
        "aryx.cpq.engine._COUNTRY_TO_REGION", {"united states": "NA"},
    ), patch(
        "aryx.cpq.engine.dt_resolve_region_allow_value",
        side_effect=lambda vn, cm, region, *a, **k: (
            "H55TGT9PW8BN" if vn == "modelSelectionbaseModel_astro" else None
        ),
    ):
        payload = engine.build_payload(
            filled, sources, {}, [base_model_attr, country_attr],
            scope_required_and_edited=True, workspace_id=93, catalog_prefix="",
        )
    assert "modelSelectionbaseModel_astro" not in payload["configData"]
    assert "ultimateDestinationCountry" in payload["configData"]


def test_build_payload_without_workspace_id_keeps_legacy_behavior():
    """Callers that don't pass workspace_id (today's default) get NO
    anchor exclusion at all -- byte-for-byte unchanged from before this
    fix existed."""
    engine = CpqEngine()
    base_model_attr = _attr(1, "modelSelectionbaseModel_astro", "Base Model")
    filled = {"modelSelectionbaseModel_astro": "H55TGT9PW8BN"}
    sources = {"modelSelectionbaseModel_astro": "rule"}

    payload = engine.build_payload(
        filled, sources, {}, [base_model_attr],
        scope_required_and_edited=True,
    )
    assert "modelSelectionbaseModel_astro" in payload["configData"]
