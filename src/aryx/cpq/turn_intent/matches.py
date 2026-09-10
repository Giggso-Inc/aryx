"""``_change_request_matches`` -- generator yielding every (attr, value_hint)
change-request match in a message (Phase 4 step 2 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

The per-candidate matching step is factored out into
``match_candidate._match_change_request_candidate`` purely to keep both
files under the file-size cap -- identical logic to the original single
220-line method, split at the natural "per try_order iteration" boundary.
Needs the live ``CpqEngine`` instance (``engine`` param): the per-candidate
helper falls back to ``engine.extract_hints`` when no direct value match
is found.
"""

from __future__ import annotations

from collections.abc import Iterator

from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.match_candidate import _match_change_request_candidate
from aryx.cpq.turn_intent.patterns import _ARROW_RE, _CHANGE_VERB_RE

# _label_mention_span is used only for the label_spans setup below.
from aryx.cpq.engine import _label_mention_span


def _change_request_matches(
    engine,
    question: str,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    filled_multi: dict[str, list[str]] | None = None,
) -> Iterator[tuple[ConfigAttr, str]]:
    """Generator yielding every (attr, new_value_hint) match — shared by
    `detect_change_request` (first match only) and
    `detect_change_requests_multi` (up to `_MAX_MULTI_CHANGE_REQUESTS`).
    See `detect_change_request`'s docstring for the matching contract;
    this is the same body with `return` turned into `yield` + `continue`
    so the `for attr in _try_order` loop keeps scanning afterward
    instead of exiting the whole function.
    """
    q_lower = question.lower()
    has_change_verb = bool(_CHANGE_VERB_RE.search(question)) or bool(_ARROW_RE.search(question))
    multi = filled_multi or {}

    # Each candidate attr's own label-mention span (start, end) in the
    # lowercased message, when found — used below to scope free-text
    # numeric extraction to the text near THIS attr's own mention
    # rather than the whole message. A message naming two sibling
    # quantity attrs (confirmed live: SVX's per-mount-type quantity
    # attrs are all named "mounting type {Mount Name} Quantity", one
    # per mount option) — e.g. "change the jacket magnetic mount
    # quantity to 15 and the pouch mount quantity to 8" — would
    # otherwise have BOTH attrs' searches independently grab the SAME
    # first number in the sentence, since neither search was scoped to
    # its own attr's mention; whichever attr `attrs` iteration reached
    # first won, regardless of which number was actually meant for it
    # (catalog order, not textual order — confirmed live by reversing
    # iteration order and getting "15" for the pouch attr instead of 8).
    label_spans: dict[str, tuple[int, int]] = {}
    for _attr in attrs:
        if _attr.variable_name not in filled and _attr.variable_name not in multi:
            continue
        span = _label_mention_span(_attr.display_label.lower(), q_lower)
        if span:
            label_spans[_attr.variable_name] = span

    # A candidate whose label is a literal SUBSTRING of another matching
    # candidate's label (e.g. "Quantity" inside "mounting type Locking
    # Molle Mount Quantity") is deprioritized — tried only as a fallback
    # if no more-specific candidate produces a result. This is narrower
    # than "shorter label loses": two independent sibling labels that
    # don't subsume each other (e.g. "Jacket Magnetic Mount Quantity" vs
    # "Pouch Mount Quantity") are NOT affected, preserving the existing
    # iteration-order contract for genuine siblings — only a real
    # substring/subsumption relationship reorders anything (confirmed
    # live: "Change the mounting type Locking Molle Mount Quantity to
    # 10" matched the generic accecsssoriesQuantityArray_viSoln — label
    # "Quantity" — instead of mountingTypeLockingMolleMountQuantity_
    # viSoln, whose real label IS "mounting type Locking Molle Mount
    # Quantity" — same principle detect_attr_query's own longest-match
    # tiebreak already applies, docs/CPQ_SESSION_2_OPEN_ISSUES.md item 2).
    _candidates = [a for a in attrs if a.variable_name in filled or a.variable_name in multi]
    _superseded: set[str] = set()
    for _a in _candidates:
        _a_label = _a.display_label.lower()
        for _b in _candidates:
            if _b is _a or _b.variable_name in _superseded:
                continue
            _b_label = _b.display_label.lower()
            if _a_label != _b_label and _a_label in _b_label:
                _superseded.add(_a.variable_name)
                break
    _try_order = (
        [a for a in attrs if a.variable_name not in _superseded]
        + [a for a in attrs if a.variable_name in _superseded]
    )

    # Try each filled attr — find one where the user's message implies a different value
    for attr in _try_order:
        result = _match_change_request_candidate(
            engine, attr, question, q_lower, filled, multi, has_change_verb, label_spans,
        )
        if result is not None:
            yield result
