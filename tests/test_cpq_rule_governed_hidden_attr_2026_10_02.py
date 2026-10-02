"""Port of dev-rv-msi #373/#374: rule-governed hidden attrs are never
surfaced as unanswerable grid-quantity questions, gated behind
``cpq_rule_governed_hidden_attr_guard_enabled`` (default off).

Flag-on tests are ported from the source commits; flag-off tests assert the
behaviour is unchanged from before the port.
"""
from __future__ import annotations

import pytest

from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


@pytest.fixture(autouse=True)
def _reset_flag():
    s = get_settings()
    prev = s.cpq_rule_governed_hidden_attr_guard_enabled
    yield
    s.cpq_rule_governed_hidden_attr_guard_enabled = prev


@pytest.fixture
def guard_on():
    get_settings().cpq_rule_governed_hidden_attr_guard_enabled = True


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attrs_with_rule_governed_quantity_lookalike():
    selector = ConfigAttr(
        entity_id=1, variable_name="conventionalOptionsFeaturesAry_astro",
        display_label="Conventional Options Features",
        required=False, default_value="", select_type="multi",
        options=_opt("FALL BACK IN CABINET REPEATER", "RECEIVER SCAN OPERATION"),
    )
    # A genuine grid-quantity companion (this heuristic's real target) --
    # no governing rule, its value comes purely from the customer's answer.
    real_qty_attr = ConfigAttr(
        entity_id=2, variable_name="fallBackInCabinetRepeaterQuantity_astro",
        display_label="Fall Back In Cabinet Repeater Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    # The live-bug shape: hidden, name contains "Quantity", but its value is
    # rule-governed (a real BML function computes it) -- must NOT be treated
    # as a customer-answerable grid-quantity companion.
    rule_governed_lookalike = ConfigAttr(
        entity_id=3, variable_name="hiddenConventionalOptionsMaxQuantityAry_astro",
        display_label="hidden max quantity",
        required=False, default_value="", options=[], hidden=True,
        is_value_rule_target=True,
    )
    return [selector, real_qty_attr, rule_governed_lookalike]


def test_flag_on_rule_governed_attr_is_excluded_from_grid_quantity_linking(guard_on):
    attrs = _attrs_with_rule_governed_quantity_lookalike()
    links = CpqEngine.resolve_array_grid_links(attrs)
    item_map = links.get("conventionalOptionsFeaturesAry_astro", {})

    assert "fall back in cabinet repeater" in item_map, (
        "the genuine, non-rule-governed grid-quantity companion must still link"
    )
    assert all(
        vn != "hiddenConventionalOptionsMaxQuantityAry_astro"
        for vn in item_map.values()
    ), (
        "a hidden attr already governed by a real rule must never be "
        "linked as a grid-quantity companion via the name-substring guess"
    )


def test_flag_on_resolve_pending_grid_quantities_never_surfaces_the_rule_governed_lookalike(guard_on):
    attrs = _attrs_with_rule_governed_quantity_lookalike()
    eng = CpqEngine()
    # Selector never answered -- the upfront flow would otherwise treat
    # every linked option (real and lookalike) as pending its own quantity.
    extra = eng.resolve_pending_grid_quantities(attrs, filled={}, filled_multi={})
    extra_vns = {a.variable_name for a in extra}

    assert "fallBackInCabinetRepeaterQuantity_astro" in extra_vns, (
        "the genuine grid-quantity companion must still surface upfront"
    )
    assert "hiddenConventionalOptionsMaxQuantityAry_astro" not in extra_vns, (
        "the rule-governed lookalike must never surface as a pending "
        "question -- its real value only ever comes from its rule firing"
    )


class _FakeRdb:
    def __init__(self, entity_attrs: dict[int, dict]):
        self._entity_attrs = entity_attrs

    def fetch_entity_attributes(self, entity_ids, workspace_id):
        return {eid: self._entity_attrs[eid] for eid in entity_ids if eid in self._entity_attrs}

    def fetch_attr_set_assoc(self, workspace_id, catalog_prefix=""):
        return {}

    def fetch_rule_inputs(self, workspace_id, catalog_prefix=""):
        return []

    def fetch_rule_actions(self, workspace_id, catalog_prefix=""):
        # Zero BmConfigRuleAction rows target our attr -- confirmed live,
        # this is exactly the real-data shape that made is_value_rule_target
        # wrongly False before this fix.
        return []

    def fetch_marked_attrs(self, workspace_id, catalog_prefix=""):
        # Two real rules mark this attr's NATIVE id (5661960272) as their
        # target -- confirmed live via Postgres BmConfigMarkedAttr rows.
        return [(5661960425, 5661960272), (5661960430, 5661960272)]

    def fetch_rule_chain_links(self, workspace_id, catalog_prefix=""):
        return []


class _FakeReader:
    def __init__(self, attr_type: str, entities: list[dict]):
        self._attr_type = attr_type
        self._entities = entities

    def distinct_types(self):
        return [self._attr_type]

    def find_entities(self, ontology_type=None, name=None, limit=50, offset=0):
        if ontology_type != self._attr_type:
            return []
        return self._entities

    def neighbors(self, entity_id):
        return []


def _load(entity_attrs, entities, monkeypatch, workspace_id):
    rdb = _FakeRdb(entity_attrs)
    import aryx.cpq.engine as engine_mod
    monkeypatch.setattr(engine_mod, "get_cpq_rdb", lambda: rdb)
    reader = _FakeReader(attr_type="Astro25ConfigdataBmConfigAttr", entities=entities)
    engine = CpqEngine()
    return engine.load_product_config(reader, workspace_id=workspace_id, product_hint="APX 900")


def test_flag_on_marked_attr_only_target_is_recognized_as_rule_governed(monkeypatch, guard_on):
    # Distinct workspace_id -- avoids any collision with _RULE_JOIN_DATA_
    # CACHE entries other tests in this session may have already populated.
    workspace_id = 9927001
    entity_attrs = {
        200: {
            "id": "5661960272", "variable_name": "addOnOptionsQuantityAry_astro",
            "name": "Add On Options Quantity", "required": "0", "default_value": "",
            "order_number": "1", "hidden": "1",
        },
    }
    entities = [{"id": 200, "type": "Astro25ConfigdataBmConfigAttr"}]
    attrs, _ = _load(entity_attrs, entities, monkeypatch, workspace_id)
    by_vn = {a.variable_name: a for a in attrs}

    assert "addOnOptionsQuantityAry_astro" in by_vn, (
        "the attr must still load (it's hidden but real rule-governed data, "
        "never dropped as noise)"
    )
    assert by_vn["addOnOptionsQuantityAry_astro"].is_value_rule_target is True, (
        "a BmConfigMarkedAttr-only target must be recognized as rule-"
        "governed, same as a BmConfigRuleAction target -- otherwise "
        "resolve_array_grid_links' name-substring 'quantity' guess has no "
        "reason to exclude it, and it surfaces as an unanswerable pending "
        "question exactly like the #373 bug"
    )


def test_flag_on_action_target_still_recognized_unaffected_by_this_change(monkeypatch, guard_on):
    """Regression guard: the pre-existing BmConfigRuleAction path (#373's
    original fix) must be completely unaffected by unioning in marked_by_
    rule -- both linkage tables contribute, neither replaces the other."""
    workspace_id = 9927002

    class _ActionOnlyRdb(_FakeRdb):
        def fetch_rule_actions(self, workspace_id, catalog_prefix=""):
            return [(555, 7778889, 2, "", -1, 0, "")]

        def fetch_marked_attrs(self, workspace_id, catalog_prefix=""):
            return []

    entity_attrs = {
        300: {
            "id": "7778889", "variable_name": "hiddenConventionalOptionsMaxQuantityAry_astro",
            "name": "hidden max quantity", "required": "0", "default_value": "",
            "order_number": "1", "hidden": "1",
        },
    }
    entities = [{"id": 300, "type": "Astro25ConfigdataBmConfigAttr"}]
    rdb = _ActionOnlyRdb(entity_attrs)
    import aryx.cpq.engine as engine_mod
    monkeypatch.setattr(engine_mod, "get_cpq_rdb", lambda: rdb)
    reader = _FakeReader(attr_type="Astro25ConfigdataBmConfigAttr", entities=entities)
    engine = CpqEngine()
    attrs, _ = engine.load_product_config(reader, workspace_id=workspace_id, product_hint="APX 900")
    by_vn = {a.variable_name: a for a in attrs}
    assert by_vn["hiddenConventionalOptionsMaxQuantityAry_astro"].is_value_rule_target is True


# ---- flag-off no-op ----

def _sel_and_gov():
    selector = ConfigAttr(
        entity_id=1, variable_name="sel", display_label="s", required=False,
        default_value="", options=_opt("RECEIVER SCAN OPERATION"),
    )
    gov = ConfigAttr(
        entity_id=2, variable_name="receiverScanOperationQuantity", display_label="q",
        required=False, default_value="", options=[], hidden=True,
        is_value_rule_target=True,
    )
    return [selector, gov]


def test_flag_default_is_off():
    assert get_settings().cpq_rule_governed_hidden_attr_guard_enabled is False


def test_flag_off_rule_target_attr_still_a_candidate():
    assert CpqEngine.resolve_array_grid_links(_sel_and_gov()) == {
        "sel": {"receiver scan operation": "receiverScanOperationQuantity"}
    }


def test_flag_on_rule_target_attr_not_a_candidate(guard_on):
    assert CpqEngine.resolve_array_grid_links(_sel_and_gov()) == {}


def test_flag_off_marked_attr_only_target_not_unioned(monkeypatch):
    attrs, _ = _load(
        {200: {"id": "5661960272", "variable_name": "addOnOptionsQuantityAry_astro",
               "name": "Add On Options Quantity", "required": "0",
               "default_value": "", "order_number": "1", "hidden": "1"}},
        [{"id": 200, "type": "Astro25ConfigdataBmConfigAttr"}],
        monkeypatch, 9927003,
    )
    by_vn = {a.variable_name: a for a in attrs}
    assert by_vn["addOnOptionsQuantityAry_astro"].is_value_rule_target is False
