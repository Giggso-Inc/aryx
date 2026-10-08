"""Quote for APX N30 / N50: after the country nothing else is asked (ws 281, full aSTRO25 XML + data tables, 2026-10-08).

Before: rules authored under other products' catalog nodes filled the base model (a code of another family, then the
placeholder '*'), ~900 attributes of other families were filled, and 'LORA Region', 'regionalSrvMgrName', ... were asked.
Four flag-gated pieces fix it without a model name in the code:

* model resolution from the BmCatalog tree when Basemodeltoconfig names no model (rule scoping then drops the rules of
  other products),
* attributes the model's sequence rows do not list are not applicable (the exact decision anchors, system variables and
  the customer's answers stay),
* the completeness check and the loop's returned list use the same scoping,
* an optional multi-select nothing defaults or recommends stays empty instead of taking its first option.

Every piece is a no-op with its flag off."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.config import get_settings
from aryx.cpq import model_resolution as mr
from aryx.cpq import model_resolution_catalog as mrc
from aryx.cpq.auto_fill_stages import multi_fallback_unconstrained as mfu
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.data_table_bridge import attr_governance as ag
from aryx.cpq.state import ConfigAttr, MenuOption

BASE, PRODUCT = "modelSelectionbaseModel_astro", "productSelectionProduct_all"


@pytest.fixture
def flags():
    s = get_settings()
    names = ("cpq_model_resolution_tree_fallback_enabled", "cpq_model_scoped_questions_enabled")
    previous = {n: getattr(s, n) for n in names}
    yield s
    for n, v in previous.items():
        setattr(s, n, v)


# --- model resolution from the catalog tree ---------------------------------------------------------------------------
NODES = {"100": ("aSTRO25", "-1"), "200": ("aSTRODevices", "100"), "300": ("aPXN30", "200"), "301": ("aPXN50", "200"),
         "302": ("aPXN300", "200")}


def _catalog(models=None):
    return SimpleNamespace(
        models=models or {}, nodes_by_id=NODES, node_id_by_name={}, upgrade_models=frozenset(),
        upgrade_node_ids=frozenset(), rule_nodes_by_name={})


def _resolve(hint, models=None):
    with patch.object(mr, "load_catalog", return_value=_catalog(models)):
        return mr.resolve_model(hint, 1, "p")


def test_the_catalog_tree_names_the_model_when_the_table_names_none(flags):
    flags.cpq_model_resolution_tree_fallback_enabled = True
    res = _resolve("I want to quote for APX N30")
    assert res.resolved and res.chosen.node_name == "aPXN30" and res.chosen.node_id == "300"
    assert res.scope_node_ids == {"300", "200", "100"}              # its own node and the ancestors: family rules stay


def test_the_tree_fallback_is_off_by_default(flags):
    flags.cpq_model_resolution_tree_fallback_enabled = False
    assert not _resolve("I want to quote for APX N30").resolved


def test_a_folder_node_is_not_a_model(flags):
    flags.cpq_model_resolution_tree_fallback_enabled = True
    assert not _resolve("quote the aSTRODevices").resolved           # a non-leaf node would scope every model below it out


def test_a_longer_model_number_is_not_matched_by_a_shorter_name(flags):
    flags.cpq_model_resolution_tree_fallback_enabled = True
    assert _resolve("APX N300").chosen.node_name == "aPXN300"        # never aPXN30 inside aPXN300


def test_rows_of_the_table_win_over_the_tree(flags):
    flags.cpq_model_resolution_tree_fallback_enabled = True
    models = {"APXN30": {"display": {"APX N30"}, "varnames": {"aPXN30"}, "base_models": {"H15UCF9PW6AN"}, "node_id": "300"}}
    res = _resolve("APX N30", models)
    assert res.chosen.cpq_model == "APXN30" and res.chosen.base_models == {"H15UCF9PW6AN"}


class _TreeOnlyRdb:
    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        if ontology_type.endswith("BmCatalog"):
            return [(i, {"id": nid, "name": name, "parent_id": parent}) for i, (nid, (name, parent)) in enumerate(NODES.items())]
        return []


@pytest.mark.parametrize("flag, kept", [(True, True), (False, False)])
def test_a_catalog_with_a_tree_but_no_table_is_kept_only_with_the_flag(flags, flag, kept):
    flags.cpq_model_resolution_tree_fallback_enabled = flag
    mrc.invalidate()
    try:
        mrc.load_catalog(9, "p", _TreeOnlyRdb())
        assert (mrc.cached(9, "p") is not None) is kept
    finally:
        mrc.invalidate()


# --- attributes the model's sequence rows do not list ----------------------------------------------------------------
def _attr(vn, options=0, multi=False, required=False):
    return ConfigAttr(entity_id=abs(hash(vn)) % 1_000_000, variable_name=vn, display_label=vn, required=required,
                      default_value="", select_type="multi" if multi else "single",
                      options=[MenuOption(item_value=f"o{i}", display_name=f"o{i}", order=i) for i in range(options)])


LISTED = {"batteryType_astro", "ultimateDestinationCountry"}
ATTRS = ["batteryType_astro", "ultimateDestinationCountry", "cloudRegion_astro", "regionalSrvMgrName_astro", "plainOther_astro",
         BASE, PRODUCT, "CRM_BILL_COUNTRY", "_bm_model_variable_name", "typedByCustomer_astro", "modelSelectionBaseModelMsl_astro"]


def _suppress(sources=None):
    filled = {BASE: "H15UCF9PW6AN", PRODUCT: "APX N30", "typedByCustomer_astro": "x"}
    with patch.object(ag, "resolve_base_model_vn", return_value=BASE), \
            patch.object(ag, "_cpq_model_candidates", return_value=["APXN30"]), \
            patch.object(ag, "dt_governed_attr_names_for_base_model", return_value=set(LISTED)), \
            patch.object(ag, "dt_attr_ever_governed_for_cpq_model", return_value=False):
        return ag._suppress_ungoverned_attrs([_attr(v) for v in ATTRS], filled, 1, "p", {},
                                             sources or {"typedByCustomer_astro": "user"})


def test_with_the_flag_an_unlisted_attribute_is_not_applicable_whatever_its_name_contains(flags):
    flags.cpq_model_scoped_questions_enabled = True
    visible, suppressed = _suppress()
    assert suppressed == {"cloudRegion_astro", "regionalSrvMgrName_astro", "plainOther_astro", "modelSelectionBaseModelMsl_astro"}
    kept = {a.variable_name for a in visible}
    assert LISTED <= kept                                                    # the model's own rows
    assert {BASE, PRODUCT} <= kept                                           # exact decision anchors
    assert {"CRM_BILL_COUNTRY", "_bm_model_variable_name"} <= kept           # system variables
    assert "typedByCustomer_astro" in kept                                   # the customer's answer


def test_a_value_the_engine_only_guessed_does_not_protect_an_unlisted_attribute(flags):
    flags.cpq_model_scoped_questions_enabled = True
    _visible, suppressed = _suppress({"typedByCustomer_astro": "blind_pick_rule_governed"})
    assert "typedByCustomer_astro" in suppressed


def test_without_the_flag_nothing_new_is_suppressed(flags):
    flags.cpq_model_scoped_questions_enabled = False
    visible, suppressed = _suppress()
    assert suppressed == set() and len(visible) == len(ATTRS)                # fragment anchors and 'silence' stay visible


# --- the completeness check and the loop's returned list --------------------------------------------------------------
class _Engine:
    def __init__(self):
        self.calls = 0

    def _suppress_ungoverned_attrs(self, attrs, filled, ws, prefix, cache, sources):
        self.calls += 1
        return [a for a in attrs if a.variable_name != "isFLASHcodeAvailable_astro"], {"isFLASHcodeAvailable_astro"}


def _session():
    return SimpleNamespace(filled={}, filled_source={})


def test_the_required_check_ignores_attributes_the_model_does_not_list(flags):
    from aryx.api.ask_stale_constraint import ask_stale_constraint_reask as reask

    attrs = [_attr("isFLASHcodeAvailable_astro", required=True), _attr("batteryType_astro", required=True)]
    engine = _Engine()
    flags.cpq_model_scoped_questions_enabled = False
    assert reask._applicable_attrs(engine, attrs, _session(), 1, "p") is attrs and engine.calls == 0
    flags.cpq_model_scoped_questions_enabled = True
    assert [a.variable_name for a in reask._applicable_attrs(engine, attrs, _session(), 1, "p")] == ["batteryType_astro"]
    assert reask._applicable_attrs(engine, attrs, _session(), None, "p") is attrs        # no workspace: unchanged


def test_the_loops_returned_list_is_scoped_only_with_the_flag(flags):
    from aryx.cpq.rules_loop import rules_loop

    state = SimpleNamespace(attrs=[_attr("isFLASHcodeAvailable_astro"), _attr("batteryType_astro")], filled={}, sources={}, dt_cache={})
    scope = SimpleNamespace(workspace_id=1, catalog_prefix="p")
    flags.cpq_model_scoped_questions_enabled = False
    assert rules_loop._scoped_attrs(_Engine(), state, scope) is state.attrs
    flags.cpq_model_scoped_questions_enabled = True
    assert [a.variable_name for a in rules_loop._scoped_attrs(_Engine(), state, scope)] == ["batteryType_astro"]


# --- an optional multi-select nothing defaults stays empty -------------------------------------------------------------
def _blind_pick(attr, flag, flags):
    flags.cpq_model_scoped_questions_enabled = flag
    ctx = SimpleNamespace(filled={}, filled_multi={}, display_filled={}, sources={}, dt_cache={})
    engine = SimpleNamespace(_resolve_narrowed_legal_values=lambda *a, **k: None)
    scope = SimpleNamespace(workspace_id=1, catalog_prefix="p")
    state = AttrResolution(vn=attr.variable_name, vn_flat=attr.variable_name.lower())
    with patch.object(mfu.fill_log, "log_write"), \
            patch.object(mfu, "resolve_select_all_narrowed_legal_multi_membership", return_value=False):
        mfu.blind_pick_narrowed(engine, attr, ctx, scope, state, list(attr.options))
    return ctx


def test_an_optional_multi_select_stays_empty_with_the_flag(flags):
    attr = _attr("systemEnhancementFeatureType_astro", options=3, multi=True)
    assert _blind_pick(attr, True, flags).filled_multi == {attr.variable_name: []}


def test_without_the_flag_it_still_takes_its_first_option(flags):
    attr = _attr("systemEnhancementFeatureType_astro", options=3, multi=True)
    assert _blind_pick(attr, False, flags).filled_multi == {attr.variable_name: ["o0"]}


def test_a_required_multi_select_is_still_filled(flags):
    attr = _attr("someRequiredMulti_astro", options=3, multi=True, required=True)
    assert _blind_pick(attr, True, flags).filled_multi == {attr.variable_name: ["o0"]}
