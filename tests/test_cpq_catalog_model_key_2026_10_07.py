"""The catalog's own product -> model key script is read once and offered ahead of a model with no rule rows.

ws 1267 (2026-10-07): the rows of the plain APX 8000 radio are filed under the key "APX8000/XE" while Aryx resolves
"APX8000", so rule lookups found nothing and fell to sibling models. Names below are generic shapes, never real
catalog codes, so the tests cover the rule and not one catalog's values.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aryx.cpq import resolved_model_candidates as rmc
from aryx.cpq.data_table import model_key_map as mkm

PRODUCT = "productSelectionProduct_all"
CHAIN = f'''
/** Mapping for the data tables. Added a condition for Series Model WIDGET1/X Series
if({PRODUCT}=="DECOY") {{ selKey = "NOT/USED"; }} */
selKey = upper(_bm_model_variable_name);
if ({PRODUCT}<>"") {{
  if ({PRODUCT}=="WIDGET1" OR {PRODUCT}=="WIDGET1X") {{ selKey = "WIDGET1/X"; }}
  elif ({PRODUCT}=="WIDGET2" OR {PRODUCT}=="WIDGET2H") {{ selKey = "WIDGET2/H"; }}
  elif ({PRODUCT}=="GADGET1") {{ selKey = "GADGET1/LI"; }}
  elif ({PRODUCT}=="GADGET2") {{ selKey = "GADGET2/LI"; }}
  elif ({PRODUCT}=="GADGET3") {{ selKey = "GADGET3/LI"; }}
  else {{ selKey = {PRODUCT}; }}
}}
rows = BMQL("SELECT distinct AttrName FROM attrSequence WHERE CPQModel=$selKey AND BaseModel in $baseModelList");
'''


@pytest.fixture(autouse=True)
def _clean():
    mkm.clear_model_key_map_cache()
    yield
    mkm.clear_model_key_map_cache()


@pytest.fixture
def setup(monkeypatch):
    """Patch settings, the script loader and the set of models that have sequence rows."""
    state = SimpleNamespace(enabled=True, scripts={101: CHAIN}, rows=frozenset({"WIDGET1/X", "WIDGET2/H", "OTHER"}),
                            loads=0)

    def load(*_a, **_k):
        state.loads += 1
        return state.scripts

    monkeypatch.setattr(mkm, "get_settings", lambda: SimpleNamespace(
        cpq_catalog_model_key_enabled=state.enabled, cpq_catalog_model_key_ttl_seconds=900))
    monkeypatch.setattr(mkm, "_load_scripts", load)
    monkeypatch.setattr(mkm, "_sequence_model_codes", lambda *_a, **_k: state.rows)
    return state


def test_chain_is_parsed_with_the_variable_the_script_gives_the_data_tables():
    var, mapping = mkm.parse_model_key_chain(CHAIN)
    assert var == "selKey"
    assert mapping == {"WIDGET1": "WIDGET1/X", "WIDGET1X": "WIDGET1/X", "WIDGET2": "WIDGET2/H",
                       "WIDGET2H": "WIDGET2/H", "GADGET1": "GADGET1/LI", "GADGET2": "GADGET2/LI",
                       "GADGET3": "GADGET3/LI"}          # the commented-out decoy is not read


def test_a_script_with_too_few_product_tests_is_not_a_mapping():
    small = CHAIN.replace('elif (' + PRODUCT + '=="GADGET1")', 'elif (x=="y")')
    assert mkm.build_model_key_map({1: 'if (' + PRODUCT + '=="A") { m = "K"; } rows = Q("CPQModel=$m");'}) == {}
    assert mkm.build_model_key_map({1: small})["WIDGET1"] == "WIDGET1/X"


def test_the_highest_function_id_wins_a_disagreement():
    older = CHAIN.replace('"WIDGET1/X"', '"OLD/KEY"')
    assert mkm.build_model_key_map({5: older, 9: CHAIN})["WIDGET1"] == "WIDGET1/X"
    assert mkm.build_model_key_map({5: CHAIN, 9: older})["WIDGET1"] == "OLD/KEY"


def test_the_key_is_offered_for_a_product_with_an_entry_and_rows(setup):
    assert mkm.mapped_model_key("WIDGET1", 1) == "WIDGET1/X"
    assert mkm.mapped_model_key(" widget1x ", 1) == "WIDGET1/X"        # case and spaces do not matter


def test_the_setting_off_offers_nothing_and_reads_nothing(setup):
    setup.enabled = False
    assert mkm.mapped_model_key("WIDGET1", 1) is None
    assert setup.loads == 0


def test_a_key_without_rows_is_never_offered(setup):
    assert mkm.mapped_model_key("GADGET1", 1) is None                   # the catalog names GADGET1/LI, no rows there


def test_a_product_with_no_entry_gets_nothing(setup):
    assert mkm.mapped_model_key("UNMAPPED", 1) is None


def test_the_first_candidate_with_rows_is_left_alone(setup):
    assert mkm.front_mapped_key(("OTHER", "WIDGET1"), "WIDGET1", 1) == ("OTHER", "WIDGET1")


def test_the_key_goes_first_when_the_first_candidate_has_no_rows(setup):
    assert mkm.front_mapped_key(("WIDGET1", "OTHER"), "WIDGET1", 1) == ("WIDGET1/X", "WIDGET1", "OTHER")


def test_a_key_already_in_the_list_moves_to_the_front_without_duplicating(setup):
    assert mkm.front_mapped_key(("WIDGET1", "WIDGET1/X"), "WIDGET1", 1) == ("WIDGET1/X", "WIDGET1")


def test_no_workspace_or_no_entry_leaves_the_candidates_unchanged(setup):
    assert mkm.front_mapped_key(("WIDGET1",), "WIDGET1", None) == ("WIDGET1",)
    assert mkm.front_mapped_key(("UNMAPPED",), "UNMAPPED", 1) == ("UNMAPPED",)


def test_changing_the_product_gets_the_new_products_key(setup):
    assert mkm.front_mapped_key(("WIDGET1",), "WIDGET1", 1)[0] == "WIDGET1/X"
    assert mkm.front_mapped_key(("WIDGET2",), "WIDGET2", 1)[0] == "WIDGET2/H"      # not the first product's key


def test_the_scripts_are_read_once_not_per_call(setup):
    for _ in range(5):
        mkm.mapped_model_key("WIDGET1", 1)
    assert setup.loads == 1


def test_a_failed_load_degrades_to_no_key_instead_of_raising(setup, monkeypatch):
    def boom(*_a, **_k):
        raise TimeoutError("db")
    monkeypatch.setattr(mkm, "_load_scripts", boom)
    assert mkm.front_mapped_key(("WIDGET1",), "WIDGET1", 1) == ("WIDGET1",)


def test_the_resolved_model_does_not_stay_ahead_of_the_catalog_key(setup, monkeypatch):
    turn = SimpleNamespace(resolution=SimpleNamespace(resolved=True, chosen=SimpleNamespace(cpq_model="WIDGET1")))
    monkeypatch.setattr(rmc._model_resolution, "get_turn", lambda: turn)
    monkeypatch.setattr(rmc, "_cpq_model_candidates", lambda *_a, **_k: ("WIDGET1/X",))
    assert rmc.resolved_model_first_candidates("WIDGET1", 1, "", None) == ["WIDGET1/X", "WIDGET1"]
    setup.enabled = False
    assert rmc.resolved_model_first_candidates("WIDGET1", 1, "", None) == ["WIDGET1", "WIDGET1/X"]
