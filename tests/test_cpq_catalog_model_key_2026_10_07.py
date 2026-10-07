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
    small = "\n".join(line for line in CHAIN.splitlines() if "GADGET1" not in line)    # one branch fewer, still a flat chain
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


# ---- review follow-ups: parser strictness, comment handling, cache timing, locking, wiring ----

def _chain(count: int, cond: str = "{P}==\"{n}\"") -> str:
    """A mapping chain with `count` single-product branches, generic names."""
    branches = "\n".join(
        f'  {"if" if i == 0 else "elif"} ({cond.format(P=PRODUCT, n=f"ITEM{i}")}) {{ selKey = "KEY{i}"; }}'
        for i in range(count))
    return f'if ({PRODUCT}<>"") {{\n{branches}\n}}\nrows = BMQL("SELECT a FROM t WHERE CPQModel=$selKey");'


def test_a_condition_with_another_test_is_not_a_plain_product_list():
    anded = _chain(6, cond='{P}=="{n}" AND region=="EU"')
    assert mkm.parse_model_key_chain(anded)[1] == {}
    negated = _chain(6, cond='{P}<>"{n}"')
    assert mkm.parse_model_key_chain(negated)[1] == {}
    assert len(mkm.parse_model_key_chain(_chain(6))[1]) == 6


def test_the_minimum_number_of_product_tests_is_exact():
    assert mkm.build_model_key_map({1: _chain(mkm._MIN_PRODUCT_TESTS - 1)}) == {}
    assert len(mkm.build_model_key_map({1: _chain(mkm._MIN_PRODUCT_TESTS)})) == mkm._MIN_PRODUCT_TESTS


def test_slashes_inside_a_string_do_not_hide_the_branches_after_them():
    script = _chain(6).replace('selKey = "KEY0";', 'selKey = "KEY0"; note = "http://x/y"; ')
    assert len(mkm.parse_model_key_chain(script)[1]) == 6


def test_a_block_comment_opener_inside_a_line_comment_does_not_swallow_code():
    script = "// see /* later\n" + _chain(6)
    assert len(mkm.parse_model_key_chain(script)[1]) == 6


class _Clock:
    now = 1000.0


@pytest.fixture
def clock(monkeypatch):
    _Clock.now = 1000.0
    monkeypatch.setattr(mkm.time, "monotonic", lambda: _Clock.now)
    return _Clock


def test_a_load_that_returned_no_scripts_is_retried_soon(setup, clock):
    setup.scripts = {}
    mkm.model_key_map(1)
    clock.now += 30
    mkm.model_key_map(1)
    assert setup.loads == 1                      # inside the retry window
    clock.now += 40
    mkm.model_key_map(1)
    assert setup.loads == 2                      # past 60 s


def test_scripts_without_a_mapping_chain_are_a_real_answer_kept_for_the_full_time(setup, clock):
    setup.scripts = {1: "x = 1;"}
    mkm.model_key_map(1)
    clock.now += 600
    mkm.model_key_map(1)
    assert setup.loads == 1
    clock.now += 400                             # past the 900 s the settings give
    mkm.model_key_map(1)
    assert setup.loads == 2


def test_a_loaded_map_expires_after_the_configured_time(setup, clock):
    mkm.model_key_map(1)
    clock.now += 899
    mkm.model_key_map(1)
    assert setup.loads == 1
    clock.now += 2
    mkm.model_key_map(1)
    assert setup.loads == 2


def test_a_slow_load_for_one_workspace_does_not_block_another(setup, monkeypatch):
    import threading
    started, release = threading.Event(), threading.Event()

    def load(workspace_id, _prefix):
        if workspace_id == 1:
            started.set()
            release.wait(timeout=10)
        return {101: CHAIN}

    monkeypatch.setattr(mkm, "_load_scripts", load)
    slow = threading.Thread(target=mkm.model_key_map, args=(1,), daemon=True)
    slow.start()
    assert started.wait(timeout=5)
    result: dict = {}
    fast = threading.Thread(target=lambda: result.update(mkm.model_key_map(2)), daemon=True)
    fast.start()
    fast.join(timeout=5)
    assert not fast.is_alive() and result                      # workspace 2 finished while workspace 1 was still loading
    release.set()
    slow.join(timeout=5)


def _candidates_setup(monkeypatch, enabled: bool):
    from aryx.cpq.data_table_bridge import candidates as cand
    calls = SimpleNamespace(punctuated=0)

    def punctuated(*_a, **_k):
        calls.punctuated += 1
        return ("X8/XE", "SIB")

    monkeypatch.setattr(cand, "get_settings", lambda: SimpleNamespace(
        cpq_catalog_model_key_enabled=enabled, data_table_candidates_empty_on_no_match_enabled=False,
        cpq_model_scope_lookups_enabled=False))
    monkeypatch.setattr(cand, "dt_resolve_product_cpq_models_from_rows", lambda *_a, **_k: ())
    monkeypatch.setattr(cand, "dt_resolve_product_cpq_model_family", lambda *_a, **_k: "FAM")
    monkeypatch.setattr(cand, "dt_resolve_sibling_models", lambda *_a, **_k: ("SIB",))
    monkeypatch.setattr(cand, "dt_resolve_punctuated_models", punctuated)
    monkeypatch.setattr(cand, "dt_front_mapped_key", lambda codes, *_a, **_k: codes)
    monkeypatch.setattr(cand, "_log_candidates", lambda *_a, **_k: None)
    return cand, calls


def test_punctuated_codes_are_not_added_while_the_setting_is_off(monkeypatch):
    cand, calls = _candidates_setup(monkeypatch, enabled=False)
    assert cand._resolve_cpq_model_candidates("P", 1, "", None) == ("SIB", "SIB_BOM", "FAM", "FAM_BOM")
    assert calls.punctuated == 0


def test_punctuated_codes_are_added_once_each_while_the_setting_is_on(monkeypatch):
    cand, calls = _candidates_setup(monkeypatch, enabled=True)
    assert cand._resolve_cpq_model_candidates("P", 1, "", None) == (
        "SIB", "SIB_BOM", "X8/XE", "X8/XE_BOM", "FAM", "FAM_BOM")        # SIB appears once although both lists have it
    assert calls.punctuated == 1


def test_the_candidate_resolver_puts_the_catalog_key_first_for_a_model_with_no_rows(setup, monkeypatch):
    cand, _calls = _candidates_setup(monkeypatch, enabled=True)
    monkeypatch.setattr(cand, "dt_front_mapped_key", mkm.front_mapped_key)          # the real one this time
    monkeypatch.setattr(cand, "dt_resolve_product_cpq_models_from_rows", lambda *_a, **_k: ("WIDGET1",))
    assert cand._resolve_cpq_model_candidates("WIDGET1", 1, "", None) == ("WIDGET1/X", "WIDGET1")
    setup.enabled = False
    assert cand._resolve_cpq_model_candidates("WIDGET1", 1, "", None) == ("WIDGET1",)


def test_a_map_that_fails_to_build_after_the_scripts_were_read_is_retried_soon(setup, clock, monkeypatch):
    calls = {"n": 0}

    def broken(_scripts):
        calls["n"] += 1
        raise ValueError("malformed script")

    monkeypatch.setattr(mkm, "build_model_key_map", broken)
    assert mkm.model_key_map(1) == {}
    clock.now += 30
    mkm.model_key_map(1)
    assert calls["n"] == 1                       # inside the 60 s retry window
    clock.now += 40
    mkm.model_key_map(1)
    assert calls["n"] == 2                       # retried after 60 s, not kept for the full 900 s


def test_a_request_gives_up_waiting_for_a_stuck_load_and_keeps_its_own_candidates(setup, monkeypatch):
    monkeypatch.setattr(mkm, "_LOAD_WAIT_SECONDS", 0.05)
    mkm._LOCKS[(1, "")] = lock = __import__("threading").Lock()
    lock.acquire()                               # another request is "loading" and never finishes
    try:
        assert mkm.model_key_map(1) == {}
        assert setup.loads == 0                  # this request did not load either
        assert mkm.front_mapped_key(("WIDGET1",), "WIDGET1", 1) == ("WIDGET1",)
    finally:
        lock.release()
    assert mkm.model_key_map(1)                  # once the lock is free the map loads normally


# ---- strict flat-chain rule (third review): the key must depend on the product alone ----

def _flat(wrap=("", ""), prefix="", suffix="", count=6):
    """A chain of `count` single-product branches with optional text around it, generic names."""
    branches = "\n".join(
        f'{"if" if i == 0 else "elif"} ({PRODUCT}=="ITEM{i}") {{ k = "KEY{i}"; }}' for i in range(count))
    return f'{prefix}{wrap[0]}\n{branches}\n{wrap[1]}{suffix}\nrows = Q("WHERE CPQModel=$k");'


def test_a_flat_chain_with_a_default_before_and_a_final_else_is_used():
    script = _flat(prefix="k = upper(_bm_model_variable_name);\n",
                   wrap=(f'if ({PRODUCT}<>"") {{', f' else {{ k = {PRODUCT}; }} }}'))
    assert len(mkm.parse_model_key_chain(script)[1]) == 6


def test_a_chain_nested_in_another_test_is_ignored():
    script = _flat(wrap=('if (region=="FED") {', '} else { k = "OTHER"; }'))
    assert mkm.parse_model_key_chain(script)[1] == {}


def test_a_later_plain_if_that_can_overwrite_the_chain_is_ignored():
    assert mkm.parse_model_key_chain(_flat(suffix=f'\nif ({PRODUCT}=="ITEM0") {{ k = "NEWKEY"; }}'))[1] == {}


def test_a_later_assignment_on_another_test_is_ignored():
    assert mkm.parse_model_key_chain(_flat(suffix='\nif (region=="NA") { k = "BASE/NA"; }'))[1] == {}


def test_a_later_fallback_that_only_fills_an_empty_key_is_allowed():
    script = _flat(suffix='\nif (k == "") { k = upper(_bm_model_variable_name); }')
    assert len(mkm.parse_model_key_chain(script)[1]) == 6


def test_an_assignment_inside_a_string_is_not_an_assignment():
    script = _flat(prefix='msg = "k = 5";\n')
    assert len(mkm.parse_model_key_chain(script)[1]) == 6
