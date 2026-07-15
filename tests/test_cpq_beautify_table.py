"""Tests for the CPQ Beautify view's structured, tabular data source.

beautify_text() is unchanged (still the original aligned "Label : Value"
plaintext, used as-is by Streamlit's st.code — that client's rendering was
deliberately left untouched). React's Beautify panel instead renders
CpqEngine.beautify_rows() — a new method returning the same filtered
[{label, value}, ...] pairs as structured data, so the Next.js client can
build a real <table> without any markdown-escaping concerns.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def test_beautify_text_still_returns_original_aligned_plaintext():
    """Streamlit's display must be completely unaffected by the React table
    work — beautify_text() keeps its original "Label : Value" shape."""
    eng = CpqEngine()
    display_filled = {"carrierAttr": "Verizon"}
    attrs = [
        ConfigAttr(entity_id=1, variable_name="carrierAttr", display_label="Carrier",
                   required=False, default_value="", options=[]),
    ]
    text = eng.beautify_text("APX NEXT", display_filled, attrs)
    lines = text.splitlines()
    assert lines[0].split(" : ")[0].strip() == "Product"
    assert "APX NEXT" in lines[0]
    assert any("Carrier" in ln and "Verizon" in ln for ln in lines)
    # No table syntax anywhere.
    assert "|" not in text


def test_beautify_rows_returns_structured_label_value_pairs():
    eng = CpqEngine()
    display_filled = {"carrierAttr": "Verizon", "billingAttr": "Monthly"}
    attrs = [
        ConfigAttr(entity_id=1, variable_name="carrierAttr", display_label="Carrier",
                   required=False, default_value="", options=[]),
        ConfigAttr(entity_id=2, variable_name="billingAttr", display_label="Billing",
                   required=False, default_value="", options=[]),
    ]
    rows = eng.beautify_rows("APX NEXT", display_filled, attrs)

    assert rows[0] == {"label": "Product", "value": "APX NEXT"}
    assert {"label": "Carrier", "value": "Verizon"} in rows
    assert {"label": "Billing", "value": "Monthly"} in rows
    # Every row is a plain {label, value} dict — no markdown escaping needed
    # since the client renders these as real table cells, not parsed text.
    for row in rows:
        assert set(row.keys()) == {"label", "value"}


def test_beautify_rows_preserves_literal_pipe_and_newlines_unescaped():
    """Unlike a markdown-table string, structured rows never need escaping —
    the client renders each value as plain table-cell text."""
    eng = CpqEngine()
    display_filled = {"optionAttr": "Fast|Slow combo\npack"}
    attrs = [
        ConfigAttr(entity_id=1, variable_name="optionAttr", display_label="Option",
                   required=False, default_value="", options=[]),
    ]
    rows = eng.beautify_rows("SL3500e", display_filled, attrs)
    option_row = next(r for r in rows if r["label"] == "Option")
    assert option_row["value"] == "Fast|Slow combo\npack"


def test_beautify_rows_still_applies_noise_and_low_signal_filtering():
    """Reuses filled_summary_pairs() — must still drop noise vars, same as
    beautify_text()/render_filled_summary()'s existing behavior."""
    eng = CpqEngine()
    display_filled = {"_internalFlag": "true", "carrierAttr": "LTE"}
    attrs = [
        ConfigAttr(entity_id=1, variable_name="_internalFlag", display_label="Internal Flag",
                   required=False, default_value="", options=[]),
        ConfigAttr(entity_id=2, variable_name="carrierAttr", display_label="Carrier",
                   required=False, default_value="", options=[]),
    ]
    rows = eng.beautify_rows("APX NEXT", display_filled, attrs)
    labels = {r["label"] for r in rows}
    assert "Internal Flag" not in labels and "_internalFlag" not in labels
    assert any(r["label"] == "Carrier" and r["value"] == "LTE" for r in rows)


def test_beautify_rows_no_filled_attrs_still_shows_product_row():
    eng = CpqEngine()
    rows = eng.beautify_rows("APX NEXT", {}, [])
    assert rows == [{"label": "Product", "value": "APX NEXT"}]
