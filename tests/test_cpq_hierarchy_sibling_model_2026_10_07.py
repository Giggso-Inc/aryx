"""ws 1267 (2026-10-07): "APX 900" resolved to the FLASHport series, which has no sequence rows, while the same
hierarchy has a blank-Product row for the plain model that does. The sibling model is added in front, only on proof."""
from __future__ import annotations

import pytest

from aryx.cpq.data_table import data_table_product as dtp
from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates


def _hier(model, product, display, family="aSTRO25"):
    row = {"productFamily": family, "cpqModelName": model, "displayCPQModel": display}
    if product:
        row["Product"] = product
    return row


HIERARCHY = [
    _hier("APX900", "", "APX 900"),
    _hier("APX3000", "", "APX 3000"),
    _hier("APXFLASHPORTSERIES", "APX900FLASHPORT", "APX 900 FLASHport"),
    _hier("APXFLASHPORTSERIES", "APX3000FLASHPORT", "APX 3000 FLASHport"),
    _hier("APXFLASHPORTSERIES", "APX3000XEFLASHPORT", "APX 3000XE FLASHport"),
    _hier("APXNEXT", "APXNEXTMULTI", "APX NEXT Multi"),
    _hier("APXNEXT", "", "APX NEXT"),
]


def _seq(*models):
    return [{"CPQModel": m, "AttrName": "x"} for m in models]


@pytest.fixture
def tables(monkeypatch):
    def install(sequence_models, hierarchy=HIERARCHY):
        monkeypatch.setattr(dtp, "_load_all_tables", lambda *a, **k: ([], _seq(*sequence_models), list(hierarchy), [], []))
    return install


def test_the_plain_model_with_sequence_rows_is_found_for_the_flashport_product(tables):
    tables(["APX900", "APX3000"])
    assert dtp.resolve_sibling_models_with_sequence_rows("APX900FLASHPORT", 1267) == ("APX900",)
    assert dtp.resolve_sibling_models_with_sequence_rows("apx3000flashport", 1267) == ("APX3000",)


def test_nothing_is_added_when_the_family_already_has_sequence_rows(tables):
    tables(["APXNEXT", "APX900"])
    assert dtp.resolve_sibling_models_with_sequence_rows("APXNEXTMULTI", 1267) == ()


def test_nothing_is_added_without_sequence_evidence_for_the_sibling(tables):
    tables(["SOMEOTHER"])
    assert dtp.resolve_sibling_models_with_sequence_rows("APX900FLASHPORT", 1267) == ()


def test_a_display_that_only_shares_characters_does_not_match(tables):
    tables(["APX3000", "APX900"])
    # "APX 900" is not a WORD prefix of "APX 9000 FLASHport", so the 900 model must not be picked for it
    rows = HIERARCHY + [_hier("APXFLASHPORTSERIES", "APX9000FLASHPORT", "APX 9000 FLASHport")]
    tables(["APX900"], rows)
    assert dtp.resolve_sibling_models_with_sequence_rows("APX9000FLASHPORT", 1267) == ()


def test_unknown_product_and_stale_models_are_ignored(tables):
    tables(["APX900-btaDelete-300725-075618-972"])
    assert dtp.resolve_sibling_models_with_sequence_rows("APX900FLASHPORT", 1267) == ()
    assert dtp.resolve_sibling_models_with_sequence_rows("NOPE", 1267) == ()


def test_candidates_put_the_sibling_in_front_of_the_family_and_keep_the_family(tables, monkeypatch):
    tables(["APX900"])
    monkeypatch.setattr("aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows", lambda *a, **k: ())
    got = _cpq_model_candidates("APX900FLASHPORT", 1267)
    assert got[:2] == ("APX900", "APX900_BOM")
    assert got[-2:] == ("APXFLASHPORTSERIES", "APXFLASHPORTSERIES_BOM")


def test_candidates_for_a_product_whose_family_has_data_are_unchanged(tables, monkeypatch):
    tables(["APXNEXT"])
    monkeypatch.setattr("aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows", lambda *a, **k: ())
    assert _cpq_model_candidates("APXNEXTMULTI", 1267) == ("APXNEXT", "APXNEXT_BOM")


# --- per-turn memo: the same arguments are resolved once per turn ---------------------------------------------
def test_repeated_calls_with_one_cache_resolve_once(tables, monkeypatch):
    tables(["APX900"])
    calls = []
    real = dtp.resolve_sibling_models_with_sequence_rows
    monkeypatch.setattr("aryx.cpq.data_table_bridge.candidates.dt_resolve_sibling_models",
                        lambda *a, **k: calls.append(a) or real(*a, **k))
    monkeypatch.setattr("aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows", lambda *a, **k: ())
    cache: dict = {}
    first = [_cpq_model_candidates("APX900FLASHPORT", 1267, "", cache) for _ in range(50)]
    assert len(calls) == 1 and all(r == first[0] for r in first)
    _cpq_model_candidates("APX3000FLASHPORT", 1267, "", cache)
    assert len(calls) == 2                                   # a different product is a different key


def test_without_a_cache_or_bound_turn_nothing_is_remembered(tables, monkeypatch):
    tables(["APX900"])
    calls = []
    real = dtp.resolve_sibling_models_with_sequence_rows
    monkeypatch.setattr("aryx.cpq.data_table_bridge.candidates.dt_resolve_sibling_models",
                        lambda *a, **k: calls.append(a) or real(*a, **k))
    monkeypatch.setattr("aryx.cpq.data_table_bridge.candidates.dt_resolve_product_cpq_models_from_rows", lambda *a, **k: ())
    _cpq_model_candidates("APX900FLASHPORT", 1267)
    _cpq_model_candidates("APX900FLASHPORT", 1267)
    assert len(calls) == 2
