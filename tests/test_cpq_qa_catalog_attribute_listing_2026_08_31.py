"""Live-confirmed gap (2026-08-31): a pre-quote "list the attributes in
APX Next" question fell through detect_attr_query (requires naming ONE
specific attribute) into the generic open-domain graph-search fallback --
which turned out to be structurally unable to answer it at all. A direct
FalkorDB topology check (real workspace 39005) confirmed why: the name-
substring match for "APX Next" resolves to an unrelated Dimension:
Updatedby lookup node, whose own neighbors are Whitelist/Internaloption/
Defaultinattr rows -- never reaching the real ~430 ApxnextConfigdataBm
ConfigAttr entities, no matter how wide the search's limits are set.

Fix: a new matcher in `_handle_cpq_qa`, before the generic fallback,
detects a whole-catalog "enumerate" intent via a cheap LLM classification
call (`_llm_detect_catalog_enumeration_query`, gated behind the existing
`_OPTIONS_KEYWORDS` pre-check so ordinary questions never pay this extra
call) and answers straight from the real, already-loaded `attrs` list
(`_build_catalog_attribute_listing_text`) -- the LLM is used only to
phrase/group the answer, never to recall or infer which attributes exist.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest
from aryx.api.ask_attr_text_helpers import _build_current_quote_attribute_listing_text
from aryx.api.ask_catalog_listing_text import _build_catalog_attribute_listing_text
from aryx.api.ask_handle.ask_handle_cpq_qa import _handle_cpq_qa
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, CpqSession
from aryx.api import ask_core_helpers as _ask_core_helpers_test_module


def _attr(
    eid, vn, label, *, hidden=False, order=999, catalog_prefix="ApxnextConfigdata",
    hide_in_trans=False, set_type="", auto_lock=False,
) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=False,
        default_value="", options=[], select_type="single", hidden=hidden,
        order=order, catalog_prefix=catalog_prefix, hide_in_trans=hide_in_trans,
        set_type=set_type, auto_lock=auto_lock,
    )


def _qa_common_mocks(monkeypatch):
    """Same lightweight monkeypatch pattern used in test_cpq_qa_status_meta_resume.py."""
    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "detect_label_collision", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "detect_attr_query", lambda *a, **k: None)
    monkeypatch.setattr(api, "all_types", lambda *a, **k: [])


# ── _build_catalog_attribute_listing_text: the real-data source ─────────

def test_listing_text_uses_only_real_visible_attrs_never_the_graph():
    attrs = [
        _attr(1, "a_astro", "Instructions and Opt-Out", order=1),
        _attr(2, "b_astro", "Promotions", order=2),
        _attr(3, "c_astro", "Internal Field", hidden=True, order=3),
    ]
    llm_reply = json.dumps({"groups": [
        {"heading": "General", "items": ["Instructions and Opt-Out", "Promotions"]},
    ]})
    with patch(
        "aryx.api.ask_api.llm_runtime.chat",
        return_value=(llm_reply, 10, 5),
    ) as mock_chat, patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ):
        result = _build_catalog_attribute_listing_text(attrs, "APX Next", workspace_id=1)

    assert "Instructions and Opt-Out" in result
    assert "Promotions" in result
    assert "Internal Field" not in result
    mock_chat.assert_called_once()
    _role, _sys, user = mock_chat.call_args[0][:3]
    assert "Instructions and Opt-Out" in user
    assert "Promotions" in user
    assert "Internal Field" not in user, "hidden attrs must never reach the LLM prompt"


def test_listing_text_excludes_attrs_that_never_reach_the_json_payload():
    """Live-confirmed 2026-08-31: `not hidden` alone was too broad -- it
    surfaced obvious payload-noise (session vars, transient UI-control
    fields, non-submittable help-text fields) that build_payload itself
    would never actually include in the real JSON/BOM. This mirrors
    build_payload's own static, attribute-level exclusions."""
    attrs = [
        _attr(1, "wirelessCarrier_astro", "Wireless Carrier", order=1),
        _attr(2, "productInformationText_astro", "Product Information Text",
              order=2, hide_in_trans=True),
        _attr(3, "mergePackage_viSoln", "Merge Package", order=3, set_type="2"),
        _attr(4, "_BM_USER_CURRENCY", "Currency", order=4),
        _attr(5, "archeType_viSoln", "Arche Type", order=5, set_type="2", auto_lock=True),
    ]
    _EMPTY_GROUPS = json.dumps({"groups": []})
    with patch(
        "aryx.api.ask_api.llm_runtime.chat", return_value=(_EMPTY_GROUPS, 0, 0),
    ) as mock_chat, patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ):
        _build_catalog_attribute_listing_text(attrs, "APX Next", workspace_id=1)
    user = mock_chat.call_args[0][2]
    assert "Wireless Carrier" in user
    assert "Arche Type" in user, "set_type=2 WITH auto_lock is a real, includable value"
    assert "Product Information Text" not in user, "hide_in_trans attrs never reach the payload"
    assert "Merge Package" not in user, "set_type=2 without auto_lock is transient, never submitted"
    assert "Currency" not in user, "underscore-prefixed session/system vars are never real BOM selections"


def test_listing_text_deduplicates_shared_labels():
    """The same label can legitimately appear on 2+ distinct attrs (see
    detect_label_collision) -- the customer-facing LIST only needs it
    once, not once per underlying variable_name."""
    attrs = [
        _attr(1, "mountType_viSoln", "Mounting Type", order=1),
        _attr(2, "mountingTypeArray_viSoln", "Mounting Type", order=2),
    ]
    _EMPTY_GROUPS = json.dumps({"groups": []})
    with patch(
        "aryx.api.ask_api.llm_runtime.chat", return_value=(_EMPTY_GROUPS, 0, 0),
    ) as mock_chat, patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ):
        result = _build_catalog_attribute_listing_text(attrs, "SVX", workspace_id=1)
    user = mock_chat.call_args[0][2]
    assert user.count("Mounting Type") == 1
    assert result.count("Mounting Type") == 1


def test_listing_text_reports_the_real_count_to_the_llm():
    attrs = [_attr(i, f"vn{i}", f"Label {i}", order=i) for i in range(50)]
    _EMPTY_GROUPS = json.dumps({"groups": []})
    with patch(
        "aryx.api.ask_api.llm_runtime.chat", return_value=(_EMPTY_GROUPS, 0, 0),
    ) as mock_chat, patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ):
        result = _build_catalog_attribute_listing_text(attrs, "APX Next", workspace_id=1)
    user = mock_chat.call_args[0][2]
    assert "50 items" in user
    for i in range(50):
        assert f"Label {i}" in user, "every real, visible attribute must reach the prompt"
        assert f"Label {i}" in result, "an empty/failed grouping must still surface every real label"


def test_listing_text_excludes_attrs_with_no_real_display_label():
    """Live-confirmed 2026-08-31: several real attrs never got a
    human-readable label from the source XML -- ingestion falls back to
    the raw internal variable_name (sometimes with a suffix trimmed, e.g.
    variable_name="commerceAttrsFlag_all" -> label="commerceAttrsFlag",
    so an exact label==variable_name check alone isn't enough). Showing
    that raw name to a customer is worse than omitting it; letting the
    LLM prettify it into English is exactly the invented-wording the
    hallucination guard blocks. So any label matching camelCase's own
    shape (no spaces, starts lowercase, has an internal capital) is
    dropped entirely -- while a genuine short label/acronym that starts
    uppercase (e.g. "CCAWARE") is kept."""
    attrs = [
        _attr(1, "wirelessCarrier_astro", "Wireless Carrier", order=1),
        _attr(2, "sessionVariable_TER", "sessionVariable_TER", order=2),
        _attr(3, "commerceAttrsFlag_all", "commerceAttrsFlag", order=3),
        _attr(4, "cCAWARE_BOM", "CCAWARE", order=4),
    ]
    _EMPTY_GROUPS = json.dumps({"groups": []})
    with patch(
        "aryx.api.ask_api.llm_runtime.chat", return_value=(_EMPTY_GROUPS, 0, 0),
    ) as mock_chat, patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ):
        result = _build_catalog_attribute_listing_text(attrs, "APX Next", workspace_id=1)
    user = mock_chat.call_args[0][2]
    assert "Wireless Carrier" in user and "Wireless Carrier" in result
    assert "CCAWARE" in user and "CCAWARE" in result, "a real short acronym label must survive"
    assert "sessionVariable_TER" not in user
    assert "sessionVariable_TER" not in result
    assert "commerceAttrsFlag" not in user, "suffix-trimmed camelCase label must also be caught"
    assert "commerceAttrsFlag" not in result


def test_listing_text_drops_hallucinated_items_never_shown_to_customer():
    """Live-confirmed 2026-08-31: at catalog scale the LLM invented
    plausible-sounding filler attributes ("Boolean Continue 1", "Session
    Variable TER") that don't exist anywhere in the real catalog. Any
    item the LLM returns that isn't an EXACT match against the real label
    set must never reach the customer -- and the real labels it dropped
    or never mentioned must still show up (via the Other bucket)."""
    attrs = [
        _attr(1, "a_astro", "Wireless Carrier", order=1),
        _attr(2, "b_astro", "Frequency Band", order=2),
    ]
    llm_reply = json.dumps({"groups": [
        {"heading": "Hardware", "items": [
            "Wireless Carrier", "Boolean Continue 1", "Session Variable TER",
        ]},
    ]})
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(llm_reply, 0, 0)), patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ):
        result = _build_catalog_attribute_listing_text(attrs, "APX Next", workspace_id=1)

    assert "Wireless Carrier" in result
    assert "Frequency Band" in result, "real label the LLM never mentioned must still appear"
    assert "Boolean Continue 1" not in result, "hallucinated item must never reach the customer"
    assert "Session Variable TER" not in result, "hallucinated item must never reach the customer"


def test_listing_text_tolerates_llm_whitespace_and_casing_drift():
    """Raven Review finding (2026-08-31): trivial LLM formatting drift on
    a real label (extra whitespace, different casing) must not fail the
    membership check -- matching is normalized, but the CANONICAL real
    label text is always what's displayed, never the LLM's own casing."""
    attrs = [_attr(1, "a_astro", "Wireless Carrier", order=1)]
    llm_reply = json.dumps({"groups": [
        {"heading": "Hardware", "items": ["wireless   carrier"]},
    ]})
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(llm_reply, 0, 0)), patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ):
        result = _build_catalog_attribute_listing_text(attrs, "APX Next", workspace_id=1)

    assert "Wireless Carrier" in result, "normalized match must still surface the canonical label"
    assert "wireless   carrier" not in result, "the LLM's own casing/spacing must never be displayed"


def test_listing_text_merges_llm_other_group_with_leftover_other_bucket():
    """Raven Review finding (2026-08-31): if the LLM itself produces a
    group titled "Other" AND there are also leftover/dropped labels, they
    must merge into ONE "Other" section, not render as two separate
    "Other" headings."""
    attrs = [
        _attr(1, "a_astro", "Wireless Carrier", order=1),
        _attr(2, "b_astro", "Frequency Band", order=2),
    ]
    llm_reply = json.dumps({"groups": [
        {"heading": "Other", "items": ["Wireless Carrier"]},
    ]})
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(llm_reply, 0, 0)), patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ):
        result = _build_catalog_attribute_listing_text(attrs, "APX Next", workspace_id=1)

    assert result.count("Other") == 1, "must be exactly one merged Other section, not two"
    assert "Wireless Carrier" in result
    assert "Frequency Band" in result, "leftover label merged into the SAME Other section"


def test_listing_text_scopes_to_the_real_native_ui_layout_when_available():
    """Live-confirmed 2026-08-31 (twice): a real submitted quote's JSON
    had only 7 keys, while filtering the full ~430-attr catalog by
    static fields alone (hide_in_trans/set_type/noise) still left ~200 --
    those static checks only decide what's excluded from an attr that's
    ALREADY been asked; they say nothing about which attrs actually get
    asked at all, which is path-dependent. `load_layout_display_order`
    is BigMachines' own curated "what the real screen shows" set (the
    same source build_payload's own display_order param already uses) --
    when available for a catalog, it's authoritative over the static-
    field guess: only attrs it lists appear, ranked by its own order,
    and an attr with real layout placement but no static exclusion still
    only appears if the layout itself includes it."""
    attrs = [
        _attr(1, "wirelessCarrier_astro", "Wireless Carrier", order=1),
        _attr(2, "hWVersion_astro", "Hardware Version", order=2),
        # Never mentioned in the layout map below -- must be excluded even
        # though it would pass every static-field check on its own.
        _attr(3, "obscureInternalField_astro", "Obscure Internal Field", order=3),
        # ON the real screen (in the layout map) but a transient action
        # button, not real data -- layout membership and payload
        # eligibility are orthoginal checks, both must hold.
        _attr(4, "mergePackage_viSoln", "Merge", order=4, set_type="2"),
    ]
    layout_order = {
        "hWVersion_astro": 0, "wirelessCarrier_astro": 1, "mergePackage_viSoln": 2,
    }
    _EMPTY_GROUPS = json.dumps({"groups": []})
    with patch(
        "aryx.api.ask_api.llm_runtime.chat", return_value=(_EMPTY_GROUPS, 0, 0),
    ) as mock_chat, patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order",
        return_value=layout_order,
    ) as mock_layout:
        result = _build_catalog_attribute_listing_text(
            attrs, "APX Next", workspace_id=1, catalog_prefix="ApxnextConfigdata",
        )
    mock_layout.assert_called_once_with(1, "ApxnextConfigdata")
    user = mock_chat.call_args[0][2]
    assert "Hardware Version" in user and "Hardware Version" in result
    assert "Wireless Carrier" in user and "Wireless Carrier" in result
    assert "Obscure Internal Field" not in user, "not in the real UI layout -- must be excluded"
    assert "Obscure Internal Field" not in result
    assert "Merge" not in user, "on-screen action button (set_type=2), not real data"
    assert "Merge" not in result


# ── _build_current_quote_attribute_listing_text: real filled state ──────

def test_current_quote_listing_reads_the_real_build_payload_keys():
    """Live-confirmed 2026-08-31: post-quote, a real submitted JSON has
    only ~7-10 keys -- reading `session.filled` through the SAME
    build_payload(scope_required_and_edited=True) call the JSON-preview
    button uses gives that exact real list, no approximation needed."""
    attrs = [
        _attr(1, "hWVersion_astro", "Hardware Version", order=1),
        _attr(2, "wirelessCarrier_astro", "Wireless Carrier", order=2),
        # Filled but excluded from the real payload (set_type=2, no
        # auto_lock) -- must never appear even though it's in `filled`.
        _attr(3, "mergePackage_viSoln", "Merge", order=3, set_type="2"),
    ]
    session = CpqSession()
    session.filled = {
        "hWVersion_astro": "NEXT ENHANCED LTE PLUS 5G",
        "wirelessCarrier_astro": "ATT/FIRSTNET",
        "mergePackage_viSoln": "true",
    }
    fake_payload = {
        "configData": {
            "hWVersion_astro": {"value": "x", "displayValue": "y"},
            "wirelessCarrier_astro": {"value": "x", "displayValue": "y"},
        },
    }
    with patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ), patch(
        "aryx.api.ask_api._cpq_engine.build_payload", return_value=fake_payload,
    ) as mock_build_payload:
        result = _build_current_quote_attribute_listing_text(
            session, attrs, workspace_id=1, catalog_prefix="ApxnextConfigdata",
            product_name="APX Next",
        )
    mock_build_payload.assert_called_once()
    _args, kwargs = mock_build_payload.call_args
    assert kwargs.get("scope_required_and_edited") is True
    assert "Hardware Version" in result
    assert "Wireless Carrier" in result
    assert "Merge" not in result, "excluded from the real payload -- must not appear"


def test_current_quote_listing_handles_no_confirmed_attrs_yet():
    attrs = [_attr(1, "a_astro", "A")]
    session = CpqSession()
    session.filled = {"a_astro": "x"}
    with patch(
        "aryx.api.ask_api._cpq_engine.load_layout_display_order", return_value=None,
    ), patch(
        "aryx.api.ask_api._cpq_engine.build_payload", return_value={"configData": {}},
    ):
        result = _build_current_quote_attribute_listing_text(
            session, attrs, workspace_id=1, catalog_prefix="ApxnextConfigdata",
            product_name="APX Next",
        )
    assert "doesn't have any confirmed attributes yet" in result


# ── Wiring: _handle_cpq_qa actually uses the new matcher ────────────────

def test_list_attributes_question_answers_from_attrs_not_the_graph(monkeypatch):
    _qa_common_mocks(monkeypatch)
    attrs = [
        _attr(1, "a_astro", "Instructions and Opt-Out"),
        _attr(2, "b_astro", "Promotions"),
    ]
    session = CpqSession()
    req = AskRequest(
        question="list the attributes in APX Next", workspace_id=1,
        session_data=session.to_dict(),
    )
    with patch(
        "aryx.api.ask_llm.ask_llm_catalog_enumeration._llm_detect_catalog_enumeration_query", return_value=True,
    ) as mock_detect, \
         patch(
             "aryx.api.ask_catalog_listing_text._build_catalog_attribute_listing_text",
             return_value="Here are the attributes: ...",
         ) as mock_build, \
         patch("aryx.api.ask_standard_pipeline._extract_terms") as mock_extract, \
         patch("aryx.api.ask_api.gather") as mock_gather:
        result = _handle_cpq_qa(req, session, attrs, reader=object())

    mock_detect.assert_called_once()
    mock_build.assert_called_once_with(attrs, "ApxnextConfigdata", 1, "ApxnextConfigdata")
    assert "Here are the attributes: ..." in result["answer"]
    # Proves the generic graph-search fallback was never reached.
    mock_extract.assert_not_called()
    mock_gather.assert_not_called()


def test_list_attributes_question_uses_human_readable_product_name(monkeypatch):
    """Raven Review finding (2026-08-31): the customer-facing "catalog"
    name must never be the raw internal catalog_prefix (e.g.
    "ApxnextConfigdata") -- that directly contradicts this same fix's
    own "no raw internal names" principle (_looks_like_raw_variable_name
    below). session.product_name (set once a real quote is in progress/
    complete) must win over catalog_prefix when building the label."""
    _qa_common_mocks(monkeypatch)
    attrs = [_attr(1, "a_astro", "Instructions and Opt-Out")]
    session = CpqSession()
    session.product_name = "APX Next Enhanced"
    req = AskRequest(
        question="list the attributes in APX Next", workspace_id=1,
        session_data=session.to_dict(),
    )
    with patch(
        "aryx.api.ask_llm.ask_llm_catalog_enumeration._llm_detect_catalog_enumeration_query", return_value=True,
    ), patch(
        "aryx.api.ask_catalog_listing_text._build_catalog_attribute_listing_text",
    ) as mock_build:
        _handle_cpq_qa(req, session, attrs, reader=object())

    mock_build.assert_called_once_with(attrs, "APX Next Enhanced", 1, "ApxnextConfigdata")


def test_list_attributes_question_uses_product_hint_when_no_session_product_name(monkeypatch):
    """Pre-quote cold QA (session.product_name intentionally unset per
    _route_qa's read-only-resolve contract): the human-readable
    product_hint threaded from _route_qa's own product-mention resolve
    must still be preferred over the raw catalog_prefix."""
    _qa_common_mocks(monkeypatch)
    attrs = [_attr(1, "a_astro", "Instructions and Opt-Out")]
    session = CpqSession()
    req = AskRequest(
        question="list the attributes in APX Next", workspace_id=1,
        session_data=session.to_dict(),
    )
    with patch(
        "aryx.api.ask_llm.ask_llm_catalog_enumeration._llm_detect_catalog_enumeration_query", return_value=True,
    ), patch(
        "aryx.api.ask_catalog_listing_text._build_catalog_attribute_listing_text",
    ) as mock_build:
        _handle_cpq_qa(
            req, session, attrs, reader=object(), product_hint="APX Next",
        )

    mock_build.assert_called_once_with(attrs, "APX Next", 1, "ApxnextConfigdata")


def test_list_attributes_question_uses_real_quote_state_once_a_quote_exists(monkeypatch):
    """Live-confirmed 2026-08-31: after a quote is already in progress/
    complete, "list the attributes" must answer from the REAL filled
    state, not fall back to the pre-quote, path-agnostic catalog-wide
    approximation -- the whole point of session.filled being non-empty
    is that the real answer is now knowable exactly."""
    _qa_common_mocks(monkeypatch)
    attrs = [_attr(1, "a_astro", "Instructions and Opt-Out")]
    session = CpqSession()
    session.filled = {"a_astro": "some value"}
    req = AskRequest(
        question="list the attributes in APX Next", workspace_id=1,
        session_data=session.to_dict(),
    )
    with patch(
        "aryx.api.ask_llm.ask_llm_catalog_enumeration._llm_detect_catalog_enumeration_query", return_value=True,
    ), patch(
        "aryx.api.ask_attr_text_helpers._build_current_quote_attribute_listing_text",
        return_value="Real quote attributes: ...",
    ) as mock_quote_build, patch(
        "aryx.api.ask_catalog_listing_text._build_catalog_attribute_listing_text",
    ) as mock_catalog_build:
        result = _handle_cpq_qa(req, session, attrs, reader=object())

    mock_quote_build.assert_called_once()
    mock_catalog_build.assert_not_called()
    assert "Real quote attributes: ..." in result["answer"]


def test_non_enumeration_options_question_still_uses_the_generic_fallback(monkeypatch):
    """Negative control: a question that merely contains an options
    keyword (e.g. "list") but the LLM correctly judges is NOT a whole-
    catalog enumeration must still fall through to the existing generic
    graph-search path unchanged."""
    _qa_common_mocks(monkeypatch)
    attrs = [_attr(1, "a_astro", "Instructions and Opt-Out")]
    session = CpqSession()
    req = AskRequest(
        question="what values can I list for the promo code",
        workspace_id=1, session_data=session.to_dict(),
    )
    with patch(
        "aryx.api.ask_llm.ask_llm_catalog_enumeration._llm_detect_catalog_enumeration_query", return_value=False,
    ) as mock_detect, \
         patch("aryx.api.ask_catalog_listing_text._build_catalog_attribute_listing_text") as mock_build, \
         patch("aryx.api.ask_standard_pipeline._extract_terms", return_value=([], 0, 0, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_standard_pipeline._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_standard_pipeline._synthesise", return_value=("fallback answer", 0, 0, 0)):
        _handle_cpq_qa(req, session, attrs, reader=object())

    mock_detect.assert_called_once()
    mock_build.assert_not_called()


def test_question_without_any_options_keyword_never_calls_the_llm_classifier(monkeypatch):
    """Cheap pre-check gate: a question with none of _OPTIONS_KEYWORDS must
    never pay the extra LLM classification call at all -- same discipline
    as the existing multi-attribute-options split."""
    _qa_common_mocks(monkeypatch)
    attrs = [_attr(1, "a_astro", "Instructions and Opt-Out")]
    session = CpqSession()
    req = AskRequest(
        question="tell me a joke", workspace_id=1, session_data=session.to_dict(),
    )
    with patch(
        "aryx.api.ask_llm.ask_llm_catalog_enumeration._llm_detect_catalog_enumeration_query",
    ) as mock_detect, \
         patch("aryx.api.ask_standard_pipeline._extract_terms", return_value=([], 0, 0, 0)), \
         patch("aryx.api.ask_api.gather", return_value=([], [])), \
         patch("aryx.api.ask_standard_pipeline._enrich_with_attributes", lambda entities, *a, **k: entities), \
         patch("aryx.api.ask_api.render_context", return_value=""), \
         patch("aryx.api.ask_standard_pipeline._synthesise", return_value=("fallback answer", 0, 0, 0)):
        _handle_cpq_qa(req, session, attrs, reader=object())

    mock_detect.assert_not_called()


def test_specific_attribute_question_is_unaffected_by_the_new_matcher(monkeypatch):
    """Regression guard: a genuine single-attribute options question
    (already handled by the existing fast path) must never reach the new
    enumeration matcher at all."""
    from aryx.cpq.state import MenuOption

    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "detect_label_collision", lambda *a, **k: None)
    attr = _attr(
        1, "wirelessCarrier_astro", "Wireless Carrier",
    )
    attr.options = [MenuOption(item_value="ATT", display_name="ATT/FirstNet", order=1)]
    monkeypatch.setattr(api._cpq_engine, "detect_attr_query", lambda *a, **k: attr)
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules", lambda *a, **k: ([], []),
    )
    session = CpqSession()
    req = AskRequest(
        question="what are the wireless carrier options",
        workspace_id=1, session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_llm.ask_llm_catalog_enumeration._llm_detect_catalog_enumeration_query") as mock_detect:
        result = _handle_cpq_qa(req, session, [attr], reader=object())

    mock_detect.assert_not_called()
    assert "ATT/FirstNet" in result["answer"]
