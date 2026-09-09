"""docs/config_consistency_issues_2026-07-30.md — live-confirmed bug:
"change the product to APX NEXT XE All Band" produced a bogus 8-attribute
disambiguation (Accessories Help Text, ConfigProcessStep, MSI Releases,
modelname, a hidden internal rule attr, ...) instead of resolving cleanly
to productSelectionProduct_all.

Two independent causes, both fixed:
1. The word "All" (from the product's own name) survived tokenization and
   generically word-overlapped the extremely common BigMachines
   variable-name suffix "_all" (msiReleases_All, modelname_all,
   accessoriesHelpText_all, ...) — fixed by adding "all" to
   _CLARIFY_STOPWORDS.
2. _ground_clarify_candidates never filtered out noise/HTML/hide_in_trans/
   set_type=="2"/hidden attrs the way build_payload()/_is_summary_excluded()
   already do — fixed by adding the same checks here.
"""
from __future__ import annotations

from aryx.api.ask_pending_clarify_grounding import _ground_clarify_candidates
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _product() -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="productSelectionProduct_all",
        display_label="Product", required=True, default_value="",
        select_type="single",
        options=_menu("APX NEXT XE ALL BAND", "APX NEXT SINGLE BAND"),
    )


def _msi_releases() -> ConfigAttr:
    return ConfigAttr(
        entity_id=2, variable_name="msiReleases_All", display_label="MSI Releases",
        required=False, default_value="", select_type="single", options=_menu("1.2"),
    )


def _modelname() -> ConfigAttr:
    return ConfigAttr(
        entity_id=3, variable_name="modelname_all", display_label="modelname",
        required=False, default_value="", select_type="single", options=[],
    )


def _accessories_help_text() -> ConfigAttr:
    """Free-text HTML noise field — no real options, matches _is_noise_var."""
    return ConfigAttr(
        entity_id=4, variable_name="accessoriesHelpText_all",
        display_label="Accessories Help Text", required=False, default_value="",
        select_type="single", options=[],
    )


def _config_process_step() -> ConfigAttr:
    return ConfigAttr(
        entity_id=5, variable_name="configProcessStepHTML_all",
        display_label="ConfigProcessStep", required=False, default_value="",
        select_type="single", options=[],
    )


def _hidden_internal_rule_attr() -> ConfigAttr:
    return ConfigAttr(
        entity_id=6, variable_name="hiddenGetrecPartsMasterStringFamilyRule_all",
        display_label="getrecPartsMasterStringFamilyRule_all", required=False,
        default_value="", select_type="single", options=[], hidden=True,
    )


def _session_with_noise_filled() -> CpqSession:
    s = CpqSession(product_name="aSTRO25_bom", status="configuring")
    s.filled = {
        "msiReleases_All": "1.2",
        "modelname_all": "aPXNext",
        "accessoriesHelpText_all": "<div>some html</div>",
        "configProcessStepHTML_all": "<div>step</div>",
        "hiddenGetrecPartsMasterStringFamilyRule_all": "somevalue",
    }
    s.display_filled = dict(s.filled)
    s.filled_source = {k: "auto" for k in s.filled}
    s.filled_multi = {}
    return s


def test_all_token_never_matches_the_common_variable_name_suffix():
    attrs = [_product(), _msi_releases(), _modelname()]
    session = _session_with_noise_filled()

    cands = _ground_clarify_candidates("change the product to APX NEXT XE All Band", attrs, session)
    vns = [a.variable_name for a in cands]

    assert "msiReleases_All" not in vns
    assert "modelname_all" not in vns


def test_noise_html_and_hidden_attrs_never_offered_as_candidates():
    attrs = [
        _product(), _accessories_help_text(), _config_process_step(),
        _hidden_internal_rule_attr(),
    ]
    session = _session_with_noise_filled()

    cands = _ground_clarify_candidates("change the product to APX NEXT XE All Band", attrs, session)
    vns = [a.variable_name for a in cands]

    assert "accessoriesHelpText_all" not in vns
    assert "configProcessStepHTML_all" not in vns
    assert "hiddenGetrecPartsMasterStringFamilyRule_all" not in vns


def test_product_still_resolves_cleanly():
    attrs = [
        _product(), _msi_releases(), _modelname(),
        _accessories_help_text(), _config_process_step(), _hidden_internal_rule_attr(),
    ]
    session = _session_with_noise_filled()
    session.filled["productSelectionProduct_all"] = "APX NEXT SINGLE BAND"
    session.display_filled["productSelectionProduct_all"] = "APX NEXT Single Band"

    cands = _ground_clarify_candidates("change the product to APX NEXT XE All Band", attrs, session)
    vns = [a.variable_name for a in cands]

    assert vns == ["productSelectionProduct_all"]


# ── Generic catalog-wide-suffix detection (2026-08-21) ──────────────────
# The "_all" fix above is ONE hardcoded stopword for ONE catalog family's
# suffix. Live-confirmed the identical bug shape recurs on a DIFFERENT
# catalog family's own near-universal suffix ("_viSoln", video-solutions/
# SVX RSM) -- a customer echoing back a suggested variable_name (e.g.
# "mountingTypeArray_viSoln") floods the candidate list via that one
# shared, meaningless fragment. These tests prove the fix is derived from
# `attrs` itself (any underscore-fragment on most of the catalog's own
# attributes), not a second hardcoded "visoln" entry -- so the NEXT
# catalog's own suffix is covered automatically too.

def _mount_type_array() -> ConfigAttr:
    return ConfigAttr(
        entity_id=10, variable_name="mountingTypeArray_viSoln",
        display_label="Mounting Type", required=False, default_value="",
        select_type="multi", options=_menu("Shirt Magnetic Mount", "Jacket Magnetic Mount"),
    )


def _smartdock_config() -> ConfigAttr:
    return ConfigAttr(
        entity_id=11, variable_name="smartDockConfigServiceNoVideoStorage_viSoln",
        display_label="SmartDock Configuration Service (No Video Storage)",
        required=False, default_value="", select_type="single", options=_menu("Yes", "No"),
    )


def _spare_battery() -> ConfigAttr:
    return ConfigAttr(
        entity_id=12, variable_name="includeASpareBatteryWithEachBodyCamera_viSoln",
        display_label="Include a Spare Battery with each body camera",
        required=False, default_value="", select_type="single", options=_menu("Yes", "No"),
    )


def _device_mgmt_duration() -> ConfigAttr:
    return ConfigAttr(
        entity_id=13, variable_name="deviceManagementDuration_viSoln",
        display_label="Device Management Duration", required=False, default_value="",
        select_type="single", options=_menu("1 Year", "5 Year"),
    )


def test_catalog_wide_suffix_never_floods_candidates_when_customer_echoes_a_variable_name():
    """A customer echoing back the exact variable_name the system just
    offered ("mountingTypeArray_viSoln") must not word-overlap every
    other "_viSoln" attribute purely on that shared, meaningless suffix
    fragment -- confirmed against a completely different catalog family
    than the "_all" precedent, with no "viSoln" stopword added anywhere."""
    attrs = [
        _mount_type_array(), _smartdock_config(), _spare_battery(),
        _device_mgmt_duration(),
    ]
    session = CpqSession(product_name="videoSolutions_BOM", status="configuring")
    session.filled = {}
    session.display_filled = {}
    session.filled_source = {}
    session.filled_multi = {}

    cands = _ground_clarify_candidates("mountingTypeArray_viSoln", attrs, session)
    vns = [a.variable_name for a in cands]

    assert "smartDockConfigServiceNoVideoStorage_viSoln" not in vns
    assert "includeASpareBatteryWithEachBodyCamera_viSoln" not in vns
    assert "deviceManagementDuration_viSoln" not in vns


def test_catalog_wide_suffix_detection_does_not_suppress_a_genuinely_shared_real_word():
    """The >40% threshold must only catch a near-universal naming
    convention, never a merely-common real word two attrs happen to
    share -- both "Mounting Type" attrs here legitimately share the word
    "mount" and must still be found for a message that actually says it,
    same catalog, no "_viSoln"-only echo involved this time."""
    mount_type = ConfigAttr(
        entity_id=14, variable_name="mountType_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="single",
        options=_menu("Swivel Clip", "Swivel Clip and Adjustable Lanyard"),
    )
    attrs = [mount_type, _mount_type_array(), _smartdock_config(), _spare_battery()]
    session = CpqSession(product_name="videoSolutions_BOM", status="configuring")
    session.filled = {}
    session.display_filled = {}
    session.filled_source = {}
    session.filled_multi = {}

    cands = _ground_clarify_candidates("I want to change the mounting type", attrs, session)
    vns = {a.variable_name for a in cands}

    assert "mountType_viSoln" in vns
    assert "mountingTypeArray_viSoln" in vns
    assert "smartDockConfigServiceNoVideoStorage_viSoln" not in vns
