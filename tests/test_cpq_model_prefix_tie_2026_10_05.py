"""F16: ask which model when the wording names a model that is a strict prefix
of another sellable model on a different catalog node. Synthetic, made-up
catalog; flag `cpq_model_prefix_tie_ask_enabled` default off.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aryx.api.ask_model_leaf import ask_model_leaf_bind as bind
from aryx.api.ask_model_leaf import ask_model_leaf_resolve as resolve
from aryx.cpq import model_resolution as mr
from aryx.cpq import model_resolution_catalog as mrc
from aryx.cpq import model_resolution_tie as tie


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


class FakeRdb:
    def __init__(self, rows):
        self.rows = rows

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        return [(i, r) for i, r in enumerate(self.rows.get(ontology_type, []))]


def _row(cpq, disp, var, bm="B1"):
    return {"cpqModel": cpq, "displayModel": disp, "CPQModelVariableName": var, "baseModel": bm}


def _rdb() -> FakeRdb:
    return FakeRdb({
        "XBmCatalog": [
            {"id": "1", "name": "root", "parent_id": "-1"},
            {"id": "2", "name": "alpha100", "parent_id": "1"},
            {"id": "3", "name": "alpha100plus", "parent_id": "1"},
            {"id": "4", "name": "beta200", "parent_id": "1"},
            {"id": "5", "name": "gamma300", "parent_id": "1"},
            {"id": "6", "name": "gamma300up", "parent_id": "1"},
            {"id": "7", "name": "delta400", "parent_id": "1"},
            {"id": "8", "name": "delta400old", "parent_id": "1"},
        ],
        "Basemodeltoconfig": [
            _row("ALPHA100", "ALPHA 100", "alpha100"),
            _row("ALPHA100PLUS", "ALPHA 100 PLUS", "alpha100plus"),
            # same node as BETA200: a series, not a tie
            _row("BETA200", "BETA 200", "beta200"),
            _row("BETA200XL", "BETA 200XL", "beta200"),
            _row("GAMMA300", "GAMMA 300", "gamma300"),
            _row("GAMMA300UP", "GAMMA 300UP", "gamma300up"),
            _row("DELTA400", "DELTA 400", "delta400"),
            _row("DELTA400OLD-remove", "DELTA 400OLD", "delta400old"),
        ],
        "Flagsforflashport": [{"cpqModel": "GAMMA300UP"}],
        "XBmConfigRule": [],
    })


@pytest.fixture(autouse=True)
def _clean():
    mrc._cache.clear()
    mrc._empty.clear()
    mr.bind_turn(None)
    yield
    mrc._cache.clear()
    mrc._empty.clear()
    mr.bind_turn(None)


def _resolve(text: str, flag: bool = True) -> mr.ModelResolution:
    with patch.object(tie, "get_settings", _cfg(cpq_model_prefix_tie_ask_enabled=flag)):
        return mr.resolve_model(text, 1, "X", _rdb())


def test_tie_listed_and_chosen_unchanged():
    res = _resolve("quote for ALPHA100")
    assert res.chosen.cpq_model == "ALPHA100"
    assert [c.cpq_model for c in res.prefix_tie] == ["ALPHA100PLUS"]


def test_longer_wording_does_not_tie():
    res = _resolve("quote for ALPHA 100 PLUS")
    assert res.chosen.cpq_model == "ALPHA100PLUS"
    assert res.prefix_tie == ()


def test_same_node_is_not_a_tie():
    res = _resolve("BETA 200")
    assert res.chosen.cpq_model == "BETA200"
    assert res.prefix_tie == ()


def test_upgrade_and_soft_deleted_ignored():
    assert _resolve("GAMMA 300").prefix_tie == ()
    assert _resolve("DELTA 400").prefix_tie == ()


def test_flag_off_identical():
    on = _resolve("ALPHA100", flag=True)
    off = _resolve("ALPHA100", flag=False)
    assert off.prefix_tie == ()
    assert (off.chosen, off.alternatives, off.deciding_step) == (
        on.chosen, on.alternatives, on.deciding_step)


def _run_leaf(question: str, flag: bool):
    res = _resolve(question)
    mr.bind_turn(mr.TurnModelContext(res, 1, "X"))
    engine = MagicMock()
    engine.single_model_variable_name.return_value = None
    engine.model_variable_candidates.return_value = ["alpha100", "alpha100plus", "beta200"]
    session = SimpleNamespace(
        pending_model_leaf_candidates=[], model_leaf_resolved=False, filled={},
        product_anchor_question="", turn=1,
    )
    req = SimpleNamespace(question=question, workspace_id=1)
    hints: dict = {}
    ask = MagicMock(return_value={"answer": "which?"})
    with patch("aryx.api.ask_api._cpq_engine", engine), \
         patch.object(resolve, "bind_turn_model_context"), \
         patch.object(resolve, "seed_model_vn_from_resolution", return_value=""), \
         patch.object(resolve, "_build_model_leaf_ask_prompt", ask), \
         patch.object(resolve, "clear_pending_scope"), \
         patch.object(bind, "get_settings", _cfg(cpq_model_prefix_tie_ask_enabled=flag)):
        out = resolve._resolve_model_leaf(req, session, object(), hints, "X", None)
    return out, ask, hints, session


def test_leaf_gate_asks_on_tie():
    out, ask, hints, _ = _run_leaf("quote for ALPHA100", True)
    assert out == {"answer": "which?"}
    assert ask.call_args.args[2] == ["alpha100", "alpha100plus"]
    assert "_bm_model_variable_name" not in hints


def test_leaf_gate_flag_off_picks_silently():
    out, ask, hints, session = _run_leaf("quote for ALPHA100", False)
    assert out is None and not ask.called
    assert hints["_bm_model_variable_name"] == "alpha100"
    assert session.model_leaf_resolved is True


def test_leaf_gate_longer_wording_no_ask():
    out, ask, hints, _ = _run_leaf("quote for ALPHA100PLUS", True)
    assert out is None and not ask.called
    assert hints["_bm_model_variable_name"] == "alpha100plus"
