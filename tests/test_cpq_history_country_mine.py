"""Residual Bug A: mine Ask history when CPQ starts after standard-Ask turn 1.

Transcript:
  H: Order APX Next … destination country is United States … HOUSTON
  Aryx: (graph menu essay — no CpqSession)
  H: need to get the quote / aSTRO25_bom
  Aryx must NOT re-ask country — mine history for United States.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aryx.api.ask_api import (
    AskRequest,
    Turn,
    _mine_history_for_cpq_context,
    _user_texts_from_history,
)
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, CpqSession


_ORDER = (
    'Order APX Next Radios for customer whose destination country is '
    'United States and customer name is "HOUSTON, CITY OF"'
)


def test_user_texts_from_history_filters_roles() -> None:
    hist = [
        Turn(role="user", text=_ORDER),
        Turn(role="assistant", text="menu essay"),
        Turn(role="user", text="need to get the quote"),
    ]
    texts = _user_texts_from_history(hist)
    assert texts == [_ORDER, "need to get the quote"]


def test_mine_history_sets_country_and_anchor() -> None:
    session = CpqSession()
    engine = CpqEngine()
    hist = [
        Turn(role="user", text=_ORDER),
        Turn(role="assistant", text="To start your order, select United States…"),
        Turn(role="user", text="need to get the quote"),
    ]
    _mine_history_for_cpq_context(session, hist, engine)
    assert session.country
    assert "united" in session.country.lower()
    assert session.product_anchor_question == _ORDER


def test_mine_history_newest_country_wins() -> None:
    session = CpqSession()
    engine = CpqEngine()
    hist = [
        Turn(role="user", text="order radios for destination country Canada"),
        Turn(role="user", text="actually destination country is United States"),
    ]
    _mine_history_for_cpq_context(session, hist, engine)
    assert "united" in (session.country or "").lower()


def test_mine_does_not_clobber_existing_country() -> None:
    session = CpqSession()
    session.country = "Germany"
    engine = CpqEngine()
    hist = [Turn(role="user", text=_ORDER)]
    _mine_history_for_cpq_context(session, hist, engine)
    assert session.country == "Germany"


def test_run_cpq_turn_mines_history_before_country_gate() -> None:
    """Full path: fresh session + history with order → no country re-ask prompt."""
    from aryx.api import ask_api as mod

    hist = [
        Turn(role="user", text=_ORDER),
        Turn(role="assistant", text="graph menu answer"),
    ]
    req = AskRequest(
        question="aSTRO25_bom",
        workspace_id=1,
        history=hist,
        session_data={},  # no prior CPQ session — Bug A residual
    )
    reader = object()

    # Minimal stubs so we stop after anchors if country is latched and
    # product is set — we only assert country was set and gate not hit.
    with patch.object(mod, "_cpq_engine") as eng:
        real = CpqEngine()
        eng.extract_hints = real.extract_hints
        # ISSUE-007: _mine_history_for_cpq_context now calls
        # is_recognized_country() and stores its resolved canonical value
        # (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_17.md) --
        # wire the real implementation through, same technique as
        # extract_hints above, so this stays a realistic mock instead of
        # an unconfigured MagicMock silently landing in session.country.
        eng.is_recognized_country = real.is_recognized_country
        eng.detect_product_mention = MagicMock(return_value="aSTRO25_bom")
        eng.resolve_product_hint = MagicMock(return_value=None)
        eng.list_ingested_families = MagicMock(return_value=["aSTRO25_bom"])
        # A real (if minimal) attrs list -- an empty one hits _run_cpq_turn_
        # inner's own "if not attrs: return {}" bailout (deliberate "no CPQ
        # data in graph, fall through to standard Ask" signal), which made
        # this test's own assertions about session_data unreachable
        # regardless of whether history-mining itself worked correctly.
        country_attr = ConfigAttr(
            entity_id=1, variable_name="ultimateDestinationCountry",
            display_label="Destination Country", required=True,
            default_value="", options=[],
        )
        eng.load_product_config = MagicMock(return_value=([country_attr], "aSTRO25_bom"))
        eng.detect_qa_question = MagicMock(return_value=False)
        eng.count_turn_intents = MagicMock(return_value=[])
        eng.extract_catalog_hints = MagicMock(return_value=({}, set()))
        eng.extract_flag_hints = MagicMock(return_value={})
        eng.single_model_variable_name = MagicMock(return_value=None)
        eng.resolve_always_ask_skips = MagicMock(return_value=set())
        eng.product_label_noise_vns = MagicMock(return_value=set())
        eng.evaluate_rules_loop = MagicMock(
            return_value=([], {}, {}, {}),
        )
        eng.auto_fill = MagicMock(return_value=({}, {}, []))
        eng._is_hardware_version_attr = real._is_hardware_version_attr
        eng.apply_answer = MagicMock(return_value=None)

        with patch.object(mod, "set_run_id"), \
             patch.object(mod, "record_utterance"), \
             patch.object(mod, "detect_undo", return_value=False), \
             patch.object(mod, "detect_guided_mode_accept", return_value=False), \
             patch.object(mod, "_persist_cpq_history"), \
             patch.object(mod, "get_settings") as gs:
            gs.return_value.cpq_shadow_intent_enabled = False
            gs.return_value.cpq_llm_first_enabled = False
            result = mod._run_cpq_turn(req, reader)

    # Must not be the country re-ask anchor response.
    answer = (result or {}).get("answer") or ""
    assert "destination country" not in answer.lower() or "United States" in answer
    # Session should carry mined country
    sd = (result or {}).get("session_data") or {}
    assert sd.get("country")
    assert "united" in str(sd.get("country")).lower()
