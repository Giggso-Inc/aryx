"""docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_2026_08_19.md -- live-
confirmed gap: build_payload(scope_required_and_edited=True)'s config_data
was missing ultimateDestinationCountry_astro, wirelessCarrier_astro,
modelSelectionFrequencyBandMsl_astro, and isProvisioningRequiredInCloudEnv_
astro -- four genuine, pure-user-input Mandatory fields with no catalog
default -- because none of them are Tier A/B structural anchors, and their
real filled_source is "hint" (extracted directly from a compound opening
sentence) or "cascade"/"cascade-dependent" (re-derived as a side effect of
a Hardware Version/Product change), never the literal string "user" the
old bare fallback required.

Fix: _is_mandatory_input_attr gained an active_sources param (None by
default, preserving beautify's/the summary's literal source=="user" check
byte-for-byte). build_payload's two config_data call sites now pass
_CONFIG_DATA_ACTIVE_SOURCES = {"user", "hint", "cascade", "cascade-
dependent", "country_derived", "product_anchor"} -- _SUMMARY_ACTIVE_
SOURCES minus "rule", since a fired-rule value (e.g. Package Type via the
ICE-Kit RecommendationRule) is exactly the "cosmetic auto-fill"/"blind-
picked default" scope_required_and_edited's own docstring says config_data
must keep excluding.

Deliberately NOT the same as Tier C (AttrSequence-Required, designed for
beautify's Mandatory-section split, documented separately in docs/CPQ_
Beautify_Mandatory_Section_Miscategorization_2026_08_19.md) -- Tier C
would wrongly promote genuinely never-edited catalog defaults (Software
Release, Solution Type, Duration, Battery Type, ...) into config_data,
which is exactly the class of value this payload must keep excluding.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attr(entity_id: int, vn: str, select_type: str = "single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn,
        required=False, default_value="", select_type=select_type,
        options=_menu("A", "B"),
    )


def test_beautify_and_summary_callers_keep_literal_user_check_unchanged():
    """No active_sources passed (beautify's/the summary's own call shape)
    -- "hint"/"cascade" sourced non-anchor attrs must NOT qualify, exactly
    today's behavior, byte-for-byte."""
    engine = CpqEngine()
    attr = _attr(1, "someAttr_astro")
    assert engine._is_mandatory_input_attr("someAttr_astro", attr, "hint") is False
    assert engine._is_mandatory_input_attr("someAttr_astro", attr, "cascade") is False
    assert engine._is_mandatory_input_attr("someAttr_astro", attr, "user") is True


def test_config_data_active_sources_includes_hint_and_cascade():
    """With _CONFIG_DATA_ACTIVE_SOURCES passed, hint/cascade/cascade-
    dependent/country_derived/product_anchor all qualify -- the exact fix
    for Country/Carrier/Frequency Band Msl/Provisioning."""
    engine = CpqEngine()
    attr = _attr(1, "ultimateDestinationCountry_astro")
    for src in ("hint", "cascade", "cascade-dependent", "country_derived", "product_anchor", "user"):
        assert engine._is_mandatory_input_attr(
            "ultimateDestinationCountry_astro", attr, src,
            active_sources=engine._CONFIG_DATA_ACTIVE_SOURCES,
        ) is True, f"source={src!r} must qualify for config_data"


def test_config_data_active_sources_excludes_rule():
    """"rule" is deliberately NOT in _CONFIG_DATA_ACTIVE_SOURCES -- a
    fired-rule value (e.g. Package Type) must stay excluded from
    config_data even though _SUMMARY_ACTIVE_SOURCES treats "rule" as
    active for the summary's own, different purpose."""
    engine = CpqEngine()
    attr = _attr(1, "packingPackageType_astro")
    assert engine._is_mandatory_input_attr(
        "packingPackageType_astro", attr, "rule",
        active_sources=engine._CONFIG_DATA_ACTIVE_SOURCES,
    ) is False
    assert engine._is_mandatory_input_attr(
        "packingPackageType_astro", attr, "default",
        active_sources=engine._CONFIG_DATA_ACTIVE_SOURCES,
    ) is False


def test_build_payload_config_data_includes_hint_sourced_country():
    """End-to-end: build_payload(scope_required_and_edited=True) now
    includes a hint-sourced Country in config_data."""
    engine = CpqEngine()
    country_attr = _attr(1, "ultimateDestinationCountry_astro")
    filled = {"ultimateDestinationCountry_astro": "A"}
    sources = {"ultimateDestinationCountry_astro": "hint"}

    payload = engine.build_payload(
        filled, sources, {}, [country_attr],
        scope_required_and_edited=True,
    )
    assert "ultimateDestinationCountry_astro" in payload["configData"]


def test_build_payload_config_data_still_excludes_rule_sourced_package_type():
    """End-to-end: a fired-rule value (Package Type analogue) stays
    excluded from config_data -- Tier C is NOT applied here."""
    engine = CpqEngine()
    package_type_attr = _attr(1, "packingPackageType_astro")
    filled = {"packingPackageType_astro": "A"}
    sources = {"packingPackageType_astro": "rule"}

    payload = engine.build_payload(
        filled, sources, {}, [package_type_attr],
        scope_required_and_edited=True,
    )
    assert "packingPackageType_astro" not in payload["configData"]
