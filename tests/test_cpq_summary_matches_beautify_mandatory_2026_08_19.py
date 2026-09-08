"""Regression coverage: the conversational summary's "Mandatory User
Input" bucket must contain the SAME attributes as Beautify's own
"Mandatory User Input" section for the same turn.

Live-confirmed gap (2026-08-19): every `_cpq_summary_text(...)` call site
in ask_api.py passed `visible_attrs` (a rule-narrowed, potentially smaller
subset computed locally in each handler) as the attrs list used to resolve
`ConfigAttr` metadata for `_is_mandatory_input_attr`'s Tier A classification
-- while `_attach_share_flags` (Beautify's home) always passes the FULL,
freshly-loaded catalog `attrs` list for the exact same purpose. An
attribute that a hiding rule excludes from `visible_attrs` at the moment
the summary is built (e.g. a country-derived Region field, still hidden
by the rule that governs it) resolved with `attr=None` in the summary's
classification call, silently failing Tier A there while Beautify's own
call -- same session, same turn, same attribute -- resolved it correctly
and showed it under Mandatory User Input. Fixed by having every
`_cpq_summary_text` call site pass the full `attrs` list, exactly like
Beautify already does; `visible_attrs` is untouched everywhere else (it's
still the correct scope for `rule_governed_ids`/pending-question
selection, a genuinely different concern).
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _build_show_summary_response
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption
from aryx.api import ask_core_helpers as _ask_core_helpers_test_module


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None, required=False, hidden=False) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=required,
        default_value="", options=options or [], hidden=hidden,
    )


def test_summary_mandatory_bucket_includes_a_tier_a_attr_hidden_from_visible_attrs(monkeypatch):
    """`baselineReleaseSW_astro` ("Software Release") is one of the named
    `_ATTRSEQ_CONFIRMED_REQUIRED_VNS` Tier A anchors -- but that whole
    tier_a check (including the `_ATTRSEQ_CONFIRMED_REQUIRED_VNS`
    membership test) is gated behind `attr is not None`, so it needs the
    real `ConfigAttr` object, not just its variable name. Its
    `filled_source` here is "rule" (NOT "user"), and Tier B/C don't apply
    to it (its name doesn't match `_DECISION_REQUIRED_KEYS`, and no
    `required_vns` is supplied here), so Tier A is the ONLY signal that
    can mark it mandatory -- this isolates the exact bug: if the summary's
    classification call resolves this attribute's `ConfigAttr` from a
    narrowed `visible_attrs` list that excludes it (hidden by an active
    rule this turn), Tier A silently fails with `attr=None`, even though
    Beautify (which always uses the full catalog attrs) still classifies
    it correctly and shows it under Mandatory User Input. Its
    variable_name also doesn't match any of Product Name/Service Plan/
    Quantity & Duration's fragments, so (unlike Hardware Version, which
    correctly and separately lands under Product Name) it can only ever
    surface via the Mandatory User Input catch-all rename."""
    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)

    def _boom_chat(*a, **k):
        raise RuntimeError("no LLM narrator in this test — force the deterministic fallback")

    monkeypatch.setattr(api.llm_runtime, "chat", _boom_chat)
    software_release = _attr(1, "baselineReleaseSW_astro", "Software Release",
                              options=_opt("Baseline Release"))
    country = _attr(2, "ultimateDestinationCountry", "Ultimate Destination Country",
                     options=_opt("United States"))
    attrs = [software_release, country]
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: (attrs, "aSTRO25_bom"),
    )
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_layout_display_order", lambda *a, **k: None)
    # Software Release is hidden from `visible_attrs` this turn (e.g. a
    # still-active "re-derive after a country change" rule) -- the 3rd
    # tuple element is the hidden_vns set `apply_hiding_rules` returns.
    monkeypatch.setattr(
        api._cpq_engine, "apply_hiding_rules",
        lambda *a, **k: (None, None, {"baselineReleaseSW_astro"}),
    )
    monkeypatch.setattr(api._cpq_engine, "rule_governed_ids", lambda *a, **k: {1, 2})

    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={
            "baselineReleaseSW_astro": "Baseline Release",
            "ultimateDestinationCountry": "United States",
        },
        display_filled={
            "baselineReleaseSW_astro": "Baseline Release",
            "ultimateDestinationCountry": "United States",
        },
        filled_source={
            "baselineReleaseSW_astro": "rule",
            "ultimateDestinationCountry": "user",
        },
        status="awaiting_approval", turn=6, pending_variables=[],
    )
    req = AskRequest(question="give the configuration", workspace_id=1,
                      session_data=session.to_dict())
    resp = _build_show_summary_response(req, session, object())

    assert resp is not None
    assert "**Mandatory User Input:**" in resp["answer"]
    assert "Software Release" in resp["answer"], (
        "Software Release was excluded from visible_attrs by a hiding rule "
        "this turn, and its source isn't 'user' -- only Tier A "
        "(_ATTRSEQ_CONFIRMED_REQUIRED_VNS, gated behind attr is not None) "
        "can mark it mandatory. It must appear in the summary's Mandatory "
        "User Input bucket the same way it appears in Beautify's, not be "
        "silently dropped because its attr resolved to None from a "
        "narrowed attrs list."
    )
    mandatory_section = resp["answer"].split("**Mandatory User Input:**", 1)[1]
    assert "Software Release" in mandatory_section
