"""PR #307 review follow-up (M1): dedicated coverage for
CpqEngine.grid_batch_count_mismatch and its wiring into
_grid_batch_count_mismatch_message / the new early-return branch in
ask_step9_lock_pending_answer.py's STEP 5 gate.

A purely positional batch reply ("5, 4" for 3 pending mount
quantities) with the wrong segment count is genuinely ambiguous -- with
one value missing, every later position could belong to any remaining
candidate, and picking one would be guessing. Before this fix, that
reply fell through silently to Step 5's single-attribute handling,
which rejected the whole string against just pending_variables[0] with
no explanation. These tests lock in the specific re-ask instead, and
confirm the correct-count and named-pair paths are unaffected.

Ported from dev-rv-msi (54a894f2, #307, not yet in dev_oci) onto this
session's Phase 10/11-phase ask_api decomposition -- adapted for two
real structural differences from the original flat ask_api.py:
_try_apply_grid_quantities_batch_reply/_grid_batch_count_mismatch_message
now live in api.ask_turn_steps.ask_grid_batch_quantity, not ask_api.py
itself; and _grid_batch_count_mismatch_message here takes the full
`req` (not a bare question string) and returns a complete turn-response
dict rather than just the message text, matching every other STEP 5
response-builder's established convention in this codebase (e.g.
ask_step9_miss_response.py's _step9_low_confidence_response).
"""
from __future__ import annotations

import aryx.api.ask_api as api
import aryx.api.ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.api.ask_turn_steps.ask_grid_batch_quantity import (
    _grid_batch_count_mismatch_message,
    _try_apply_grid_quantities_batch_reply,
)
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption

_QTY_VNS = [
    "mountingTypeShirtMagneticMountQuantity_viSoln",
    "mountingTypeJacketMagneticMountQuantity_viSoln",
    "mountingTypeShirtClipMountQuantity_viSoln",
]
_QTY_LABELS = [
    "mounting type Shirt Magnetic Mount Quantity",
    "mounting type Jacket Magnetic Mount Quantity",
    "mounting type Shirt Clip Mount Quantity",
]


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attrs() -> list[ConfigAttr]:
    multi_mount = ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount"),
    )
    qty_attrs = [
        ConfigAttr(
            entity_id=2 + i, variable_name=vn, display_label=label,
            required=False, default_value="", options=[], hidden=True,
            select_type="integer",
        )
        for i, (vn, label) in enumerate(zip(_QTY_VNS, _QTY_LABELS))
    ]
    return [multi_mount, *qty_attrs]


def _setup(monkeypatch, attrs):
    monkeypatch.setattr(_ask_core_helpers_module, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: (attrs, "Svx Video Remote Speaker Microphone"),
    )


def _session(turn: int = 2) -> CpqSession:
    return CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=turn,
        filled={}, filled_multi={},
        pending_variables=list(_QTY_VNS),
    )


# ── Unit-level: CpqEngine.grid_batch_count_mismatch directly ────────────

def test_engine_reports_wrong_count_for_positional_undercount():
    e = CpqEngine()
    candidates = [(vn, vn) for vn in _QTY_VNS]
    assert e.grid_batch_count_mismatch(candidates, "5, 4") == 2


def test_engine_returns_none_for_correct_count():
    e = CpqEngine()
    candidates = [(vn, vn) for vn in _QTY_VNS]
    assert e.grid_batch_count_mismatch(candidates, "5, 4, 3") is None


def test_engine_returns_none_when_a_label_is_present():
    """A named-pair attempt (even partial) is never a count mismatch --
    parse_grid_batch_quantities already resolves those correctly."""
    e = CpqEngine()
    candidates = [("shirtMagneticMountQty", "Shirt Magnetic Mount")]
    assert e.grid_batch_count_mismatch(
        candidates, "Shirt Magnetic Mount: 5, Jacket Magnetic Mount: 4",
    ) is None


def test_engine_returns_none_for_non_positional_text():
    e = CpqEngine()
    candidates = [(vn, vn) for vn in _QTY_VNS]
    assert e.grid_batch_count_mismatch(candidates, "yes") is None


# ── End-to-end: the new early-return branch in the STEP 5 gate ──────────

def test_wrong_count_positional_reply_gets_specific_reask(monkeypatch):
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    req = AskRequest(question="5, 4", workspace_id=1, session_data=_session().to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert "You gave 2 value(s)" in resp["answer"]
    assert "3 mount quantities pending" in resp["answer"]
    session2 = CpqSession.from_dict(resp["session_data"])
    for vn in _QTY_VNS:
        assert session2.filled.get(vn) is None, f"{vn} must stay unfilled on a mismatched reply"
        assert vn in session2.pending_variables, f"{vn} must remain pending, not dropped"


def test_correct_count_positional_reply_still_resolves_all(monkeypatch):
    """Regression guard: the new mismatch check must never fire (and
    never block) a reply with the right number of values."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    req = AskRequest(question="5, 4, 3", workspace_id=1, session_data=_session().to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert "You gave" not in resp["answer"]
    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled.get(_QTY_VNS[0]) == "5"
    assert session2.filled.get(_QTY_VNS[1]) == "4"
    assert session2.filled.get(_QTY_VNS[2]) == "3"


def test_engine_reports_unparseable_segment_at_right_count():
    """N1 follow-up: right count, one segment isn't a recognized
    quantity ("seven" is fine via the word-number vocabulary, but a
    genuine typo like "sevn" is not)."""
    e = CpqEngine()
    candidates = [(vn, vn) for vn in _QTY_VNS]
    assert e.grid_batch_unparseable_segment(candidates, "7, sevn, 3") == _QTY_VNS[1]


def test_engine_unparseable_segment_returns_none_when_all_parse():
    e = CpqEngine()
    candidates = [(vn, vn) for vn in _QTY_VNS]
    assert e.grid_batch_unparseable_segment(candidates, "7, seven, 3") is None


def test_engine_unparseable_segment_returns_none_on_wrong_count():
    e = CpqEngine()
    candidates = [(vn, vn) for vn in _QTY_VNS]
    assert e.grid_batch_unparseable_segment(candidates, "7, sevn") is None


def test_right_count_one_bad_segment_gets_specific_reask(monkeypatch):
    """N1 e2e: right segment count, one unparseable value -- must name
    the specific mount, not fall through to the generic single-attr
    rejection."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    req = AskRequest(question="7, sevn, 3", workspace_id=1, session_data=_session().to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert "couldn't read one of those quantities" in resp["answer"]
    assert _QTY_LABELS[1] in resp["answer"]
    session2 = CpqSession.from_dict(resp["session_data"])
    for vn in _QTY_VNS:
        assert session2.filled.get(vn) is None
        assert vn in session2.pending_variables


def test_partial_named_pair_reply_is_unaffected_by_mismatch_check():
    """Regression guard: naming only some mounts is a legitimate partial
    answer, not a count mismatch -- must resolve exactly what was named
    and leave the rest genuinely pending, with no mismatch message.

    Exercises _try_apply_grid_quantities_batch_reply and
    _grid_batch_count_mismatch_message directly rather than through the
    full turn pipeline (_run_cpq_turn_inner): the reply text contains
    the literal word "Quantity" (it's part of the mount's own display
    label, which the batch prompt's own reply example instructs
    customers to use), which also matches an UNRELATED, pre-existing
    session-level "did they mean the overall product quantity?" gate
    (question_mentions_quantity/quantity_turn_precheck) earlier in that
    pipeline -- orthogonal to this PR's scope, and dependent on a live
    LLM call (_llm_resolve_quantity_target) to disambiguate, which this
    test environment can't exercise deterministically. Calling the two
    functions this PR actually touches directly keeps the test fast and
    focused on what it's meant to cover.
    """
    attrs = _attrs()
    session = _session()
    question = "mounting type Shirt Magnetic Mount Quantity: 5"
    resolved = _try_apply_grid_quantities_batch_reply(question, session, attrs)
    assert resolved == {_QTY_VNS[0]}
    assert session.filled.get(_QTY_VNS[0]) == "5"
    assert session.filled.get(_QTY_VNS[1]) is None
    assert session.filled.get(_QTY_VNS[2]) is None
    assert _QTY_VNS[0] not in session.pending_variables
    assert _QTY_VNS[1] in session.pending_variables
    assert _QTY_VNS[2] in session.pending_variables
    # And the mismatch-message helper must stay silent for this reply --
    # it was resolved, not mismatched, so no "You gave..." re-ask.
    req = AskRequest(question=question, workspace_id=1, session_data=_session().to_dict())
    assert _grid_batch_count_mismatch_message(req, _session(), attrs) is None
