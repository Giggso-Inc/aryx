"""Plan F8: models of series children that the series-mapping table does not offer
for the quote's country/region are dropped before attrSequence is read.
Synthetic names only.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.catalog_profile import PRODUCT_LITERAL
from aryx.cpq.data_table_bridge import series_narrowing as sn


def _series(child, *conds, series="S1"):
    row = {"seriesCPQModel": series, "childCPQModel": child}
    for i, (attr, op, val) in enumerate(conds, 1):
        row[f"attr{i}"], row[f"op{i}"], row[f"val{i}"] = attr, op, val
    return row


def _wl(model, child):
    return {"CPQModel": model, "BaseModel": "B", "attr1": "target", "val1": "x", "attr2": PRODUCT_LITERAL, "val2": child}


SERIES = [
    _series("CHILD_A", ("country_vn", "=", "AA,BB")),
    _series("CHILD_B", ("country_vn", "=", "BB")),
    _series("CHILD_B", ("region_vn", "=", "R9")),
    _series("CHILD_C", ("country_vn", "<>", "AA")),
    _series("CHILD_D", ("other_vn", "=", "1")),
]
WL = [_wl("MODEL_A", "CHILD_A"), _wl("MODEL_B", "CHILD_B"), _wl("MODEL_C", "CHILD_C"), _wl("MODEL_D", "CHILD_D"),
      _wl("MODEL_AB", "CHILD_A"), _wl("MODEL_AB", "CHILD_B")]


def _narrow(models, filled):
    with patch.object(sn, "_load_all_tables", return_value=(WL, [], [], SERIES, [])):
        return sn.narrow_models_by_series(models, filled, 1)


def test_a_child_not_offered_for_the_country_loses_its_model():
    got = _narrow(["MODEL_A", "MODEL_B", "MODEL_C", "MODEL_D"], {"country_vn": "AA", "region_vn": "R1"})
    assert got == ["MODEL_A", "MODEL_D"]
    # CHILD_B: country row False and region row False -> blocked; CHILD_C: country <> AA False -> blocked
    # CHILD_D: attribute not filled -> undecided -> kept


def test_a_row_that_is_true_or_undecided_keeps_the_child():
    assert _narrow(["MODEL_B"], {"country_vn": "BB"}) == ["MODEL_B"]                       # country row True
    assert _narrow(["MODEL_B", "MODEL_A"], {"country_vn": "AA"}) == ["MODEL_B", "MODEL_A"]  # region row undecided keeps CHILD_B
    assert _narrow(["MODEL_C"], {}) == ["MODEL_C"]                                          # nothing filled: nothing decided


def test_a_model_is_kept_while_any_of_its_children_is_offered():
    assert _narrow(["MODEL_AB"], {"country_vn": "AA", "region_vn": "R1"}) == ["MODEL_AB"]   # CHILD_A offered for AA


def test_the_result_never_becomes_empty_and_unmapped_models_stay():
    assert _narrow(["MODEL_C"], {"country_vn": "AA"}) == ["MODEL_C"]                        # all dropped -> unchanged
    assert _narrow(["MODEL_X", "MODEL_C"], {"country_vn": "AA"}) == ["MODEL_X"]             # MODEL_X has no series child
    assert _narrow(["MODEL_X"], {"country_vn": "AA"}) == ["MODEL_X"]


def test_unknown_operators_and_text_operators_are_handled():
    rows = [_series("CHILD_A", ("country_vn", ">>", "AA")), _series("CHILD_C", ("country_vn", "!=", "AA"))]
    with patch.object(sn, "_load_all_tables", return_value=(WL, [], [], rows, [])):
        assert sn.blocked_children({"country_vn": "AA"}, 1) == {"CHILD_C"}                  # unknown operator keeps CHILD_A
