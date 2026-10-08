"""Quote for APX N30 / N50: after the country nothing else is asked (ws 281, full aSTRO25 XML + data tables, 2026-10-08).

Before: rules authored under other products' catalog nodes filled the base model (a code of another family, then the
placeholder '*'), ~900 attributes of other families were filled, and 'LORA Region', 'regionalSrvMgrName', ... were asked.
Four flag-gated pieces fix it without a model name in the code:

* model resolution from the BmCatalog tree when Basemodeltoconfig names no model (rule scoping then drops the rules of
  other products),
* attributes the model's sequence rows do not list are not applicable (the exact decision anchors and any
  non-guessed value stay),
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


def test_two_leaves_with_the_same_specificity_are_not_guessed(flags):
    """Review N3: a name that is not unique in the tree (an option group sharing a model's name) must not scope rules out
    on a guess: the model stays unresolved and nothing is filtered."""
    flags.cpq_model_resolution_tree_fallback_enabled = True
    nodes = dict(NODES)
    nodes["400"] = ("APX N30", "250")                 # another leaf with the same normalised name under another parent
    nodes["250"] = ("optionGroups", "100")
    catalog = _catalog()
    catalog.nodes_by_id = nodes
    with patch.object(mr, "load_catalog", return_value=catalog):
        assert not mr.resolve_model("I want to quote for APX N30", 1, "p").resolved


def test_a_duplicate_name_under_an_upgrade_node_prefers_the_sellable_leaf(flags):
    """Review N5: the same name on an upgrade branch must not make the fallback do nothing: the non-upgrade leaf wins,
    as on the table path."""
    flags.cpq_model_resolution_tree_fallback_enabled = True
    nodes = dict(NODES)
    nodes["250"] = ("upgrades", "100")
    nodes["400"] = ("aPXN30", "250")                  # the same model name on an upgrade branch
    catalog = _catalog()
    catalog.nodes_by_id = nodes
    catalog.upgrade_node_ids = frozenset({"400"})
    with patch.object(mr, "load_catalog", return_value=catalog):
        res = mr.resolve_model("I want to quote for APX N30", 1, "p")
    assert res.resolved and res.chosen.node_id == "300" and not res.chosen.is_upgrade


def test_two_different_models_named_together_resolve_like_the_table_path(flags):
    """Review N5: "compare APX N30 and APX N50" names two different models of equal length; the deterministic pick of
    `rank_candidates` (alphabetical, last step) applies, with the other kept as an alternative, instead of nothing."""
    flags.cpq_model_resolution_tree_fallback_enabled = True
    res = _resolve("compare APX N30 and APX N50")
    assert res.resolved and res.chosen.node_name == "aPXN30" and [a.node_name for a in res.alternatives] == ["aPXN50"]


def test_the_most_specific_leaf_still_wins_over_a_shorter_one(flags):
    flags.cpq_model_resolution_tree_fallback_enabled = True
    nodes = dict(NODES)
    nodes["410"] = ("aPXN30Plus", "200")
    catalog = _catalog()
    catalog.nodes_by_id = nodes
    with patch.object(mr, "load_catalog", return_value=catalog):
        assert mr.resolve_model("quote the APX N30 Plus", 1, "p").chosen.node_name == "aPXN30Plus"


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
def _attr(vn, options=0, multi=False, required=False, hidden=False):
    return ConfigAttr(entity_id=abs(hash(vn)) % 1_000_000, variable_name=vn, display_label=vn, required=required,
                      default_value="", select_type="multi" if multi else "single", hidden=hidden,
                      options=[MenuOption(item_value=f"o{i}", display_name=f"o{i}", order=i) for i in range(options)])


LISTED = {"batteryType_astro", "ultimateDestinationCountry"}
ATTRS = ["batteryType_astro", "ultimateDestinationCountry", "cloudRegion_astro", "regionalSrvMgrName_astro", "plainOther_astro",
         BASE, PRODUCT, "CRM_BILL_COUNTRY", "_bm_model_variable_name", "typedByCustomer_astro", "someRuleValue_astro",
         "hiddenDefault_astro", "modelSelectionBaseModelMsl_astro"]


def _suppress(sources=None):
    filled = {BASE: "H15UCF9PW6AN", PRODUCT: "APX N30", "typedByCustomer_astro": "x", "CRM_BILL_COUNTRY": "United States",
              "_bm_model_variable_name": "aPXN30", "someRuleValue_astro": "v", "hiddenDefault_astro": "d"}
    with patch.object(ag, "resolve_base_model_vn", return_value=BASE), \
            patch.object(ag, "_cpq_model_candidates", return_value=["APXN30"]), \
            patch.object(ag, "dt_governed_attr_names_for_base_model", return_value=set(LISTED)), \
            patch.object(ag, "dt_attr_ever_governed_for_cpq_model", return_value=False):
        return ag._suppress_ungoverned_attrs([_attr(v, hidden=(v == "hiddenDefault_astro")) for v in ATTRS], filled, 1, "p", {},
                                             sources or {"typedByCustomer_astro": "user", "CRM_BILL_COUNTRY": "hint",
                                                         "_bm_model_variable_name": "hint", "someRuleValue_astro": "rule",
                                                         "hiddenDefault_astro": "default"})


def test_with_the_flag_an_unlisted_attribute_is_not_applicable_whatever_its_name_contains(flags):
    flags.cpq_model_scoped_questions_enabled = True
    visible, suppressed = _suppress()
    assert {"cloudRegion_astro", "regionalSrvMgrName_astro", "plainOther_astro", "modelSelectionBaseModelMsl_astro"} <= suppressed
    kept = {a.variable_name for a in visible}
    assert LISTED <= kept                                                    # the model's own rows
    assert {BASE, PRODUCT} <= kept                                           # exact decision anchors
    # values from the customer or the engine's own context are kept whatever the name; a hidden attribute's own default too
    assert {"CRM_BILL_COUNTRY", "_bm_model_variable_name", "typedByCustomer_astro", "hiddenDefault_astro"} <= kept
    assert "someRuleValue_astro" in suppressed                               # only a rule put a value on an unlisted attribute


def test_a_value_the_engine_only_guessed_does_not_protect_an_unlisted_attribute(flags):
    flags.cpq_model_scoped_questions_enabled = True
    _visible, suppressed = _suppress({"typedByCustomer_astro": "blind_pick_rule_governed"})
    assert "typedByCustomer_astro" in suppressed


def test_the_scoped_drops_are_reported_apart_from_the_old_rule(flags):
    """Review N1: `scoped_out` names exactly the attributes dropped by the new scoping, so the caller can log a distinct
    reason and a before/after replay can tell them from what the old rule suppressed."""
    flags.cpq_model_scoped_questions_enabled = True
    filled = {BASE: "H15UCF9PW6AN", PRODUCT: "APX N30", "elsewhere_astro": "x"}     # the customer answered elsewhere_astro
    scoped: set[str] = set()
    with patch.object(ag, "resolve_base_model_vn", return_value=BASE),             patch.object(ag, "_cpq_model_candidates", return_value=["APXN30"]),             patch.object(ag, "dt_governed_attr_names_for_base_model", return_value=set(LISTED)),             patch.object(ag, "dt_attr_ever_governed_for_cpq_model", side_effect=lambda cm, vn, *a, **k: vn == "elsewhere_astro"):
        _visible, suppressed = ag._suppress_ungoverned_attrs(
            [_attr("plainOther_astro"), _attr("elsewhere_astro"), _attr("batteryType_astro")], filled, 1, "p", {},
            {"elsewhere_astro": "user"}, scoped)
    assert scoped == {"plainOther_astro"}                    # dropped by the new scoping
    assert suppressed == {"plainOther_astro", "elsewhere_astro"}   # elsewhere_astro: the old 'tracked for another model' rule


def test_without_the_flag_nothing_new_is_suppressed(flags):
    flags.cpq_model_scoped_questions_enabled = False
    visible, suppressed = _suppress()
    assert suppressed == set() and len(visible) == len(ATTRS)                # fragment anchors and 'silence' stay visible


# --- the completeness check and the loop's returned list --------------------------------------------------------------
class _Engine:
    def __init__(self):
        self.calls = 0

    def _suppress_ungoverned_attrs(self, attrs, filled, ws, prefix, cache, sources, scoped_out=None):
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


def _loop_state():
    return SimpleNamespace(attrs=[_attr("isFLASHcodeAvailable_astro"), _attr("batteryType_astro")],
                           filled={"isFLASHcodeAvailable_astro": "YES", "batteryType_astro": "B"},
                           display_filled={"isFLASHcodeAvailable_astro": "Yes"}, sources={"isFLASHcodeAvailable_astro": "rule"},
                           multi={"isFLASHcodeAvailable_astro": ["a"]}, dt_cache={})


def test_the_loops_returned_list_is_scoped_only_with_the_flag(flags):
    from aryx.cpq.rules_loop import rules_loop

    scope = SimpleNamespace(workspace_id=1, catalog_prefix="p")
    flags.cpq_model_scoped_questions_enabled = False
    state = _loop_state()
    assert rules_loop._scoped_attrs(_Engine(), state, scope) is state.attrs and "isFLASHcodeAvailable_astro" in state.filled
    flags.cpq_model_scoped_questions_enabled = True
    state = _loop_state()
    assert [a.variable_name for a in rules_loop._scoped_attrs(_Engine(), state, scope)] == ["batteryType_astro"]


def test_a_dropped_attribute_keeps_no_value_in_the_loops_state(flags):
    """Review N2: the early pass pops a suppressed attribute's value from filled / display / sources / multi; the final
    scoping of the returned list does the same, so a rule's or a guess's value does not survive for the rest of the turn."""
    from aryx.cpq.rules_loop import rules_loop

    flags.cpq_model_scoped_questions_enabled = True
    state = _loop_state()
    rules_loop._scoped_attrs(_Engine(), state, SimpleNamespace(workspace_id=1, catalog_prefix="p"))
    assert "isFLASHcodeAvailable_astro" not in state.filled and "isFLASHcodeAvailable_astro" not in state.display_filled
    assert "isFLASHcodeAvailable_astro" not in state.sources and "isFLASHcodeAvailable_astro" not in state.multi
    assert state.filled == {"batteryType_astro": "B"}                        # the listed attribute keeps its value


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
    ctx = _blind_pick(attr, True, flags)
    assert ctx.filled_multi == {attr.variable_name: []} and ctx.sources == {attr.variable_name: "optional_multi_empty"}


def test_without_the_flag_it_still_takes_its_first_option(flags):
    attr = _attr("systemEnhancementFeatureType_astro", options=3, multi=True)
    assert _blind_pick(attr, False, flags).filled_multi == {attr.variable_name: ["o0"]}


def test_a_required_multi_select_is_still_filled(flags):
    attr = _attr("someRequiredMulti_astro", options=3, multi=True, required=True)
    assert _blind_pick(attr, True, flags).filled_multi == {attr.variable_name: ["o0"]}


# --- the not-applicable guard must not clear the decision anchors ---------------------------------------------------------
def _guard(vn, flag, flags, not_applicable=True):
    from aryx.cpq.auto_fill_stages import tier0_not_applicable_guard as guard

    flags.cpq_model_scoped_questions_enabled = flag
    settings = get_settings()
    previous = settings.cpq_not_applicable_guard_enabled
    settings.cpq_not_applicable_guard_enabled = True
    try:
        engine = SimpleNamespace(_is_hardware_version_attr=lambda a: False, _is_product_line_selector=lambda a: False,
                                 _named_attr_confirmed_not_applicable=lambda *a, **k: not_applicable)
        ctx = SimpleNamespace(filled={vn: "x"}, display_filled={vn: "x"}, sources={vn: "default"}, filled_multi={},
                              dt_cache={})
        scope = SimpleNamespace(workspace_id=1, catalog_prefix="p", product_anchor_hint="APX N30")
        state = AttrResolution(vn=vn, vn_flat=vn.lower())
        with patch.object(guard, "_log_device_once"):
            guard.stage_not_applicable_guard(engine, _attr(vn), ctx, scope, state)
        return state, ctx
    finally:
        settings.cpq_not_applicable_guard_enabled = previous


def test_the_guard_does_not_clear_the_base_model_with_the_flag(flags):
    """ws 1267, APX N30: the model's sequence rows do not list the base model attribute, so the guard cleared it in every
    pass and nothing was derived."""
    state, ctx = _guard(BASE, True, flags)
    assert not state.done and BASE in ctx.filled


def test_the_guard_still_clears_another_unlisted_attribute_with_the_flag(flags):
    state, ctx = _guard("someOtherFamilyAttr_astro", True, flags)
    assert state.done and "someOtherFamilyAttr_astro" not in ctx.filled


def test_without_the_flag_the_guard_behaves_as_before(flags):
    state, ctx = _guard(BASE, False, flags)
    assert state.done and BASE not in ctx.filled


# --- the settled empty selection is not reopened by the already-filled stage ------------------------------------------------
def _revalidate(source, flag, flags, recommendation=None):
    from aryx.cpq.auto_fill_stages import tier0_already_filled_multi as stage

    flags.cpq_model_scoped_questions_enabled = flag
    attr = _attr("systemEnhancementFeatureType_astro", options=3, multi=True)
    vn = attr.variable_name
    ctx = SimpleNamespace(filled_multi={vn: []}, sources={vn: source}, display_filled={}, dt_cache={}, dropped={},
                          default_fill_signatures=None, filled={})
    scope = SimpleNamespace(constrained_opts=None, grid_selector_vns=set(), grid_declined_vns=None, attrs=[attr])
    if recommendation is not None:        # a recommendation rule targets the attribute: (item value, display, rule name) or None
        scope.rec_by_target = {attr.entity_id: ["rule"]}
        scope.satisfied_recommendation = lambda a, opts: recommendation
    state = AttrResolution(vn=vn, vn_flat=vn.lower())
    with patch.object(stage.fill_log, "log_decision"), patch.object(stage.fill_log, "log_pruned"):
        stage.stage_already_filled_multi(SimpleNamespace(), attr, ctx, scope, state)
    return state, ctx, vn


def test_a_settled_empty_optional_multi_select_is_kept_not_reopened(flags):
    """The final post-loop pass reopened it as 'emptied by a constraint' and asked it among 227 options (ws 1267 shape)."""
    state, ctx, vn = _revalidate("optional_multi_empty", True, flags)
    assert state.done and vn in ctx.filled_multi and ctx.display_filled[vn]


def test_an_empty_multi_select_a_constraint_emptied_is_still_reopened(flags):
    state, ctx, vn = _revalidate("default", True, flags)
    assert not state.done and vn not in ctx.filled_multi


def test_without_the_flag_an_empty_multi_select_is_reopened_as_before(flags):
    state, ctx, vn = _revalidate("optional_multi_empty", False, flags)
    assert not state.done and vn not in ctx.filled_multi


def test_a_settled_empty_multi_select_is_reopened_once_a_recommendation_is_satisfied(flags):
    """Review N1: a rule that becomes satisfiable after the empty was settled (after the base model is derived, or a later
    answer) must still be able to fill the attribute."""
    state, ctx, vn = _revalidate("optional_multi_empty", True, flags, recommendation=("o1", "o1", "some rule"))
    assert not state.done and vn not in ctx.filled_multi and vn not in ctx.sources


def test_a_settled_empty_multi_select_stays_when_no_recommendation_is_satisfied(flags):
    state, ctx, vn = _revalidate("optional_multi_empty", True, flags, recommendation=None)
    assert state.done and vn in ctx.filled_multi


def test_a_failing_recommendation_check_keeps_the_settled_empty(flags):
    from aryx.cpq.auto_fill_stages import tier0_already_filled_multi as stage

    attr = _attr("x_astro", options=2, multi=True)
    scope = SimpleNamespace(rec_by_target={1: ["r"]}, satisfied_recommendation=lambda a, o: 1 / 0)
    assert stage._recommendation_now_satisfied(attr, scope) is False


# --- review N2 / N3: the anchor list is built once, the flags are read in one place ----------------------------------------
def test_the_anchor_list_is_built_once_and_holds_the_base_model():
    from aryx.cpq import model_scoping_flags as msf

    first = msf.scoped_anchor_vns()
    assert first is msf.scoped_anchor_vns()                                  # cached, not rebuilt per attribute
    assert BASE in first and PRODUCT in first and "ultimateDestinationCountry" in first


def test_the_flag_helpers_default_to_off_for_a_settings_double_without_the_flags():
    from aryx.cpq import model_scoping_flags as msf

    with patch("aryx.config.get_settings", return_value=SimpleNamespace()):
        assert msf.scoped_questions_enabled() is False and msf.tree_fallback_enabled() is False
    with patch("aryx.config.get_settings", return_value=SimpleNamespace(
            cpq_model_scoped_questions_enabled=True, cpq_model_resolution_tree_fallback_enabled=True)):
        assert msf.scoped_questions_enabled() is True and msf.tree_fallback_enabled() is True


def test_the_recommendation_is_not_evaluated_for_an_attribute_no_rule_targets(flags):
    """Review N4: the check can evaluate BML scripts, so it is skipped unless a rule targets the attribute."""
    from aryx.cpq.auto_fill_stages import tier0_already_filled_multi as stage

    attr = _attr("untargeted_astro", options=2, multi=True)
    calls = []
    scope = SimpleNamespace(rec_by_target={999999999: ["a rule on another attribute"]},
                            satisfied_recommendation=lambda a, o: calls.append(1) or ("o0", "o0", "r"))
    assert stage._recommendation_now_satisfied(attr, scope) is False and calls == []
    scope.rec_by_target = {attr.entity_id: ["r"]}                  # now a rule targets it: evaluated
    assert stage._recommendation_now_satisfied(attr, scope) is True and calls == [1]
