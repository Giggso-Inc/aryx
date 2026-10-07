"""Base model narrowing, both directions (ws 1267, 2026-10-08: "I want a quote for APX 900 for US").

APX 900 has 10 base models and each is fully determined by its frequency band and keypad type (5 x 2). The engine used
to ask the customer for the base model (660 options), blind-pick the typed frequency and keypad, and ignore a typed
"700/800 MHz, Limited Keypad" (an option of several attributes, so the never-guess rule dropped it). With the flag on:
the separating attributes are read from the model's own rows, asked and never guessed; the base model waits for them
(the existing derivation then fills it); a known base model fills them; a typed phrase is hinted for the one owner the
rows use. Off: nothing changes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.cpq import base_model_narrowing as bmn
from aryx.cpq.auto_fill_stages import governance_flags, region_and_base_model, tier0_forward_fill
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.catalog_hints_product import product_selector_entries
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption

FREQ, KEYPAD = "modelSelectionFrequencyBands_astro", "modelSelectionKeypadType_astro"
DISPLAY, REGION = "modelSelectionDisplayType_astro", "modelSelectionRegion_astro"
BASE, MSL = "modelSelectionbaseModel_astro", "modelSelectionBaseModelMsl_astro"
ANT = "antennasFrequency_astro"
COUNTRY, PRODUCT = "ultimateDestinationCountry", "productSelectionProduct_all"

BANDS = {"K": "VHF", "Q": "UHF R1", "S": "UHF R2", "U": "700/800 MHZ", "W": "380-470 MHZ"}
KEYPADS = {"F": "FULL KEYPAD", "H": "LIMITED KEYPAD"}
# the 10 APX 900 base models
CODES = [f"H92{b}D{k}9PW{'6' if k == 'F' else '7'}AN" for b in BANDS for k in KEYPADS]


def _rows() -> list[dict]:
    rows = []
    for code in CODES:
        band, keypad = BANDS[code[3]], KEYPADS[code[5]]
        rows.append({"CPQModel": "APX900", "BaseModel": code, "attr1": FREQ, "val1": band,
                     "attr2": KEYPAD, "val2": keypad, "attr3": PRODUCT, "val3": "APX 900"})
        rows.append({"CPQModel": "APX900", "BaseModel": code, "attr1": COUNTRY, "val1": "US"})
        # several values per base model: not separating
        rows.append({"CPQModel": "APX900", "BaseModel": code, "attr1": COUNTRY, "val1": "CA"})
    rows.append({"CPQModel": "APX900", "BaseModel": CODES[0], "attr1": "modelSelectionHousing_astro", "val1": "BLACK"})
    rows.append({"CPQModel": "APX900", "BaseModel": "ALL", "attr1": "other_astro", "val1": "x"})
    return rows


def _attr(vn: str, pairs=(), hidden: bool = False) -> ConfigAttr:
    return ConfigAttr(
        entity_id=abs(hash(vn)) % 100_000, variable_name=vn, display_label=vn, required=False, default_value="",
        select_type="single", hidden=hidden,
        options=[MenuOption(item_value=iv, display_name=dn, order=i) for i, (iv, dn) in enumerate(pairs, start=1)])


def _attrs() -> list[ConfigAttr]:
    return [
        _attr(FREQ, [(v, v.title()) for v in BANDS.values()]),
        _attr(KEYPAD, [(v, v.title()) for v in KEYPADS.values()]),
        _attr(REGION, [("NA", "NA")], hidden=True),
        _attr(BASE, [(c, c) for c in CODES]),
        _attr(MSL, [("T7766A", "T7766A"), ("T8164A", "T8164A")]),
    ]


@pytest.fixture
def rows():
    """APX900 resolves to its own rows; other candidate models (`_BOM`) have none."""
    def model_rows(model, *a, **k):
        return (_rows(), set(CODES)) if model == "APX900" else ([], set())
    with patch.object(bmn, "resolved_model_first_candidates", return_value=["APX900", "APX900_BOM"]), \
            patch.object(bmn, "model_rows_and_base_models", side_effect=model_rows):
        yield


def _build(filled=None, sources=None, product="APX 900", attrs=None):
    return bmn.build_base_model_narrowing(attrs or _attrs(), filled or {}, sources, product, 1267, "p", {})


# --- which attributes separate the base models: read from the rows ------------------------------------------------
def test_only_attributes_every_base_model_holds_exactly_one_value_of_separate_them():
    disc = bmn.single_valued_discriminators(_rows(), set(CODES))
    assert set(disc) == {FREQ, KEYPAD}
    assert len(disc[FREQ]) == 10 and set(disc[FREQ].values()) == set(BANDS.values())
    # not separating: the country list is several values per base model, housing is on one base model, the product is
    # the same value everywhere
    assert COUNTRY not in disc and "modelSelectionHousing_astro" not in disc and PRODUCT not in disc


def test_the_five_bands_times_two_keypads_identify_every_base_model():
    disc = bmn.single_valued_discriminators(_rows(), set(CODES))
    pairs = {(disc[FREQ][c], disc[KEYPAD][c]) for c in CODES}
    assert len(pairs) == 10


# --- the bare "I want a quote for APX 900 for US" ------------------------------------------------------------------
def test_a_bare_quote_asks_the_separating_attributes_first(rows):
    narrowing = _build(filled={COUNTRY: "US", PRODUCT: "APX 900"})
    assert narrowing.ask_first == {FREQ, KEYPAD} and narrowing.forward == {}


def test_hidden_attributes_and_attributes_without_options_are_not_asked(rows):
    attrs = _attrs() + [_attr("modelSelectionOptionless_astro")]
    assert _build(attrs=attrs).ask_first == {FREQ, KEYPAD}          # REGION is hidden


def test_an_answered_attribute_is_not_asked_again(rows):
    assert _build(filled={FREQ: "VHF"}, sources={FREQ: "user"}).ask_first == {KEYPAD}


def test_a_guess_is_not_an_answer(rows):
    narrowing = _build(filled={FREQ: "VHF", KEYPAD: "FULL KEYPAD"},
                       sources={FREQ: "default_first_available", KEYPAD: "blind_pick_rule_governed"})
    assert narrowing.ask_first == {FREQ, KEYPAD}


def test_nothing_to_narrow_without_a_product_a_single_base_model_or_a_separating_attribute():
    with patch.object(bmn, "resolved_model_first_candidates", return_value=["ONE"]), \
            patch.object(bmn, "model_rows_and_base_models",
                         return_value=([{"CPQModel": "ONE", "BaseModel": "A", "attr1": FREQ, "val1": "VHF"}], {"A"})):
        assert _build() is None
    with patch.object(bmn, "resolved_model_first_candidates", return_value=["TWO"]), \
            patch.object(bmn, "model_rows_and_base_models",
                         return_value=([{"CPQModel": "TWO", "BaseModel": "A", "attr1": FREQ, "val1": "VHF"},
                                        {"CPQModel": "TWO", "BaseModel": "B", "attr1": FREQ, "val1": "VHF"}],
                                       {"A", "B"})):
        assert _build() is None                                      # the same value for both: nothing separates
    assert _build(product="") is None
    assert bmn.build_base_model_narrowing(_attrs(), {}, None, "APX 900", None, "p", {}) is None


# --- the other direction: a base model the customer has fills what it implies ------------------------------------
def test_a_known_base_model_fills_its_frequency_band_and_keypad(rows):
    narrowing = _build(filled={BASE: "h92udh9pw7an"}, sources={BASE: "user"})        # U = 700/800, H = limited
    assert narrowing.ask_first == frozenset()
    assert narrowing.forward == {FREQ: "700/800 MHZ", KEYPAD: "LIMITED KEYPAD"}


def test_a_forward_fill_never_overrides_an_answered_attribute(rows):
    narrowing = _build(filled={BASE: "H92UDH9PW7AN", FREQ: "VHF"}, sources={BASE: "user", FREQ: "user"})
    assert FREQ not in narrowing.forward and KEYPAD in narrowing.forward


def test_a_blind_filled_base_model_is_not_a_known_base_model(rows):
    narrowing = _build(filled={BASE: "H92UDH9PW7AN"}, sources={BASE: "default_first_available"})
    assert narrowing.forward == {} and narrowing.ask_first == {FREQ, KEYPAD}


# --- the stages -------------------------------------------------------------------------------------------------
def _scope(narrowing, display_order=None):
    return SimpleNamespace(
        base_model_narrowing=narrowing, display_order=display_order, skip_always_ask=None, governed=set(),
        rule_governed=set(), product_anchor_hint=None, workspace_id=1267, catalog_prefix="p", country="US",
        bm_region_allow_value=None)


def _state(attr: ConfigAttr) -> AttrResolution:
    return AttrResolution(vn=attr.variable_name, vn_flat=attr.variable_name.lower().replace("_", ""))


def _governance(attr, narrowing):
    engine = SimpleNamespace(_is_hardware_version_attr=lambda a: False,
                             _hardware_version_confirmed_not_applicable=lambda *a, **k: True)
    state = _state(attr)
    governance_flags.stage_governance_flags(engine, attr, SimpleNamespace(dt_cache={}), _scope(narrowing), state)
    return state


def test_a_separating_attribute_becomes_a_decision_attribute(rows):
    narrowing = _build()
    attrs = {a.variable_name: a for a in _attrs()}
    assert _governance(attrs[FREQ], narrowing).is_decision_attr is True        # asked, never guessed
    assert _governance(attrs[KEYPAD], narrowing).is_decision_attr is True
    assert _governance(_attr("somethingElse_astro", [("a", "A")]), narrowing).is_decision_attr is False


def test_with_the_flag_off_no_attribute_changes(rows):
    assert _governance(_attr(FREQ, [("VHF", "VHF")]), None).is_decision_attr is False


def _base_model_stage(attr, narrowing, display_order=None):
    state = _state(attr)
    ctx = SimpleNamespace(filled={}, dt_cache={}, sources={})
    with patch.object(region_and_base_model, "derived_base_model_option", return_value=None):
        region_and_base_model.stage_region_and_base_model(
            SimpleNamespace(), attr, ctx, _scope(narrowing, display_order), state)
    return state


def test_the_base_model_waits_while_a_separating_attribute_is_unanswered(rows):
    attrs = {a.variable_name: a for a in _attrs()}
    assert _base_model_stage(attrs[BASE], _build()).done is True


def test_the_base_model_is_asked_once_nothing_separating_is_left_unanswered(rows):
    attrs = {a.variable_name: a for a in _attrs()}
    # both answered: one base model is left, so there is nothing to narrow and the derivation fills it
    assert _build(filled={FREQ: "VHF", KEYPAD: "FULL KEYPAD"}, sources={FREQ: "user", KEYPAD: "user"}) is None
    # an explicit empty ask set also leaves the base model question alone
    assert _base_model_stage(attrs[BASE], bmn.BaseModelNarrowing(base_model_codes=frozenset(CODES))).done is False


def test_a_part_number_attribute_the_layout_hides_is_not_asked(rows):
    attrs = {a.variable_name: a for a in _attrs()}
    layout = {FREQ: 0, KEYPAD: 1}                                              # the layout places neither base model
    assert _base_model_stage(attrs[MSL], _build(), layout).done is True
    assert _base_model_stage(attrs[MSL], _build(), None).done is True           # with no layout it still waits


def test_a_part_number_attribute_the_layout_places_is_left_alone(rows):
    attrs = {a.variable_name: a for a in _attrs()}
    ask = _build()
    assert _base_model_stage(attrs[MSL], ask, {MSL: 3}).done is True            # still waits for the answers
    done = bmn.BaseModelNarrowing(base_model_codes=frozenset(CODES))
    assert _base_model_stage(attrs[MSL], done, {MSL: 3}).done is False          # placed, nothing left to wait for


def test_with_the_flag_off_the_base_model_stage_is_unchanged(rows):
    attrs = {a.variable_name: a for a in _attrs()}
    assert _base_model_stage(attrs[BASE], None).done is False


def _forward(attr, narrowing, value=None):
    state = _state(attr)
    state.value = value
    tier0_forward_fill.stage_forward_fill(SimpleNamespace(), attr, SimpleNamespace(), _scope(narrowing), state)
    return state


def test_the_forward_stage_fills_a_separating_attribute_from_the_known_base_model(rows):
    attrs = {a.variable_name: a for a in _attrs()}
    narrowing = _build(filled={BASE: "H92UDH9PW7AN"}, sources={BASE: "user"})
    state = _forward(attrs[FREQ], narrowing)
    assert (state.value, state.source) == ("700/800 MHZ", "derived_from_base_model")
    assert _forward(attrs[KEYPAD], narrowing).value == "LIMITED KEYPAD"
    assert _forward(attrs[BASE], narrowing).value is None                      # not a separating attribute


def test_the_forward_stage_keeps_a_value_already_set_and_does_nothing_with_the_flag_off(rows):
    attrs = {a.variable_name: a for a in _attrs()}
    narrowing = _build(filled={BASE: "H92UDH9PW7AN"}, sources={BASE: "user"})
    assert _forward(attrs[FREQ], narrowing, value="VHF").value == "VHF"
    assert _forward(attrs[FREQ], None).value is None


def test_the_forward_stage_fills_nothing_when_the_value_is_not_one_of_the_options(rows):
    attrs = {a.variable_name: a for a in _attrs()}
    narrowing = bmn.BaseModelNarrowing(forward={FREQ: "NOT A BAND"})
    assert _forward(attrs[FREQ], narrowing).value is None


# --- typed answers: the multi-owner tie-break --------------------------------------------------------------------
def _hint_attrs():
    return [
        _attr(FREQ, [("700/800 MHZ", "700/800 MHz"), ("VHF", "VHF")]),
        _attr(ANT, [("700/800 MHZ", "700/800 MHz")]),                                 # a second owner of the phrase
        _attr(KEYPAD, [("LIMITED KEYPAD", "Limited Keypad"), ("FULL KEYPAD", "Full Keypad")]),
        _attr(DISPLAY, [("LIMITED KEYPAD", "Limited Keypad")]),                       # a second owner of the phrase
    ]


def _hints(question, discriminators=None):
    return CpqEngine().extract_catalog_hints(question, _hint_attrs(), *((discriminators,) if discriminators else ()))[0]


DISC = {FREQ: frozenset(BANDS.values()), KEYPAD: frozenset(KEYPADS.values())}
TYPED = "I want a quote for APX 900 for US, 700/800 MHz, Limited Keypad"


def test_today_both_typed_phrases_are_dropped_by_the_never_guess_rule():
    assert _hints(TYPED) == {}


def test_with_the_models_discriminators_each_phrase_is_hinted_for_the_one_owner_its_rows_use():
    assert _hints(TYPED, DISC) == {FREQ: "700/800 MHZ", KEYPAD: "LIMITED KEYPAD"}


def test_the_tie_break_needs_exactly_one_qualifying_owner():
    entries = [(FREQ, "700/800 MHZ"), (ANT, "700/800 MHZ")]
    assert product_selector_entries(entries, {FREQ: frozenset({"700/800 MHZ"}), ANT: frozenset({"700/800 MHZ"})}) == []
    assert product_selector_entries(entries, {FREQ: frozenset({"700/800 MHZ"})}) == [(FREQ, "700/800 MHZ")]
    # the value is not one of that attribute's row values
    assert product_selector_entries(entries, {FREQ: frozenset({"VHF"})}) == []
    assert product_selector_entries(entries, None) == [] and product_selector_entries(entries, {}) == []


def test_a_single_owner_phrase_and_the_product_selector_rule_are_unchanged():
    one = [(FREQ, "VHF")]
    assert product_selector_entries(one, DISC) == one
    mixed = [(PRODUCT, "APX900"), (FREQ, "APX900")]
    assert product_selector_entries(mixed, {FREQ: frozenset({"APX900"})}) == [(PRODUCT, "APX900")]


def test_the_hint_for_the_step_is_built_only_with_the_flag_on(rows):
    from aryx.api.ask_turn_steps import ask_step2_catalog_hints as step2
    req = SimpleNamespace(workspace_id=1267)
    session = SimpleNamespace(filled={PRODUCT: "APX 900"}, product_name="APX 900")
    with patch.object(step2, "get_settings", return_value=SimpleNamespace(cpq_base_model_narrowing_enabled=False)):
        assert step2._model_discriminators(req, session, "p") is None
    with patch.object(step2, "get_settings", return_value=SimpleNamespace(cpq_base_model_narrowing_enabled=True)):
        assert step2._model_discriminators(req, session, "p") == DISC_FROM_ROWS


DISC_FROM_ROWS = {FREQ: frozenset(BANDS.values()), KEYPAD: frozenset(KEYPADS.values())}


def test_a_failure_while_reading_the_rows_leaves_hint_extraction_as_it_was():
    from aryx.api.ask_turn_steps import ask_step2_catalog_hints as step2
    req, session = SimpleNamespace(workspace_id=1267), SimpleNamespace(filled={}, product_name="APX 900")
    with patch.object(step2, "get_settings", return_value=SimpleNamespace(cpq_base_model_narrowing_enabled=True)), \
            patch.object(bmn, "resolved_model_first_candidates", side_effect=RuntimeError("boom")):
        assert step2._model_discriminators(req, session, "p") is None


def test_the_setup_builds_the_narrowing_only_with_the_flag_on(rows):
    from aryx.cpq.auto_fill import auto_fill_setup
    kwargs = dict(
        engine=SimpleNamespace(_attr_index=lambda attrs: {}), attrs=_attrs(), hints={},
        already_filled={PRODUCT: "APX 900"},
        constrained_opts=None, filled_source={}, governed_ids=set(), already_filled_multi={}, dropped_multi={},
        rule_governed_ids=set(), country="US", rec_rules=[], negated_vns=set(), skip_always_ask=set(), bml_eval=None,
        validation_rules=[], display_order=None, workspace_id=1267, catalog_prefix="p", _dt_cache={},
        hiding_rules=[], _default_fill_signatures=None, _signature_exclude_vns=None, grid_declined_vns=None)
    dt = SimpleNamespace(grid_selector_vns=set(), bm_region_allow_value=None, dt_governed_vns=set(),
                         missing_data_target_ids=set(), dt_never_governed_anywhere=lambda vn: False)
    with patch.object(auto_fill_setup, "compute_data_table_setup", return_value=dt), \
            patch.object(auto_fill_setup, "compute_conflicted_optional_ids", return_value=set()):
        for flag, expect_none in ((False, True), (True, False)):
            with patch.object(auto_fill_setup, "get_settings",
                              return_value=SimpleNamespace(cpq_base_model_narrowing_enabled=flag,
                                                           cpq_derive_base_model_enabled=True)):
                _ctx, scope = auto_fill_setup.build_fill_context_and_scope(**kwargs)
            assert (scope.base_model_narrowing is None) is expect_none
        assert scope.base_model_narrowing.ask_first == {FREQ, KEYPAD}


# --- end to end through the real auto_fill: the four flows, with the data layer faked only at the RDB ----------------
from aryx.config import get_settings                                                         # noqa: E402
from aryx.cpq.data_table import data_table_loader                                            # noqa: E402


class _FakeRdb:
    """Serves the APX 900 rows as one constraint-shaped table (the same fake-RDB pattern the auto_fill tests use)."""

    def __init__(self, table):
        self._table = table

    def list_ontology_types(self, workspace_id):
        return ["WhitelistTest"]

    def fetch_entities_by_type(self, workspace_id, type_suffix, catalog_prefix=""):
        return [(i, r) for i, r in enumerate(self._table, start=1)]

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        return [(i, r) for i, r in enumerate(self._table, start=1)]

    def fetch_all_entities_grouped_by_type(self, workspace_id):
        return {"WhitelistTest": [(i, r) for i, r in enumerate(self._table, start=1)]}


@pytest.fixture
def pipeline(monkeypatch):
    settings = get_settings()
    previous = (settings.cpq_base_model_narrowing_enabled, settings.cpq_derive_base_model_enabled)
    settings.cpq_derive_base_model_enabled = True
    data_table_loader._clear_tables_cache()
    monkeypatch.setattr(data_table_loader, "get_cpq_rdb", lambda: _FakeRdb(_rows()))
    yield settings
    settings.cpq_base_model_narrowing_enabled, settings.cpq_derive_base_model_enabled = previous
    data_table_loader._clear_tables_cache()


def _fill(narrowing: bool, filled=None, sources=None, hints=None):
    get_settings().cpq_base_model_narrowing_enabled = narrowing
    attrs = [_attr(PRODUCT, [("APX 900", "APX 900")]), _attr(FREQ, [(v, v.title()) for v in BANDS.values()]),
             _attr(KEYPAD, [(v, v.title()) for v in KEYPADS.values()]), _attr(BASE, [(c, c) for c in CODES])]
    for index, a in enumerate(attrs, start=1):
        a.entity_id = index
    source = {PRODUCT: "user", **(sources or {})}
    filled_out, _display, pending = CpqEngine().auto_fill(
        attrs, hints or {}, already_filled={PRODUCT: "APX 900", **(filled or {})}, filled_source=source,
        workspace_id=7)
    return filled_out, {a.variable_name for a in pending}, source


def test_end_to_end_a_bare_quote_asks_frequency_and_keypad_and_never_the_base_model(pipeline):
    filled, pending, _ = _fill(True)
    assert {FREQ, KEYPAD} <= pending and BASE not in pending
    assert FREQ not in filled and KEYPAD not in filled and BASE not in filled          # nothing guessed


def test_end_to_end_with_the_flag_off_the_base_model_is_asked_as_before(pipeline):
    filled, pending, _ = _fill(False)
    assert BASE in pending and BASE not in filled


def test_end_to_end_the_answers_fill_the_base_model_through_the_existing_derivation(pipeline):
    filled, pending, sources = _fill(True, filled={FREQ: "700/800 MHZ", KEYPAD: "LIMITED KEYPAD"},
                                     sources={FREQ: "user", KEYPAD: "user"})
    assert filled[BASE] == "H92UDH9PW7AN" and sources[BASE] == "derived_from_known_attrs"
    assert not ({FREQ, KEYPAD, BASE} & pending)


def test_end_to_end_a_typed_answer_that_became_a_hint_derives_the_base_model(pipeline):
    """"…700/800 MHz, Limited Keypad" typed in the first message: the tie-break hinted the two attributes."""
    filled, pending, sources = _fill(True, hints={FREQ: "700/800 MHZ", KEYPAD: "LIMITED KEYPAD"})
    assert filled[FREQ] == "700/800 MHZ" and filled[KEYPAD] == "LIMITED KEYPAD"
    assert filled[BASE] == "H92UDH9PW7AN" and not ({FREQ, KEYPAD, BASE} & pending)
    assert not sources[FREQ].startswith(("blind_pick", "default_first_available"))


def test_end_to_end_a_base_model_the_customer_gives_fills_frequency_and_keypad(pipeline):
    filled, pending, sources = _fill(True, filled={BASE: "H92KDF9PW6AN"}, sources={BASE: "user"})
    assert (filled[FREQ], filled[KEYPAD]) == ("VHF", "FULL KEYPAD")
    assert sources[FREQ] == sources[KEYPAD] == "derived_from_base_model" and not ({FREQ, KEYPAD, BASE} & pending)


def test_end_to_end_one_answer_still_leaves_the_other_to_ask_and_the_base_model_waiting(pipeline):
    filled, pending, _ = _fill(True, filled={FREQ: "VHF"}, sources={FREQ: "user"})
    assert KEYPAD in pending and BASE not in pending and BASE not in filled


# --- review of #473 -----------------------------------------------------------------------------------------------
GUESSES = ["blind_pick_rule_governed", "default_first_available"]


@pytest.mark.parametrize("source", GUESSES)
def test_end_to_end_an_earlier_guess_is_reopened_so_the_attribute_is_asked(pipeline, source):
    """A session that already holds a guessed frequency band and keypad (ws 1267 has `blind_pick_rule_governed` ones)
    must not end up with nothing asked and the base model waiting forever."""
    filled, pending, sources = _fill(True, filled={FREQ: "VHF", KEYPAD: "FULL KEYPAD"},
                                     sources={FREQ: source, KEYPAD: source})
    assert {FREQ, KEYPAD} <= pending and BASE not in pending
    assert FREQ not in filled and KEYPAD not in filled and BASE not in filled
    assert FREQ not in sources and KEYPAD not in sources                    # the guess is forgotten with its value


def test_end_to_end_only_the_guessed_attribute_is_reopened(pipeline):
    filled, pending, sources = _fill(True, filled={FREQ: "VHF", KEYPAD: "FULL KEYPAD"},
                                     sources={FREQ: "user", KEYPAD: "blind_pick_rule_governed"})
    assert filled[FREQ] == "VHF" and sources[FREQ] == "user"                # the answer is untouched
    assert KEYPAD in pending and KEYPAD not in filled and BASE not in pending


def test_end_to_end_a_guessed_base_model_is_reopened_for_the_forward_fill_only_when_answered(pipeline):
    filled, pending, _ = _fill(True, filled={BASE: "H92KDF9PW6AN"}, sources={BASE: "default_first_available"})
    assert BASE in pending or BASE not in filled          # a guessed base model is not a known one
    assert FREQ in pending and KEYPAD in pending


def test_reopening_forgets_only_guessed_values_of_the_attributes_the_narrowing_uses():
    narrowing = bmn.BaseModelNarrowing(ask_first=frozenset({FREQ}), forward={KEYPAD: "FULL KEYPAD"})
    filled = {FREQ: "VHF", KEYPAD: "FULL KEYPAD", BASE: "x", "other_astro": "v"}
    display = {FREQ: "Vhf", KEYPAD: "Full Keypad"}
    sources = {FREQ: "blind_pick_rule_governed", KEYPAD: "default_first_available", BASE: "blind_pick_x",
               "other_astro": "blind_pick_y"}
    reopened = bmn.reopen_guessed_values(narrowing, filled, display, sources)
    assert sorted(reopened) == sorted([FREQ, KEYPAD])
    assert filled == {BASE: "x", "other_astro": "v"} and display == {} and set(sources) == {BASE, "other_astro"}
    assert bmn.reopen_guessed_values(None, filled, display, sources) == []
    assert bmn.reopen_guessed_values(narrowing, filled, display, None) == []


def test_end_to_end_a_failure_building_the_narrowing_leaves_the_fill_as_it_was(pipeline):
    with patch.object(bmn, "resolved_model_first_candidates", side_effect=RuntimeError("db down")):
        filled, pending, _ = _fill(True)                                    # no exception
    assert BASE in pending and BASE not in filled                          # asked, exactly as with the flag off


def test_the_narrowing_needs_the_derivation_flag_too(pipeline):
    pipeline.cpq_derive_base_model_enabled = False
    filled, pending, _ = _fill(True)
    assert BASE in pending                                                  # not deferred: nothing would fill it
    pipeline.cpq_derive_base_model_enabled = True
    assert BASE not in _fill(True)[1]


def test_a_base_model_or_part_number_attribute_is_never_a_separating_attribute_to_ask():
    rows = [{"CPQModel": "M", "BaseModel": bm, "attr1": MSL, "val1": part, "attr2": FREQ, "val2": band}
            for bm, part, band in (("A", "T1", "VHF"), ("B", "T2", "UHF"))]
    attrs = [_attr(MSL, [("T1", "T1"), ("T2", "T2")]), _attr(FREQ, [("VHF", "VHF"), ("UHF", "UHF")])]
    with patch.object(bmn, "resolved_model_first_candidates", return_value=["M"]), \
            patch.object(bmn, "model_rows_and_base_models", return_value=(rows, {"A", "B"})):
        narrowing = bmn.build_base_model_narrowing(attrs, {}, None, "P", 1267, "p", {})
    assert narrowing.ask_first == {FREQ}                                    # MSL has one value per base model too


def test_separating_attributes_are_worked_out_over_the_base_models_the_answers_have_left():
    """The country excludes some base models; an attribute whose value is then already decided is not asked."""
    rows = []
    for bm, country, band, keypad in (("A", "US", "VHF", "FULL"), ("B", "US", "VHF", "LIMITED"),
                                       ("C", "CA", "UHF", "FULL"), ("D", "CA", "UHF", "LIMITED")):
        rows.append({"CPQModel": "M", "BaseModel": bm, "attr1": COUNTRY, "val1": country,
                     "attr2": FREQ, "val2": band, "attr3": KEYPAD, "val3": keypad})
    attrs = [_attr(FREQ, [("VHF", "VHF"), ("UHF", "UHF")]), _attr(KEYPAD, [("FULL", "FULL"), ("LIMITED", "LIMITED")])]

    def build(filled):
        with patch.object(bmn, "resolved_model_first_candidates", return_value=["M"]), \
                patch.object(bmn, "model_rows_and_base_models", return_value=(rows, {"A", "B", "C", "D"})):
            return bmn.build_base_model_narrowing(attrs, filled, {COUNTRY: "user"}, "P", 1267, "p", {})

    assert build({}).ask_first == {FREQ, KEYPAD}                            # nothing known: both separate the four
    us = build({COUNTRY: "US"})
    assert us.ask_first == {KEYPAD}                                         # US leaves A and B: only the keypad differs
    assert build({COUNTRY: "US", KEYPAD: "FULL"}) is None                    # one left: the derivation fills it


def test_a_guess_does_not_narrow_the_base_models_left():
    rows = [{"CPQModel": "M", "BaseModel": bm, "attr1": COUNTRY, "val1": c, "attr2": FREQ, "val2": b}
            for bm, c, b in (("A", "US", "VHF"), ("B", "CA", "UHF"))]
    attrs = [_attr(FREQ, [("VHF", "VHF"), ("UHF", "UHF")])]
    with patch.object(bmn, "resolved_model_first_candidates", return_value=["M"]), \
            patch.object(bmn, "model_rows_and_base_models", return_value=(rows, {"A", "B"})):
        guessed = bmn.build_base_model_narrowing(attrs, {COUNTRY: "US"}, {COUNTRY: "default_first_available"},
                                                 "P", 1267, "p", {})
    assert guessed.ask_first == {FREQ}


def test_the_option_matching_rule_is_shared_by_the_typed_tie_break_and_the_forward_fill():
    assert bmn.value_matches({"700/800 MHZ"}, "F700", "700/800 MHz") is True          # by display name
    assert bmn.value_matches({"700/800 MHZ"}, "700/800 mhz", "x") is True             # by item value
    assert bmn.value_matches({"700/800 MHZ"}, "F700", "VHF") is False
    attrs = [_attr(FREQ, [("F700", "700/800 MHz"), ("FV", "VHF")]), _attr(ANT, [("F700", "700/800 MHz")])]
    disc = {FREQ: frozenset({"700/800 MHZ"})}                       # the rows hold display names, not item values
    hints = CpqEngine().extract_catalog_hints("quote for APX 900, 700/800 MHz", attrs, disc)[0]
    assert hints == {FREQ: "F700"}
    state = _forward(attrs[0], bmn.BaseModelNarrowing(forward={FREQ: "700/800 MHZ"}))
    assert (state.value, state.source) == ("F700", "derived_from_base_model")
