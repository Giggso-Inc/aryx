"""Regression coverage: the chat answer's own "Mandatory User Input"
section must be a VERBATIM copy of Beautify's "Mandatory User Input"
section for the same turn -- not just conceptually equivalent facts
spread across categories, but the literal same aligned text block.

Live-confirmed ask (2026-08-20): PR #226 (test_cpq_summary_matches_
beautify_mandatory_2026_08_19.py) made sure every fact Beautify puts
under Mandatory User Input is SOMEWHERE in the summary -- but items
whose variable_name matches Product Name/Service Plan/Quantity &
Duration's fragments (Base Model, Hardware Version, Product,
Application Services Selection) land under THOSE headers instead, so
the summary's own "Mandatory User Input" heading still showed a
narrower subset than Beautify's. The customer explicitly asked for the
two to match under the SAME heading, verbatim.

Fixed by `_attach_share_flags` splicing Beautify's own Mandatory rows
(from the structured `beautify_rows()`, not the rendered `beautify_
text()` string -- see PR #236 review) directly into the chat answer's
"Mandatory User Input" section, fenced as a code block. Product Name/
Service Plan/Quantity & Duration keep their own narrower, LLM-narrated
bullet lists untouched; only the Mandatory User Input section is forced
to mirror Beautify, MINUS whatever those narrower categories already
showed (PR #236 H1 -- no duplication).

Raven review on PR #236 (aryx-enterprise#236) found the first cut of
this fix fragile in several ways, each covered here:
  C1 -- trailer-boundary detection only recognized "\\n\\nClick **JSON**"
        literally; anything else silently deleted the trailer.
  C2 -- header detection (substring) and header replacement (stricter
        regex) could disagree, leaving a duplicated section.
  H1 -- an attribute matching both a named category AND Beautify's
        Mandatory set rendered twice, in two different formats.
  H2 -- the "next header" boundary matched ANY bold+colon line, so a
        stray LLM aside like "**Note:**" inside the Mandatory body
        could be misread as the next category and truncate the splice.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import (
    AskRequest,
    _beautify_mandatory_block,
    _labels_already_shown,
    _OTHER_SUMMARY_CATEGORY_HEADERS,
    _splice_mandatory_block_into_summary,
)
from aryx.cpq.engine import SUMMARY_CATEGORY_NAMES, SUMMARY_FALLBACK_CATEGORY
from aryx.cpq.state import ConfigAttr, MenuOption


def test_other_summary_category_headers_is_derived_not_duplicated():
    """Raven PR #236 review, Medium follow-up: the splice boundary's
    category names must come from the same source of truth
    `categorized_summary_groups` itself uses (SUMMARY_CATEGORY_NAMES/
    SUMMARY_FALLBACK_CATEGORY), not a second, hand-maintained copy that
    could silently drift if a category is ever renamed or added."""
    assert _OTHER_SUMMARY_CATEGORY_HEADERS == SUMMARY_CATEGORY_NAMES + (SUMMARY_FALLBACK_CATEGORY,)
    assert "Product Name" in _OTHER_SUMMARY_CATEGORY_HEADERS
    assert "Service Plan" in _OTHER_SUMMARY_CATEGORY_HEADERS
    assert SUMMARY_FALLBACK_CATEGORY in _OTHER_SUMMARY_CATEGORY_HEADERS


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=False,
        default_value="", options=options or [],
    )


def _row(section, label, value):
    return {"section": section, "label": label, "value": value}


MANDATORY = "Mandatory User Input"


# ── _beautify_mandatory_block: dedup against already-shown (label, value)
# pairs, not label alone (H1, plus the Low follow-up below) ──

def test_beautify_mandatory_block_excludes_labels_already_shown_above():
    """Base Model is both Mandatory (per Beautify) and already rendered
    under Product Name -- the spliced block must NOT repeat it."""
    rows = [
        _row(MANDATORY, "Base Model", "H55TGT9PW8BN"),
        _row(MANDATORY, "Carrier Selection", "ATT/FirstNet (provided by Motorola)"),
        _row("System-Configured / Recommended", "Region", "NA"),
    ]
    block = _beautify_mandatory_block(rows, already_shown={("base model", "h55tgt9pw8bn")})
    assert "Base Model" not in block
    assert "Carrier Selection" in block


def test_beautify_mandatory_block_returns_none_when_everything_was_already_shown():
    rows = [_row(MANDATORY, "Base Model", "H55TGT9PW8BN")]
    assert _beautify_mandatory_block(
        rows, already_shown={("base model", "h55tgt9pw8bn")}) is None


def test_beautify_mandatory_block_returns_none_when_no_mandatory_rows_exist():
    rows = [_row("System-Configured / Recommended", "Region", "NA")]
    assert _beautify_mandatory_block(rows, already_shown=set()) is None


def test_beautify_mandatory_block_realigns_after_dropping_a_long_label():
    """The alignment width must be recomputed from the SURVIVING labels,
    not Beautify's original (wider) label set."""
    rows = [
        _row(MANDATORY, "Application Services Selection", "Customize App Services"),
        _row(MANDATORY, "Carrier", "ATT/FirstNet"),
    ]
    # Drop the long label -- "Carrier" alone should now set the width.
    block = _beautify_mandatory_block(
        rows, already_shown={("application services selection", "customize app services")})
    assert block == "Carrier : ATT/FirstNet"


def test_beautify_mandatory_block_does_not_exclude_a_same_label_different_value_row():
    """Raven PR #236 review, Low follow-up: two distinct attributes could
    plausibly share a display label across a large catalog. Keying the
    exclusion on (label, value) rather than label alone means a
    same-label row with a DIFFERENT value is never incorrectly dropped."""
    rows = [_row(MANDATORY, "Service Type", "Advantage")]
    # Something upstream already showed "Service Type" -> a DIFFERENT
    # value -- this must not suppress the genuinely-different Mandatory
    # fact that happens to share only the label.
    block = _beautify_mandatory_block(rows, already_shown={("service type", "installation")})
    assert block == "Service Type : Advantage"


# ── _labels_already_shown ──

def test_labels_already_shown_only_looks_before_the_mandatory_header():
    answer = (
        "**Product Name:**\n- **Base Model** → H55TGT9PW8BN\n\n"
        "**Mandatory User Input:**\n- **Carrier** → ATT/FirstNet"
    )
    shown = _labels_already_shown(answer)
    assert shown == {("base model", "h55tgt9pw8bn")}


def test_labels_already_shown_is_case_insensitive():
    answer = "**Product Name:**\n- **BASE MODEL** → H55TGT9PW8BN"
    assert ("base model", "h55tgt9pw8bn") in _labels_already_shown(answer)


# ── _splice_mandatory_block_into_summary: C1, C2, H2 ──

def test_splice_replaces_the_narrower_llm_narrated_mandatory_section():
    answer = (
        "Configuration complete for **aSTRO25_bom**.\n\n"
        "**Product Name:**\n- **Hardware Version** → APX NEXT (4G LTE+5G)\n\n"
        "**Mandatory User Input:**\n"
        "- **Destination Country** → United States\n"
        "- **Software Release** → Baseline Release\n\n"
        "Click **JSON** below to see the full payload, say **confirm** to submit, "
        "or describe any changes."
    )
    block = (
        "Ultimate Destination Country  : United States\n"
        "Software Release              : Baseline Release\n"
        "Carrier Selection             : ATT/FirstNet (provided by Motorola)"
    )
    spliced = _splice_mandatory_block_into_summary(answer, block)

    assert "**Product Name:**\n- **Hardware Version**" in spliced
    assert f"**Mandatory User Input:**\n```\n{block}\n```" in spliced
    assert "- **Destination Country**" not in spliced
    assert spliced.rstrip().endswith("or describe any changes.")
    assert spliced.index("```") < spliced.index("Click **JSON**")


def test_splice_inserts_a_mandatory_section_when_the_summary_had_none():
    answer = (
        "Configuration complete for **aSTRO25_bom**.\n\n"
        "**Product Name:**\n- **Quantity** → 1\n\n"
        "Click **JSON** below to see the full payload, say **confirm** to submit, "
        "or describe any changes."
    )
    block = "Product                       : aSTRO25_bom\nRegion                        : NA"
    spliced = _splice_mandatory_block_into_summary(answer, block)
    assert f"**Mandatory User Input:**\n```\n{block}\n```" in spliced
    assert spliced.index("```") < spliced.index("Click **JSON**")


def test_c1_trailer_with_no_blank_line_does_not_delete_the_call_to_action():
    """Raven PR #236, C1: a single newline (not "\\n\\n") before the
    trailer used to defeat every lookahead alternative, forcing the
    match to \\Z and deleting the trailer along with the old section."""
    answer = (
        "**Mandatory User Input:**\n- **Carrier** → ATT/FirstNet\n"
        "Click **JSON** below to see the full payload, say **confirm** to submit."
    )
    spliced = _splice_mandatory_block_into_summary(answer, "Carrier : ATT/FirstNet")
    assert "Click **JSON**" in spliced, "the call-to-action must survive the splice"


def test_c1_trailer_with_no_preceding_newline_at_all_is_preserved():
    answer = "**Mandatory User Input:**\n- **Carrier** → ATT/FirstNetClick **JSON** now."
    # Pathological (no separating newline at all) -- still must not eat
    # the whole rest of the string silently. The trailer regex requires
    # "Click **JSON**" as a literal token, which is still present here.
    spliced = _splice_mandatory_block_into_summary(answer, "Carrier : ATT/FirstNet")
    assert "Click **JSON**" in spliced


def test_c2_header_with_trailing_space_before_newline_replaces_cleanly_no_duplicate():
    """Raven PR #236, C2: a stray space after the header's closing "**"
    (before its newline) used to pass the old substring check but fail
    the stricter replace regex, falling through to insert and leaving
    TWO "Mandatory User Input:" sections in the same message."""
    answer = (
        "**Mandatory User Input:** \n"
        "- **Destination Country** → United States\n\n"
        "Click **JSON** below to see the full payload."
    )
    spliced = _splice_mandatory_block_into_summary(answer, "Destination Country : United States")
    assert spliced.count("**Mandatory User Input:**") == 1, (
        "must never leave two Mandatory User Input headers in one message"
    )
    assert "- **Destination Country**" not in spliced


def test_h2_a_bold_colon_aside_inside_the_body_does_not_truncate_the_match():
    """Raven PR #236, H2: the old boundary matched ANY "**...:**" line as
    the next category header. An LLM aside like "**Note:**" inside the
    Mandatory section's own narration must not be mistaken for one."""
    answer = (
        "**Mandatory User Input:**\n"
        "- **Carrier** → ATT/FirstNet\n"
        "**Note:** pricing may vary by region.\n\n"
        "Click **JSON** below to see the full payload."
    )
    spliced = _splice_mandatory_block_into_summary(answer, "Carrier : ATT/FirstNet")
    # The old bug stitched the fenced block directly against "**Note:**
    # pricing may vary..." with no separating header; the fenced block
    # must fully replace the section instead, and only ONE Mandatory
    # header must remain.
    assert spliced.count("**Mandatory User Input:**") == 1
    assert "```\nCarrier : ATT/FirstNet\n```" in spliced


def test_splice_is_idempotent_when_run_twice():
    """Medium (PR #236): running the splice again on its own output must
    not duplicate or corrupt the section -- the fenced block it produces
    is itself valid input to the same function."""
    answer = (
        "**Mandatory User Input:**\n- **Carrier** → ATT/FirstNet\n\n"
        "Click **JSON** below to see the full payload."
    )
    block = "Carrier : ATT/FirstNet"
    once = _splice_mandatory_block_into_summary(answer, block)
    twice = _splice_mandatory_block_into_summary(once, block)
    assert once == twice
    assert twice.count("**Mandatory User Input:**") == 1


# ── end-to-end: _attach_share_flags ──

def test_attach_share_flags_forces_full_beautify_mandatory_parity_without_duplication(monkeypatch):
    """End-to-end: Base Model (which the summary's own category grouping
    puts under "Product Name") and Carrier Selection (only Beautify's
    Mandatory logic recognizes it) must BOTH be reflected exactly once
    each: Base Model stays under Product Name only, Carrier Selection
    appears in the spliced Mandatory block -- never duplicated."""
    base_model = _attr(1, "modelSelectionbaseModel_astro", "Base Model", options=_opt("H55TGT9PW8BN"))
    carrier = _attr(2, "carrierSelectionMultiSelect_astro", "Carrier Selection",
                     options=_opt("ATT/FirstNet (provided by Motorola)"))
    attrs = [base_model, carrier]

    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "payload_flow_exclusions", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "load_layout_display_order", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "mandatory_tier_c_vns", lambda *a, **k: frozenset())

    session_data = {
        "mode": "cpq", "product_name": "aSTRO25_bom", "status": "awaiting_approval",
        "filled": {
            "modelSelectionbaseModel_astro": "H55TGT9PW8BN",
            "carrierSelectionMultiSelect_astro": "ATT/FirstNet (provided by Motorola)",
        },
        "display_filled": {
            "modelSelectionbaseModel_astro": "H55TGT9PW8BN",
            "carrierSelectionMultiSelect_astro": "ATT/FirstNet (provided by Motorola)",
        },
        "filled_source": {
            "modelSelectionbaseModel_astro": "cascade",
            "carrierSelectionMultiSelect_astro": "user",
        },
    }
    result = {
        "answer": (
            "Configuration complete for **aSTRO25_bom**.\n\n"
            "**Product Name:**\n- **Base Model** → H55TGT9PW8BN\n\n"
            "Click **JSON** below to see the full payload, say **confirm** to submit, "
            "or describe any changes."
        ),
        "session_data": session_data,
    }
    req = AskRequest(question="give the configuration", workspace_id=1, session_data=session_data)
    api._attach_share_flags(result, req, object())

    answer = result["answer"]
    assert "**Mandatory User Input:**\n```" in answer
    mandatory_section = answer.split("**Mandatory User Input:**", 1)[1]
    assert "Carrier Selection" in mandatory_section
    # Base Model must NOT be duplicated inside the spliced block -- it's
    # already shown under Product Name.
    assert "Base Model" not in mandatory_section
    assert answer.count("Base Model") == 1
    assert "**Product Name:**\n- **Base Model**" in answer


def test_attach_share_flags_suppresses_the_splice_while_still_configuring(monkeypatch):
    """Explicit ask (2026-08-20): the Mandatory User Input splice must
    only fire once the configuration is genuinely complete (session.
    status != "configuring") -- NOT merely once the JSON/Beautify
    buttons' own, deliberately-earlier readiness threshold
    (_SHARE_READY_MIN_FILLED filled attrs) is met. Live-confirmed
    regression: with 3+ attrs filled but the session still mid-
    conversation (status="configuring", a real question still pending),
    the splice was appending a Mandatory User Input block onto a
    "Hardware Version -- choose one" turn that had no such section and
    was nowhere near "Configuration complete"."""
    base_model = _attr(1, "modelSelectionbaseModel_astro", "Base Model", options=_opt("H55TGT9PW8BN"))
    country = _attr(2, "ultimateDestinationCountry", "Ultimate Destination Country",
                     options=_opt("United States"))
    carrier = _attr(3, "carrierSelectionMultiSelect_astro", "Carrier Selection",
                     options=_opt("ATT/FirstNet (provided by Motorola)"))
    attrs = [base_model, country, carrier]

    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "payload_flow_exclusions", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "load_layout_display_order", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "mandatory_tier_c_vns", lambda *a, **k: frozenset())

    filled = {
        "modelSelectionbaseModel_astro": "H55TGT9PW8BN",
        "ultimateDestinationCountry": "United States",
        "carrierSelectionMultiSelect_astro": "ATT/FirstNet (provided by Motorola)",
    }
    session_data = {
        "mode": "cpq", "product_name": "aSTRO25_bom", "status": "configuring",
        "pending_variables": ["hWVersion_astro"],
        "filled": filled, "display_filled": dict(filled),
        "filled_source": {k: "user" for k in filled},
    }
    result = {
        "answer": "**Hardware Version** — choose one:\n\n1. APX NEXT (4G LTE+5G)\n2. APX NEXT (4G LTE Only)",
        "session_data": session_data,
    }
    req = AskRequest(question="APX NEXT for USA", workspace_id=1, session_data=session_data)
    api._attach_share_flags(result, req, object())

    # JSON/Beautify buttons are still allowed to show early (unaffected,
    # pre-existing behavior) -- only the splice must be suppressed.
    assert result["beautify_button_flag"] is True
    assert "**Mandatory User Input:**" not in result["answer"]
    assert result["answer"] == (
        "**Hardware Version** — choose one:\n\n1. APX NEXT (4G LTE+5G)\n2. APX NEXT (4G LTE Only)"
    )


def test_attach_share_flags_suppresses_the_splice_after_confirm_too(monkeypatch):
    """Explicit ask (2026-08-20): after the customer says **confirm**,
    `_handle_approval` moves `session.status` to "post_approval" -- a
    turn that should show ONLY the submitted JSON payload, nothing else.
    Live-confirmed regression: gating the splice on `status !=
    "configuring"` also matched "post_approval" (it's neither
    "configuring" nor excluded), so the spliced Mandatory User Input
    block kept appearing under the post-confirm JSON response too. The
    splice must fire ONLY on "awaiting_approval" -- the one turn that is
    both complete AND still waiting on the customer."""
    carrier = _attr(1, "carrierSelectionMultiSelect_astro", "Carrier Selection",
                     options=_opt("ATT/FirstNet (provided by Motorola)"))
    attrs = [carrier]

    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "payload_flow_exclusions", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "load_layout_display_order", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "mandatory_tier_c_vns", lambda *a, **k: frozenset())

    filled = {"carrierSelectionMultiSelect_astro": "ATT/FirstNet (provided by Motorola)"}
    session_data = {
        "mode": "cpq", "product_name": "aSTRO25_bom", "status": "post_approval",
        "filled": filled, "display_filled": dict(filled),
        "filled_source": {k: "user" for k in filled},
    }
    result = {
        "answer": '```json\n{\n  "configData": {"carrierSelectionMultiSelect_astro": "..."}\n}\n```',
        "session_data": session_data,
    }
    req = AskRequest(question="confirm", workspace_id=1, session_data=session_data)
    api._attach_share_flags(result, req, object())

    assert "**Mandatory User Input:**" not in result["answer"]
