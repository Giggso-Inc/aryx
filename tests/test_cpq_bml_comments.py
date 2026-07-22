"""Regression coverage: Tier-1 BML evaluation must ignore `//` line
comments, never mistake a commented-out scratch assignment for the real,
live statement that follows it.

Confirmed live: APX NEXT Enhanced's real "Default APX Next Enhanced based
on HW version" recommendation script has

    if (hWVersion_astro == "NEXT ENHANCED LTE PLUS 5G") {
        //returnVal = "APX NEXT Enhanced";
        returnVal = "APX NEXT ENHANCED";
    }

— the commented-out line's (wrong-cased) string was returned instead of
the real assignment right after it, because `_ASSIGN_RE`/`_BOOL_RETURN_RE`
scanned raw script text including comments.
"""
from __future__ import annotations

from aryx.cpq.bml import evaluate_tier1, evaluate_hide_tier1, _strip_line_comments


def test_commented_out_assign_is_ignored_real_apx_next_script():
    script = (
        '//8/1/2025 Afifa added to add APX NEXT Enhanced if NEXT ENHANCED LTE PLUS 5G is selected\n'
        'returnVal = "";\n'
        'if(hWVersion_astro == "NEXT ENHANCED LTE PLUS 5G"){\n'
        '\t//returnVal = "APX NEXT Enhanced";\n'
        '\treturnVal = "APX NEXT ENHANCED";\n'
        '\t//print productSelectionProduct_all;\n'
        '}\n'
        'return returnVal;'
    )
    allowed, blocked = evaluate_tier1(script, {"hWVersion_astro": "NEXT ENHANCED LTE PLUS 5G"})
    assert blocked is False
    assert allowed == ["APX NEXT ENHANCED"]


def test_commented_out_bool_return_is_ignored():
    script = (
        'if (region_all == "NA") {\n'
        '    //return true;\n'
        '    return false;\n'
        '} else {\n'
        '    return true;\n'
        '}'
    )
    hide, blocked = evaluate_hide_tier1(script, {"region_all": "NA"})
    assert blocked is False
    assert hide is False


def test_strip_line_comments_preserves_urls_inside_string_literals():
    text = 'returnVal = "see http://example.com/path for docs";'
    stripped = _strip_line_comments(text)
    assert stripped == text


def test_strip_line_comments_removes_trailing_comment():
    text = 'returnVal = "A"; // trailing note\nreturn returnVal;'
    stripped = _strip_line_comments(text)
    assert "// trailing note" not in stripped
    assert 'returnVal = "A";' in stripped
    assert "return returnVal;" in stripped
