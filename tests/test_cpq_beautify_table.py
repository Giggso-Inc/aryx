"""Tests for beautify_text()'s tabular (Markdown table) output.

Was: aligned "Label : Value" plaintext lines, rendered in a <pre>/st.code
block. Now: a two-column GFM Markdown table (Attribute | Value), rendered
as a real table by the existing Markdown component (Next.js) / st.markdown
(Streamlit) — both already support GFM tables, so no new rendering
dependency was needed, only the string shape changed.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def test_beautify_text_produces_a_valid_gfm_table():
    eng = CpqEngine()
    display_filled = {"carrierAttr": "Verizon", "billingAttr": "Monthly"}
    attrs = [
        ConfigAttr(entity_id=1, variable_name="carrierAttr", display_label="Carrier",
                   required=False, default_value="", options=[]),
        ConfigAttr(entity_id=2, variable_name="billingAttr", display_label="Billing",
                   required=False, default_value="", options=[]),
    ]
    text = eng.beautify_text("APX NEXT", display_filled, attrs)
    lines = text.splitlines()

    assert lines[0] == "| Attribute | Value |"
    assert lines[1] == "| --- | --- |"
    # Product row always first, then the filtered attribute rows.
    assert lines[2] == "| Product | APX NEXT |"
    assert any("Carrier" in ln and "Verizon" in ln for ln in lines[3:])
    assert any("Billing" in ln and "Monthly" in ln for ln in lines[3:])
    # Every data row is well-formed GFM: starts and ends with a pipe, and
    # has exactly 2 columns (3 pipe characters: | c1 | c2 |).
    for ln in lines[2:]:
        assert ln.startswith("| ") and ln.endswith(" |")
        assert ln.count("|") == 3


def test_beautify_text_escapes_literal_pipe_in_values():
    """A value containing a literal '|' must not corrupt the table
    structure — GFM would otherwise read it as an extra column boundary."""
    eng = CpqEngine()
    display_filled = {"optionAttr": "Fast|Slow combo pack"}
    attrs = [
        ConfigAttr(entity_id=1, variable_name="optionAttr", display_label="Option",
                   required=False, default_value="", options=[]),
    ]
    text = eng.beautify_text("SL3500e", display_filled, attrs)
    row = next(ln for ln in text.splitlines() if "Option" in ln)
    # The literal pipe must be escaped (backslash-prefixed) so a GFM parser
    # reads it as cell content, not a 3rd column boundary.
    assert "Fast\\|Slow" in row
    unescaped_pipe_count = row.replace("\\|", "").count("|")
    assert unescaped_pipe_count == 3, "exactly the 2 structural + 1 boundary pipes, no stray unescaped pipe"


def test_beautify_text_collapses_embedded_newlines_in_values():
    """A value with embedded newlines must collapse to one line — GFM
    table cells cannot span multiple physical lines."""
    eng = CpqEngine()
    display_filled = {"noteAttr": "Line one\nLine two"}
    attrs = [
        ConfigAttr(entity_id=1, variable_name="noteAttr", display_label="Note",
                   required=False, default_value="", options=[]),
    ]
    text = eng.beautify_text("SL3500e", display_filled, attrs)
    lines = text.splitlines()
    # Exactly: header, separator, Product row, Note row — 4 lines, not 5.
    assert len(lines) == 4
    assert "Line one Line two" in lines[3]


def test_beautify_text_still_applies_noise_and_low_signal_filtering():
    """Reuses filled_summary_pairs() — must still drop noise vars, same as
    the pre-existing render_filled_summary()/verbose-summary behavior."""
    eng = CpqEngine()
    display_filled = {"_internalFlag": "true", "carrierAttr": "LTE"}
    attrs = [
        ConfigAttr(entity_id=1, variable_name="_internalFlag", display_label="Internal Flag",
                   required=False, default_value="", options=[]),
        ConfigAttr(entity_id=2, variable_name="carrierAttr", display_label="Carrier",
                   required=False, default_value="", options=[]),
    ]
    text = eng.beautify_text("APX NEXT", display_filled, attrs)
    assert "_internalFlag" not in text and "Internal Flag" not in text
    assert "LTE" in text


def test_beautify_text_no_filled_attrs_still_shows_product_row():
    eng = CpqEngine()
    text = eng.beautify_text("APX NEXT", {}, [])
    lines = text.splitlines()
    assert lines[0] == "| Attribute | Value |"
    assert lines[2] == "| Product | APX NEXT |"
    assert len(lines) == 3
