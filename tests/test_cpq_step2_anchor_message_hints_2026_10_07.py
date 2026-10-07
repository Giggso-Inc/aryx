"""STEP 2 also reads option text from the earlier message that named the product.

Live case (2026-10-07, ws 1267): "I want a quote for APX 900" was answered by
the country gate before catalog hints ran; turn 2 ("United States") scanned
only its own text, so Product was asked with ~300 options.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from aryx.api import ask_api
from aryx.api.ask_turn_steps import ask_step2_catalog_hints as step2
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption

_SENTINEL = "SENTINEL_ANCHOR_TEXT_51c"


def _attr(vn: str, pairs: list[tuple[str, str]]) -> ConfigAttr:
    return ConfigAttr(
        entity_id=hash(vn) % 10_000, variable_name=vn, display_label=vn,
        required=False, default_value="", select_type="single",
        options=[MenuOption(item_value=iv, display_name=dn, order=i)
                 for i, (iv, dn) in enumerate(pairs, start=1)],
    )


def _attrs() -> list[ConfigAttr]:
    """Real ws 1267 shape: "APX 900" is on the product selector and on the DMS picker."""
    return [
        _attr("productSelectionProduct_all", [("APX900FLASHPORT", "APX 900"), ("APX6500", "APX 6500")]),
        _attr("productSelectionDMSO_astro", [("APX900", "APX 900"), ("APX6500", "APX 6500")]),
    ]


@pytest.fixture
def engine(monkeypatch):
    """Real catalog-hint matcher; flag hints and trace binding stubbed (no DB)."""
    eng = CpqEngine()
    calls: list[str] = []
    real = eng.extract_catalog_hints

    def _spy(question, attrs):
        calls.append(question)
        return real(question, attrs)

    monkeypatch.setattr(eng, "extract_catalog_hints", _spy)
    monkeypatch.setattr(eng, "extract_flag_hints", lambda *a, **k: {})
    monkeypatch.setattr(ask_api, "_cpq_engine", eng)
    monkeypatch.setattr(step2.rule_trace, "bind_context", lambda *a: None)
    eng.calls = calls
    return eng


@pytest.fixture
def recs(monkeypatch):
    out: list[dict] = []

    def fake(level, criticality, message, **kw):
        out.append({"message": message, "context": kw.get("context") or {}})
        return {}

    monkeypatch.setattr(step2, "raven_log", fake)
    monkeypatch.setattr(step2, "would_log", lambda lv: True)
    return out


def _run(
    question: str, anchor: str, hints: dict | None = None,
    negated_vns: list | None = None, filled: dict | None = None,
):
    req = SimpleNamespace(question=question, workspace_id=1267)
    session = SimpleNamespace(
        product_anchor_question=anchor, negated_vns=list(negated_vns or []),
        filled=dict(filled or {}), turn=2,
    )
    hints = {} if hints is None else hints
    step2._step2_catalog_hints_and_negation(req, session, _attrs(), hints, "")
    return hints, session


def test_turn2_reads_product_from_the_anchor_message(engine, recs):
    hints, _ = _run("United States", "I want a quote for APX 900")
    assert hints == {"productSelectionProduct_all": "APX900FLASHPORT"}
    rec = [r for r in recs if "product anchor" in r["message"]][-1]
    assert rec["context"]["added_hint_vns"] == ["productSelectionProduct_all"]


def test_this_turn_wins_over_the_anchor(engine, recs):
    hints, _ = _run("make it an APX 6500", "I want a quote for APX 900")
    assert hints == {"productSelectionProduct_all": "APX6500"}


def test_hint_already_present_is_not_overwritten(engine, recs):
    hints, _ = _run("United States", "I want a quote for APX 900",
                    hints={"productSelectionProduct_all": "APX6500"})
    assert hints["productSelectionProduct_all"] == "APX6500"


def test_no_anchor_or_same_text_reads_once(engine, recs):
    _run("United States", "")
    assert engine.calls == ["United States"]
    engine.calls.clear()
    _run("I want a quote for APX 900", "I want a quote for APX 900")
    assert engine.calls == ["I want a quote for APX 900"]


def test_anchor_negations_are_ignored(engine, recs):
    hints, session = _run("United States", "quote please, exclude the APX 900")
    assert "productSelectionProduct_all" not in hints
    assert session.negated_vns == []


def test_this_turn_negation_blocks_the_anchor_rehint(engine, recs):
    """Review finding (Medium 1): a positive anchor ("I want a quote for
    APX 900") must not re-hint the product this turn's OWN message just
    rejected ("no, not the APX 900") -- before the fix, negated_now was
    never consulted by _merge_anchor_hints, so the anchor's positive
    phrase won anyway and tier1_hint_match (negation-blind) could fill
    the rejected product."""
    hints, session = _run("no, not the APX 900", "I want a quote for APX 900")
    assert "productSelectionProduct_all" not in hints
    assert "productSelectionProduct_all" in session.negated_vns


def test_carried_over_negation_blocks_the_anchor_rehint(engine, recs):
    """Review finding (Medium 1): a negation recorded on an EARLIER turn
    (session.negated_vns, not this turn's negated_now) must also block
    the anchor rescan -- the bug reproduces on every later turn, not
    just the turn the customer said "no" on."""
    hints, session = _run(
        "United States", "I want a quote for APX 900",
        negated_vns=["productSelectionProduct_all"],
    )
    assert "productSelectionProduct_all" not in hints
    assert session.negated_vns == ["productSelectionProduct_all"]


def test_rescan_skipped_once_product_already_filled(engine, recs):
    """Review finding (Medium 2): extract_catalog_hints does a full,
    uncached scan of every visible attr's options against the anchor
    text -- real cost on a large catalog (ws 1267: ~3.2k attrs, ~25k
    options), repeated every turn for a result that can't change once
    the one variable_name this function exists to backfill is filled."""
    hints, _ = _run(
        "United States", "I want a quote for APX 900",
        filled={"productSelectionProduct_all": "APX900FLASHPORT"},
    )
    assert hints == {}
    assert engine.calls == ["United States"]


def test_log_has_lengths_not_text(engine, recs):
    _run("United States", f"I want a quote for APX 900 {_SENTINEL}")
    assert _SENTINEL not in json.dumps(recs)
