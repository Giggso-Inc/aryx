"""Regression tests: CPQ mid-session product switching.

Bug: "CPQ is not getting generated for two products in single session, need
to create the separate session." Root cause (confirmed by reading the code):
CpqSession.product_name is a single scalar, and the old anchor gate in
_run_cpq_turn was `if not session.product_name:` — product detection only
ran while the field was empty. Once Product 1 was anchored on turn 1, every
later turn skipped detection entirely and kept configuring Product 1, no
matter what the user asked about.

Fix (Andie-planned, converged design): re-run detect_product_mention() every
turn. If it returns a DIFFERENT product than session.product_name, don't
silently switch — ask for confirmation first (new pending_anchor value
"confirm_switch" + new CpqSession.pending_switch_product field). Only reset
the config-scoped state (filled/pending_variables/country/catalog_prefix/...)
on an explicit "yes", and never on "no" — this is the safety net against a
false-positive detection (e.g. a curated product name appearing inside an
answer's value text) causing silent data loss.

These tests exercise _run_cpq_turn directly with hand-constructed
CpqSession state (rather than the full fake_rdb/truth fixture used
elsewhere in test_cpq_e2e.py) because the switch-gate logic runs and
returns BEFORE Step 2's graph/reader access — no real product catalog is
needed to verify it.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn
from aryx.cpq.state import CpqSession


def _mid_config_session(product_name="SL3500e", country="United States",
                         filled=None, turn=3, cascade_log=None) -> dict:
    """A CpqSession already anchored and mid-configuration, serialised."""
    session = CpqSession(
        mode="cpq", product_name=product_name, country=country,
        filled=dict(filled or {"battery": "STANDARD"}),
        display_filled=dict(filled or {"battery": "Standard"}),
        pending_variables=["some_other_var"],
        pending_anchor="", turn=turn,
        cascade_log=list(cascade_log or []),
    )
    return session.to_dict()


def _no_switch_setup(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    # Step 2 onward needs real graph/RDB data we don't have here — force the
    # "no CPQ data in graph" fallthrough so any turn that reaches Step 2
    # returns cleanly ({}) instead of crashing on a bare reader double.
    monkeypatch.setattr(api._cpq_engine, "load_product_config", lambda *a, **k: ([], ""))


# ── Scenario 1: baseline — no switch signal, existing behavior unaffected ──

def test_baseline_no_switch_signal_leaves_session_untouched(monkeypatch):
    _no_switch_setup(monkeypatch)
    session_data = _mid_config_session()
    req = AskRequest(question="what color options are available",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader=None)

    # No product mentioned -> no switch candidate -> falls through to Step 2,
    # which we've mocked to report "no attrs" -> {} (existing behavior).
    assert resp == {}


# ── Scenario 2: a different product is mentioned mid-session ───────────────

def test_different_product_mention_triggers_confirm_prompt(monkeypatch):
    _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(question="Actually I also need a MOTOTRBO radio",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader=None)

    assert resp, "engine returned no response for a switch candidate"
    assert "MOTOTRBO" in resp["answer"]
    assert "SL3500e" in resp["answer"]
    assert resp["tools_called"] == ["cpq_switch_candidate()"]
    sd = resp["session_data"]
    assert sd["pending_anchor"] == "confirm_switch"
    assert sd["pending_switch_product"] == "MOTOTRBO"
    # Nothing reset yet — only a candidate, not a confirmed switch.
    assert sd["product_name"] == "SL3500e"
    assert sd["filled"] == {"battery": "STANDARD"}


# ── Scenario 3: user confirms the switch ────────────────────────────────────

def test_confirmed_switch_resets_config_state_and_reanchors_country(monkeypatch):
    _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"

    req = AskRequest(question="yes", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader=None)

    assert resp
    sd = resp["session_data"]
    assert sd["product_name"] == "MOTOTRBO"
    assert sd["pending_switch_product"] == ""
    assert sd["filled"] == {}, "old product's answers must be discarded on confirmed switch"
    assert sd["display_filled"] == {}
    assert sd["pending_variables"] == []
    # Country was cleared by the switch, so the next anchor step re-asks it.
    assert sd["pending_anchor"] == "country"
    assert "country" in resp["answer"].lower()
    # Audit trail: the switch is recorded, not silently dropped.
    assert sd["cascade_log"][-1] == {
        "event": "product_switch", "from": "SL3500e", "to": "MOTOTRBO", "turn": sd["turn"],
    }


# ── Scenario 4: user declines the switch — zero data loss ──────────────────

def test_declined_switch_preserves_original_product_and_answers(monkeypatch):
    _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e",
                                        filled={"battery": "STANDARD", "carry": "BELT"})
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"

    req = AskRequest(question="no", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader=None)

    assert resp
    sd = resp["session_data"]
    assert sd["product_name"] == "SL3500e"
    assert sd["filled"] == {"battery": "STANDARD", "carry": "BELT"}
    assert sd["pending_switch_product"] == ""
    assert sd["pending_anchor"] == ""
    assert "SL3500e" in resp["answer"]


# ── Scenario 5: a curated product name inside an answer's value text ───────
# (e.g. an accessory question whose answer happens to name another product)
# still must not lose data even if detection misfires — declining resumes
# with the original configuration completely intact.

def test_value_text_mention_does_not_lose_data_when_declined(monkeypatch):
    _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(
        product_name="SL3500e", filled={"accessory": "STANDARD_KIT"})
    req = AskRequest(
        question="Add the MOTOTRBO-compatible carry accessory",
        workspace_id=1, session_data=session_data,
    )
    resp = _run_cpq_turn(req, reader=None)
    assert resp["tools_called"] == ["cpq_switch_candidate()"]  # detection did fire

    # User clarifies they meant to stay on SL3500e.
    req2 = AskRequest(question="no, stay on SL3500e",
                      workspace_id=1, session_data=resp["session_data"])
    resp2 = _run_cpq_turn(req2, reader=None)
    sd2 = resp2["session_data"]
    assert sd2["product_name"] == "SL3500e"
    assert sd2["filled"] == {"accessory": "STANDARD_KIT"}, "declining must not touch prior answers"


# ── Scenario 6: switching back and forth loses the earlier product's ───────
# in-progress answers by design (documented tradeoff — concurrent per-product
# state was explicitly rejected in the plan as too large a change surface).

def test_switching_back_and_forth_does_not_restore_prior_answers(monkeypatch):
    _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(
        product_name="SL3500e", filled={"battery": "STANDARD"})

    # Switch SL3500e -> MOTOTRBO.
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"
    resp1 = _run_cpq_turn(
        AskRequest(question="yes", workspace_id=1, session_data=session_data),
        reader=None,
    )
    sd1 = resp1["session_data"]
    assert sd1["product_name"] == "MOTOTRBO"
    assert sd1["filled"] == {}

    # Switch back MOTOTRBO -> SL3500e.
    sd1["pending_anchor"] = "confirm_switch"
    sd1["pending_switch_product"] = "SL3500e"
    resp2 = _run_cpq_turn(
        AskRequest(question="yes", workspace_id=1, session_data=sd1),
        reader=None,
    )
    sd2 = resp2["session_data"]
    assert sd2["product_name"] == "SL3500e"
    # The original battery="STANDARD" answer from before the FIRST switch is
    # gone — known, accepted limitation of the confirm/reset design.
    assert sd2["filled"] == {}
    assert len(sd2["cascade_log"]) == 2
    assert sd2["cascade_log"][0]["to"] == "MOTOTRBO"
    assert sd2["cascade_log"][1]["to"] == "SL3500e"


# ── Scenario 7: backward compatibility with pre-fix session_data payloads ──

def test_old_session_data_without_pending_switch_field_does_not_crash(monkeypatch):
    _no_switch_setup(monkeypatch)
    session = CpqSession(mode="cpq", product_name="SL3500e",
                          country="United States", pending_anchor="")
    old_style = session.to_dict()
    del old_style["pending_switch_product"]  # simulate a pre-fix client payload

    req = AskRequest(question="what color options are available",
                      workspace_id=1, session_data=old_style)
    resp = _run_cpq_turn(req, reader=None)

    assert resp == {}  # falls through exactly like the baseline case, no KeyError
