"""PROMPT 6 — reversed-cue replacement clause extraction.

`_extract_replacement_clause` must yield only the WANTED value for both
forward forms ("use Premium instead of Standard") and reversed forms
("instead of Standard, prefer Premium"). The rejected value must never
appear in the clause passed to apply_answer, and must be recorded so the
constrained path can exclude it.

Design (a): deterministic contrast-first pre-pattern before leftmost-cue.
"""
from __future__ import annotations

import pytest

import aryx.api.ask_api as api
from aryx.api.ask_api import (
    AskRequest,
    _constrain_excluding_rejected,
    _extract_replacement_clause,
    _run_cpq_turn,
)
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=False,
        default_value="", options=options or [], select_type="single",
    )


def _rules_setup(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])


# ── Pure unit cases ────────────────────────────────────────────────────────

# (input, expected_wanted, expected_rejected_substring_or_None)
_CASES: list[tuple[str, str | None, str | None]] = [
    # Forward forms (prior rounds — must not regress)
    ("use Premium instead of Standard", "Premium", "Standard"),
    ("prefer Premium over Standard", "Premium", "Standard"),
    ("rather Premium than Standard", "Premium", "Standard"),
    ("I don't want Standard, use Premium", "Premium", None),
    ("use Premium", "Premium", None),
    # Reversed forms (this prompt)
    ("instead of Standard, prefer Premium", "Premium", "Standard"),
    ("rather than Standard, use Premium", "Premium", "Standard"),
    ("not Standard, Premium please", "Premium", "Standard"),
    ("not Standard — Premium", "Premium", "Standard"),
    ("instead of Standard prefer Premium", "Premium", "Standard"),
    ("rather than X, use Y", "Y", "X"),
    # No cue — fall through
    ("Premium", None, None),
    ("H45", None, None),
    ("", None, None),
]


@pytest.mark.parametrize("text,exp_wanted,exp_rejected", _CASES)
def test_extract_replacement_clause_wanted_and_rejected(text, exp_wanted, exp_rejected):
    wanted, rejected = _extract_replacement_clause(text)
    assert wanted == exp_wanted, f"wanted for {text!r}"
    if exp_rejected is None:
        assert rejected is None, f"rejected for {text!r}"
    else:
        assert rejected is not None
        assert exp_rejected.lower() in rejected.lower(), f"rejected for {text!r}"


@pytest.mark.parametrize("text,exp_wanted,exp_rejected", _CASES)
def test_clause_never_contains_rejected_string(text, exp_wanted, exp_rejected):
    """Property: when both wanted and rejected are known, the wanted clause
    must not contain the rejected token (apply_answer cannot re-match it)."""
    wanted, rejected = _extract_replacement_clause(text)
    if not wanted or not rejected:
        return
    # Rejected token as a whole word must not appear in wanted
    assert rejected.lower() not in wanted.lower(), (
        f"wanted {wanted!r} still contains rejected {rejected!r} for {text!r}"
    )


def test_constrain_excluding_rejected_drops_option():
    tier = _attr(1, "priceTier_astro", "Price Tier", options=_opt("Standard", "Premium", "Basic"))
    filtered = _constrain_excluding_rejected(tier, "Standard", None)
    assert filtered is not None
    assert "Standard" not in filtered
    assert "Premium" in filtered
    assert "Basic" in filtered


def test_constrain_excluding_unknown_rejected_leaves_base():
    tier = _attr(1, "priceTier_astro", "Price Tier", options=_opt("Standard", "Premium"))
    base = ["Premium"]
    assert _constrain_excluding_rejected(tier, "NotARealOption", base) == base
    assert _constrain_excluding_rejected(tier, None, base) == base


# ── Integration: pending_change_no_value path ──────────────────────────────

def _pcnv_tier_session() -> CpqSession:
    return CpqSession(
        mode="cpq", product_name="aSTRO25_bom",
        filled={"priceTier_astro": "Standard"},
        display_filled={"priceTier_astro": "Standard"},
        pending_change_no_value_vn="priceTier_astro",
        country="United States", status="configuring", turn=3,
    )


def _run_pcnv(monkeypatch, question: str) -> dict:
    _rules_setup(monkeypatch)
    tier = _attr(1, "priceTier_astro", "Price Tier", options=_opt("Standard", "Premium"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([tier], "aSTRO25_bom"))
    session = _pcnv_tier_session()
    req = AskRequest(question=question, workspace_id=1, session_data=session.to_dict())
    return _run_cpq_turn(req, object())


@pytest.mark.parametrize("question", [
    "instead of Standard, prefer Premium",
    "rather than Standard, use Premium",
    "not Standard, Premium please",
    "prefer Premium over Standard",
    "use Premium instead of Standard",
    "I don't want Standard, use Premium",
])
def test_pending_change_applies_wanted_never_rejected(monkeypatch, question):
    resp = _run_pcnv(monkeypatch, question)
    assert resp is not None
    filled = resp["session_data"]["filled"].get("priceTier_astro")
    display = resp["session_data"]["display_filled"].get("priceTier_astro")
    assert filled == "Premium", f"filled={filled!r} for {question!r}"
    assert display == "Premium"
    assert filled != "Standard"
