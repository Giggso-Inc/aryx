"""Regression: _label_mentioned must recognize a 2-word display label
when the user's message drops the label's generic leading qualifier and
names only the last word.

Confirmed live: SVX's "Select Model" attr — "change the model to SVX
Video Remote Speaker Mic TAA" fell through to "I didn't quite catch that"
because the old min_words floor of 2 meant a 2-word label could NEVER
drop any leading word at all (max(2, 2-2)=2, requiring the full 2-word
phrase verbatim), even though "select" never appears in the message and
longer labels already get this exact leading-qualifier-drop tolerance
(e.g. "mounting type X Quantity" -> "X Quantity").
"""
from __future__ import annotations

from aryx.cpq.engine import _label_mentioned, _label_mention_span


def test_two_word_label_matches_with_leading_word_dropped():
    assert _label_mentioned(
        "select model", "change the model to svx video remote speaker mic taa")


def test_two_word_label_span_is_the_last_word_only():
    text = "change the model to svx video remote speaker mic taa"
    span = _label_mention_span("select model", text)
    assert span is not None
    start, end = span
    assert text[start:end] == "model"


def test_two_word_label_still_matches_full_phrase():
    assert _label_mentioned(
        "select model", "change the select model to svx video remote speaker mic taa")


def test_two_word_label_does_not_match_when_neither_word_present():
    assert not _label_mentioned("select model", "change the billing option to up front")
