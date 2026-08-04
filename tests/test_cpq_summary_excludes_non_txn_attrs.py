"""Issue 5 items 1/2 (docs/config_consistency_issues_2026-07-30.md):
build_payload() already excludes hide_in_trans==1 and set_type=="2"
(non-auto_lock) attrs from the submitted BOM, but the conversational
summary (beautify_text/beautify_rows/render_filled_summary, all routed
through _is_summary_excluded) never applied the same two checks — a
sales rep could see an "Associated Options" line for a field that will
never actually be submitted. Fixed by adding the same checks to
_is_summary_excluded, which already receives the ConfigAttr object.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def test_hide_in_trans_attr_excluded_from_beautify():
    eng = CpqEngine()
    display_filled = {"productInformationText_astro": "Some internal blurb", "carrierAttr": "Verizon"}
    attrs = [
        ConfigAttr(
            entity_id=1, variable_name="productInformationText_astro",
            display_label="Product Information Text", required=False,
            default_value="", options=[], hide_in_trans=True,
        ),
        ConfigAttr(
            entity_id=2, variable_name="carrierAttr", display_label="Carrier",
            required=False, default_value="", options=[],
        ),
    ]
    rows = eng.beautify_rows("APX NEXT", display_filled, attrs)
    labels = {r["label"] for r in rows}
    assert "Product Information Text" not in labels
    assert "Carrier" in labels


def test_transient_set_type_2_attr_excluded_from_beautify():
    eng = CpqEngine()
    display_filled = {"transientAttr": "some value", "carrierAttr": "Verizon"}
    attrs = [
        ConfigAttr(
            entity_id=1, variable_name="transientAttr", display_label="Transient Attr",
            required=False, default_value="", options=[], set_type="2", auto_lock=False,
        ),
        ConfigAttr(
            entity_id=2, variable_name="carrierAttr", display_label="Carrier",
            required=False, default_value="", options=[],
        ),
    ]
    rows = eng.beautify_rows("APX NEXT", display_filled, attrs)
    labels = {r["label"] for r in rows}
    assert "Transient Attr" not in labels
    assert "Carrier" in labels


def test_set_type_2_with_auto_lock_still_shown():
    """set_type=="2" alone isn't excluded from the payload either — only
    when it's NOT auto_lock (see build_payload's own exclusion). Must not
    over-exclude a genuinely-shown auto_lock attr."""
    eng = CpqEngine()
    display_filled = {"lockedAttr": "some value"}
    attrs = [
        ConfigAttr(
            entity_id=1, variable_name="lockedAttr", display_label="Locked Attr",
            required=False, default_value="", options=[], set_type="2", auto_lock=True,
        ),
    ]
    rows = eng.beautify_rows("APX NEXT", display_filled, attrs)
    labels = {r["label"] for r in rows}
    assert "Locked Attr" in labels
