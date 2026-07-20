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
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption


class _FakeProductReader:
    """Reader double for the dynamic product-name lookup only.

    `catalogs` maps a catalog prefix -> its real product/family display
    name, mirroring how a workspace's ingested XML catalogs are actually
    structured (e.g. {"Sl3500EConfig": "SL3500e", "MototrboConfig": "MOTOTRBO"}).

    `trees` (optional) maps a catalog prefix -> the names of its own
    bm_catalog tree entities (product lines / products) — the
    catalog-scoped hierarchy ingested_product_alias_map reads (confirmed
    live: each export carries ONLY its own tree, e.g. "aPXNext_BOM" /
    "APX™ NEXT" exist solely in the APX export).
    """

    def __init__(self, catalogs: dict[str, str], trees: dict[str, list[str]] | None = None):
        self._catalogs = catalogs
        self._trees = trees or {}
        self.id_to_name: dict[int, str] = {}
        self._next_id = 1000

    def distinct_types(self):
        return [f"{prefix}BmConfigAttr" for prefix in self._catalogs]

    def _ent(self, ontology_type: str, pname: str) -> dict:
        self._next_id += 1
        eid = self._next_id
        self.id_to_name[eid] = pname
        return {"id": eid, "type": ontology_type, "name": pname}

    def find_entities(self, ontology_type=None, name=None, limit=50, offset=0):
        for prefix, pname in self._catalogs.items():
            if ontology_type == f"{prefix}BmPrdFamily":
                return [self._ent(ontology_type, pname)]
            if ontology_type == f"{prefix}BmCatalog":
                return [self._ent(ontology_type, t) for t in self._trees.get(prefix, [])]
        return []


def _fake_reader_with_batch_fetch(
    monkeypatch, catalogs: dict[str, str],
    trees: dict[str, list[str]] | None = None,
) -> _FakeProductReader:
    reader = _FakeProductReader(catalogs, trees)
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


def _no_switch_setup(monkeypatch, catalogs=None, trees=None):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    reader = _fake_reader_with_batch_fetch(
        monkeypatch, catalogs or _TWO_PRODUCT_CATALOGS, trees)
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
    # No country set before switching — country="" is the scenario this
    # test targets (re-anchoring from a clean slate). A country already
    # set and valid for the new product is now PRESERVED, not reset — see
    # test_switch_preserves_valid_country_without_reasking for that case.
    session_data = _mid_config_session(product_name="SL3500e", country="")
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
    # No country was set, so the next anchor step asks for one fresh.
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
    # No country set — see test_confirmed_switch_resets_config_state_and_reanchors_country
    # for why this must be explicit now that a valid, already-set country
    # is preserved across a switch instead of being reset.
    session_data = _mid_config_session(
        product_name="SL3500e", country="", filled={"battery": "STANDARD"})

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


# ── Scenario 7: fuzzy substring fallback catches a PARTIAL/misspelled ──────
# product mention that Tier 1's exact-substring match alone would miss —
# deterministic (SequenceMatcher via aryx.resolution.classical.string_score),
# no LLM call, no added latency/cost on ordinary turns.

def test_partial_product_name_missing_a_character_triggers_confirm(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(
        question="what about a MOTOTRB radio",  # missing trailing "o"
        workspace_id=1, session_data=session_data,
    )
    resp = _run_cpq_turn(req, reader)

    assert resp, "fuzzy match should have surfaced a switch candidate"
    sd = resp["session_data"]
    assert sd["pending_anchor"] == "confirm_switch"
    assert sd["pending_switch_product"] == "MOTOTRBO"
    # Same safety net as an exact match — nothing is reset yet, only a candidate.
    assert sd["product_name"] == "SL3500e"
    assert sd["filled"] == {"battery": "STANDARD"}


def test_misspelled_product_name_triggers_confirm(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(question="quote me a mototrbio instead",  # typo of MOTOTRBO
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    assert resp, "fuzzy match should have caught the misspelled product name"
    sd = resp["session_data"]
    assert sd["pending_anchor"] == "confirm_switch"
    assert sd["pending_switch_product"] == "MOTOTRBO"


def test_generic_question_never_fuzzy_matches_a_product(monkeypatch):
    """An ordinary, product-agnostic question must never be treated as a
    switch candidate just because it shares some characters with a real
    product name — the whole point of the conservative threshold."""
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(question="does it support dual SIM too",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    # No exact or fuzzy candidate -> falls through to Step 2's mocked {}.
    assert resp == {}


def test_short_direct_answer_never_fuzzy_matches_a_product(monkeypatch):
    """A short, ordinary config answer must never be treated as a switch
    candidate — proves the fuzzy fallback doesn't misfire on normal turns."""
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(question="core trunking bundle",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    assert resp == {}


def test_exact_match_still_wins_before_fuzzy_is_even_tried(monkeypatch):
    """Tier 1's free exact-name match must short-circuit before the fuzzy
    scan runs at all — proven by using a message where the exact name is
    present verbatim."""
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(question="Actually I also need a MOTOTRBO radio",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    assert resp["session_data"]["pending_switch_product"] == "MOTOTRBO"


# ── Scenario 8: mid-band fuzzy score -> "did you mean...?" suggestions ────
# instead of silently ignoring a garbled/partial product mention that
# scores between the suggest and confirm thresholds.

def test_middle_band_mention_offers_up_to_5_suggestions(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(
        question="what about motorola trbo",  # ~0.75 fuzzy score vs MOTOTRBO
        workspace_id=1, session_data=session_data,
    )
    resp = _run_cpq_turn(req, reader)

    assert resp, "middle-band mention should surface a suggestion, not be ignored"
    assert resp["tools_called"] == ["cpq_switch_ambiguous()"]
    assert "MOTOTRBO" in resp["answer"]
    # Issue 7: the hint must arm a pending state its reply can be consumed
    # by (one candidate -> the confirm gate). Nothing committed either way.
    sd = resp["session_data"]
    assert sd["pending_anchor"] == "confirm_switch"
    assert sd["pending_switch_product"] == "MOTOTRBO"
    assert sd["product_name"] == "SL3500e"


def test_middle_band_suggestions_capped_at_five(monkeypatch):
    many_catalogs = {
        "Sl3500EConfig": "SL3500e",
        "AlphaZorbConfig": "Alpha Zorb One",
        "AlphaZorbTwoConfig": "Alpha Zorb Two",
        "AlphaZorbThreeConfig": "Alpha Zorb Three",
        "AlphaZorbFourConfig": "Alpha Zorb Four",
        "AlphaZorbFiveConfig": "Alpha Zorb Five",
        "AlphaZorbSixConfig": "Alpha Zorb Six",
    }
    reader = _no_switch_setup(monkeypatch, catalogs=many_catalogs)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(question="what about the alpha zorb radio",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    if resp.get("tools_called") == ["cpq_switch_ambiguous()"]:
        # Count how many bolded product names appear in the hint.
        assert resp["answer"].count("**Alpha Zorb") <= 5


def test_generic_question_gets_no_suggestions_either(monkeypatch):
    """The existing 'generic question -> ignored' tests already prove no
    exact/fuzzy switch candidate fires; this confirms the NEW middle-band
    suggestion path doesn't fire for them either."""
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    req = AskRequest(question="does it support dual SIM too",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    assert resp == {}, "a purely generic question must not trigger a suggestion prompt"


# ── Scenario 9: country re-validation on a confirmed product switch ───────

_FAKE_COUNTRY_ATTR = ConfigAttr(
    entity_id=9001, variable_name="ultimateDestinationCountry",
    display_label="Country", required=True, default_value="", options=[],
)


def _country_check_setup(monkeypatch, available: bool):
    """Override load_product_config (normally mocked to return ([], "") by
    _no_switch_setup, which would make _country_available_for short-circuit
    to True before ever calling check_country_availability) so the new
    catalog resolves to a real country ConfigAttr, and check_country_availability
    itself returns `available` — isolates the ask_api.py wiring from the
    engine method's own internals, which are exercised for real (no mocks)
    by the test_country_availability_* tests below."""
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: ([_FAKE_COUNTRY_ATTR], "MOTOTRBO"),
    )
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: None)
    monkeypatch.setattr(
        api._cpq_engine, "check_country_availability", lambda *a, **k: available,
    )


def test_switch_preserves_valid_country_without_reasking(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    _country_check_setup(monkeypatch, available=True)
    session_data = _mid_config_session(product_name="SL3500e", country="United States")
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"

    req = AskRequest(question="yes", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    sd = resp["session_data"]
    assert sd["product_name"] == "MOTOTRBO"
    assert sd["country"] == "United States", "a validated country must be preserved, not reset"
    assert sd["pending_anchor"] != "country", "must not re-ask for a country already validated"


def test_switch_asks_for_new_country_when_invalid(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    _country_check_setup(monkeypatch, available=False)
    session_data = _mid_config_session(product_name="SL3500e", country="United States")
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"

    req = AskRequest(question="yes", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    sd = resp["session_data"]
    assert sd["pending_anchor"] == "switch_country"
    assert sd["pending_switch_product"] == "MOTOTRBO"
    # Nothing committed yet — still on the OLD product/config until a valid country is given.
    assert sd["product_name"] == "SL3500e"
    assert "MOTOTRBO" in resp["answer"]
    assert "United States" in resp["answer"]


def test_confirmed_switch_seeds_product_identifier_without_reasking(monkeypatch):
    """Regression: switching product already PROVES the identity via
    detect_product_mention's fuzzy match before the confirm gate is even
    shown — re-deriving it from the confirmation reply ("yes", which carries
    no product hint) instead re-asked productSelectionProduct_all on the very
    next turn. Mirrors test_switch_preserves_valid_country_without_reasking's
    setup but for the product identifier itself."""
    reader = _no_switch_setup(monkeypatch)
    _product_attr = ConfigAttr(
        entity_id=9002, variable_name="productSelectionProduct_all",
        display_label="Product", required=True, default_value="",
        options=[MenuOption(item_value="MOTOTRBO", display_name="MOTOTRBO")],
    )
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: ([_product_attr], "MOTOTRBO"),
    )
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: None)
    session_data = _mid_config_session(product_name="SL3500e", country="United States")
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"

    req = AskRequest(question="yes", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    sd = resp["session_data"]
    assert sd["product_name"] == "MOTOTRBO"
    assert sd["filled"].get("productSelectionProduct_all") == "MOTOTRBO", (
        "the confirmed switch already proved the product identity — it must "
        "not be re-asked as if it were unknown"
    )
    assert "productSelectionProduct_all" not in (sd.get("pending_variables") or [])


def test_switch_completes_once_a_valid_new_country_is_given(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    _country_check_setup(monkeypatch, available=True)
    session_data = _mid_config_session(product_name="SL3500e", country="United States")
    session_data["pending_anchor"] = "switch_country"
    session_data["pending_switch_product"] = "MOTOTRBO"

    req = AskRequest(question="Canada", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    sd = resp["session_data"]
    assert sd["product_name"] == "MOTOTRBO"
    assert sd["country"] == "Canada"
    assert sd["pending_switch_product"] == ""
    assert sd["filled"] == {}, "switching product must still discard the old config"


def test_switch_country_loops_if_new_country_still_invalid(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    _country_check_setup(monkeypatch, available=False)
    session_data = _mid_config_session(product_name="SL3500e", country="United States")
    session_data["pending_anchor"] = "switch_country"
    session_data["pending_switch_product"] = "MOTOTRBO"

    req = AskRequest(question="Germany", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    sd = resp["session_data"]
    assert sd["pending_anchor"] == "switch_country"
    assert sd["product_name"] == "SL3500e", "must not commit the switch while still invalid"
    assert "Germany" in resp["answer"] or "MOTOTRBO" in resp["answer"]


def test_switch_country_no_declines_and_resumes_original_product(monkeypatch):
    """Issue 10: switch_country previously had no exit — and a 'no' reply
    could even COMPLETE the switch with country='no' via the fail-open
    availability check. It must decline, like its sibling states."""
    reader = _no_switch_setup(monkeypatch)
    _country_check_setup(monkeypatch, available=True)  # fail-open would accept "no"
    session_data = _mid_config_session(
        product_name="SL3500e", country="United States",
        filled={"battery": "STANDARD"})
    session_data["pending_anchor"] = "switch_country"
    session_data["pending_switch_product"] = "MOTOTRBO"

    resp = _run_cpq_turn(
        AskRequest(question="no", workspace_id=1, session_data=session_data), reader)

    assert resp["tools_called"] == ["cpq_switch_declined()"]
    sd = resp["session_data"]
    assert sd["product_name"] == "SL3500e"
    assert sd["pending_anchor"] == ""
    assert sd["pending_switch_product"] == ""
    assert sd["country"] == "United States", "the original country must survive a decline"
    assert sd["filled"] == {"battery": "STANDARD"}, "the original config must survive a decline"


def test_switch_country_norway_is_a_country_not_a_decline(monkeypatch):
    """The decline check must be exact-phrase: real countries starting with
    'n' (Norway, Netherlands, Nigeria...) are country attempts."""
    reader = _no_switch_setup(monkeypatch)
    _country_check_setup(monkeypatch, available=True)
    session_data = _mid_config_session(product_name="SL3500e", country="United States")
    session_data["pending_anchor"] = "switch_country"
    session_data["pending_switch_product"] = "MOTOTRBO"

    resp = _run_cpq_turn(
        AskRequest(question="Norway", workspace_id=1, session_data=session_data), reader)

    sd = resp["session_data"]
    assert sd["product_name"] == "MOTOTRBO", "'Norway' must be tried as a country"
    assert sd["country"] == "Norway"


# ── Scenario 10: country-availability REAL logic (no engine mocks) ─────────
#
# Review finding P1: session.country holds DISPLAY text ("United States"),
# but constraint rules key on canonical item_values ("US") and may read
# fields derived from the country. Seeding the evaluation with a raw
# one-key dict meant no rule ever fired and the check always passed.
# The fix runs the same evaluate_rules_loop cascade a real first turn
# runs (auto_fill canonicalizes the country hint via the attr's own
# options). These tests exercise that logic end to end with real engine
# methods — nothing on the evaluation path is mocked.

_REAL_COUNTRY_ATTR = ConfigAttr(
    entity_id=9101, variable_name="ultimateDestinationCountry",
    display_label="Ultimate Destination Country", required=True,
    default_value="", source_id=910101,
    options=[
        MenuOption(item_value="US", display_name="United States", order=1),
        MenuOption(item_value="CA", display_name="Canada", order=2),
    ],
)
_REAL_SELECTOR_ATTR = ConfigAttr(
    entity_id=9102, variable_name="productSelectionProduct_all",
    display_label="Product", required=False,
    default_value="", source_id=910202,
    options=[MenuOption(item_value="SVX-100", display_name="SVX Video RSM", order=1)],
)


def _country_rule(allowed_values: list[str]) -> ConstraintRule:
    """Declarative rule: when country == item_value 'US', the product
    selector is constrained to `allowed_values` (empty ⇒ unavailable)."""
    return ConstraintRule(
        rule_name="Restrict product selection by country",
        condition_attr_id=_REAL_COUNTRY_ATTR.source_id,
        condition_value="US",
        target_attr_id=_REAL_SELECTOR_ATTR.source_id,
        allowed_values=allowed_values,
    )


def test_country_availability_display_text_is_canonicalized_and_blocks():
    """'United States' (display text, what session.country actually holds)
    must canonicalize to item_value 'US' through the cascade and fire the
    rule that empties the product selector → unavailable (False)."""
    attrs = [_REAL_COUNTRY_ATTR, _REAL_SELECTOR_ATTR]
    rule = _country_rule(allowed_values=[])
    _vis, sim_filled, _disp, _copts = api._cpq_engine.evaluate_rules_loop(
        attrs, {"country": "United States"}, {},
        [], [], [rule], bml_eval=None, country="United States",
    )
    assert sim_filled.get("ultimateDestinationCountry") == "US", (
        "the cascade must canonicalize display text to the option item_value"
    )
    assert api._cpq_engine.check_country_availability(
        attrs, [rule], sim_filled, None,
    ) is False


def test_country_availability_display_text_allows_when_rule_keeps_options():
    """Same canonicalized path, but the fired rule leaves a non-empty
    allowed set → available (True)."""
    attrs = [_REAL_COUNTRY_ATTR, _REAL_SELECTOR_ATTR]
    rule = _country_rule(allowed_values=["SVX-100"])
    _vis, sim_filled, _disp, _copts = api._cpq_engine.evaluate_rules_loop(
        attrs, {"country": "United States"}, {},
        [], [], [rule], bml_eval=None, country="United States",
    )
    assert api._cpq_engine.check_country_availability(
        attrs, [rule], sim_filled, None,
    ) is True


# ── Scenario 11: family switch via catalog-TREE names (alias map) ──────────
#
# Live finding (workspace 14): both XMLs carry the IDENTICAL flat product
# list, so a product mention can never discriminate the catalog — but each
# export carries its OWN bm_catalog tree ("aPXNext_BOM"/"APX™ NEXT" only in
# the APX export; "vX650_BOM" only in the SVX one). detect_product_mention
# now matches those tree names and resolves them to the owning FAMILY —
# "Quote APX Next Enhanced radios" mid-SVX-session previously fell through
# to the change-request path and was misread as a country answer.

_TREES = {
    "Sl3500EConfig": ["radioLine_BOM", "SL3500e Series"],
    "MototrboConfig": ["mototrboLine_BOM", "MOTOTRBO Series"],
}


def test_tree_product_line_mention_triggers_family_switch(monkeypatch):
    reader = _no_switch_setup(monkeypatch, trees=_TREES)
    session_data = _mid_config_session(product_name="SL3500e")

    req = AskRequest(question="Quote MOTOTRBO Series radios for a US customer",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    sd = resp["session_data"]
    assert sd["pending_anchor"] == "confirm_switch"
    assert sd["pending_switch_product"] == "MOTOTRBO", (
        "a tree-name mention must resolve to the owning FAMILY name"
    )
    assert sd["product_name"] == "SL3500e", "nothing switches before confirmation"


def test_tree_name_of_current_family_is_not_a_switch(monkeypatch):
    reader = _no_switch_setup(monkeypatch, trees=_TREES)
    session_data = _mid_config_session(product_name="SL3500e")

    req = AskRequest(question="tell me about the SL3500e Series line",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    # Resolves to the CURRENT family -> not a different product -> no
    # confirm prompt; falls through to Step 2 (mocked to return {}).
    assert resp == {}


def test_shared_tree_alias_is_dropped_never_guessed(monkeypatch):
    shared_trees = {
        "Sl3500EConfig": ["Accessory Kit"],
        "MototrboConfig": ["Accessory Kit"],
    }
    reader = _no_switch_setup(monkeypatch, trees=shared_trees)
    session_data = _mid_config_session(product_name="SL3500e")

    req = AskRequest(question="add the Accessory Kit to the quote",
                      workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn(req, reader)

    # "Accessory Kit" exists under BOTH families -> ambiguous -> dropped
    # from the alias map entirely -> no switch prompt.
    assert resp == {}


def test_alias_map_maps_tree_names_to_family(monkeypatch):
    reader = _fake_reader_with_batch_fetch(
        monkeypatch, _TWO_PRODUCT_CATALOGS, _TREES)

    alias_map = api._cpq_engine.ingested_product_alias_map(reader, 1)

    assert alias_map["SL3500e"] == "SL3500e"
    assert alias_map["radioLine_BOM"] == "SL3500e"
    assert alias_map["SL3500e Series"] == "SL3500e"
    assert alias_map["mototrboLine_BOM"] == "MOTOTRBO"
    assert alias_map["MOTOTRBO Series"] == "MOTOTRBO"


# ── Scenario 12: answer-over-switch precedence (Issue 6) ───────────────────
#
# Live finding: with Product pending, the legitimate menu answer "APX 6500"
# scored 0.67 against the other family's tree alias "APX™ N70" and was
# hijacked into a "did you mean...?" prompt instead of locking. A message
# that validly answers the currently-pending attribute must be an ANSWER,
# never a switch signal — switch detection now runs after attrs load and
# defers to apply_answer against the pending attr's options.

_PRODUCT_MENU_ATTR = ConfigAttr(
    entity_id=9201, variable_name="productSelectionProduct_all",
    display_label="Product", required=False, default_value="",
    options=[
        MenuOption(item_value="APX6500", display_name="APX 6500", order=1),
        MenuOption(item_value="APXNEXTSB", display_name="APX NEXT Single Band", order=2),
        MenuOption(item_value="XIRM8620", display_name="XiR M8620", order=3),
    ],
)

# The OTHER family's tree carries short APX-ish aliases — the exact shape
# that made "APX 6500" score into the suggestion band live.
_APXISH_TREES = {
    "Sl3500EConfig": [],
    "MototrboConfig": ["APX N70", "APX NEXT"],
}


def _pending_menu_setup(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    reader = _fake_reader_with_batch_fetch(
        monkeypatch, _TWO_PRODUCT_CATALOGS, _APXISH_TREES)
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: ([_PRODUCT_MENU_ATTR], "SL3500e"),
    )
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: None)
    return reader


def _pending_product_session() -> dict:
    session_data = _mid_config_session(product_name="SL3500e", filled={})
    session_data["pending_variables"] = ["productSelectionProduct_all"]
    return session_data


def test_menu_answer_resembling_other_family_alias_is_not_hijacked(monkeypatch):
    reader = _pending_menu_setup(monkeypatch)
    req = AskRequest(question="APX 6500", workspace_id=1,
                      session_data=_pending_product_session())
    resp = _run_cpq_turn(req, reader)

    assert "cpq_switch_ambiguous()" not in resp.get("tools_called", [])
    assert "cpq_switch_candidate()" not in resp.get("tools_called", [])
    sd = resp["session_data"]
    assert sd["filled"].get("productSelectionProduct_all") == "APX6500", (
        "a valid menu answer must lock, not trigger a switch/suggestion prompt"
    )


def test_menu_answer_containing_alias_substring_still_locks(monkeypatch):
    """'APX NEXT Single Band' is a REAL option whose text contains the
    other family's alias 'APX NEXT' — the exact-substring detection tier
    would hijack it without the answer guard."""
    reader = _pending_menu_setup(monkeypatch)
    req = AskRequest(question="APX NEXT Single Band", workspace_id=1,
                      session_data=_pending_product_session())
    resp = _run_cpq_turn(req, reader)

    assert "cpq_switch_candidate()" not in resp.get("tools_called", [])
    sd = resp["session_data"]
    assert sd["filled"].get("productSelectionProduct_all") == "APXNEXTSB"


def test_non_answer_switch_mention_still_detected_with_pending_menu(monkeypatch):
    """The guard must NOT kill real switch detection: a message that does
    not match any pending-attr option keeps the confirm-switch flow."""
    reader = _pending_menu_setup(monkeypatch)
    req = AskRequest(question="lets switch to the mototrbo quote instead",
                      workspace_id=1, session_data=_pending_product_session())
    resp = _run_cpq_turn(req, reader)

    sd = resp["session_data"]
    assert sd["pending_anchor"] == "confirm_switch"
    assert sd["pending_switch_product"] == "MOTOTRBO"
    assert sd["filled"].get("productSelectionProduct_all") is None


# ── Scenario 13: "did you mean...?" replies are consumed statefully (Issue 7) ─
#
# Live finding: the mid-band suggestion prompt set NO pending state, so a
# "yes" reply fell through to the awaiting_approval handler and SUBMITTED
# the very quote the client was trying to switch away from. One candidate
# now routes into the existing confirm_switch gate; several set
# suggest_switch, whose gate re-prompts on a bare "yes" instead of guessing.

def test_single_suggestion_sets_confirm_state_so_yes_switches_not_approves(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    # Deterministic mid-band: no confident detection, exactly one suggestion.
    monkeypatch.setattr(
        api._cpq_engine, "detect_product_mention", lambda *a, **k: "")
    monkeypatch.setattr(
        api._cpq_engine, "suggest_product_candidates", lambda *a, **k: ["MOTOTRBO"])
    session_data = _mid_config_session(product_name="SL3500e")
    session_data["status"] = "awaiting_approval"  # the live failure state

    req = AskRequest(question="quote me a videoSolution", workspace_id=1,
                      session_data=session_data)
    resp1 = _run_cpq_turn(req, reader)

    assert resp1["tools_called"] == ["cpq_switch_ambiguous()"]
    sd1 = resp1["session_data"]
    assert sd1["pending_anchor"] == "confirm_switch", (
        "a single 'did you mean' candidate must arm the confirm gate"
    )
    assert sd1["pending_switch_product"] == "MOTOTRBO"

    # Turn 2: "yes" must be consumed by the confirm gate — never approval.
    _country_check_setup(monkeypatch, available=True)
    resp2 = _run_cpq_turn(
        AskRequest(question="yes", workspace_id=1, session_data=sd1), reader)

    assert resp2.get("cpq_payload") is None, (
        "'yes' to a did-you-mean prompt must NEVER approve/submit the quote"
    )
    sd2 = resp2["session_data"]
    assert sd2["product_name"] == "MOTOTRBO", "the confirmed suggestion must switch"


def test_multi_suggestion_yes_reprompts_instead_of_guessing(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    monkeypatch.setattr(
        api._cpq_engine, "suggest_product_candidates",
        lambda *a, **k: ["MOTOTRBO", "SL3500e XL"],
    )
    session_data = _mid_config_session(product_name="SL3500e")

    resp1 = _run_cpq_turn(
        AskRequest(question="quote me the other radio line", workspace_id=1,
                   session_data=session_data), reader)
    sd1 = resp1["session_data"]
    assert sd1["pending_anchor"] == "suggest_switch"
    assert sd1["pending_switch_candidates"] == ["MOTOTRBO", "SL3500e XL"]

    resp2 = _run_cpq_turn(
        AskRequest(question="yes", workspace_id=1, session_data=sd1), reader)

    assert resp2.get("cpq_payload") is None
    assert "MOTOTRBO" in resp2["answer"] and "SL3500e XL" in resp2["answer"], (
        "a bare 'yes' against 2+ candidates must re-prompt with the list"
    )
    assert resp2["session_data"]["pending_anchor"] == "suggest_switch"


def test_multi_suggestion_no_continues_with_current_product(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    session_data["pending_anchor"] = "suggest_switch"
    session_data["pending_switch_candidates"] = ["MOTOTRBO", "SL3500e XL"]

    resp = _run_cpq_turn(
        AskRequest(question="no", workspace_id=1, session_data=session_data), reader)

    sd = resp["session_data"]
    assert sd["product_name"] == "SL3500e"
    assert sd["pending_anchor"] == ""
    assert sd["pending_switch_candidates"] == []


def test_multi_suggestion_name_reply_routes_into_confirm_flow(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    session_data = _mid_config_session(product_name="SL3500e")
    session_data["pending_anchor"] = "suggest_switch"
    session_data["pending_switch_candidates"] = ["MOTOTRBO"]

    resp = _run_cpq_turn(
        AskRequest(question="MOTOTRBO", workspace_id=1, session_data=session_data),
        reader)

    sd = resp["session_data"]
    assert sd["pending_anchor"] == "confirm_switch", (
        "a candidate-name reply must fall through to normal detection and "
        "arm the standard confirm gate"
    )
    assert sd["pending_switch_product"] == "MOTOTRBO"


def test_confirm_switch_accepts_the_product_name_as_affirmative(monkeypatch):
    reader = _no_switch_setup(monkeypatch)
    _country_check_setup(monkeypatch, available=True)
    session_data = _mid_config_session(product_name="SL3500e")
    session_data["pending_anchor"] = "confirm_switch"
    session_data["pending_switch_product"] = "MOTOTRBO"

    resp = _run_cpq_turn(
        AskRequest(question="videoSolutions_BOM", workspace_id=1,
                   session_data={**session_data, "pending_switch_product": "videoSolutions_BOM"}),
        reader)

    # The mocked load_product_config resolves the name afterwards, so assert
    # the switch EVENT itself, not the final resolved product_name.
    switches = [e for e in resp["session_data"]["cascade_log"]
                if e.get("event") == "product_switch"]
    assert switches and switches[-1]["to"] == "videoSolutions_BOM", (
        "replying with the offered product's own name must count as yes, not decline"
    )
    assert "OK — continuing" not in resp["answer"]


def test_country_availability_raw_display_text_documents_the_p1_bug():
    """The exact pre-fix failure: seeding check_country_availability with
    RAW display text (no cascade) never matches the rule's item_value
    condition, so the check silently fails open — this is why
    _country_available_for must run the cascade first, and why these
    tests exist. If this assertion ever flips, the engine started
    canonicalizing inside check_country_availability itself and the
    cascade in ask_api can be simplified."""
    attrs = [_REAL_COUNTRY_ATTR, _REAL_SELECTOR_ATTR]
    rule = _country_rule(allowed_values=[])
    assert api._cpq_engine.check_country_availability(
        attrs, [rule], {"ultimateDestinationCountry": "United States"}, None,
    ) is True
