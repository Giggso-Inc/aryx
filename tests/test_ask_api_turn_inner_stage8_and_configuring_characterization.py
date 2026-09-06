"""Golden-master characterization tests for `_run_cpq_turn_inner`'s
Stage 8 (the awaiting_approval/post_approval routing sub-machine, ~lines
10744-11238) and Stages 9-13 (the mid-configuration routing block —
response-mode/label-collision/attr-query detection, mid-config change-
request handling, and STEP 5's answer-locking, ~lines 11240-12047 in the
current file) of src/aryx/api/ask_api.py.

This is step 1 of Phase 4 of docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md
("Phase 4 planning analysis"): pinning CURRENT behavior (bugs included,
documented not fixed) before a future refactor splits this 3,640-line
function into a shared-context-object design. Sibling files for the SAME
function's other stages were already written in a prior session
(tests/test_ask_api_cascade_multi_and_llm_first_gateway_characterization.py,
tests/test_ask_api_dispatch_intent_result_gap_characterization.py) — this
file does not duplicate their coverage.

Method: follows the exact pattern established by
tests/test_cpq_llm_first_universal_cutover_2026_08_13.py and
tests/test_ask_api_cascade_multi_and_llm_first_gateway_characterization.py
-- `_run_cpq_turn_inner(req, object())` called directly (the `reader` arg
is `object()` unless a test needs `_handle_cpq_qa`'s graph lookup, in which
case `_handle_cpq_qa` itself is patched instead of standing up a real
FalkorDB reader), only the DB/catalog-config loaders on `_cpq_engine` are
stubbed (`load_product_config`, `load_hiding_rules`,
`load_recommendation_and_constraint_rules`, `load_validation_rules`,
`build_bml_evaluator`) so the real matching/rule-evaluation/session-mutation
logic runs unmodified. `cpq_llm_first_enabled` is forced off for every test
in this file so the LLM-first gateway (`_llm_first_gateway_turn`,
`gateway_classify_intent`) never intercepts the turn before it reaches the
deterministic regex/collision/STEP-5 branches this file targets -- that
gateway's own behavior is already covered by the two sibling
characterization files above and by test_cpq_llm_first_universal_cutover_
2026_08_13.py / test_cpq_llm_verdict_checkpoint_2026_08_13.py.

No pre-existing test-assumption bugs were hit while writing this file (the
"flat ConfigAttr.required is unreliable" finding from the cascade-multi
sibling file was reused as-is here, not re-discovered) -- see individual
test docstrings for characterized (not fixed) production-code quirks.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, HidingRule, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None, required=False, select_type="single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=required,
        default_value="", options=options or [], select_type=select_type,
    )


def _setup(monkeypatch, attrs, product_name="aSTRO25_bom"):
    """Same lightweight-loader stubbing as the sibling characterization
    files -- real CpqEngine matching/rule-eval logic runs unmodified, only
    the DB/catalog-config loaders are stubbed. `cpq_llm_first_enabled` is
    forced False so the LLM-first gateway never intercepts these turns
    before reaching the deterministic branches under test here."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, product_name))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator",
                         lambda *a, **k: BmlEvaluator({}))
    # `_handle_cascade` (reached by any change-request/cascade-triggering
    # test in this file) calls `resolve_always_ask_skips`, which in turn
    # calls `resolve_ui_layout_scope` -- an OCI-DB-backed lookup with no
    # stub here previously. Under ARYX_DB_BACKEND=oci with no real DB
    # reachable, that call blocks indefinitely (near-zero CPU, no
    # progress) instead of raising -- same discipline as the sibling file
    # tests/test_cpq_llm_first_universal_cutover_2026_08_13.py, which
    # already stubs this for the same reason.
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    # A completed cascade (all attrs resolved) calls `_cpq_summary_text`,
    # which calls the real `llm_runtime.chat` to narrate the summary --
    # under ARYX_DB_BACKEND=oci with no real OCI credentials/network
    # reachable, that blocks for minutes trying instance-principal auth
    # (confirmed via a SIGALRM traceback dump: oci.auth...urlopen ->
    # llm_runtime.chat -> _cpq_summary_text -> _handle_cascade). Same
    # discipline as tests/test_cpq_summary_matches_beautify_mandatory_
    # 2026_08_19.py: force it to raise so `_cpq_summary_text` takes its
    # own documented fallback to the deterministic `render_filled_summary`
    # bullet list instead of ever reaching the network.
    def _boom_chat(*a, **k):
        raise RuntimeError("no LLM narrator in this test — force the deterministic fallback")
    monkeypatch.setattr(api.llm_runtime, "chat", _boom_chat)
    # The "session-level product quantity" block (~line 8886) runs
    # UNCONDITIONALLY on every turn, before any status/stage gate and
    # regardless of `cpq_llm_first_enabled` -- any question with both a
    # digit and a change verb ("change the mounting types quantity to 5")
    # reaches `_llm_confirm_and_extract_quantity`, which calls the real
    # `gateway_classify_intent` -> real OCI network auth, hanging for
    # minutes with no real network reachable (confirmed via a SIGALRM
    # traceback dump). `_llm_confirm_and_extract_quantity` already
    # reject-on-failures any exception from the gateway call back to
    # confirmed=False -- forcing it to raise here is a no-op for every
    # test that doesn't care about this background quantity capture.
    def _boom_gateway_classify_intent(*a, **k):
        raise RuntimeError("no LLM gateway in this test — force reject-on-failure")
    monkeypatch.setattr(api, "gateway_classify_intent", _boom_gateway_classify_intent)
    real_settings = api.get_settings()
    patched_settings = real_settings.model_copy(update={
        "cpq_llm_first_enabled": False,
        "cpq_llm_first_universal_enabled": False,
    })
    monkeypatch.setattr(api, "get_settings", lambda: patched_settings)


# ═══════════════════════════════════════════════════════════════════════
# STAGE 8 — awaiting_approval / post_approval routing sub-machine
# ═══════════════════════════════════════════════════════════════════════

def test_stage8_json_preview_request_wins_before_approval_and_qa_checks(monkeypatch):
    """"show me the json" while awaiting_approval must route to
    _build_json_preview_response, checked BEFORE detect_approval/Q&A/change
    detection so it's never misread as one of those."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    _setup(monkeypatch, [battery])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval",
                          filled={"batteryType_astro": "STANDARD"},
                          display_filled={"batteryType_astro": "STANDARD"}, turn=3)
    req = AskRequest(question="show me the json", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    # _build_json_preview_response's own docstring: "Preview only -- never
    # sets cpq_payload, never mutates session.status." Only STEP 8's real
    # approval (_handle_approval) ever sets cpq_payload.
    assert resp["cpq_payload"] is None
    assert "```json" in resp["answer"]
    assert "preview, not final" in resp["answer"]
    assert resp["session_data"]["status"] == "awaiting_approval"


def test_stage8_explicit_approval_generates_bom_payload(monkeypatch):
    """detect_approval("confirm") -> _handle_approval -> STEP 8: real BOM
    payload generation, status becomes post_approval."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    _setup(monkeypatch, [battery])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval",
                          filled={"batteryType_astro": "STANDARD"},
                          display_filled={"batteryType_astro": "STANDARD"}, turn=3)
    req = AskRequest(question="confirm", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["cpq_payload"] is not None
    assert resp["session_data"]["status"] == "post_approval"


def test_stage8_pending_label_collision_index_resolves_and_resumes_original_question(
    monkeypatch,
):
    """A prior turn's detect_label_collision (inside _handle_cpq_qa) stored
    2 colliding candidates + the original question. Replying with the
    1-based list index resolves it and resumes the ORIGINAL question via
    _handle_cpq_qa(resume_review=True) -- pinned by patching _handle_cpq_qa
    and asserting it is called with the re-injected original question."""
    a = _attr(1, "productInformationText_astro", "Product")
    b = _attr(2, "productSelectionProduct_all", "Product")
    _setup(monkeypatch, [a, b])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval", turn=4,
        pending_label_collision_vns=["productInformationText_astro", "productSelectionProduct_all"],
        pending_label_collision_question="what values are available for Product?",
    )
    req = AskRequest(question="2", workspace_id=1, session_data=session.to_dict())
    with patch.object(api, "_handle_cpq_qa") as mock_qa:
        mock_qa.return_value = {
            "answer": "resumed", "terms": [], "tools_called": [], "usage": {},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
        _run_cpq_turn_inner(req, object())
    mock_qa.assert_called_once()
    _call_req = mock_qa.call_args.args[0]
    assert _call_req.question == "what values are available for Product?"
    assert mock_qa.call_args.kwargs.get("resume_review") is True
    # `session` in this test's own scope is a separate object -- the turn
    # reconstructs its own session via CpqSession.from_dict internally and
    # mutates THAT object, which is passed as _handle_cpq_qa's own 2nd
    # positional arg.
    _call_session = mock_qa.call_args.args[1]
    assert _call_session.pending_label_collision_vns == []
    assert _call_session.pending_label_collision_question == ""


def test_stage8_pending_label_collision_system_initiated_asks_next_pending(monkeypatch):
    """System-initiated collision (no original question stored, per
    _label_collision_for): resolving it re-asks the now-disambiguated attr
    directly as the next pending question, never resumes a Q&A."""
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product",
              options=_opt("APX NEXT", "APX 8000"))
    _setup(monkeypatch, [a, b])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval", turn=4,
        pending_label_collision_vns=["productInformationText_astro", "productSelectionProduct_all"],
        pending_label_collision_question="",
    )
    req = AskRequest(question="productSelectionProduct_all", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_pending_question_collision_resolved()"]
    assert resp["session_data"]["pending_label_collision_vns"] == []
    assert resp["session_data"]["pending_variables"][0] == "productSelectionProduct_all"


def test_stage8_pending_label_collision_llm_fallback_resolves(monkeypatch):
    """Neither exact variable_name nor a 1-based index matched the reply --
    falls back to _llm_resolve_label_collision for looser phrasing."""
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))
    _setup(monkeypatch, [a, b])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval", turn=4,
        pending_label_collision_vns=["productInformationText_astro", "productSelectionProduct_all"],
        pending_label_collision_question="",
    )
    req = AskRequest(question="the second one, the actual product selector",
                      workspace_id=1, session_data=session.to_dict())
    with patch.object(api, "_llm_resolve_label_collision",
                       return_value="productSelectionProduct_all"):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["pending_variables"][0] == "productSelectionProduct_all"


def test_stage8_pending_label_collision_unrecognized_reply_clears_and_falls_through(
    monkeypatch,
):
    """Deterministic AND LLM fallback both come up empty -- the stale
    pending state is cleared and the turn falls through to normal routing
    (here: the final review nudge) instead of getting stuck forever."""
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))
    _setup(monkeypatch, [a, b])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval", turn=4,
        pending_label_collision_vns=["productInformationText_astro", "productSelectionProduct_all"],
        pending_label_collision_question="",
    )
    req = AskRequest(question="huh what", workspace_id=1, session_data=session.to_dict())
    with patch.object(api, "_llm_resolve_label_collision", return_value=None):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["pending_label_collision_vns"] == []
    assert resp["tools_called"] == ["cpq_review_nudge()"]


def test_stage8_qa_during_review_resumes_review_after_answering(monkeypatch):
    """STEP 7: a real graph question during awaiting_approval is answered
    via _handle_cpq_qa(resume_review=True) -- pinned via patching
    _handle_cpq_qa itself since standing up a real FalkorDB reader is out
    of scope for this characterization."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    _setup(monkeypatch, [battery])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval",
                          filled={"batteryType_astro": "STANDARD"}, turn=3)
    req = AskRequest(question="what is the STANDARD battery type made of?", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(api, "_handle_cpq_qa") as mock_qa:
        mock_qa.return_value = {
            "answer": "it is a lithium battery", "terms": [], "tools_called": [],
            "usage": {}, "grounding": None, "session_data": session.to_dict(),
            "cpq_payload": None,
        }
        _run_cpq_turn_inner(req, object())
    mock_qa.assert_called_once()
    assert mock_qa.call_args.kwargs.get("resume_review") is True


def test_stage8_pending_change_collision_resolves_and_cascades(monkeypatch):
    """A prior turn's detect_change_request_collision asked "which one did
    you mean?" -- replying with the variable_name resolves it, re-derives
    the value from the ORIGINAL message against the now-disambiguated
    attr, and applies it via _handle_cascade."""
    info = _attr(1, "productInformationText_astro", "Product Information Text")
    prod = _attr(2, "productSelectionProduct_all", "Product",
                 options=_opt("APX NEXT", "APX 8000"))
    _setup(monkeypatch, [info, prod])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval", turn=4,
        filled={"productSelectionProduct_all": "APX NEXT"},
        display_filled={"productSelectionProduct_all": "APX NEXT"},
        pending_change_collision_vns=["productInformationText_astro", "productSelectionProduct_all"],
        pending_change_collision_question="change product to APX 8000",
    )
    req = AskRequest(question="productSelectionProduct_all", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["productSelectionProduct_all"] == "APX 8000"
    assert resp["session_data"]["pending_change_collision_vns"] == []


def test_stage8_pending_change_collision_resolved_but_unparseable_value_reasks(monkeypatch):
    """Resolved target, but the ORIGINAL message's value hint doesn't
    resolve to a real option for it (e.g. it was really naming a
    different attr's value) -- re-asked as a genuine pending question
    (status forced back to "configuring") instead of being orphaned."""
    info = _attr(1, "productInformationText_astro", "Product Information Text")
    prod = _attr(2, "productSelectionProduct_all", "Product",
                 options=_opt("APX NEXT", "APX 8000"))
    _setup(monkeypatch, [info, prod])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval", turn=4,
        filled={"productSelectionProduct_all": "APX NEXT"},
        pending_change_collision_vns=["productInformationText_astro", "productSelectionProduct_all"],
        pending_change_collision_question="change product to something totally unrelated blah",
    )
    req = AskRequest(question="productSelectionProduct_all", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_change_label_collision_resolved()"]
    assert resp["session_data"]["status"] == "configuring"
    assert resp["session_data"]["pending_variables"][0] == "productSelectionProduct_all"


def test_stage8_pending_change_collision_unrecognized_reply_clears_and_falls_through(
    monkeypatch,
):
    info = _attr(1, "productInformationText_astro", "Product Information Text")
    prod = _attr(2, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))
    _setup(monkeypatch, [info, prod])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval", turn=4,
        pending_change_collision_vns=["productInformationText_astro", "productSelectionProduct_all"],
        pending_change_collision_question="change product to APX 8000",
    )
    req = AskRequest(question="no idea what you mean", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(api, "_llm_resolve_label_collision", return_value=None):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["pending_change_collision_vns"] == []
    assert resp["tools_called"] == ["cpq_review_nudge()"]


def test_stage8_bulk_quantity_change_applies_during_review(monkeypatch):
    """STEP 6: bulk quantity change ("change both mounting types quantity
    to 67") is checked FIRST among the STEP-6 mutating detectors, even
    during awaiting_approval/post_approval."""
    # `resolve_array_grid_links` (real, unstubbed code -- ask_api.py:5046)
    # only links a selector to a quantity attr when the candidate is
    # `hidden=True` AND its variable_name literally contains "quantity"
    # (its own docstring: "hidden `*Quantity*`-named attrs") -- the
    # original attrs here used "_qty" (not "quantity") and left `hidden`
    # at its default False, so grid_links resolved empty and neither
    # quantity attr was ever actually updated. Renamed/hidden to match the
    # real heuristic's contract instead of assuming it linked on shared
    # substring/prefix alone.
    mount = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                  options=_opt("Shirt Mount", "Jacket Mount"))
    qty_shirt = ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln_ShirtMount_Quantity",
        display_label="Shirt Mount Qty", required=False, default_value="", options=[],
        hidden=True,
    )
    qty_jacket = ConfigAttr(
        entity_id=3, variable_name="mountingTypeArray_viSoln_JacketMount_Quantity",
        display_label="Jacket Mount Qty", required=False, default_value="", options=[],
        hidden=True,
    )
    _setup(monkeypatch, [mount, qty_shirt, qty_jacket], product_name="videoSolutions_BOM")
    session = CpqSession(
        mode="cpq", country="United States", product_name="videoSolutions_BOM", status="awaiting_approval", turn=3,
        filled_multi={"mountingTypeArray_viSoln": ["Shirt Mount", "Jacket Mount"]},
        filled={
            "mountingTypeArray_viSoln_ShirtMount_Quantity": "1",
            "mountingTypeArray_viSoln_JacketMount_Quantity": "1",
        },
    )
    req = AskRequest(question="change the mounting types quantity to 5", workspace_id=1,
                      session_data=session.to_dict())
    # `detect_bulk_quantity_change` returns (selector_variable_name: str,
    # item_values, new_qty: str) per its own docstring/signature -- the
    # original mock passed the ConfigAttr object itself as the first
    # element instead of its `variable_name`, which crashed downstream at
    # `_handle_bulk_quantity_change`'s `grid_links.get(selector_vn, {})`
    # with `TypeError: unhashable type: 'ConfigAttr'` (a dict key lookup
    # needs the hashable variable-name string, not the attr object). Fixed
    # to match the real contract rather than the code.
    with patch.object(api._cpq_engine, "detect_bulk_quantity_change",
                       return_value=(mount.variable_name, ["Shirt Mount", "Jacket Mount"], "5")):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["mountingTypeArray_viSoln_ShirtMount_Quantity"] == "5"
    assert resp["session_data"]["filled"]["mountingTypeArray_viSoln_JacketMount_Quantity"] == "5"


def test_stage8_multi_select_removal_deselects_an_option(monkeypatch):
    """STEP 6: "remove X" during review deselects one option from an
    already-selected multi-select — a distinct intent from a value-
    replacement change request."""
    mount = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                  options=_opt("Shirt Mount", "Jacket Mount"))
    _setup(monkeypatch, [mount], product_name="videoSolutions_BOM")
    session = CpqSession(
        mode="cpq", country="United States", product_name="videoSolutions_BOM", status="awaiting_approval", turn=3,
        filled_multi={"mountingTypeArray_viSoln": ["Shirt Mount", "Jacket Mount"]},
    )
    req = AskRequest(question="remove Jacket Mount", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(api, "_llm_confirm_deterministic_intent", return_value=True):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled_multi"]["mountingTypeArray_viSoln"] == ["Shirt Mount"]


def test_stage8_change_collision_identical_labels_asks_which_one(monkeypatch):
    """Identical-label collision check runs BEFORE detect_change_request,
    which would otherwise silently resolve the tie to whichever attr is
    first in catalog order."""
    info = _attr(1, "productInformationText_astro", "Product Information Text")
    prod = _attr(2, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))
    _setup(monkeypatch, [info, prod])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval",
                          turn=3)
    req = AskRequest(question="change product to X", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(api._cpq_engine, "detect_change_request_collision",
                       return_value=[info, prod]):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_change_label_collision()"]
    assert resp["session_data"]["pending_change_collision_vns"] == [
        "productInformationText_astro", "productSelectionProduct_all",
    ]
    assert resp["session_data"]["pending_change_collision_question"] == "change product to X"


def test_stage8_change_requests_multi_dispatches_two_named_changes(monkeypatch):
    """STEP 6: 2+ distinct attrs named in one message during review route
    to _handle_cascade_multi, not the single-change path."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD", "EXTENDED"))
    carrier = _attr(2, "carrierSelection_astro", "Carrier", options=_opt("ATT", "Verizon"))
    _setup(monkeypatch, [battery, carrier])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval", turn=3,
        filled={"batteryType_astro": "STANDARD", "carrierSelection_astro": "ATT"},
        display_filled={"batteryType_astro": "STANDARD", "carrierSelection_astro": "ATT"},
    )
    # detect_change_request/_matches (real, unstubbed code) requires the
    # candidate attr's own LABEL to be mentioned -- via `_label_mentioned`
    # / `_label_mention_span` -- not just any word from it: "Battery Type"
    # needs its "type" word present somewhere too (live-verified: a bare
    # "battery" alone matches nothing, confirmed directly against
    # CpqEngine.detect_change_request). The original "change battery to
    # Extended..." phrasing never actually matched the battery attr at
    # all in real behavior.
    req = AskRequest(question="change battery type to Extended and carrier to Verizon",
                      workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_cascade_multi()"]
    assert resp["session_data"]["filled"]["batteryType_astro"] == "EXTENDED"
    assert resp["session_data"]["filled"]["carrierSelection_astro"] == "Verizon"


def test_stage8_single_change_request_dispatches_via_cascade(monkeypatch):
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD", "EXTENDED"))
    _setup(monkeypatch, [battery])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval", turn=3,
        filled={"batteryType_astro": "STANDARD"},
        display_filled={"batteryType_astro": "STANDARD"},
    )
    # Same real-behavior fix as the sibling multi-dispatch test above:
    # "Battery Type"'s label match requires its "type" word present too.
    req = AskRequest(question="change battery type to Extended", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(api, "_llm_confirm_deterministic_intent", return_value=True):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["batteryType_astro"] == "EXTENDED"


def test_stage8_llm_fallback_classifies_a_remove_intent(monkeypatch):
    """Every regex detector found nothing -- _llm_classify_change_intent
    is tried before giving up, reusing the SAME _handle_multi_select_
    removal handler as the regex path."""
    mount = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                  options=_opt("Shirt Mount", "Jacket Mount"))
    _setup(monkeypatch, [mount], product_name="videoSolutions_BOM")
    session = CpqSession(
        mode="cpq", country="United States", product_name="videoSolutions_BOM", status="awaiting_approval", turn=3,
        filled_multi={"mountingTypeArray_viSoln": ["Shirt Mount", "Jacket Mount"]},
    )
    req = AskRequest(question="I don't want the jacket one anymore", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api, "_llm_classify_change_intent",
        return_value=(
            {"intent": "remove", "variable_name": "mountingTypeArray_viSoln",
             "value": "Jacket Mount"},
            5, 5,
        ),
    ):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled_multi"]["mountingTypeArray_viSoln"] == ["Shirt Mount"]


def test_stage8_llm_fallback_change_with_no_value_asks_which_value(monkeypatch):
    """The LLM correctly named the target attr but had nothing to set it
    to -- asks which value instead of discarding the identified target."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD", "EXTENDED"))
    _setup(monkeypatch, [battery])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval",
                          filled={"batteryType_astro": "STANDARD"}, turn=3)
    req = AskRequest(question="change the battery please", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api, "_llm_classify_change_intent",
        return_value=(
            {"intent": "change", "variable_name": "batteryType_astro", "value": ""}, 5, 5,
        ),
    ):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["batteryType_astro"] == "STANDARD"
    assert "Battery Type" in resp["answer"]


def test_stage8_change_target_without_value_asks_which_value(monkeypatch):
    """detect_change_target_without_value: a recognized change-verb naming
    an already-filled attr with no resolvable new value asks which value
    instead of falling through to the generic review nudge."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD", "EXTENDED"))
    _setup(monkeypatch, [battery])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval",
                          filled={"batteryType_astro": "STANDARD"}, turn=3)
    req = AskRequest(question="change battery type", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    # `_build_no_value_response` (real, unstubbed code) always names the
    # target attr in the tool-call string, never a bare `()` -- same fix
    # as the mid-config sibling test above.
    assert resp["tools_called"] == ["cpq_change_target_no_value(batteryType_astro)"]
    assert resp["session_data"]["filled"]["batteryType_astro"] == "STANDARD"


def test_stage8_unrecognized_message_falls_through_to_review_nudge(monkeypatch):
    """Zero prior direct-name coverage anywhere in tests/ for
    "cpq_review_nudge()" (confirmed by repo-wide grep): could not parse as
    approval, Q&A, change, or JSON request -- nudges with the verbose
    summary, never the raw JSON (JSON stays on-demand only)."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    _setup(monkeypatch, [battery])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="awaiting_approval",
                          filled={"batteryType_astro": "STANDARD"},
                          display_filled={"batteryType_astro": "STANDARD"}, turn=3)
    req = AskRequest(question="asdkjhasd nonsense gibberish", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_review_nudge()"]
    assert "I didn't quite catch that" in resp["answer"]
    assert "confirm" in resp["answer"]
    assert resp["cpq_payload"] is None


# ═══════════════════════════════════════════════════════════════════════
# STAGES 9-13 — mid-configuration routing block
# ═══════════════════════════════════════════════════════════════════════

def test_configuring_mode_request_returns_json_preview_when_questions_still_pending(monkeypatch):
    """§6: an explicit response-mode request ("show me the json") detected
    early is consumed at the end of the mid-configuration path (only once
    `pending` is known) -- when there's still an unanswered required attr,
    the answer is the JSON-fenced preview + "Still need: ..." rather than
    the next question prompt.

    NOTE (test-assumption fix): an earlier version of this test tried to
    prove mode_request "wins over" a label collision by giving two attrs
    the same display_label ("Product") and asserting no collision message
    appeared. That was a vacuous setup — the chosen question ("show me the
    json so far") never mentions "Product" at all, so
    detect_label_collision was never going to fire regardless of
    mode_request; and with the fixture's own filled-state, `pending` came
    back empty, so the turn never even reached this branch — it hit an
    entirely different "configuration complete" summary path instead
    (confirmed by running it and reading the actual `resp["answer"]`).
    Simplified to pin what mode_request=="json" actually does when there
    genuinely is a pending attr, which is the behavior this branch exists
    for; real collision-suppression is out of scope for this test."""
    color = _attr(1, "deviceColor_astro", "Device Color", options=_opt("Black", "Silver"), required=True)
    _setup(monkeypatch, [color])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=3)
    req = AskRequest(question="show me the json so far", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    # cpq_payload is only ever generated on STEP 8's real approval -- this
    # branch's own contract is the "preview" flag plus the JSON fenced
    # block inside `answer`, never cpq_payload itself.
    assert resp["cpq_payload"] is None
    assert resp["preview"] is True
    assert "```json" in resp["answer"]
    assert "preview, not final" in resp["answer"]
    assert "Still need: Device Color" in resp["answer"]


def test_configuring_label_collision_asks_which_one(monkeypatch):
    """Shared display_label across 2+ distinct attrs must be disambiguated
    during normal mid-configuration turns too, not just during review."""
    a = _attr(1, "productInformationText_astro", "Product")
    b = _attr(2, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))
    _setup(monkeypatch, [a, b])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=3)
    req = AskRequest(question="tell me about Product", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(api._cpq_engine, "detect_label_collision", return_value=[a, b]):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_label_collision()"]
    assert "which one" in resp["answer"]


def test_configuring_attr_query_answers_available_values(monkeypatch):
    """"what values are available for X?" during active configuring routes
    to _build_attr_query_response."""
    color = _attr(1, "deviceColor_astro", "Device Color", options=_opt("Black", "Silver"))
    _setup(monkeypatch, [color])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=3)
    req = AskRequest(question="what values are available for Device Color?", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert "Black" in resp["answer"] and "Silver" in resp["answer"]


def test_configuring_free_text_constraint_query_describes_the_rule(monkeypatch):
    """Zero prior direct coverage anywhere in tests/ for
    describe_free_text_constraint (confirmed by repo-wide grep): a
    free-text (no-options) pending attr's own constraint description is
    answered without any attr-matching, when a ValidationRule's script
    matches a describable idiom."""
    serial = _attr(1, "serialNumber_astro", "Serial Number", options=[])
    _setup(monkeypatch, [serial])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=3,
                          pending_variables=["serialNumber_astro"])
    req = AskRequest(question="what values are available for serial number?", workspace_id=1,
                      session_data=session.to_dict())
    # detect_attr_query's own word-overlap fallback is checked FIRST and,
    # for a real catalog, often can't resolve a natural paraphrase either
    # (the free-text branch's whole reason to exist) -- but this fixture's
    # attr label happens to literally overlap with the question, which
    # would otherwise route to cpq_attr_query() instead of the free-text
    # branch under test. Forcing it to miss isolates the free-text branch
    # itself, matching this docstring's own "detect_attr_query above can't
    # help here" framing.
    with patch.object(api._cpq_engine, "detect_attr_query", return_value=None), \
         patch.object(api._cpq_engine, "describe_free_text_constraint",
                       return_value="exactly 10 digits"):
        resp = _run_cpq_turn_inner(req, object())
    assert "exactly 10 digits" in resp["answer"]
    assert resp["tools_called"] == ["cpq_free_text_constraint()"]


def test_configuring_step7_qa_strict_answers_and_does_not_lock_pending(monkeypatch):
    """STEP 7 (strict, only ? or Q&A keywords) during active configuring:
    a real graph question about the PENDING attr is answered via
    _handle_cpq_qa(resume_review=False), never locked in as an answer to
    that pending question."""
    color = _attr(1, "deviceColor_astro", "Device Color", options=_opt("Black", "Silver"))
    _setup(monkeypatch, [color])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=3,
                          pending_variables=["deviceColor_astro"])
    req = AskRequest(question="what is device color used for?", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(api, "_handle_cpq_qa") as mock_qa:
        mock_qa.return_value = {
            "answer": "cosmetic finish", "terms": [], "tools_called": [],
            "usage": {}, "grounding": None, "session_data": session.to_dict(),
            "cpq_payload": None,
        }
        _run_cpq_turn_inner(req, object())
    mock_qa.assert_called_once()
    assert mock_qa.call_args.kwargs.get("resume_review") is False


def test_configuring_pending_label_collision_system_initiated_resolves(monkeypatch):
    """The system-initiated next-question collision path is ALSO wired
    into mid-configuration turns (2026-07-26 fix) -- previously it only
    ran inside the awaiting_approval/post_approval branch and was dead
    code for the normal configuring flow."""
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))
    _setup(monkeypatch, [a, b])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=3,
        pending_label_collision_vns=["productInformationText_astro", "productSelectionProduct_all"],
    )
    req = AskRequest(question="1", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_pending_question_collision_resolved()"]
    assert resp["session_data"]["pending_variables"][0] == "productInformationText_astro"


def test_configuring_pending_label_collision_unrecognized_clears_state(monkeypatch):
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product", options=_opt("APX NEXT"))
    _setup(monkeypatch, [a, b])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=3,
        pending_label_collision_vns=["productInformationText_astro", "productSelectionProduct_all"],
    )
    req = AskRequest(question="huh", workspace_id=1, session_data=session.to_dict())
    with patch.object(api, "_llm_resolve_label_collision", return_value=None):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["pending_label_collision_vns"] == []


def test_mid_config_change_requests_multi_dispatches(monkeypatch):
    """Change-request handling is ALSO wired into normal mid-configuration
    turns (Amendment 22 follow-up): a message naming two already-filled
    attrs is dispatched via _handle_cascade_multi even while OTHER
    attributes are still pending."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD", "EXTENDED"))
    carrier = _attr(2, "carrierSelection_astro", "Carrier", options=_opt("ATT", "Verizon"))
    other = _attr(3, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    _setup(monkeypatch, [battery, carrier, other])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=3,
        filled={"batteryType_astro": "STANDARD", "carrierSelection_astro": "ATT"},
        display_filled={"batteryType_astro": "STANDARD", "carrierSelection_astro": "ATT"},
        pending_variables=["hWVersion_astro"],
    )
    # Same real-behavior fix as the Stage 8 sibling above: "Battery
    # Type"'s label match requires its "type" word present too.
    req = AskRequest(question="change battery type to Extended and carrier to Verizon",
                      workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["batteryType_astro"] == "EXTENDED"
    assert resp["session_data"]["filled"]["carrierSelection_astro"] == "Verizon"


def test_mid_config_change_request_no_value_asks_which_value(monkeypatch):
    """A recognized change-verb naming an already-filled attr with no
    resolvable new value, during mid-configuration (a distinct call site
    from Stage 8's own identical-shaped check)."""
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD", "EXTENDED"))
    other = _attr(2, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H2"))
    _setup(monkeypatch, [battery, other])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=3,
        filled={"batteryType_astro": "STANDARD"},
        pending_variables=["hWVersion_astro"],
    )
    req = AskRequest(question="change the battery type", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    # `_build_no_value_response` (real, unstubbed code) always names the
    # target attr in the tool-call string --
    # `f"{tool_name}({target_attr.variable_name})"` -- never a bare
    # `()`; the original assertion's empty-parens form never matches any
    # real call.
    assert resp["tools_called"] == ["cpq_change_target_no_value(batteryType_astro)"]


# ═══════════════════════════════════════════════════════════════════════
# STEP 5 — answer-locking (the 514-line block within stages 9-13)
# ═══════════════════════════════════════════════════════════════════════

def test_step5_single_select_answer_locks_and_advances(monkeypatch):
    """Plain happy path: a pending single-select attr's answer is matched,
    locked into session.filled/display_filled/filled_source, and the turn
    advances past it."""
    color = _attr(1, "deviceColor_astro", "Device Color", options=_opt("Black", "Silver"))
    _setup(monkeypatch, [color])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=2,
                          pending_variables=["deviceColor_astro"])
    req = AskRequest(question="Black", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["deviceColor_astro"] == "Black"
    assert resp["session_data"]["filled_source"]["deviceColor_astro"] == "user"


def test_step5_multi_select_answer_unions_all_named_options(monkeypatch):
    """A multi-select pending answer can name several options at once --
    apply_multi_answer scans for every option mentioned, not just one."""
    mount = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                  options=_opt("Shirt Mount", "Jacket Mount", "Vest Mount"))
    _setup(monkeypatch, [mount], product_name="videoSolutions_BOM")
    session = CpqSession(mode="cpq", country="United States", product_name="videoSolutions_BOM", status="configuring",
                          turn=2, pending_variables=["mountingTypeArray_viSoln"])
    req = AskRequest(question="Shirt Mount and Jacket Mount", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert set(resp["session_data"]["filled_multi"]["mountingTypeArray_viSoln"]) == {
        "Shirt Mount", "Jacket Mount",
    }


def test_step5_validation_rule_rejects_and_re_asks(monkeypatch):
    """A catalog-authored warning-message ValidationRule (Amendment 12)
    must not be silently accepted just because the value fragment-matched
    -- the value is reverted out of session.filled and the same question
    is re-asked with the warning prepended."""
    count = _attr(1, "videoDeviceCount_astro", "Video Device Count", options=[])
    _setup(monkeypatch, [count])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=2,
                          pending_variables=["videoDeviceCount_astro"])
    req = AskRequest(question="13", workspace_id=1, session_data=session.to_dict())
    with patch.object(
        api._cpq_engine, "apply_validation_rules",
        return_value={"videoDeviceCount_astro": "Video device count must be a multiple of 25."},
    ):
        resp = _run_cpq_turn_inner(req, object())
    assert "videoDeviceCount_astro" not in resp["session_data"]["filled"]
    assert resp["tools_called"] == ["cpq_validation_warning()"]
    assert "multiple of 25" in resp["answer"]


def test_step5_cascade_dependent_pop_is_overwritten_by_the_same_turns_auto_fill_pass(
    monkeypatch,
):
    """Test-assumption correction (found while writing this test, same
    category as the sibling cascade-multi file's flat-`required`-field
    finding): the inline comment directly above STEP 5's dependent-
    invalidation code (2026-08-21) claims this closes the SAME gap
    `_handle_cascade` fixes -- that answering a re-asked Hardware Version
    question clears a hiding-rule dependent's stale `filled_multi` value.

    Traced live (patching `_invalidate_stale_base_model` and `auto_fill`
    directly) to confirm what actually happens in THIS harness: the STEP-5
    pop genuinely runs and empties `session.filled_multi` immediately
    afterward -- but STEP 3's rule-evaluation pass (`_recompute_pending`,
    which calls `evaluate_rules_loop`/`auto_fill` with
    `already_filled_multi=session.filled_multi` passed BY REFERENCE) runs
    unconditionally right after, and by the time Amendment 17's SECOND
    `_recompute_pending` call fires later in the same turn,
    `already_filled_multi` already shows `{"carrierSelectionMultiSelect_
    astro": ["ATT"]}` again -- something inside that first evaluate_rules_
    loop/auto_fill pass re-derives/restores the just-popped value before
    the turn ends. `auto_fill` is explicitly documented elsewhere in this
    codebase (docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md's own Phase 4
    analysis) as a 2,056-line method not worth root-causing inside this
    characterization pass -- this test pins the OBSERVED end-of-turn
    behavior (the dependent's stale value survives) rather than the
    comment's claimed intent, so a future split of `_run_cpq_turn_inner`
    can tell whether this behavior was preserved or accidentally fixed."""
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1 4G", "H2 5G"))
    carrier = _attr(2, "carrierSelectionMultiSelect_astro", "Carrier", select_type="multi",
                     options=_opt("ATT", "Verizon"))
    hide_rule = HidingRule(
        rule_name="Hide carrier unless 5G", condition_attr_id=1,
        condition_value="H1 4G", target_attr_id=2, hide=True,
    )
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [hide_rule])
    _setup(monkeypatch, [hw, carrier])
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [hide_rule])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=2,
        pending_variables=["hWVersion_astro"],
        filled_multi={"carrierSelectionMultiSelect_astro": ["ATT"]},
        display_filled={"carrierSelectionMultiSelect_astro": "ATT"},
    )
    req = AskRequest(question="H2 5G", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["hWVersion_astro"] == "H2 5G"
    # Observed (not claimed) behavior: the dependent's stale multi-select
    # value survives the turn -- see docstring above.
    assert resp["session_data"]["filled_multi"]["carrierSelectionMultiSelect_astro"] == ["ATT"]


def test_step5_optional_multi_select_explicit_decline_records_empty_selection(monkeypatch):
    """"no mounts needed" for an OPTIONAL multi-select IS the answer --
    recorded as a user-confirmed empty selection rather than being
    rejected and re-asked forever."""
    mount = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                  required=False, options=_opt("Shirt Mount", "Jacket Mount"))
    _setup(monkeypatch, [mount], product_name="videoSolutions_BOM")
    session = CpqSession(mode="cpq", country="United States", product_name="videoSolutions_BOM", status="configuring",
                          turn=2, pending_variables=["mountingTypeArray_viSoln"])
    req = AskRequest(question="no mounts needed", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled_multi"]["mountingTypeArray_viSoln"] == []
    assert resp["session_data"]["filled_source"]["mountingTypeArray_viSoln"] == "user"


def test_step5_llm_low_confidence_fallback_asks_to_confirm_which_option(monkeypatch):
    """Gap A (Amendment 2): the LLM fallback found 2+ real, plausible
    options -- a judgment call between real options, never silently
    committed to one."""
    color = _attr(1, "deviceColor_astro", "Device Color",
                  options=_opt("Slate Gray", "Storm Gray"))
    _setup(monkeypatch, [color])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=2,
                          pending_variables=["deviceColor_astro"])
    req = AskRequest(question="the gray one", workspace_id=1, session_data=session.to_dict())
    with patch.object(
        api, "_llm_resolve_pending_answer",
        return_value={"confidence": "low", "candidates": ["Slate Gray", "Storm Gray"]},
    ):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_low_confidence_answer()"]
    assert "Slate Gray" in resp["answer"] and "Storm Gray" in resp["answer"]
    assert "deviceColor_astro" not in resp["session_data"]["filled"]


def test_step5_llm_high_confidence_fallback_commits_the_match(monkeypatch):
    """The sibling branch to the low-confidence case: a HIGH-confidence
    LLM pick inside the active (unconstrained here) scope is committed
    directly, same as a real deterministic apply_answer match."""
    color = _attr(1, "deviceColor_astro", "Device Color",
                  options=_opt("Slate Gray", "Storm Gray"))
    _setup(monkeypatch, [color])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=2,
                          pending_variables=["deviceColor_astro"])
    req = AskRequest(question="the darker gray", workspace_id=1, session_data=session.to_dict())
    with patch.object(
        api, "_llm_resolve_pending_answer",
        return_value={"confidence": "high", "iv": "Storm Gray", "disp": "Storm Gray"},
    ):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["deviceColor_astro"] == "Storm Gray"


def test_step5_invalid_answer_with_no_match_reasks_with_scoped_options(monkeypatch):
    """Answer matched nothing at all (deterministic AND LLM fallback both
    failed) -- a scoped re-ask naming the unrecognized text and the still-
    legal options, never a bare "didn't understand". (The actual wording is
    "I didn't get **<answer>** for **<label>** ...", not "didn't recognise"
    -- pinned as observed.)"""
    color = _attr(1, "deviceColor_astro", "Device Color", options=_opt("Black", "Silver"))
    _setup(monkeypatch, [color])
    session = CpqSession(mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=2,
                          pending_variables=["deviceColor_astro"])
    req = AskRequest(question="paisley", workspace_id=1, session_data=session.to_dict())
    with patch.object(api, "_llm_resolve_pending_answer", return_value=None):
        resp = _run_cpq_turn_inner(req, object())
    assert "deviceColor_astro" not in resp["session_data"]["filled"]
    assert resp["tools_called"] == ["cpq_invalid_answer()"]
    assert "I didn't get" in resp["answer"]
    assert "Device Color" in resp["answer"]


def test_step5_pending_reply_topic_switch_skips_answer_locking(monkeypatch):
    """Live-verified gap (2026-07-28): a message with a change verb AND a
    deterministically-named OTHER real attr must never be locked in as an
    answer to the currently-pending (unrelated) question -- it falls
    through to the mid-config change-request block instead."""
    product = _attr(1, "productSelectionProduct_all", "Product", options=_opt(*[f"P{i}" for i in range(5)]))
    solution = _attr(2, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    _setup(monkeypatch, [product, solution])
    session = CpqSession(
        mode="cpq", country="United States", product_name="aSTRO25_bom", status="configuring", turn=2,
        pending_variables=["productSelectionProduct_all"],
        filled={"solutionTypeDevices_astro": "RadioCentral"},
        display_filled={"solutionTypeDevices_astro": "RadioCentral"},
    )
    req = AskRequest(question="change solution type to CloudRC", workspace_id=1,
                      session_data=session.to_dict())
    # Only ONE filled attr is named here, so this falls to the single-
    # match `detect_change_request` branch, which (real, unstubbed code)
    # requires `_llm_confirm_deterministic_intent` to positively confirm
    # via `gateway_classify_intent` before acting -- reject-on-failure
    # discipline means `_setup`'s forced gateway exception (needed
    # elsewhere in this file to avoid a real network hang) would silently
    # swallow this change request instead. Same mock as the Stage 8
    # sibling single-change test.
    with patch.object(api, "_llm_confirm_deterministic_intent", return_value=True):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["solutionTypeDevices_astro"] == "CloudRC"
    assert "productSelectionProduct_all" not in resp["session_data"]["filled"]
