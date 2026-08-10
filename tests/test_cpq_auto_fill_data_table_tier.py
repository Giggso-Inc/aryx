"""End-to-end: CpqEngine.auto_fill uses the real ingested Data Table source
(data_table_resolver.py, via aryx_entity) as a fallback when a governed
attribute has no active constraint resolving a value -- real data wins over
"ask the user", but only when it resolves to exactly one confirmed answer
(docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md §11-§12).
"""
from __future__ import annotations

import pytest

from aryx.cpq import data_table_resolver
from aryx.cpq.engine import CpqEngine, _cpq_model_candidates
from aryx.cpq.state import ConfigAttr, MenuOption


@pytest.fixture(autouse=True)
def _clear_tables_cache():
    """_load_all_tables now has a module-level, process-lifetime (short-TTL)
    cache keyed by (workspace_id, catalog_prefix) -- clear it between tests
    so one test's fake/monkeypatched rows can never leak into another via
    that shared cache."""
    data_table_resolver._clear_tables_cache()
    yield
    data_table_resolver._clear_tables_cache()


class _FakeRdb:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def list_ontology_types(self, workspace_id):
        return list(self._tables.keys())

    def fetch_entities_by_type(self, workspace_id, type_suffix, catalog_prefix=""):
        rows = self._tables.get(type_suffix, [])
        return [(i, r) for i, r in enumerate(rows, start=1)]

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        rows = self._tables.get(ontology_type, [])
        return [(i, r) for i, r in enumerate(rows, start=1)]


def _patch_rdb(monkeypatch, tables: dict[str, list[dict]]) -> None:
    from aryx.cpq import data_table_resolver
    monkeypatch.setattr(data_table_resolver, "get_cpq_rdb", lambda: _FakeRdb(tables))


def _base_model_attr():
    return ConfigAttr(
        entity_id=1, variable_name="modelSelectionbaseModel_astro",
        display_label="Base Model", required=True, default_value="",
        options=[], select_type="single",
    )


def _product_attr():
    return ConfigAttr(
        entity_id=2, variable_name="productSelectionProduct_all",
        display_label="Product", required=True, default_value="",
        options=[], select_type="single",
    )


def _wireless_carrier_attr():
    return ConfigAttr(
        entity_id=3, variable_name="wirelessCarrier_astro",
        display_label="Wireless Carrier", required=False, default_value="",
        select_type="single",
        options=[
            MenuOption(item_value="VERIZON", display_name="Verizon"),
            MenuOption(item_value="ATT/FIRSTNET", display_name="ATT/FirstNet (provided by Motorola)"),
        ],
    )


def _keypad_type_attr():
    return ConfigAttr(
        entity_id=4, variable_name="modelSelectionKeypadType_astro",
        display_label="Keypad Type", required=False, default_value="",
        select_type="single",
        options=[
            MenuOption(item_value="NO KEYPAD", display_name="No Keypad"),
            MenuOption(item_value="TOUCH SCREEN", display_name="Touch Screen"),
        ],
    )


def test_auto_fill_uses_the_data_table_when_no_active_constraint_resolved_a_value(monkeypatch):
    """modelSelectionKeypadType_astro is governed (some rule targets it) but
    has no active constraint narrowing it (constrained_opts has no entry
    for its entity_id) -- exactly the state a script-based rule that fails
    to resolve leaves auto_fill in. Real Data Table data resolves to
    exactly ONE value (TOUCH SCREEN) -- proves auto_fill reaches and uses
    the real resolver in that gap, when workspace_id is supplied."""
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "modelSelectionKeypadType_astro", "val1": "TOUCH SCREEN"},
        ],
    })
    eng = CpqEngine()
    attrs = [_base_model_attr(), _product_attr(), _keypad_type_attr()]
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }

    filled_out, display_out, _ = eng.auto_fill(
        attrs, hints={}, already_filled=filled,
        governed_ids={4}, rule_governed_ids={4},
        workspace_id=7,
    )

    assert filled_out.get("modelSelectionKeypadType_astro") == "TOUCH SCREEN"
    assert display_out.get("modelSelectionKeypadType_astro") == "Touch Screen"


def test_blind_first_pick_gets_overridden_once_data_table_narrows_to_a_real_answer(monkeypatch):
    """Live bug (2026-08-09): §2f's blind first-by-order fallback picks a
    value with nothing to justify it on a pass where the Data Table lookup
    doesn't yet narrow to exactly one answer (e.g. base model/product not
    filled yet on an early pass). Confirmed live: extendRangeTo762764MHz_
    astro got locked to "YES" this way even though the real ingested
    constraint data unambiguously says "NO" once given the full context --
    nothing ever re-checked it. This is the single-select counterpart of
    the multi-select `_option_value_owners`... `default_first_available`
    re-validation the sibling branch already has.

    Reproduced here as two sequential auto_fill calls (pass 1 with no
    Data Table coverage at all -- forces the blind pick; pass 2 with real
    Data Table rows now available, resolving to a DIFFERENT single value)
    -- the second call must override the first pass's wrong guess, not
    keep it forever just because it's already `filled`."""
    keypad = _keypad_type_attr()

    base_context = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }

    # Pass 1: no Data Table rows ingested at all -- _resolve_via_data_tables
    # returns None, so §2f's blind first-by-order picks the FIRST menu
    # option ("NO KEYPAD", per _keypad_type_attr's own option order).
    _patch_rdb(monkeypatch, {"WhitelistTest": []})
    eng = CpqEngine()
    filled_pass1, display_pass1, _ = eng.auto_fill(
        [keypad], hints={}, already_filled=dict(base_context),
        governed_ids={4}, rule_governed_ids={4},
        workspace_id=7, display_order={"modelSelectionKeypadType_astro": 0},
    )
    assert filled_pass1.get("modelSelectionKeypadType_astro") == "NO KEYPAD"

    sources_pass1 = {"modelSelectionKeypadType_astro": "default_first_available"}

    # Pass 2: real Data Table coverage now exists and unambiguously
    # resolves to "TOUCH SCREEN" -- a DIFFERENT value than pass 1's guess.
    # Module-level TTL cache (data_table_resolver._TABLES_CACHE) would
    # otherwise still return pass 1's empty scan within the same 30s
    # window that two real, separate /ask turns wouldn't hit in practice.
    data_table_resolver._clear_tables_cache()
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "modelSelectionKeypadType_astro", "val1": "TOUCH SCREEN"},
        ],
    })
    already_filled_pass2 = {**base_context, **filled_pass1}
    filled_pass2, display_pass2, _ = eng.auto_fill(
        [keypad], hints={},
        already_filled=already_filled_pass2, filled_source=sources_pass1,
        governed_ids={4}, rule_governed_ids={4},
        workspace_id=7, display_order={"modelSelectionKeypadType_astro": 0},
    )
    assert filled_pass2.get("modelSelectionKeypadType_astro") == "TOUCH SCREEN"
    assert display_pass2.get("modelSelectionKeypadType_astro") == "Touch Screen"


def test_ambiguous_data_table_result_does_not_change_the_pre_existing_fallback(monkeypatch):
    """2 real options for wirelessCarrier_astro -- genuinely ambiguous, so
    the new data_table tier itself contributes nothing (returns None, per
    _resolve_via_data_tables' own "2+ values -> None" rule). This is NOT the
    same as auto_fill leaving the attr pending: a governed attr with no
    active constraint already falls through to this codebase's pre-existing
    "first eligible item_value by order" behavior (documented in auto_fill's
    own docstring, step 6) -- unchanged by this new tier, since the tier
    only ever contributes a value when it has exactly one confident answer.
    Proves the new tier doesn't override that baseline when it can't help."""
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "wirelessCarrier_astro", "val1": "ATT/FIRSTNET",
             "attr2": "ultimateDestinationCountry", "val2": "US"},
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "wirelessCarrier_astro", "val1": "VERIZON",
             "attr2": "ultimateDestinationCountry", "val2": "US"},
        ],
    })
    eng = CpqEngine()
    attrs = [_base_model_attr(), _product_attr(), _wireless_carrier_attr()]
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
        "ultimateDestinationCountry": "US",
    }

    filled_out, _, _ = eng.auto_fill(
        attrs, hints={}, already_filled=filled,
        governed_ids={3}, rule_governed_ids={3},
        workspace_id=7,
    )

    # Pre-existing blind first-by-order fallback (options=[VERIZON, ATT/
    # FIRSTNET]) persists -- the new tier correctly declined to answer
    # (2 real options is ambiguous) and did not suppress this old behavior.
    assert filled_out.get("wirelessCarrier_astro") == "VERIZON"


def test_auto_fill_falls_back_to_ingested_cpqmodelhierarchy_for_an_unmapped_product(monkeypatch):
    """"APX NEXT XE MULTI" has no entry in engine.py's hand-verified
    _PRODUCT_TO_CPQ_MODEL override map -- proves the ingested
    CPQModelHierarchy-shaped table resolves the real CPQModel family code
    dynamically instead of falling back to the static APXNEXT/APXNEXT_BOM
    guess, and that family code is then actually used to find the real
    whitelist row."""
    _patch_rdb(monkeypatch, {
        "CpqModelHierarchy": [
            {"cpqModelName": "APXNEXT", "Product": "APX NEXT XE MULTI"},
        ],
        "WhitelistTest": [
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "modelSelectionKeypadType_astro", "val1": "TOUCH SCREEN"},
        ],
    })
    eng = CpqEngine()
    attrs = [_base_model_attr(), _product_attr(), _keypad_type_attr()]
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT XE MULTI",
    }

    filled_out, _, _ = eng.auto_fill(
        attrs, hints={}, already_filled=filled,
        governed_ids={4}, rule_governed_ids={4},
        workspace_id=7,
    )

    assert filled_out.get("modelSelectionKeypadType_astro") == "TOUCH SCREEN"


def test_without_workspace_id_the_data_table_tier_is_a_no_op(monkeypatch):
    """Omitting workspace_id (every existing caller, unchanged) must behave
    identically to before this tier existed: no DB call, and the same
    pre-existing blind first-by-order fallback as any other governed,
    unconstrained attr -- proves this is purely additive, opt-in behavior."""
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXT", "BaseModel": "H55TGT9PW8AN",
             "attr1": "modelSelectionKeypadType_astro", "val1": "TOUCH SCREEN"},
        ],
    })
    eng = CpqEngine()
    attrs = [_base_model_attr(), _product_attr(), _keypad_type_attr()]
    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8AN",
        "productSelectionProduct_all": "APX NEXT MULTI",
    }

    filled_out, _, _ = eng.auto_fill(
        attrs, hints={}, already_filled=filled,
        governed_ids={4}, rule_governed_ids={4},
        # workspace_id omitted entirely
    )

    # Pre-existing blind first-by-order fallback (options=[NO KEYPAD, TOUCH
    # SCREEN]) -- the real TOUCH SCREEN answer sitting in the (unreachable
    # without workspace_id) Data Table is never consulted.
    assert filled_out.get("modelSelectionKeypadType_astro") == "NO KEYPAD"


def _product_select_attr():
    return ConfigAttr(
        entity_id=5, variable_name="productSelectionProduct_all",
        display_label="Product", required=True, default_value="",
        select_type="single",
        options=[
            MenuOption(item_value="APX NEXT ALL BAND", display_name="APX NEXT All Band"),
            MenuOption(item_value="APX NEXT INTL FED",
                       display_name="APX NEXT International (Federal)"),
        ],
    )


_SERIES_MAPPING_ROWS = [
    {"key": "APXNEXT-11", "op1": "=", "op2": "=", "val1": "AP", "val2": "KR",
     "attr1": "modelSelectionRegion_astro", "attr2": "ultimateDestinationCountry",
     "childCPQModel": "APX NEXT INTL FED", "seriesCPQModel": "APXNEXT",
     "childCPQModelLabel": "APX NEXT™ International (Federal)"},
    {"key": "APXNEXT-29", "op1": "=", "op2": "=", "val1": "NA", "val2": "US",
     "attr1": "modelSelectionRegion_astro", "attr2": "ultimateDestinationCountry",
     "childCPQModel": "APX NEXT INTL FED_future", "seriesCPQModel": "APXNEXT",
     "childCPQModelLabel": "APX NEXT™ International (Federal)"},
]


def test_series_mapping_exclusion_hides_the_not_yet_real_us_variant(monkeypatch):
    """Live bug (2026-08-08): with country=US, "APX NEXT International
    (Federal)" still showed up as a selectable Product option even though
    Oracle CPQ's own Seriesmodelsmapping Data Table maps it to a distinct
    "_future"-suffixed code for the US market -- not a real, orderable
    model here. _apply_series_mapping_exclusions must remove it from
    constrained_opts once region+country are known."""
    _patch_rdb(monkeypatch, {"Seriesmodelsmapping": _SERIES_MAPPING_ROWS})
    attrs = [_product_select_attr()]
    filled = {
        "modelSelectionRegion_astro": "NA",
        "ultimateDestinationCountry": "US",
    }
    constrained_opts: dict[int, list[str]] = {}

    CpqEngine._apply_series_mapping_exclusions(
        attrs, constrained_opts, filled, workspace_id=7,
    )

    assert constrained_opts.get(5) == ["APX NEXT ALL BAND"]


def test_series_mapping_exclusion_keeps_the_option_for_a_region_where_it_is_real(monkeypatch):
    """Same product, region/country where the real row's childCPQModel
    matches the option's own item_value -- genuinely valid, must not be
    excluded."""
    _patch_rdb(monkeypatch, {"Seriesmodelsmapping": _SERIES_MAPPING_ROWS})
    attrs = [_product_select_attr()]
    filled = {
        "modelSelectionRegion_astro": "AP",
        "ultimateDestinationCountry": "KR",
    }
    constrained_opts: dict[int, list[str]] = {}

    CpqEngine._apply_series_mapping_exclusions(
        attrs, constrained_opts, filled, workspace_id=7,
    )

    assert constrained_opts == {}


def test_series_mapping_exclusion_is_a_no_op_without_workspace_id(monkeypatch):
    """Omitting workspace_id (every existing caller, unchanged) must not
    touch constrained_opts at all."""
    _patch_rdb(monkeypatch, {"Seriesmodelsmapping": _SERIES_MAPPING_ROWS})
    attrs = [_product_select_attr()]
    filled = {
        "modelSelectionRegion_astro": "NA",
        "ultimateDestinationCountry": "US",
    }
    constrained_opts: dict[int, list[str]] = {}

    CpqEngine._apply_series_mapping_exclusions(
        attrs, constrained_opts, filled, workspace_id=None,
    )

    assert constrained_opts == {}


# --- _suppress_ungoverned_attrs / _invalidate_inconsistent_paired_values
# (2026-08-08) -- confirmed live: with a base model whose real attrSequence
# rows list wirelessCarrier_astro (required) and carry ZERO rows for
# carrierSelectionMultiSelect_astro, auto_fill still filled BOTH -- two
# mutually-exclusive carrier mechanisms populated at once, because nothing
# ever asked the real data which one actually applies.

_BASE_MODEL = "H45TGU9PW8AN"
_PRODUCT = "APX NEXT SINGLE BAND"  # maps to APXNEXTSINGLE via the override map


def _wireless_carrier_attr2():
    return ConfigAttr(
        entity_id=10, variable_name="wirelessCarrier_astro",
        display_label="Wireless Carrier", required=True, default_value="",
        select_type="single", options=[],
    )


def _carrier_multiselect_attr():
    return ConfigAttr(
        entity_id=11, variable_name="carrierSelectionMultiSelect_astro",
        display_label="Carrier Selection", required=False, default_value="",
        select_type="multi", options=[],
    )


def test_cpq_model_candidates_appends_the_base_model_discovered_variant(monkeypatch):
    """Base model H45TGU9PW8AN's real rows are keyed to APXNEXTXNSINGLE --
    a MORE SPECIFIC variant than "APX NEXT SINGLE BAND"'s own real-row-
    resolved primary (APXNEXTSINGLE). Both must be tried, primary first."""
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ANY",
             "attr1": "productSelectionProduct_all", "val1": _PRODUCT},
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": _BASE_MODEL,
             "attr1": "wirelessCarrier_astro", "val1": "ATT/FIRSTNET"},
        ],
    })
    cands = _cpq_model_candidates(_PRODUCT, workspace_id=7, base_model=_BASE_MODEL)
    assert cands[0] == "APXNEXTSINGLE"  # primary, unchanged priority
    assert "APXNEXTXNSINGLE" in cands  # supplementary, discovered from real data


def test_cpq_model_candidates_unchanged_without_base_model(monkeypatch):
    """Omitting base_model (every existing caller) is a complete no-op."""
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ANY",
             "attr1": "productSelectionProduct_all", "val1": _PRODUCT},
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": _BASE_MODEL,
             "attr1": "wirelessCarrier_astro", "val1": "ATT/FIRSTNET"},
        ],
    })
    cands = _cpq_model_candidates(_PRODUCT, workspace_id=7)
    assert cands == ("APXNEXTSINGLE",)


def test_suppress_ungoverned_attrs_drops_the_sibling_with_no_real_coverage(monkeypatch):
    _patch_rdb(monkeypatch, {
        "AttrSeqTest": [
            # Real base-model-exact coverage for wirelessCarrier_astro only --
            # carrierSelectionMultiSelect_astro never appears for this base
            # model at all, even though the type has real rows for it.
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": _BASE_MODEL,
             "AttrName": "wirelessCarrier_astro", "Seq": "355", "optionOrReqFlag": "R"},
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": _BASE_MODEL,
             "AttrName": "carrierSelectionMultiSelect_astro", "Seq": "356", "optionOrReqFlag": "O"},
        ],
    })
    attrs = [_wireless_carrier_attr2(), _carrier_multiselect_attr()]
    filled = {
        "modelSelectionbaseModel_astro": _BASE_MODEL,
        "productSelectionProduct_all": _PRODUCT,
    }
    visible, suppressed = CpqEngine._suppress_ungoverned_attrs(attrs, filled, workspace_id=7)
    assert suppressed == set()
    assert {a.variable_name for a in visible} == {
        "wirelessCarrier_astro", "carrierSelectionMultiSelect_astro",
    }


def test_suppress_ungoverned_attrs_drops_the_attr_excluded_here_but_tracked_elsewhere(monkeypatch):
    """carrierSelectionMultiSelect_astro has NO attrSequence row at THIS
    base model, but the catalog does track it via a row at a DIFFERENT
    base model of the same CPQModel -- a confident "not part of THIS base
    model" exclusion, not silence. Confidently suppressed."""
    _patch_rdb(monkeypatch, {
        "AttrSeqTest": [
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": _BASE_MODEL,
             "AttrName": "wirelessCarrier_astro", "Seq": "355", "optionOrReqFlag": "R"},
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": "SOME-OTHER-BASE-MODEL",
             "AttrName": "carrierSelectionMultiSelect_astro", "Seq": "356", "optionOrReqFlag": "O"},
        ],
    })
    attrs = [_wireless_carrier_attr2(), _carrier_multiselect_attr()]
    filled = {
        "modelSelectionbaseModel_astro": _BASE_MODEL,
        "productSelectionProduct_all": _PRODUCT,
    }
    visible, suppressed = CpqEngine._suppress_ungoverned_attrs(attrs, filled, workspace_id=7)
    assert suppressed == {"carrierSelectionMultiSelect_astro"}
    assert {a.variable_name for a in visible} == {"wirelessCarrier_astro"}


def test_suppress_ungoverned_attrs_asks_instead_of_dropping_when_never_governed_anywhere(monkeypatch):
    """carrierSelectionMultiSelect_astro has NO attrSequence row at this
    base model AND none at any other base model of this CPQModel either --
    confirmed live 2026-08-09: the catalog never tracks it via sequence
    rows at all for most CPQModels. That's silence, not a confident
    exclusion -- must stay visible/askable, not be silently dropped."""
    _patch_rdb(monkeypatch, {
        "AttrSeqTest": [
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": _BASE_MODEL,
             "AttrName": "wirelessCarrier_astro", "Seq": "355", "optionOrReqFlag": "R"},
        ],
    })
    attrs = [_wireless_carrier_attr2(), _carrier_multiselect_attr()]
    filled = {
        "modelSelectionbaseModel_astro": _BASE_MODEL,
        "productSelectionProduct_all": _PRODUCT,
    }
    visible, suppressed = CpqEngine._suppress_ungoverned_attrs(attrs, filled, workspace_id=7)
    assert suppressed == set()
    assert {a.variable_name for a in visible} == {
        "wirelessCarrier_astro", "carrierSelectionMultiSelect_astro",
    }


def test_suppress_ungoverned_attrs_never_touches_decision_attrs(monkeypatch):
    """productSelectionProduct_all/modelSelectionbaseModel_astro must never
    be suppressed even with zero attrSequence coverage for them."""
    _patch_rdb(monkeypatch, {
        "AttrSeqTest": [
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": _BASE_MODEL,
             "AttrName": "wirelessCarrier_astro", "Seq": "355", "optionOrReqFlag": "R"},
        ],
    })
    attrs = [_wireless_carrier_attr2(), _product_select_attr()]
    filled = {
        "modelSelectionbaseModel_astro": _BASE_MODEL,
        "productSelectionProduct_all": _PRODUCT,
    }
    visible, suppressed = CpqEngine._suppress_ungoverned_attrs(attrs, filled, workspace_id=7)
    assert "productSelectionProduct_all" not in suppressed
    assert {a.variable_name for a in visible} == {
        "wirelessCarrier_astro", "productSelectionProduct_all",
    }


def test_suppress_ungoverned_attrs_is_a_no_op_without_workspace_id(monkeypatch):
    _patch_rdb(monkeypatch, {
        "AttrSeqTest": [
            {"CPQModel": "APXNEXTXNSINGLE", "BaseModel": _BASE_MODEL,
             "AttrName": "wirelessCarrier_astro", "Seq": "355", "optionOrReqFlag": "R"},
        ],
    })
    attrs = [_wireless_carrier_attr2(), _carrier_multiselect_attr()]
    filled = {
        "modelSelectionbaseModel_astro": _BASE_MODEL,
        "productSelectionProduct_all": _PRODUCT,
    }
    visible, suppressed = CpqEngine._suppress_ungoverned_attrs(attrs, filled, workspace_id=None)
    assert suppressed == set()
    assert visible == attrs


def test_invalidate_inconsistent_paired_values_clears_a_real_contradiction(monkeypatch):
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ANY",
             "attr1": "productSelectionProduct_all", "val1": _PRODUCT},
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ALL",
             "attr1": "modelSelectionFrequencyBands_astro", "val1": "VHF",
             "attr2": "modelSelectionFrequencyBandPlus_astro", "val2": "700/800 MHZ +"},
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ALL",
             "attr1": "modelSelectionFrequencyBands_astro", "val1": "700/800 MHZ",
             "attr2": "modelSelectionFrequencyBandPlus_astro", "val2": "VHF +"},
        ],
    })
    filled = {
        "modelSelectionbaseModel_astro": _BASE_MODEL,
        "productSelectionProduct_all": _PRODUCT,
        "modelSelectionFrequencyBands_astro": "700/800 MHZ",
        "modelSelectionFrequencyBandPlus_astro": "700/800 MHZ +",
    }
    sources = {
        "modelSelectionFrequencyBands_astro": "data_table",
        "modelSelectionFrequencyBandPlus_astro": "data_table",
    }
    invalid = CpqEngine._invalidate_inconsistent_paired_values(
        filled, sources, workspace_id=7,
    )
    assert invalid == {
        "modelSelectionFrequencyBands_astro", "modelSelectionFrequencyBandPlus_astro",
    }


def test_invalidate_inconsistent_paired_values_never_clears_a_user_answer(monkeypatch):
    """A real customer's own answer is never second-guessed -- only the
    OTHER, non-user side of the contradiction is cleared, so it can
    re-resolve against the user's real (now-fixed) value on the next
    pass."""
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ANY",
             "attr1": "productSelectionProduct_all", "val1": _PRODUCT},
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ALL",
             "attr1": "modelSelectionFrequencyBands_astro", "val1": "VHF",
             "attr2": "modelSelectionFrequencyBandPlus_astro", "val2": "700/800 MHZ +"},
        ],
    })
    filled = {
        "modelSelectionbaseModel_astro": _BASE_MODEL,
        "productSelectionProduct_all": _PRODUCT,
        "modelSelectionFrequencyBands_astro": "700/800 MHZ",
        "modelSelectionFrequencyBandPlus_astro": "700/800 MHZ +",
    }
    sources = {
        "modelSelectionFrequencyBands_astro": "user",
        "modelSelectionFrequencyBandPlus_astro": "data_table",
    }
    invalid = CpqEngine._invalidate_inconsistent_paired_values(
        filled, sources, workspace_id=7,
    )
    assert invalid == {"modelSelectionFrequencyBandPlus_astro"}


def test_auto_fill_asks_an_attr_never_governed_anywhere_even_with_layout_loaded(monkeypatch):
    """Confirmed live 2026-08-09: modelSelectionFrequencyBandMsl_astro
    survives `_suppress_ungoverned_attrs` (no attrSequence row anywhere
    mentions it for this CPQModel) but was still silently dropped by
    auto_fill's OWN separate §2c "not a decision attr -> skip" gate when a
    layout map is loaded -- the same silent-drop bug one layer deeper.
    Must reach `pending` instead of vanishing."""
    _patch_rdb(monkeypatch, {
        "AttrSeqTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": _BASE_MODEL,
             "AttrName": "wirelessCarrier_astro", "Seq": "355", "optionOrReqFlag": "R"},
        ],
    })
    eng = CpqEngine()
    freq_band = ConfigAttr(
        entity_id=20, variable_name="modelSelectionFrequencyBandMsl_astro",
        display_label="Additional Frequency Bands", required=False, default_value="",
        select_type="single",
        options=[
            MenuOption(item_value="UHF", display_name="UHF"),
            MenuOption(item_value="VHF", display_name="VHF"),
        ],
    )
    attrs = [_base_model_attr(), _product_attr(), freq_band]
    filled = {
        "modelSelectionbaseModel_astro": _BASE_MODEL,
        "productSelectionProduct_all": _PRODUCT,
    }
    _, _, pending = eng.auto_fill(
        attrs, hints={}, already_filled=filled,
        display_order={"modelSelectionbaseModel_astro": 0, "productSelectionProduct_all": 1},
        workspace_id=7,
    )
    assert "modelSelectionFrequencyBandMsl_astro" in {a.variable_name for a in pending}


def test_auto_fill_still_skips_an_attr_confidently_excluded_from_this_base_model(monkeypatch):
    """Unchanged control: an attr the sequence table DOES track (for a
    DIFFERENT base model of the same CPQModel) but confidently excludes
    from this one must still be skipped, not treated as unknown."""
    _patch_rdb(monkeypatch, {
        "AttrSeqTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": _BASE_MODEL,
             "AttrName": "wirelessCarrier_astro", "Seq": "355", "optionOrReqFlag": "R"},
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "SOME-OTHER-BASE-MODEL",
             "AttrName": "modelSelectionFrequencyBandMsl_astro", "Seq": "356", "optionOrReqFlag": "O"},
        ],
    })
    eng = CpqEngine()
    freq_band = ConfigAttr(
        entity_id=20, variable_name="modelSelectionFrequencyBandMsl_astro",
        display_label="Additional Frequency Bands", required=False, default_value="",
        select_type="single",
        options=[
            MenuOption(item_value="UHF", display_name="UHF"),
            MenuOption(item_value="VHF", display_name="VHF"),
        ],
    )
    attrs = [_base_model_attr(), _product_attr(), freq_band]
    filled = {
        "modelSelectionbaseModel_astro": _BASE_MODEL,
        "productSelectionProduct_all": _PRODUCT,
    }
    _, _, pending = eng.auto_fill(
        attrs, hints={}, already_filled=filled,
        display_order={"modelSelectionbaseModel_astro": 0, "productSelectionProduct_all": 1},
        workspace_id=7,
    )
    assert "modelSelectionFrequencyBandMsl_astro" not in {a.variable_name for a in pending}


def test_auto_fill_does_not_inherit_always_ask_from_an_unrelated_sibling_base_model_share(monkeypatch):
    """Live bug (2026-08-09): a base model can be genuinely shared between
    the customer's actual product (here, "APX NEXT Single Band" ->
    APXNEXTSINGLE) and a totally unrelated regional/federal sibling CPQModel
    (confirmed live: H55TGT9RW8AN has ZERO real Data Table coverage under
    APXNEXTSINGLE, but 120 attrs' worth of coverage under APXNEXTINTL/
    APXNEXTINTLFED). The `_dt_governed_vns` "always ask, never blind-guess"
    gate was built from the FULL base-model-widened candidate set
    (_cpq_model_candidates(..., base_model=...)), so it inherited that
    unrelated sibling's entire governance scope -- forcing real questions
    (Configuration Type, System Key, ...) the actual Single Band data never
    requires. The gate must be built from the PRIMARY, product-derived
    candidates only; the base-model-widened set stays reserved for value
    RESOLUTION (the keypad-type XN-variant fix), never for this gate."""
    _patch_rdb(monkeypatch, {
        # APXNEXTINTL is an unrelated sibling that happens to share this
        # exact base model -- real coverage for it, none for APXNEXTSINGLE
        # (the primary candidate "APX NEXT SINGLE BAND" actually maps to).
        "AttrSeqTest": [
            {"CPQModel": "APXNEXTINTL", "BaseModel": "H99SHARED",
             "AttrName": "softwareBundlesBundleType_astro", "Seq": "10", "optionOrReqFlag": "O"},
        ],
    })
    eng = CpqEngine()
    config_type = ConfigAttr(
        entity_id=5, variable_name="softwareBundlesBundleType_astro",
        display_label="Configuration Type", required=False, default_value="",
        select_type="single",
        options=[
            MenuOption(item_value="STANDARD BUNDLE", display_name="Software Bundles"),
            MenuOption(item_value="CUSTOM", display_name="Custom Configuration"),
        ],
    )
    attrs = [_base_model_attr(), _product_attr(), config_type]
    filled = {
        "modelSelectionbaseModel_astro": "H99SHARED",
        "productSelectionProduct_all": _PRODUCT,
    }
    result_filled, display_filled, pending = eng.auto_fill(
        attrs, hints={}, already_filled=filled,
        governed_ids={5}, rule_governed_ids=set(),
        display_order={
            "modelSelectionbaseModel_astro": 0,
            "productSelectionProduct_all": 1,
            "softwareBundlesBundleType_astro": 2,
        },
        workspace_id=7,
    )
    assert "softwareBundlesBundleType_astro" not in {a.variable_name for a in pending}
    assert result_filled.get("softwareBundlesBundleType_astro") == "STANDARD BUNDLE"


def test_auto_fill_resolves_base_model_from_region_allow_default(monkeypatch):
    """Confirmed live (2026-08-10): a NewCountryRegMapping-shaped ("region_
    rule") Data Table gives a real, per-(CPQModel, region) ALLOW default
    for modelSelectionbaseModel_astro -- APXNEXTSINGLE/NA resolves to
    exactly one value. Base Model's own unconditional always-ask override
    must defer to this real resolved value instead of forcing a question,
    when it resolves -- not a blind guess, a real ingested default (the
    same answer Oracle CPQ's own "Set Base Model" rules compute at runtime
    against a table this repo never has ingested)."""
    _patch_rdb(monkeypatch, {
        "WhitelistTest": [
            {"CPQModel": "APXNEXTSINGLE", "BaseModel": "ANY",
             "attr1": "productSelectionProduct_all", "val1": _PRODUCT},
        ],
        "NewCountryRegMappingTest": [
            {"key": "APXNEXTSINGLE-1", "model": "APXNEXTSINGLE",
             "value": "H45TGT9PW8AN", "region": "NA", "ruleType": "ALLOW",
             "attribute": "modelSelectionbaseModel_astro"},
        ],
    })
    eng = CpqEngine()
    base_model_attr = ConfigAttr(
        entity_id=1, variable_name="modelSelectionbaseModel_astro",
        display_label="Base Model", required=True, default_value="",
        select_type="single",
        options=[
            MenuOption(item_value="H45TGU9PW8AN", display_name="H45TGU9PW8AN"),
            MenuOption(item_value="H45TGT9PW8AN", display_name="H45TGT9PW8AN"),
            MenuOption(item_value="H55TGT9PW8AN", display_name="H55TGT9PW8AN"),
        ],
    )
    filled = {
        "productSelectionProduct_all": _PRODUCT,
        "ultimateDestinationCountry": "US",
    }
    result_filled, display_filled, pending = eng.auto_fill(
        [base_model_attr], hints={}, already_filled=filled,
        display_order={"modelSelectionbaseModel_astro": 0},
        workspace_id=7,
    )
    assert result_filled.get("modelSelectionbaseModel_astro") == "H45TGT9PW8AN"
    assert "modelSelectionbaseModel_astro" not in {a.variable_name for a in pending}


def test_auto_fill_still_asks_base_model_when_no_region_allow_value_resolves(monkeypatch):
    """Control: with no region-rule coverage at all, Base Model keeps its
    unconditional always-ask behavior unchanged -- confirms this fix is
    additive, not a relaxation of the existing anchor for every other
    base model / catalog without this data."""
    _patch_rdb(monkeypatch, {"WhitelistTest": []})
    eng = CpqEngine()
    base_model_attr = ConfigAttr(
        entity_id=1, variable_name="modelSelectionbaseModel_astro",
        display_label="Base Model", required=True, default_value="",
        select_type="single",
        options=[
            MenuOption(item_value="H45TGU9PW8AN", display_name="H45TGU9PW8AN"),
            MenuOption(item_value="H45TGT9PW8AN", display_name="H45TGT9PW8AN"),
        ],
    )
    filled = {
        "productSelectionProduct_all": _PRODUCT,
        "ultimateDestinationCountry": "US",
    }
    result_filled, display_filled, pending = eng.auto_fill(
        [base_model_attr], hints={}, already_filled=filled,
        display_order={"modelSelectionbaseModel_astro": 0},
        workspace_id=7,
    )
    assert "modelSelectionbaseModel_astro" not in result_filled
    assert "modelSelectionbaseModel_astro" in {a.variable_name for a in pending}
