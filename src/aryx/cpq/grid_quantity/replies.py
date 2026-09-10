"""Grid-quantity reply recognition -- deciding whether a pending attr is
one of the per-option quantity companions, and parsing its answer (Phase 4
step 3 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless and purely
functional -- no ``CpqEngine`` instance needed.
"""

from __future__ import annotations

import re

from aryx.cpq.engine import (
    _GRID_QUANTITY_SKIP_RE,
    _GRID_QUANTITY_WORD_NUMBERS,
    _parse_grid_quantity_dozen_phrase,
)
from aryx.cpq.grid_quantity.links import resolve_array_grid_links
from aryx.cpq.state import ConfigAttr


def is_grid_quantity_attr(attr: ConfigAttr, attrs: list[ConfigAttr]) -> bool:
    """True when `attr` is one of `resolve_array_grid_links`' hidden
    per-option quantity companions (any selector's item_map value) —
    used to gate the skip/zero reply parsing below to exactly the
    upfront-flow's own quantity attrs, never an ordinary free-text
    field."""
    links = resolve_array_grid_links(attrs)
    return any(
        attr.variable_name in item_map.values() for item_map in links.values()
    )


def parse_grid_quantity_reply(text: str) -> str | None:
    """Parse a reply to one grid-selector option's upfront quantity
    question (2026-08-26, explicit product decision): "skip" or a bare
    "0" both mean the option isn't included — stored as the literal
    "0" so it still appears in the final payload (a real, confirmed
    customer decision, not an unanswered gap) — and a plain whole
    number is that option's quantity.

    2026-08-27 follow-up: also recognizes a small, fixed vocabulary of
    natural-language quantities — spelled-out numbers ("three" -> 3)
    and the "dozen" family ("a dozen" -> 12, "half a dozen" -> 6, "2
    dozen"/"two dozen" -> 24) — converting each to its digit string.
    Deliberately NOT a general NLP number parser (see
    _GRID_QUANTITY_WORD_NUMBERS' own comment); a negative quantity
    ("-5", "minus 6") is intentionally never recognized here — a
    negative mount count has no real business meaning.

    Returns None for anything else, letting the caller fall back to
    its normal answer handling rather than guessing.
    """
    t = text.strip()
    if _GRID_QUANTITY_SKIP_RE.match(t):
        return "0"
    if t.isdigit():
        return t
    tl = t.lower()
    if tl in _GRID_QUANTITY_WORD_NUMBERS:
        return str(_GRID_QUANTITY_WORD_NUMBERS[tl])
    dozen_val = _parse_grid_quantity_dozen_phrase(t)
    if dozen_val is not None:
        return str(dozen_val)
    return None


def _extract_quantity_phrase(text: str) -> int | None:
    """The same three recognized quantity shapes parse_grid_quantity_reply
    accepts for a WHOLE single-attr reply (decline word, bare digit,
    spelled-out word number, dozen-phrase) -- but for an already-isolated
    segment of a larger multi-attr reply, not requiring the entire
    original reply to be just this. Returns None for anything
    unrecognized -- never a guess, same discipline as the single-value
    parser this mirrors."""
    t = text.strip().rstrip(".,;")
    if not t:
        return None
    if _GRID_QUANTITY_SKIP_RE.match(t):
        return 0
    if t.isdigit():
        return int(t)
    tl = t.lower()
    if tl in _GRID_QUANTITY_WORD_NUMBERS:
        return _GRID_QUANTITY_WORD_NUMBERS[tl]
    return _parse_grid_quantity_dozen_phrase(t)


# A label naming its quantity via a copula/equals/dash connector ("X is
# three", "X as a dozen", "X: 7", "X=9", "X - 7") rather than bare
# adjacency ("X 7") -- stripped from the front of the text immediately
# following a matched label before _extract_quantity_phrase runs, so the
# quantity-shape recognition above doesn't need a separate rule per
# connector word/symbol. Deliberately NOT "of"/reversed-order support
# ("7 of X", "7 Xs") -- a number appearing BEFORE the label it belongs to
# is more ambiguous (which of several labels does it modify?) and isn't
# something the single-value parser handles either; left unsupported
# rather than guessed.
_GRID_QTY_CONNECTOR_RE = re.compile(
    r"^\s*(?:is\s+a\s+|is\s+|are\s+a\s+|are\s+|as\s+a\s+|as\s+|[:=\-]\s*)?",
    re.IGNORECASE,
)


def parse_grid_batch_quantities(
    candidates: list[tuple[str, str]], user_answer: str,
) -> dict[str, int]:
    """Parse ONE reply that may cover several (key, label) candidates at
    once -- e.g. several grid-quantity attrs a customer was shown
    together in a single batched question (see
    api.ask_turn_steps.ask_grid_batch_quantity's
    _grid_batch_pending_answer/_try_apply_grid_quantities_batch_reply).
    Generic over any (key, label) pairing -- no attribute, option, or
    catalog name anywhere in this function.

    Two independent reply shapes, same "never guess" discipline as every
    other parser in this module:

    1. Positional: exactly as many comma- or newline-separated segments
       as there are candidates, in the SAME order they were presented.
       A blank segment or a bare decline word means 0 (matches the real
       native UI's own "Whole Number, 0, or Blank" convention). Resolves
       EVERY candidate, or none at all if segment count doesn't match or
       any segment fails to parse as a quantity.
    2. Named pairs: a candidate's own label (word-boundary matched,
       longest-label-first with span-masking so a shorter label that's a
       substring of a longer one already matched can't also match and
       double-assign -- e.g. "Belt Mount" vs "TEK-LOK Belt Mount") found
       in the reply, with the quantity phrase immediately following it
       (after stripping an optional connector -- see
       _GRID_QTY_CONNECTOR_RE) recognized via the SAME vocabulary
       _extract_quantity_phrase uses: bare digit, spelled-out word
       number, or dozen-phrase -- not just a bare digit, so "is three"
       and "as a dozen" both resolve, not only "7"/"9". A candidate never
       mentioned, or mentioned with no recognizable quantity nearby, is
       simply left OUT of the result -- unlike a selector's own
       inclusion-decision quantities (where an unmentioned option
       legitimately defaults to "not included"/0), every candidate here
       is already a relevant, already-decided item; not yet answering
       one is not the same as declining it, so it stays genuinely
       pending rather than being silently zeroed.

    Returns {key: quantity} for whatever it could confidently resolve --
    an EMPTY dict (never None) when neither shape resolves anything,
    letting the caller fall back to its pre-existing single-value
    handling unchanged.
    """
    if not candidates:
        return {}

    if "\n" in user_answer.strip():
        segments: list[str] | None = user_answer.strip().splitlines()
    elif "," in user_answer:
        segments = user_answer.split(",")
    else:
        segments = None
    if segments is not None and len(segments) == len(candidates):
        positional: dict[str, int] = {}
        for (key, _label), seg in zip(candidates, segments):
            qty = _extract_quantity_phrase(seg) if seg.strip() else 0
            if qty is None or qty < 0:
                positional = {}
                break
            positional[key] = qty
        if positional:
            return positional

    resolved: dict[str, int] = {}
    claimed_spans: list[tuple[int, int]] = []
    remaining_lower = user_answer.lower()
    for key, label in sorted(candidates, key=lambda kl: len(kl[1] or ""), reverse=True):
        if not label:
            continue
        m = re.search(r"(?<!\w)" + re.escape(label.lower()) + r"(?!\w)", remaining_lower)
        if not m or any(a <= m.start() < b for a, b in claimed_spans):
            continue
        zone_end = len(user_answer)
        for delim_idx in (user_answer.find(d, m.end()) for d in (",", "\n", ";")):
            if delim_idx != -1:
                zone_end = min(zone_end, delim_idx)
        zone = _GRID_QTY_CONNECTOR_RE.sub("", user_answer[m.end():zone_end], count=1)
        qty = _extract_quantity_phrase(zone)
        if qty is not None and qty >= 0:
            resolved[key] = qty
            claimed_spans.append((m.start(), m.end()))
    return resolved


def grid_batch_count_mismatch(
    candidates: list[tuple[str, str]], user_answer: str,
) -> int | None:
    """True count-mismatch detector for a positional-shaped batch reply
    that `parse_grid_batch_quantities` couldn't resolve.

    A purely positional reply ("5, 4, 3, 2") with a different segment
    count than `candidates` is genuinely ambiguous -- with one value
    missing, every later position could belong to any one of several
    candidates, and picking one would be guessing (this module's
    standing discipline). This helper exists only to let the caller give
    the customer a SPECIFIC "you gave N, I need M" message instead of a
    confusing generic rejection -- it never attempts to resolve the
    mismatch itself.

    Returns the segment count when the reply looks positional (no
    candidate label appears anywhere in it -- a named-pair reply, even a
    partial one, is not a count mismatch, it's already handled by
    parse_grid_batch_quantities) and that count differs from
    `len(candidates)`. Returns None otherwise (no candidates, no
    comma/newline segments, count matches, or any label is present --
    meaning this was a named-pair attempt, not a positional one).
    """
    if not candidates:
        return None
    if "\n" in user_answer.strip():
        segments = user_answer.strip().splitlines()
    elif "," in user_answer:
        segments = user_answer.split(",")
    else:
        return None
    if len(segments) == len(candidates):
        return None
    answer_lower = user_answer.lower()
    if any(
        label and re.search(r"(?<!\w)" + re.escape(label.lower()) + r"(?!\w)", answer_lower)
        for _key, label in candidates
    ):
        return None
    return len(segments)


def grid_batch_unparseable_segment(
    candidates: list[tuple[str, str]], user_answer: str,
) -> str | None:
    """Sibling to grid_batch_count_mismatch (dev-rv-msi PR #307 review
    follow-up, N1): the RIGHT segment count can still fail to resolve in
    parse_grid_batch_quantities if exactly one segment isn't a
    recognized quantity (e.g. "7, seven, three" with a stray typo in the
    middle) -- grid_batch_count_mismatch doesn't fire there since the
    count already matches, so that reply previously fell through to the
    same generic single-attr rejection this whole mismatch-messaging
    effort exists to avoid.

    Returns the display_label of the FIRST candidate whose positional
    segment failed to parse (so the caller can name it specifically), or
    None when the count doesn't match, a label is present (named-pair
    territory, not positional), or every segment parses fine (nothing to
    report -- parse_grid_batch_quantities would have already resolved
    it).
    """
    if not candidates:
        return None
    if "\n" in user_answer.strip():
        segments: list[str] | None = user_answer.strip().splitlines()
    elif "," in user_answer:
        segments = user_answer.split(",")
    else:
        return None
    if len(segments) != len(candidates):
        return None
    answer_lower = user_answer.lower()
    if any(
        label and re.search(r"(?<!\w)" + re.escape(label.lower()) + r"(?!\w)", answer_lower)
        for _key, label in candidates
    ):
        return None
    for (_key, label), seg in zip(candidates, segments):
        qty = _extract_quantity_phrase(seg) if seg.strip() else 0
        if qty is None or qty < 0:
            return label
    return None
