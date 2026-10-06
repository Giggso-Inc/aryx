"""Plan F6 / F4 / F13: the derived required-attribute set. Synthetic names only
(no product, model or attribute of any real catalog).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aryx.cpq import mandatory_input
from aryx.cpq.payload_building import required_set as rs
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption, ValidationRule


_OFF = ("cpq_getconstraintvals_port_enabled", "cpq_series_model_narrowing_enabled", "cpq_required_set_guards_assumed_open",
        "cpq_required_set_enabled")


def _cfg(**kw):
    """Settings stand-in: every flag the derivation reads is off unless a test turns it on."""
    m = MagicMock()
    for k in _OFF:
        setattr(m.return_value, k, False)
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


def _attr(eid, vn, hidden=False, hide_in_trans=False):
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=vn, required=False, default_value="",
        options=[MenuOption(item_value="x", display_name="x", order=1)], source_id=eid + 1000,
        hidden=hidden, hide_in_trans=hide_in_trans,
    )


ATTRS = [_attr(1, "a_vn"), _attr(2, "b_vn"), _attr(3, "c_vn"), _attr(4, "hid_vn", hidden=True),
         _attr(5, "hit_vn", hide_in_trans=True), _attr(6, "d_vn")]


def _seq(model, base, name, flag):
    return {"CPQModel": model, "BaseModel": base, "AttrName": name, "Seq": "1", "optionOrReqFlag": flag}


SEQ = [
    _seq("M", "B1", "a_vn", "R"), _seq("M", "B1", "b_vn", "O"), _seq("M", "B1", "hid_vn", "R"),
    _seq("M", "B2", "a_vn", "R"), _seq("M", "B2", "b_vn", "R"), _seq("M", "ALL", "c_vn", "R"),
    _seq("M", "B1", "hit_vn", "R"),
]


def _engine(con=(), val=(), narrowed=None):
    eng = MagicMock()
    eng.load_recommendation_and_constraint_rules.return_value = ([], list(con))
    eng.load_validation_rules.return_value = list(val)
    eng.resolve_array_grid_links.return_value = {}
    eng._resolve_narrowed_legal_values.side_effect = lambda vn, *a, **k: (narrowed or {}).get(vn)
    return eng


def _derive(eng, filled=None, sources=None, hidden=None, order=None, product="P", base_vn="base_vn", models=("M",), **kw):
    with patch.object(rs, "_load_all_tables", return_value=([], SEQ, [], [], [])), \
            patch.object(rs, "resolve_base_model_vn", return_value=base_vn), \
            patch.object(rs._engine_module, "_cpq_model_candidates", return_value=tuple(models)), \
            patch.object(rs, "get_settings", _cfg(cpq_required_set_guards_assumed_open=kw.get("assume_open", False))):
        return rs.derive_required_vns(
            eng, ATTRS, filled or {}, kw.get("filled_multi"), sources, hidden, order, 1, "", product)


def test_r_flag_for_the_resolved_base_model_plus_all_rows_and_visibility_filters():
    got = _derive(_engine(), filled={"base_vn": "B1"})
    assert got == {"a_vn", "c_vn"}            # b_vn is O on B1; hid_vn catalog-hidden; hit_vn hide_in_trans


def test_unresolved_base_model_requires_r_on_every_base_model():
    got = _derive(_engine())
    assert got == {"a_vn", "c_vn"}            # b_vn is R only on B2


def test_layout_visible_order_and_rule_hidden_vns_remove_candidates():
    assert _derive(_engine(), filled={"base_vn": "B1"}, order={"a_vn": 0}) == {"a_vn"}
    assert _derive(_engine(), filled={"base_vn": "B1"}, hidden={"a_vn"}) == {"c_vn"}


def test_a_value_filled_by_the_catalog_is_not_required_but_an_engine_guess_is():
    filled = {"base_vn": "B1", "a_vn": "x", "c_vn": "x"}
    got = _derive(_engine(), filled=filled, sources={"a_vn": "default", "c_vn": "blind_pick_governed"})
    assert got == {"c_vn"}
    got = _derive(_engine(), filled=filled, sources={"a_vn": "user", "c_vn": "rule"})
    assert got == {"a_vn"}


def test_confirmed_empty_legal_set_removes_the_candidate_unknown_keeps_it():
    assert _derive(_engine(narrowed={"a_vn": []}), filled={"base_vn": "B1"}) == {"c_vn"}
    assert _derive(_engine(narrowed={"a_vn": None}), filled={"base_vn": "B1"}) == {"a_vn", "c_vn"}


def _blank_rule(guard="", conditions=((11, "BR", "4"),), target=1006):
    return ConstraintRule(rule_name="r", condition_attr_id=11, condition_value="", target_attr_id=target,
                          allowed_values=[], conditions=list(conditions), mode="DISALLOW", guard_attr=guard, blank=True)


def _by_rule_id_patch():
    # attribute ids the rules reference: the condition attribute (11) is attr "cond_vn"
    cond = _attr(11, "cond_vn")
    cond.source_id = 11
    return cond


def _derive_rules(eng, filled, **kw):
    attrs = [*ATTRS, _by_rule_id_patch()]
    with patch.object(rs, "_load_all_tables", return_value=([], [], [], [], [])), \
            patch.object(rs, "resolve_base_model_vn", return_value="base_vn"), \
            patch.object(rs._engine_module, "_cpq_model_candidates", return_value=("M",)), \
            patch.object(rs, "get_settings", _cfg(cpq_required_set_guards_assumed_open=kw.get("assume_open", False))):
        return rs.derive_required_vns(eng, attrs, filled, None, None, None, None, 1, "", "P")


def test_blank_disallow_rule_makes_its_target_required_only_when_it_fires():
    eng = _engine(con=[_blank_rule()])
    assert _derive_rules(eng, {"cond_vn": "BR"}) == {"d_vn"}
    assert _derive_rules(eng, {"cond_vn": "US"}) == set()        # condition false
    assert _derive_rules(eng, {}) == set()                       # condition unknown (F13): never fires


def test_guard_variable_must_hold_a_value_unless_assumed_open():
    eng = _engine(con=[_blank_rule(guard="g_var")])
    assert _derive_rules(eng, {"cond_vn": "BR"}) == set()                             # guard absent, not assumed
    assert _derive_rules(eng, {"cond_vn": "BR", "g_var": "T"}) == {"d_vn"}            # guard populated
    assert _derive_rules(eng, {"cond_vn": "BR"}, assume_open=True) == {"d_vn"}        # host populates it
    assert _derive_rules(eng, {"cond_vn": "BR", "g_var": " "}, assume_open=True) == set()   # present but empty


def test_message_only_validation_rule_requires_its_target_when_declarative_and_true():
    fires = ValidationRule(rule_name="v", target_attr_id=1002, message="m", condition_attr_id=11, condition_value="BR",
                           conditions=[(11, "BR", "4")])
    scripted = ValidationRule(rule_name="v2", target_attr_id=1003, message="m", condition_attr_id=0, condition_value="",
                              condition_script="return true;")
    eng = _engine(val=[fires, scripted])
    assert _derive_rules(eng, {"cond_vn": "BR"}) == {"b_vn"}
    assert _derive_rules(eng, {"cond_vn": "US"}) == set()


def test_no_product_means_no_r_candidates_but_rules_still_apply():
    eng = _engine(con=[_blank_rule()])
    with patch.object(rs, "_load_all_tables", return_value=([], SEQ, [], [], [])), \
            patch.object(rs, "resolve_base_model_vn", return_value="base_vn"), \
            patch.object(rs, "get_settings", _cfg(cpq_required_set_guards_assumed_open=False)):
        got = rs.derive_required_vns(eng, [*ATTRS, _by_rule_id_patch()], {"cond_vn": "BR"}, None, None, None, None, 1, "", "")
    assert got == {"d_vn"}


def test_no_attrs_or_workspace_gives_an_empty_set():
    assert rs.derive_required_vns(_engine(), [], {}, None, None, None, None, 1) == frozenset()
    assert rs.derive_required_vns(_engine(), ATTRS, {}, None, None, None, None, None) == frozenset()


def test_hand_listed_names_are_ignored_when_the_derived_set_drives():
    eng = SimpleNamespace(_is_hardware_version_attr=lambda a: False, _hardware_version_confirmed_not_applicable=lambda *a: False)
    attr = _attr(9, "listed_vn")
    with patch.object(mandatory_input._engine_module, "_ATTRSEQ_CONFIRMED_REQUIRED_VNS", frozenset({"listed_vn"})), \
            patch.object(mandatory_input._engine_module, "_DECISION_REQUIRED_KEYS", ()):
        with patch.object(mandatory_input, "get_settings", _cfg(cpq_required_set_enabled=False)):
            assert mandatory_input.is_mandatory_input_attr(eng, "listed_vn", attr, "default") is True
        with patch.object(mandatory_input, "get_settings", _cfg(cpq_required_set_enabled=True)):
            assert mandatory_input.is_mandatory_input_attr(eng, "listed_vn", attr, "default") is False
            assert mandatory_input.is_mandatory_input_attr(
                eng, "listed_vn", attr, "default", required_vns=frozenset({"listed_vn"})) is True


def test_shadow_difference_is_logged_and_nothing_is_returned(caplog):
    with caplog.at_level("INFO", logger=rs.logger.name):
        assert rs.log_shadow_difference("t", frozenset({"a", "b"}), {"b", "c"}) is None
    assert "only_derived=['a']" in caplog.text and "only_current=['c']" in caplog.text


def test_a_quantity_attribute_filled_by_a_script_rule_is_not_required():
    from aryx.cpq.state import RecommendationRule
    eng = _engine()
    eng.resolve_array_grid_links.return_value = {"sel_vn": {"opt": "c_vn"}}       # c_vn is a per-option quantity
    script_rule = RecommendationRule(rule_name="q", condition_attr_id=0, condition_value="", target_attr_id=1003, script="loop")
    eng.load_recommendation_and_constraint_rules.return_value = ([script_rule], [])
    assert _derive(eng, filled={"base_vn": "B1"}) == {"a_vn"}                      # c_vn dropped
    eng.load_recommendation_and_constraint_rules.return_value = ([], [])           # no rule fills it: stays required
    assert _derive(eng, filled={"base_vn": "B1"}) == {"a_vn", "c_vn"}


def test_legal_options_use_the_port_when_its_flag_is_on_and_the_base_model_is_known():
    eng = _engine(narrowed={"a_vn": None})
    port = {"B1": {"a_vn": {"values": [], "blank_allowed": True, "required": False}}}

    def fake_port(cm, base, vn, filled, ws, prefix, cache):
        return port.get(base, {}).get(vn)

    def run(flag, filled):
        with patch.object(rs, "get_constraint_vals", side_effect=fake_port),                 patch.object(rs, "get_settings", _cfg(cpq_getconstraintvals_port_enabled=flag, cpq_required_set_guards_assumed_open=False)):
            return _derive_with_settings(eng, filled)

    assert run(True, {"base_vn": "B1"}) == {"c_vn"}                 # port: nothing legal yet for a_vn -> not red yet
    assert run(False, {"base_vn": "B1"}) == {"a_vn", "c_vn"}        # flag off: the old resolver says unknown -> required
    assert run(True, {}) == {"a_vn", "c_vn"}                        # no base model: the port is not consulted


def _derive_with_settings(eng, filled):
    # derive_required_vns reads get_settings itself; _cfg above already patched rs.get_settings
    with patch.object(rs, "_load_all_tables", return_value=([], SEQ, [], [], [])),             patch.object(rs, "resolve_base_model_vn", return_value="base_vn"),             patch.object(rs._engine_module, "_cpq_model_candidates", return_value=("M",)):
        return rs.derive_required_vns(eng, ATTRS, filled, None, None, None, None, 1, "", "P")


def test_no_legal_value_treats_missing_port_rows_as_unknown():
    eng = _engine(narrowed={})
    with patch.object(rs, "get_constraint_vals", return_value=None),             patch.object(rs, "get_settings", _cfg(cpq_getconstraintvals_port_enabled=True)):
        assert rs.no_legal_value(eng, "a_vn", {}, ["M"], "B1", 1, "", None) is False
    with patch.object(rs, "get_constraint_vals", return_value={"values": ["x"], "blank_allowed": True, "required": False}),             patch.object(rs, "get_settings", _cfg(cpq_getconstraintvals_port_enabled=True)):
        assert rs.no_legal_value(eng, "a_vn", {}, ["M"], "B1", 1, "", None) is False


def test_series_narrowing_runs_before_attr_sequence_is_read_only_when_its_flag_is_on():
    eng = _engine()
    seq = SEQ + [_seq("N", "B1", "d_vn", "R")]
    calls = []

    def fake_narrow(models, filled, ws, prefix, cache):
        calls.append(list(models))
        return ["M"]

    def run(flag):
        calls.clear()
        with patch.object(rs, "_load_all_tables", return_value=([], seq, [], [], [])), \
                patch.object(rs, "resolve_base_model_vn", return_value="base_vn"), \
                patch.object(rs, "narrow_models_by_series", side_effect=fake_narrow), \
                patch.object(rs._engine_module, "_cpq_model_candidates", return_value=("M", "N")), \
                patch.object(rs, "get_settings", _cfg(cpq_series_model_narrowing_enabled=flag)):
            return rs.derive_required_vns(eng, ATTRS, {"base_vn": "B1"}, None, None, None, None, 1, "", "P")

    assert run(True) == {"a_vn", "c_vn"} and calls == [["M", "N"]]          # model N (with d_vn) was dropped
    assert run(False) == {"a_vn", "c_vn", "d_vn"} and calls == []           # flag off: nothing dropped


def test_config_data_sources_are_customer_entered_only_when_the_derived_set_drives():
    from aryx.cpq.payload.payload_state import PayloadContext, config_data_sources
    wide = frozenset({"user", "hint", "cascade", "country_derived", "product_anchor"})
    ctx = PayloadContext.__new__(PayloadContext)
    ctx.derived_required_vns = None
    assert config_data_sources(ctx, wide) == wide
    ctx.derived_required_vns = frozenset({"a"})
    assert config_data_sources(ctx, wide) == frozenset({"user"})
