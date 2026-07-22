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

from aryx.cpq.bml import evaluate_tier1, evaluate_hide_tier1, _strip_line_comments, _branch_values


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


def test_branch_values_rejects_string_concatenation_instead_of_truncating():
    # Real SVX script (confirmed live: sVXTAAKitHelpText_viSoln's payload
    # value was the literal truncated string "<model style=" — _ASSIGN_RE
    # silently matched only the FIRST quoted fragment of a `+`-concatenated
    # expression and returned it as if it were the whole intended value).
    body = (
        'link="Note: ships with 2 batteries.";\n'
        'returnval ="<model style="+"\\""+"color:#2B8838; font-size:9pt;"'
        '+"\\""+">"+"<b>"+link+"</b></model>";'
    )
    assert _branch_values(body) is None


def test_branch_values_still_resolves_clean_pipe_delimited_literals():
    # Regression guard: the real Tier-1 idiom (no concatenation) must be
    # completely unaffected by the concatenation-rejection check above.
    body = 'returnVal = "APX NEXT ENHANCED"|"APX NEXT XE 4G LTE PLUS 5G";'
    assert _branch_values(body) == ["APX NEXT ENHANCED", "APX NEXT XE 4G LTE PLUS 5G"]
