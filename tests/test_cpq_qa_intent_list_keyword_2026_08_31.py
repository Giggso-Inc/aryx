"""Live-confirmed gap (2026-08-31): after a quote reaches `awaiting_approval`
(or during active `configuring`), asking "list the attributes in APX Next"
was misread as a change-request attempt ("which attribute and value did
you mean?") instead of reaching `_handle_cpq_qa`'s whole-catalog
enumeration matcher (docs/CPQ_QA_Catalog_Attribute_Listing_Fix_2026_08_31.md).

Root cause: `CpqEngine.detect_qa_question` gates on `_QA_INTENT_RE`, whose
leading-word alternation never included "list"/"show me" -- the message
has no "?" either, so it fell through to change-request detection in
BOTH the strict (active configuration) and non-strict (awaiting_approval)
modes. Fix: added "list the/all/available"/"show me the/all/available"
as recognized leading Q&A-intent phrasing (same enumeration-intent
vocabulary `_OPTIONS_KEYWORDS` already uses for the pre-quote router),
anchored at the start of the message so a genuine change request
mentioning "list" mid-sentence is unaffected.

Raven Review finding (2026-08-31): the first cut used a BARE leading
"list"/"show me" word match, which is the mirror-image of the bug
this whole fix closes -- a genuine imperative change request like "list
Hardware Version as APX NEXT" would itself start with "list" and get
wrongly routed into Q&A instead of change-request handling. Requiring
an article after the verb ("the"/"all"/"available") keeps the match
scoped to genuine enumeration phrasing, which a "set this to that"
change command does not naturally produce.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine


def test_list_the_attributes_is_detected_as_qa_strict():
    eng = CpqEngine()
    assert eng.detect_qa_question("list the attributes in APX Next", strict=True)


def test_list_the_attributes_is_detected_as_qa_non_strict():
    eng = CpqEngine()
    assert eng.detect_qa_question("list the attributes in APX Next", strict=False)


def test_show_me_the_attributes_is_detected_as_qa():
    eng = CpqEngine()
    assert eng.detect_qa_question("show me the attributes in APX Next", strict=True)


def test_original_qa_leading_words_still_detected():
    """Regression guard: the fix only adds a new alternative, it must not
    change any pre-existing recognized phrasing."""
    eng = CpqEngine()
    for q in [
        "what are the wireless carrier options",
        "why is this required",
        "how does this work",
        "explain the difference between these",
    ]:
        assert eng.detect_qa_question(q, strict=True), q


def test_genuine_change_request_wording_is_unaffected():
    """Negative control: a real change request (doesn't start with "list"
    or "show me") must still NOT be read as Q&A -- the leading-word
    anchor means this fix only changes behavior for messages that
    actually start with the enumeration verb."""
    eng = CpqEngine()
    assert not eng.detect_qa_question(
        "change hardware version to APX NEXT 4G LTE Only", strict=True,
    )
    assert not eng.detect_qa_question(
        "change hardware version to APX NEXT 4G LTE Only", strict=False,
    )


def test_imperative_list_change_request_is_not_misrouted_as_qa():
    """Raven Review finding (2026-08-31): a genuine imperative change
    request phrased as "list X as Y" must NOT be caught by the new
    "list"-leading QA gate -- that would be the mirror-image regression
    of the bug this whole fix closes (a QA question wrongly routed as a
    change request, now potentially inverted into a change request
    wrongly routed as QA). The fix requires an article ("the"/"all"/
    "available") after "list"/"show me", which this phrasing lacks."""
    eng = CpqEngine()
    assert not eng.detect_qa_question(
        "list Hardware Version as APX NEXT", strict=True,
    )
    assert not eng.detect_qa_question(
        "list Hardware Version as APX NEXT", strict=False,
    )
    assert not eng.detect_qa_question(
        "show me Hardware Version as APX NEXT", strict=True,
    )
