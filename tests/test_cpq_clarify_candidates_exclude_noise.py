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

from aryx.api.ask_api import _ground_clarify_candidates
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
