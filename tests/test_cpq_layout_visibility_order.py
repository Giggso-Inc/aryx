"""docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md — a catalog's decoded
native-UI layout export (`Config Layout APX Next.txt`-shaped JSON) becomes
an additional source of truth for: (§2) which attributes appear in the
summary/payload and in what order, (§2b) the order pending questions get
asked and how same-target rule conflicts resolve, (§2c) which attributes
get asked at all versus silently skipped when nothing can resolve them.

Every mechanism here is gated on a loaded layout map being present for the
catalog in play — `None` (no matching/no-longer-Active layout file) must
leave every existing behavior byte-for-byte unchanged, which is the
single most load-bearing invariant across this whole plan and is checked
explicitly throughout.
"""
from __future__ import annotations

import json

import pytest

from aryx.cpq import engine as engine_module
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, HidingRule, MenuOption, RecommendationRule


@pytest.fixture(autouse=True)
def _clear_layout_caches():
    """These loaders are cached process-lifetime, keyed by
    (workspace_id, catalog_prefix) — clear between tests so one test's
    result can never leak into another via the shared module cache."""
    engine_module._LAYOUT_COMPONENTS_CACHE.clear()
    engine_module._LAYOUT_DISPLAY_ORDER_CACHE.clear()
    engine_module._LAYOUT_FULL_ORDER_CACHE.clear()
    yield
    engine_module._LAYOUT_COMPONENTS_CACHE.clear()
    engine_module._LAYOUT_DISPLAY_ORDER_CACHE.clear()
    engine_module._LAYOUT_FULL_ORDER_CACHE.clear()


class _FakeLayoutFileSource:
    """Test double for the LayoutFileSource Protocol — an in-memory
    {catalog_name: raw_text} map instead of reading real files."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def get(self, catalog_name: str) -> str | None:
        return self._mapping.get(catalog_name)


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _leaf(vn: str, hide: bool, resource_attr_type: str = "Text") -> dict:
    return {
        "resourceAttributeVarName": vn, "hide": hide,
        "resourceAttrType": resource_attr_type,
    }


def _layout_json(components: list[dict], status: str = "Active") -> str:
    return json.dumps({
        "id": 1, "variableName": "testFlow", "title": "Test Flow",
        "status": status, "components": {"items": components},
    })


# ── load_layout_display_order / _load_layout_full_order ────────────────────

def test_valid_layout_returns_filtered_ordered_visible_map():
    comps = [
        _leaf("a", False), _leaf("b", True), _leaf("html_a", False, "HTML"),
        _leaf("c", False),
    ]
    source = _FakeLayoutFileSource({"Cat": _layout_json(comps)})
    eng = CpqEngine()
    order = eng.load_layout_display_order(1, "Cat", layout_source=source)
    assert order == {"a": 0, "c": 1}


def test_full_order_includes_hidden_and_html_attrs():
    """Rule-conflict ranking (§2b) needs hidden condition attrs (e.g. a
    derived Base Model) to have a real rank — the visible-only map must
    not be the only thing available."""
    comps = [_leaf("a", False), _leaf("b", True), _leaf("html_a", False, "HTML")]
    source = _FakeLayoutFileSource({"Cat": _layout_json(comps)})
    eng = CpqEngine()
    full = eng._load_layout_full_order(2, "Cat", layout_source=source)
    assert full == {"a": 0, "b": 1, "html_a": 2}


def test_inactive_status_returns_none():
    comps = [_leaf("a", False)]
    source = _FakeLayoutFileSource({"Cat": _layout_json(comps, status="Old")})
    eng = CpqEngine()
    assert eng.load_layout_display_order(3, "Cat", layout_source=source) is None


def test_no_matching_file_returns_none():
    source = _FakeLayoutFileSource({})
    eng = CpqEngine()
    assert eng.load_layout_display_order(4, "Cat", layout_source=source) is None


def test_malformed_json_returns_none_not_raises():
    source = _FakeLayoutFileSource({"Cat": "{ this is not json"})
    eng = CpqEngine()
    assert eng.load_layout_display_order(5, "Cat", layout_source=source) is None


def test_duplicate_variable_name_keeps_first_occurrence_rank():
    comps = [_leaf("a", False), _leaf("b", False), _leaf("a", False)]
    source = _FakeLayoutFileSource({"Cat": _layout_json(comps)})
    eng = CpqEngine()
    order = eng.load_layout_display_order(6, "Cat", layout_source=source)
    assert order == {"a": 0, "b": 1}


def test_result_is_cached_process_lifetime():
    calls = []

    class _CountingSource:
        def get(self, catalog_name):
            calls.append(catalog_name)
            return _layout_json([_leaf("a", False)])

    eng = CpqEngine()
    source = _CountingSource()
    eng.load_layout_display_order(7, "Cat", layout_source=source)
    eng.load_layout_display_order(7, "Cat", layout_source=source)
    assert len(calls) == 1


# ── LocalDirLayoutFileSource ────────────────────────────────────────────────

def test_local_dir_source_matches_by_normalized_catalog_name_substring(tmp_path):
    from aryx.cpq.layout_source import LocalDirLayoutFileSource

    (tmp_path / "Config Layout APX Next.txt").write_text(_layout_json([_leaf("a", False)]))
    (tmp_path / "APX Next.xml").write_text("<not-a-layout-file/>")
    source = LocalDirLayoutFileSource(tmp_path)
    text = source.get("Apx Next")
    assert text is not None
    assert json.loads(text)["variableName"] == "testFlow"


def test_local_dir_source_ignores_non_txt_files(tmp_path):
    from aryx.cpq.layout_source import LocalDirLayoutFileSource

    (tmp_path / "SVX.xml").write_text(_layout_json([_leaf("a", False)]))
    source = LocalDirLayoutFileSource(tmp_path)
    assert source.get("SVX") is None


def test_local_dir_source_no_match_returns_none(tmp_path):
    from aryx.cpq.layout_source import LocalDirLayoutFileSource

    source = LocalDirLayoutFileSource(tmp_path)
    assert source.get("Anything") is None


def test_local_dir_source_matches_the_real_filename_derived_catalog_prefix(tmp_path):
    """Live bug (2026-08-08): the real ingested catalog_prefix is whatever
    aryx.pipeline.doc_discovery._stem_type derived from the source XML's
    OWN filename ("ApxnextCnofigdata", from "APXNext_CnofigData.xml",
    typo included) -- a completely different naming scheme than the
    human-authored layout export's filename ("Config Layout APX Next.
    txt"). Neither is a raw substring of the other; only stripping the
    filename's own "config"/"layout" boilerplate surfaces the shared
    "apxnext" core both sides agree on. The file, the env var, and
    load_layout_display_order's own wiring were all already correct --
    only this match ever silently failed."""
    from aryx.cpq.layout_source import LocalDirLayoutFileSource

    (tmp_path / "Config Layout APX Next.txt").write_text(_layout_json([_leaf("a", False)]))
    source = LocalDirLayoutFileSource(tmp_path)
    assert source.get("ApxnextCnofigdata") is not None


def test_local_dir_source_boilerplate_stripping_does_not_create_false_positives(tmp_path):
    """A catalog_prefix that doesn't genuinely share a core with a given
    layout filename must still correctly NOT match it, even after
    boilerplate stripping -- e.g. "ApxnextCnofigdata" must not spuriously
    match an unrelated "AstroApx" layout file."""
    from aryx.cpq.layout_source import LocalDirLayoutFileSource

    (tmp_path / "Config Layout AstroApx.txt").write_text(_layout_json([_leaf("a", False)]))
    source = LocalDirLayoutFileSource(tmp_path)
    assert source.get("ApxnextCnofigdata") is None
    assert source.get("AstroApx") is not None


# ── §2: summary/payload filtering + ordering ────────────────────────────────

def _attrs_for_filter_test() -> list[ConfigAttr]:
    return [
        ConfigAttr(entity_id=1, variable_name="country", display_label="Country",
                   required=False, default_value="", select_type="single", options=_menu("US")),
        ConfigAttr(entity_id=2, variable_name="internalCode_astro", display_label="Internal Code",
                   required=False, default_value="", select_type="single", options=_menu("X1")),
        ConfigAttr(entity_id=3, variable_name="product", display_label="Product",
                   required=False, default_value="", select_type="single", options=_menu("P1")),
    ]


def test_build_payload_filters_and_reorders_by_display_order():
    eng = CpqEngine()
    filled = {"country": "US", "internalCode_astro": "X1", "product": "P1"}
    display_order = {"product": 0, "country": 1}
    result = eng.build_payload(filled, attrs=_attrs_for_filter_test(), display_order=display_order)
    assert list(result["configData"].keys()) == ["product", "country"]


def test_build_payload_display_order_none_keeps_todays_behavior():
    eng = CpqEngine()
    filled = {"country": "US", "internalCode_astro": "X1"}
    result = eng.build_payload(filled, attrs=_attrs_for_filter_test())
    assert set(result["configData"].keys()) == {"country", "internalCode_astro"}


def _attrs_for_summary_test() -> list[ConfigAttr]:
    # Deliberately avoids "country"/"product" — both trigger unrelated,
    # pre-existing `_is_summary_excluded` business rules (a real product
    # name IS shown via the summary header already, secondary/warranty
    # attrs, etc.) that have nothing to do with the display_order
    # mechanism these tests target.
    return [
        ConfigAttr(entity_id=1, variable_name="widgetColor_astro", display_label="Widget Color",
                   required=False, default_value="", select_type="single", options=_menu("Red")),
        ConfigAttr(entity_id=2, variable_name="widgetSize_astro", display_label="Widget Size",
                   required=False, default_value="", select_type="single", options=_menu("Large")),
    ]


def test_filled_summary_triples_filters_and_reorders():
    eng = CpqEngine()
    attrs = _attrs_for_summary_test()
    display_filled = {"widgetColor_astro": "Red", "widgetSize_astro": "Large"}
    display_order = {"widgetSize_astro": 0, "widgetColor_astro": 1}
    triples = eng._filled_summary_triples(display_filled, attrs, display_order=display_order)
    assert [t[0] for t in triples] == ["widgetSize_astro", "widgetColor_astro"]


def test_categorized_summary_groups_passes_display_order_through():
    eng = CpqEngine()
    attrs = _attrs_for_summary_test()
    display_filled = {"widgetColor_astro": "Red", "widgetSize_astro": "Large"}
    display_order = {"widgetSize_astro": 0, "widgetColor_astro": 1}
    groups = eng.categorized_summary_groups(display_filled, attrs, display_order=display_order)
    flat = [label for _cat, pairs in groups for label, _val in pairs]
    assert flat.index("Widget Size") < flat.index("Widget Color")


# ── §2c: ask-only-anchors / skip-if-unresolved ──────────────────────────────

def test_auto_fill_asks_decision_attr_even_with_display_order():
    country = ConfigAttr(
        entity_id=1, variable_name="ultimateDestinationCountry", display_label="Country",
        required=False, default_value="", select_type="single", options=_menu("US", "CA"),
    )
    eng = CpqEngine()
    _, _, pending = eng.auto_fill([country], {}, display_order={"ultimateDestinationCountry": 0})
    assert [a.variable_name for a in pending] == ["ultimateDestinationCountry"]


def test_auto_fill_skips_unresolvable_non_anchor_attr_when_layout_loaded():
    plain = ConfigAttr(
        entity_id=1, variable_name="someOptionalChoice_astro", display_label="Some Choice",
        required=False, default_value="", select_type="single", options=_menu("A", "B"),
    )
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [plain], {}, display_order={"someOptionalChoice_astro": 0},
    )
    assert pending == []
    assert "someOptionalChoice_astro" not in filled


def test_auto_fill_asks_an_ungoverned_base_model_attr_even_when_layout_loaded():
    """Live bug (2026-08-08): modelSelectionbaseModel_astro -- a real,
    16-real-option, ZERO-governing-rule menu attr -- was identically
    shaped to test_auto_fill_skips_unresolvable_non_anchor_attr_when_
    layout_loaded's "someOptionalChoice_astro" fixture above, and got
    silently skipped once §2c's display_order-gated behavior activated,
    dropping a genuine, structurally load-bearing customer decision.
    "basemodel" is carved out via the same fragment-match convention
    _DECISION_REQUIRED_KEYS already uses for country/region -- a
    structural naming convention, not a literal per-catalog name."""
    base_model = ConfigAttr(
        entity_id=1, variable_name="modelSelectionbaseModel_astro",
        display_label="Base Model", required=False, default_value="",
        select_type="single", options=_menu("H45TGU9PW8AN", "H55TGT9PW8AN"),
    )
    eng = CpqEngine()
    _, _, pending = eng.auto_fill(
        [base_model], {}, display_order={"modelSelectionbaseModel_astro": 0},
    )
    assert [a.variable_name for a in pending] == ["modelSelectionbaseModel_astro"]


def test_auto_fill_asks_base_model_even_when_it_is_governed():
    """Live bug (2026-08-08): a "basemodel"-named attr CAN be `governed`
    (some hiding rule references it as a condition variable) while still
    never having its value resolved by anything -- §2f's own comment
    already establishes "governed" only means "some rule cares about this
    attr," not "a rule decided its value." An earlier version of this
    carve-out required `not in governed`, based on an incomplete manual
    trace that missed this; confirmed live the real attr WAS governed and
    still got silently skipped. Unconditional on governed status now,
    matching every other decision-key fragment/anchor in the same
    expression (none of them check governed status either)."""
    base_model = ConfigAttr(
        entity_id=1, variable_name="modelSelectionbaseModel_astro",
        display_label="Base Model", required=False, default_value="",
        select_type="single", options=_menu("H45TGU9PW8AN", "H55TGT9PW8AN"),
    )
    eng = CpqEngine()
    _, _, pending = eng.auto_fill(
        [base_model], {}, display_order={"modelSelectionbaseModel_astro": 0},
        governed_ids={1}, rule_governed_ids={1},
    )
    assert [a.variable_name for a in pending] == ["modelSelectionbaseModel_astro"]


def test_auto_fill_asks_same_unresolvable_attr_without_layout_map():
    """Regression: strictly additive — no display_order means zero change
    to today's "ask everything with options" behavior."""
    plain = ConfigAttr(
        entity_id=1, variable_name="someOptionalChoice_astro", display_label="Some Choice",
        required=False, default_value="", select_type="single", options=_menu("A", "B"),
    )
    eng = CpqEngine()
    _, _, pending = eng.auto_fill([plain], {})
    assert [a.variable_name for a in pending] == ["someOptionalChoice_astro"]


def test_auto_fill_still_asks_grid_selector_when_layout_loaded(monkeypatch):
    grid_selector = ConfigAttr(
        entity_id=1, variable_name="mountingTypeSelector_astro", display_label="Mounting Type",
        required=False, default_value="", select_type="multi", options=_menu("CLAMP", "BRACKET"),
    )
    eng = CpqEngine()
    monkeypatch.setattr(
        eng, "resolve_array_grid_links",
        lambda attrs: {"mountingTypeSelector_astro": {"clamp": "qty_astro"}},
    )
    _, _, pending = eng.auto_fill(
        [grid_selector], {}, display_order={"mountingTypeSelector_astro": 0},
        already_filled_multi={},
    )
    assert [a.variable_name for a in pending] == ["mountingTypeSelector_astro"]


# ── §2b: pending ask order ───────────────────────────────────────────────────

def test_order_pending_hardware_before_product_uses_display_order_when_supplied():
    hw = ConfigAttr(entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
                     required=False, default_value="", select_type="single", options=_menu("V1"))
    country = ConfigAttr(entity_id=2, variable_name="ultimateDestinationCountry", display_label="Country",
                          required=False, default_value="", select_type="single", options=_menu("US"))
    product = ConfigAttr(entity_id=3, variable_name="productSelectionProduct_all", display_label="Product",
                          required=False, default_value="", select_type="single", options=_menu("P1"))
    eng = CpqEngine()
    # Deliberately scrambled input order. Hardware already filled, so the
    # deferral rule (tested separately below) doesn't mask pure ordering.
    pending = [product, hw, country]
    display_order = {"ultimateDestinationCountry": 0, "hWVersion_astro": 1, "productSelectionProduct_all": 2}
    ordered = eng._order_pending_hardware_before_product(
        pending, {"hWVersion_astro": "V1"}, [hw, country, product], display_order=display_order,
    )
    assert [a.variable_name for a in ordered] == [
        "ultimateDestinationCountry", "hWVersion_astro", "productSelectionProduct_all",
    ]


def test_order_pending_still_defers_product_until_hardware_filled_with_display_order():
    hw = ConfigAttr(entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
                     required=False, default_value="", select_type="single", options=_menu("V1"))
    product = ConfigAttr(entity_id=3, variable_name="productSelectionProduct_all", display_label="Product",
                          required=False, default_value="", select_type="single", options=_menu("P1"))
    eng = CpqEngine()
    display_order = {"hWVersion_astro": 0, "productSelectionProduct_all": 1}
    ordered = eng._order_pending_hardware_before_product(
        [product, hw], {}, [hw, product], display_order=display_order,
    )
    # Hardware not yet filled -> Product must still be dropped from pending,
    # regardless of layout order (a correctness constraint, not a preference).
    assert [a.variable_name for a in ordered] == ["hWVersion_astro"]


# ── §2b: rule-conflict ranking by condition layout position ─────────────────

def _housing_conflict_attrs() -> list[ConfigAttr]:
    housing = ConfigAttr(entity_id=1, variable_name="modelSelectionHousing_astro",
                          display_label="Housing", required=False, default_value="",
                          select_type="single", options=_menu("BLACK", "GREEN"))
    base_model = ConfigAttr(entity_id=2, variable_name="modelSelectionbaseModel_astro",
                             display_label="Base Model", required=False, default_value="",
                             select_type="single", options=_menu("H45TGT9PW8AN"))
    return [housing, base_model]


def test_unresolvable_condition_always_ranks_lowest_regardless_of_layout_order():
    attrs = _housing_conflict_attrs()
    green = RecommendationRule(
        rule_name="Set Housing as GREEN", condition_attr_id=2, condition_value="H45TGT9PW8AN",
        target_attr_id=1, conditions=[(2, "H45TGT9PW8AN", "4")], recommended_value="GREEN",
    )
    black = RecommendationRule(
        rule_name="Associated rec rule for Hide Housing if not XE", condition_attr_id=0,
        condition_value="", target_attr_id=1, conditions=None, recommended_value="BLACK",
    )
    eng = CpqEngine()
    _, sorted_no_layout, _ = eng.rank_rules_by_specificity(attrs, [], [black, green], [])
    assert sorted_no_layout[-1].rule_name == "Set Housing as GREEN"

    display_order = {"modelSelectionbaseModel_astro": 184, "modelSelectionHousing_astro": 14}
    _, sorted_with_layout, _ = eng.rank_rules_by_specificity(
        attrs, [], [black, green], [], display_order=display_order,
    )
    assert sorted_with_layout[-1].rule_name == "Set Housing as GREEN"


def test_two_declarative_conditions_ranked_by_layout_position_not_depth():
    """Real counterexample this plan is built on: depth and layout order
    can disagree. Layout order must win when supplied."""
    target = ConfigAttr(entity_id=1, variable_name="target_astro", display_label="Target",
                         required=False, default_value="", select_type="single", options=_menu("A", "B"))
    cond_shallow = ConfigAttr(entity_id=2, variable_name="cond_shallow", display_label="Shallow",
                               required=False, default_value="", select_type="single", options=_menu("X"))
    cond_deep = ConfigAttr(entity_id=3, variable_name="cond_deep", display_label="Deep",
                            required=False, default_value="", select_type="single", options=_menu("Y"))
    attrs = [target, cond_shallow, cond_deep]

    # A real dependency edge: cond_shallow gates cond_deep, so cond_deep has
    # greater graph depth than cond_shallow.
    gate_rule = RecommendationRule(
        rule_name="gate cond_deep from cond_shallow", condition_attr_id=2, condition_value="X",
        target_attr_id=3, conditions=[(2, "X", "4")], recommended_value="Y",
    )
    rule_shallow = RecommendationRule(
        rule_name="rule_on_shallow", condition_attr_id=2, condition_value="X",
        target_attr_id=1, conditions=[(2, "X", "4")], recommended_value="A",
    )
    rule_deep = RecommendationRule(
        rule_name="rule_on_deep", condition_attr_id=3, condition_value="Y",
        target_attr_id=1, conditions=[(3, "Y", "4")], recommended_value="B",
    )
    eng = CpqEngine()

    _, depth_sorted, _ = eng.rank_rules_by_specificity(
        attrs, [], [rule_shallow, rule_deep, gate_rule], [],
    )
    assert depth_sorted[-1].rule_name == "rule_on_deep"  # depth-based: deep condition wins

    # Layout order disagrees with depth: cond_shallow sits LATER in the file.
    display_order = {"cond_deep": 5, "cond_shallow": 50}
    _, layout_sorted, _ = eng.rank_rules_by_specificity(
        attrs, [], [rule_shallow, rule_deep, gate_rule], [], display_order=display_order,
    )
    assert layout_sorted[-1].rule_name == "gate cond_deep from cond_shallow"


def test_constraint_rules_never_reordered_by_display_order():
    from aryx.cpq.state import ConstraintRule

    con = ConstraintRule(
        rule_name="con", condition_attr_id=1, condition_value="", target_attr_id=2,
        allowed_values=["A"],
    )
    eng = CpqEngine()
    attrs = _housing_conflict_attrs()
    _, _, con_sorted = eng.rank_rules_by_specificity(
        attrs, [], [], [con], display_order={"modelSelectionbaseModel_astro": 0},
    )
    assert con_sorted == [con]


def test_evaluate_rules_loop_accepts_rule_conflict_order_without_error():
    """Wiring smoke test: evaluate_rules_loop must not choke on the new
    kwarg and must produce identical filled state whether or not a layout
    map is supplied, for a catalog with no actual same-target conflict."""
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="V1", select_type="single", options=_menu("V1"))
    eng = CpqEngine()
    visible1, filled1, _disp1, _c1 = eng.evaluate_rules_loop(
        [attr], {}, {}, [], [], [],
    )
    visible2, filled2, _disp2, _c2 = eng.evaluate_rules_loop(
        [attr], {}, {}, [], [], [], rule_conflict_order={"a": 0},
    )
    assert filled1 == filled2 == {"a": "V1"}


# ── §2d: stop filling from default_value / unsatisfied first-available ─────

def test_single_select_default_value_skipped_when_layout_loaded():
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="V1", select_type="single", options=_menu("V1", "V2"))
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill([attr], {}, display_order={"a": 0})
    assert "a" not in filled
    assert pending == []  # not an anchor, not a grid selector -- §2c skip


def test_boolean_true_false_default_value_skipped_when_layout_loaded():
    """Real gap found live: a SEPARATE default_value branch exists
    specifically for boolean attrs whose default_value is the literal
    string "true"/"false" (_valid() otherwise treats bare "false" as a
    none-sentinel) -- this branch has its own independent default_value
    check and was missed on the first §2d pass."""
    attr = ConfigAttr(entity_id=1, variable_name="b", display_label="B",
                       required=False, default_value="false", select_type="boolean", options=[])
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill([attr], {}, display_order={"b": 0})
    assert "b" not in filled


def test_boolean_true_false_default_value_still_fills_without_layout_map():
    attr = ConfigAttr(entity_id=1, variable_name="b", display_label="B",
                       required=False, default_value="false", select_type="boolean", options=[])
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill([attr], {})
    assert filled.get("b") == "false"


def test_single_select_default_value_still_fills_without_layout_map():
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="V1", select_type="single", options=_menu("V1", "V2"))
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill([attr], {})
    assert filled.get("a") == "V1"


def test_multiselect_default_value_skipped_when_layout_loaded():
    attr = ConfigAttr(entity_id=1, variable_name="m", display_label="M",
                       required=False, default_value="V1", select_type="multi", options=_menu("V1", "V2"))
    eng = CpqEngine()
    _filled, _display, pending = eng.auto_fill(
        [attr], {}, already_filled_multi={}, display_order={"m": 0},
    )
    assert pending == []


def test_multiselect_first_available_skipped_when_layout_loaded():
    """No default_value, genuinely unconstrained -- today picks first
    option; under §2d (layout loaded) it must skip instead."""
    attr = ConfigAttr(entity_id=1, variable_name="m", display_label="M",
                       required=False, default_value="", select_type="multi", options=_menu("V1", "V2"))
    eng = CpqEngine()
    filled_multi = {}
    eng.auto_fill([attr], {}, already_filled_multi=filled_multi, display_order={"m": 0})
    assert "m" not in filled_multi


def test_multiselect_first_available_still_picked_without_layout_map():
    attr = ConfigAttr(entity_id=1, variable_name="m", display_label="M",
                       required=False, default_value="", select_type="multi", options=_menu("V1", "V2"))
    eng = CpqEngine()
    filled_multi = {}
    eng.auto_fill([attr], {}, already_filled_multi=filled_multi)
    assert filled_multi.get("m") == ["V1"]


def _rec_rule_fixture():
    target = ConfigAttr(entity_id=1, variable_name="target", display_label="Target",
                         required=False, default_value="", select_type="single", options=_menu("A", "B"))
    cond = ConfigAttr(entity_id=2, variable_name="cond", display_label="Cond",
                       required=False, default_value="", select_type="single", options=_menu("X"))
    rule = RecommendationRule(
        rule_name="Set target to B when cond is X", condition_attr_id=2, condition_value="X",
        target_attr_id=1, conditions=[(2, "X", "4")], recommended_value="B",
    )
    return target, cond, rule


def test_satisfied_recommendation_still_fills_under_2d():
    target, cond, rule = _rec_rule_fixture()
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [target, cond], {}, already_filled={"cond": "X"}, rec_rules=[rule],
        display_order={"target": 0, "cond": 1},
    )
    assert filled.get("target") == "B"


# ── §2e: rule attribution — record which specific rule fired ───────────────

def test_satisfied_recommendation_returns_rule_name(monkeypatch):
    target, cond, rule = _rec_rule_fixture()
    fired = []
    monkeypatch.setattr(
        engine_module.rule_trace, "record_fire",
        lambda **kwargs: fired.append(kwargs),
    )
    eng = CpqEngine()
    eng.auto_fill([target, cond], {}, already_filled={"cond": "X"}, rec_rules=[rule])
    rec_fires = [f for f in fired if f.get("attr") == "target"]
    assert rec_fires, "expected a trace entry for the satisfied recommendation"
    assert rec_fires[-1]["rule_type"] == "recommendation"
    assert rec_fires[-1]["rule_id"] == "Set target to B when cond is X"


def test_multiselect_satisfied_recommendation_traces_rule_name(monkeypatch):
    """The multi-select rec_match path never traced its fill at all before
    §2e -- a real, separate gap, closed the same way as single-select."""
    target = ConfigAttr(entity_id=1, variable_name="target", display_label="Target",
                         required=False, default_value="", select_type="multi", options=_menu("A", "B"))
    cond = ConfigAttr(entity_id=2, variable_name="cond", display_label="Cond",
                       required=False, default_value="", select_type="single", options=_menu("X"))
    rule = RecommendationRule(
        rule_name="Set target to B (multi) when cond is X", condition_attr_id=2, condition_value="X",
        target_attr_id=1, conditions=[(2, "X", "4")], recommended_value="B",
    )
    fired = []
    monkeypatch.setattr(
        engine_module.rule_trace, "record_fire",
        lambda **kwargs: fired.append(kwargs),
    )
    eng = CpqEngine()
    eng.auto_fill(
        [target, cond], {}, already_filled={"cond": "X"}, already_filled_multi={},
        rec_rules=[rule],
    )
    rec_fires = [f for f in fired if f.get("attr") == "target"]
    assert rec_fires, "expected a trace entry for the satisfied multi-select recommendation"
    assert rec_fires[-1]["rule_type"] == "recommendation"
    assert rec_fires[-1]["rule_id"] == "Set target to B (multi) when cond is X"


def test_unattributed_fill_still_uses_generic_tag(monkeypatch):
    """Regression: the governed_source path (source=="rule" but NOT via
    _satisfied_recommendation) has no single rule to name -- must keep
    using the old generic tag, not silently drop tracing."""
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=True, default_value="", select_type="single", options=_menu("V1"))
    fired = []
    monkeypatch.setattr(
        engine_module.rule_trace, "record_fire",
        lambda **kwargs: fired.append(kwargs),
    )
    eng = CpqEngine()
    eng.auto_fill([attr], {}, governed_ids={1})
    rec_fires = [f for f in fired if f.get("attr") == "a"]
    if rec_fires:  # only asserts shape when this path actually traced
        assert rec_fires[-1]["rule_type"] in ("auto_fill", "recommendation")


# ── §2f (superseded 2026-08-09): governed default-or-first blind-fill ──────
# now applies WITH a layout map loaded too, per explicit instruction --
# an attr with no rule-resolved default gets the first real eligible
# option instead of falling through to `pending`, same as without a
# layout map, just tagged with a distinct traceable source.

def test_governed_single_select_blind_fills_first_option_when_layout_loaded():
    """No recommendation satisfied, no default_value -- picks the first
    real eligible option (source="default_first_available") instead of
    skipping to `pending`, same as the no-layout-map case below."""
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="", select_type="single", options=_menu("V1", "V2"))
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1}, rule_governed_ids={1}, display_order={"a": 0},
    )
    assert filled.get("a") == "V1"
    assert _pending == []


def test_governed_single_select_still_blind_fills_without_layout_map():
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="", select_type="single", options=_menu("V1", "V2"))
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1}, rule_governed_ids={1},
    )
    assert filled.get("a") == "V1"


def test_governed_boolean_no_options_skipped_when_layout_loaded():
    attr = ConfigAttr(entity_id=1, variable_name="b", display_label="B",
                       required=False, default_value="", select_type="boolean", options=[])
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1}, rule_governed_ids={1}, display_order={"b": 0},
    )
    assert "b" not in filled


def test_governed_boolean_no_options_still_defaults_false_without_layout_map():
    attr = ConfigAttr(entity_id=1, variable_name="b", display_label="B",
                       required=False, default_value="", select_type="boolean", options=[])
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1}, rule_governed_ids={1},
    )
    assert filled.get("b") == "false"


def test_governed_satisfied_recommendation_still_wins_under_2f():
    """§2f only removes the BLIND fallback -- a genuinely satisfied
    recommendation on a governed attr must still fill it."""
    target, cond, rule = _rec_rule_fixture()
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [target, cond], {}, already_filled={"cond": "X"}, rec_rules=[rule],
        governed_ids={1}, rule_governed_ids={1}, display_order={"target": 0, "cond": 1},
    )
    assert filled.get("target") == "B"


# ── §2g: use default_value only when it survives an active constraint ──────

def test_default_value_used_when_it_survives_an_active_constraint():
    """Real case found live: APX NEXT Single Band's Frequency Bands attr
    has an active constraint narrowing to {UHF, VHF, 700/800 MHz} and no
    recommendation ever fires, but its catalog default_value ("700/800
    MHz") is one of the constrained options -- fill it.

    governed_ids={1} makes this attr reach the §2f/§2g branch at all --
    without it, is_governed is False and this code path never runs
    (the attr would instead hit the plain, ungoverned ask/skip logic)."""
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="700/800 MHz", select_type="single",
                       options=_menu("UHF", "VHF", "700/800 MHz"))
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, constrained_opts={1: ["UHF", "VHF", "700/800 MHz"]},
        display_order={"a": 0}, governed_ids={1},
    )
    assert filled.get("a") == "700/800 MHz"
    assert _pending == []


def test_default_value_not_used_when_it_does_not_survive_the_constraint():
    """The default_value exists but was excluded by the active constraint
    -- structurally distinct from "no default value at all" (this
    session's new instruction only covers the latter): §2g's own elif
    condition (`_valid(attr.default_value)` is True for "X") still claims
    this branch even though its internal match fails, so §2f's sibling
    elif never gets a chance to run here -- stays unfilled, not
    force-picked from the surviving constrained options."""
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="X", select_type="single",
                       options=_menu("UHF", "VHF", "X"))
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, constrained_opts={1: ["UHF", "VHF"]},
        display_order={"a": 0}, governed_ids={1},
    )
    assert "a" not in filled


def test_default_value_matches_constrained_option_case_insensitively():
    """Real bug found live: APX NEXT Single Band's Frequency Bands
    default_value ("700/800 MHZ") and the constraint's own allowed-values
    casing didn't agree character-for-character even though they meant
    the same option -- an exact-string match silently failed to fill it.
    Case-insensitive comparison fixes it without weakening anything else
    (every OTHER exact-match in this branch stays exact)."""
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="700/800 MHZ", select_type="single",
                       options=_menu("UHF", "VHF", "700/800 MHz"))
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, constrained_opts={1: ["UHF", "VHF", "700/800 MHz"]},
        display_order={"a": 0}, governed_ids={1},
    )
    assert filled.get("a") == "700/800 MHz"


def test_no_default_value_with_active_constraint_picks_first_constrained_option():
    """Constraint active, no default_value at all -- no §2g carve-out
    applies (nothing to survive the constraint), so §2f's first-eligible
    pick uses the first of the CONSTRAINED options, not the full menu."""
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="", select_type="single",
                       options=_menu("UHF", "VHF", "700/800 MHz"))
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, constrained_opts={1: ["UHF", "VHF", "700/800 MHz"]},
        display_order={"a": 0}, governed_ids={1},
    )
    assert filled.get("a") == "UHF"


def test_constraint_surviving_default_reaches_via_step3_without_layout_map():
    """§2g's own branch is gated the same way as §2f (only relevant when
    display_order is loaded) -- but note this attr's default_value is
    ALSO reachable via the separate, pre-existing, EARLIER "step 3" plain
    default_value assignment (§2d's own gate), which already fires
    whenever display_order is None, regardless of governed status. So
    without a layout map, this resolves to the default anyway -- via
    step 3, not §2g -- confirming §2g adds nothing new to today's
    behavior when no layout map is loaded."""
    attr = ConfigAttr(entity_id=1, variable_name="a", display_label="A",
                       required=False, default_value="700/800 MHz", select_type="single",
                       options=_menu("UHF", "VHF", "700/800 MHz"))
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, constrained_opts={1: ["UHF", "VHF", "700/800 MHz"]},
        governed_ids={1},
    )
    assert filled.get("a") == "700/800 MHz"
