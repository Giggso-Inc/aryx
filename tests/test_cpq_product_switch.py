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
the config-scoped state (filled/pending_variables/country/...) on an
explicit "yes", and never on "no" — this is the safety net against a
false-positive detection causing silent data loss.

detect_product_mention() itself is DYNAMIC — no hardcoded product-name
list. It matches against the real product/family names of whatever
catalogs are actually ingested into the workspace, read live from the
graph (CpqEngine._ingested_product_names — the same BmPrdFamily/BmCatalog
lookup _scope_to_catalog already uses). _FakeProductReader below is a
minimal double exposing exactly that: distinct_types() to derive catalog
prefixes, and find_entities(ontology_type=...) to return each catalog's
family entity carrying its real product name.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn
from aryx.cpq.state import CpqSession


class _FakeProductReader:
    """Reader double for the dynamic product-name lookup only.

    `catalogs` maps a catalog prefix -> its real product/family display
    name, mirroring how a workspace's ingested XML catalogs are actually
    structured (e.g. {"Sl3500EConfig": "SL3500e", "MototrboConfig": "MOTOTRBO"}).
    """

    def __init__(self, catalogs: dict[str, str]):
        self._catalogs = catalogs
        self.id_to_name: dict[int, str] = {}
        self._next_id = 1000

    def distinct_types(self):
        return [f"{prefix}BmConfigAttr" for prefix in self._catalogs]

    def find_entities(self, ontology_type=None, name=None, limit=50):
        for prefix, pname in self._catalogs.items():
            if ontology_type == f"{prefix}BmPrdFamily":
                self._next_id += 1
                eid = self._next_id
                self.id_to_name[eid] = pname
                return [{"id": eid, "type": ontology_type, "name": pname}]
        return []


def _fake_reader_with_batch_fetch(monkeypatch, catalogs: dict[str, str]) -> _FakeProductReader:
    reader = _FakeProductReader(catalogs)
    monkeypatch.setattr(
        api._cpq_engine, "_batch_fetch",
        lambda ids, ws: {i: {"name": reader.id_to_name.get(i, "")} for i in ids},
    )
    return reader


_TWO_PRODUCT_CATALOGS = {"Sl3500EConfig": "SL3500e", "MototrboConfig": "MOTOTRBO"}


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


def _no_switch_setup(monkeypatch, catalogs=None):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    reader = _fake_reader_with_batch_fetch(monkeypatch, catalogs or _TWO_PRODUCT_CATALOGS)
    # Step 2 onward needs real graph/RDB config-attr data we don't have here
    # — force the "no CPQ data in graph" fallthrough so any turn that
    # reaches Step 2 returns cleanly ({}) instead of crashing.
    monkeypatch.setattr(api._cpq_engine, "load_product_config", lambda *a, **k: ([], ""))
    return reader


# ── Scenario 1: baseline — no switch signal, existing behavior unaffected ──

def test_baseline_no_switch_signal_leaves_session_untouched(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session()
    req = AskRequest(question="what color options are available",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    # No product mentioned -> no switch candidate -> falls through to Step 2,
    # which we've mocked to report "no attrs" -> {} (existing behavior).
    assert resp == {}


# ── Scenario 2: a different, actually-ingested product is mentioned ────────

def test_different_product_mention_triggers_confirm_prompt(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(question="Actually I also need a MOTOTRBO radio",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

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


def test_product_not_ingested_in_workspace_is_never_a_switch_candidate(monkeypatch):
    """Dynamic detection only recognises products actually ingested into
    THIS workspace — a name that isn't one of the live catalogs must not
    trigger a switch, proving there is no hardcoded product list left."""
    reader = _no_switch_setup(monkeypatch, catalogs={"Sl3500EConfig": "SL3500e"})
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(question="what about a MOTOTRBO radio",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    # MOTOTRBO isn't ingested in this workspace (only SL3500e is) -> no
    # candidate detected -> falls through to Step 2's mocked empty-attrs {}.
    assert resp == {}


# ── Scenario 3: user confirms the switch ────────────────────────────────────

def test_confirmed_switch_resets_config_state_and_reanchors_country(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"

    req = AskRequest(question="yes", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

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
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e",
                                        filled={"battery": "STANDARD", "carry": "BELT"})
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"

    req = AskRequest(question="no", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    assert resp
    sd = resp["session_data"]
    assert sd["product_name"] == "SL3500e"
    assert sd["filled"] == {"battery": "STANDARD", "carry": "BELT"}
    assert sd["pending_switch_product"] == ""
    assert sd["pending_anchor"] == ""
    assert "SL3500e" in resp["answer"]


# ── Scenario 5: a real ingested product name inside an answer's value text ─
# still must not lose data even if detection misfires — declining resumes
# with the original configuration completely intact.

def test_value_text_mention_does_not_lose_data_when_declined(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(
        product_name="SL3500e", filled={"accessory": "STANDARD_KIT"})
    req = AskRequest(
        question="Add the MOTOTRBO-compatible carry accessory",
        workspace_id=1, session_data=session_data,
    )
    resp = _run_cpq_turn(req, reader)
    assert resp["tools_called"] == ["cpq_switch_candidate()"]  # detection did fire

    # User clarifies they meant to stay on SL3500e.
    req2 = AskRequest(question="no, stay on SL3500e",
                      workspace_id=1, session_data=resp["session_data"])
    resp2 = _run_cpq_turn(req2, reader)
    sd2 = resp2["session_data"]
    assert sd2["product_name"] == "SL3500e"
    assert sd2["filled"] == {"accessory": "STANDARD_KIT"}, "declining must not touch prior answers"


# ── Scenario 6: switching back and forth loses the earlier product's ───────
# in-progress answers by design (documented tradeoff — concurrent per-product
# state was explicitly rejected in the plan as too large a change surface).

def test_switching_back_and_forth_does_not_restore_prior_answers(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(
        product_name="SL3500e", filled={"battery": "STANDARD"})

    # Switch SL3500e -> MOTOTRBO.
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"
    resp1 = _run_cpq_turn(
        AskRequest(question="yes", workspace_id=1, session_data=session_data),
        reader,
    )
    sd1 = resp1["session_data"]
    assert sd1["product_name"] == "MOTOTRBO"
    assert sd1["filled"] == {}

    # Switch back MOTOTRBO -> SL3500e.
    sd1["pending_anchor"] = "confirm_switch"
    sd1["pending_switch_product"] = "SL3500e"
    resp2 = _run_cpq_turn(
        AskRequest(question="yes", workspace_id=1, session_data=sd1),
        reader,
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
    reader = _no_switch_setup(monkeypatch)
    session = CpqSession(mode="cpq", product_name="SL3500e",
                          country="United States", pending_anchor="")
    old_style = session.to_dict()
    del old_style["pending_switch_product"]  # simulate a pre-fix client payload

    req = AskRequest(question="what color options are available",
                      workspace_id=1, session_data=old_style)
    resp = _run_cpq_turn(req, reader)

    assert resp == {}  # falls through exactly like the baseline case, no KeyError


# ── Dynamic detection itself — no hardcoded list anywhere ───────────────────

def test_detect_product_mention_has_no_hardcoded_pattern_list():
    """Guard against regressing back to a hardcoded product list: the
    engine module must not define a fixed pattern table anymore."""
    import aryx.cpq.engine as engine_mod
    assert not hasattr(engine_mod, "_PRODUCT_PATTERNS")


def test_detect_product_mention_prefers_specific_variant_over_generic_name(monkeypatch):
    """Regression (caught in Raven review): the old hardcoded _PRODUCT_PATTERNS
    table deliberately ordered variant patterns ("APX NEXT XE") before the
    generic one ("APX NEXT") — "Spec rule 3: if user says 'APX NEXT XE', map
    to XE, not Single Band." The dynamic replacement lost this guarantee by
    matching candidates in whatever order the graph returned them, with no
    length-based tie-break. Deliberately insert the GENERIC name first in
    the fake catalog dict (the unfavorable graph-return order) and assert
    the specific variant still wins."""
    reader = _fake_reader_with_batch_fetch(monkeypatch, {
        "ApxNextConfig": "APX NEXT",        # generic, inserted FIRST (unfavorable order)
        "ApxNextXeConfig": "APX NEXT XE",   # specific variant
    })
    from aryx.cpq.engine import CpqEngine
    engine = CpqEngine()
    result = engine.detect_product_mention(
        "I need a quote for the APX NEXT XE", hints={},
        reader=reader, workspace_id=1,
    )
    assert result == "APX NEXT XE", (
        "a specific variant name must win over a generic name it contains, "
        "regardless of graph return order"
    )

    # The generic name alone must still resolve correctly (no over-matching).
    result_generic = engine.detect_product_mention(
        "I need a quote for the APX NEXT", hints={},
        reader=reader, workspace_id=1,
    )
    assert result_generic == "APX NEXT"


def test_detect_product_mention_recognises_a_brand_new_product_with_no_code_change(monkeypatch):
    """A product family invented for this test alone (never referenced
    anywhere in source) is recognised purely because it's "ingested" in
    the fake workspace — proving detection is genuinely dynamic."""
    reader = _fake_reader_with_batch_fetch(
        monkeypatch, {"ZorbaxUltraConfig": "Zorbax Ultra 9000"})
    from aryx.cpq.engine import CpqEngine
    engine = CpqEngine()
    result = engine.detect_product_mention(
        "I need a quote for the Zorbax Ultra 9000", hints={},
        reader=reader, workspace_id=1,
    )
    assert result == "Zorbax Ultra 9000"
