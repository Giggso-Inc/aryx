"""Attr-label mention-detection helpers, split out of `cpq/engine.py`'s
module-level scope (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.
md — module-level helper extraction beyond the 8 previously-deferred
methods, done purely to shrink engine.py further). Re-exported from
`aryx.cpq.engine` (see the import there) so every existing `from
aryx.cpq.engine import <name>` caller/test keeps working unchanged.
Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

import re


def _label_mention_span(
    label_lower: str, q_lower: str, max_dropped_leading: int = 2,
) -> "tuple[int, int] | None":
    """(start, end) of the label's first match in q_lower, or None.

    Three tiers, each stricter than the risk of the next: full-phrase
    substring, then up to `max_dropped_leading` leading words dropped
    (both preserve the label's own word ORDER), then — only if neither
    finds anything — a word-SET fallback requiring EVERY one of the
    label's own words to appear as a whole word somewhere in q_lower,
    order-independent. Factored out so callers that need WHERE the label
    was mentioned (not just whether) can scope a search to nearby text
    instead of the whole message. See `_label_mentioned`'s docstring for
    why the dropped-leading-words retry exists, and the word-set tier's
    own docstring note below for why it's safe to add.
    """
    if label_lower in q_lower:
        idx = q_lower.index(label_lower)
        return idx, idx + len(label_lower)
    words = label_lower.split()
    # Floor of 1, not 2 — a genuine 2-word label (e.g. SVX's "Select
    # Model") naturally gets its generic leading qualifier dropped just
    # like longer labels do ("change the model to X" for "Select Model"),
    # but the old floor of 2 meant a 2-word label could NEVER drop any
    # word at all (max(2, 2-2)=2, requiring the exact 2-word phrase
    # verbatim) — confirmed live: "change the model to SVX Video Remote
    # Speaker Mic TAA" fell through to "I didn't quite catch that"
    # because "select" never appears in the message. Docstring's own
    # "at least half the label's own words remain" already implies a
    # floor of 1 for a 2-word label; this was an off-by-one versus that
    # stated intent.
    min_words = max(1, len(words) - max_dropped_leading)
    if len(words) > min_words:
        for start in range(1, len(words) - min_words + 1):
            suffix = " ".join(words[start:])
            if suffix in q_lower:
                idx = q_lower.index(suffix)
                return idx, idx + len(suffix)
    # Word-set fallback (Raven-flagged, previously deferred pending a
    # false-positive review): a REORDERED phrase — "change the quantity of
    # jacket magnetic mount" states the quantity word BEFORE the mount name,
    # reversed from the label's own "...Jacket Magnetic Mount Quantity"
    # order, AND drops the generic "mounting type" prefix in the same
    # breath — never matches either tier above (which only ever drop
    # leading words WITHOUT reordering the rest), nor a naive order-blind
    # check requiring every word INCLUDING the dropped prefix (confirmed
    # still failing after c570bf4, see docs/CPQ_SESSION_2_OPEN_ISSUES.md
    # item 1). Combines both tolerances: try progressively shorter
    # leading-word-dropped SUFFIXES of the label's word list (same
    # min_words bound as the tier above), but check each suffix's words
    # as a SET (any order) instead of a contiguous phrase — the least
    # permissive candidate (full word list, order-blind) is tried first,
    # only dropping more leading words if that still doesn't match. Safe
    # to add here because this function only ever gates a coarse "is this
    # attr even relevant" pre-filter (detect_change_request still requires
    # apply_answer/the numeric-extraction span to independently confirm a
    # real value nearby before ever resolving anything) — a false-positive
    # span here costs an extra attr considered, never a wrongly-resolved
    # value. Each candidate still requires ALL its words present (not a
    # fuzzy majority) — same "match fully or bail" discipline as every
    # other matcher in this file, just order-blind within the candidate.
    for start in range(0, len(words) - min_words + 1):
        candidate = words[start:]
        spans: list[tuple[int, int]] = []
        for w in candidate:
            m = re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", q_lower)
            if not m:
                spans = []
                break
            spans.append((m.start(), m.end()))
        if spans:
            return min(s for s, _e in spans), max(e for _s, e in spans)
    return None


def _label_mentioned(label_lower: str, q_lower: str, max_dropped_leading: int = 2) -> bool:
    """True when the user's message plausibly names this attr's label.

    A full-phrase substring match is tried first (existing behavior). Some
    display labels are auto-generated compound names carrying a generic
    leading qualifier shared by many sibling attrs (confirmed live: every
    per-mount-type quantity attr on the SVX catalog is literally named
    "mounting type {Mount Name} Quantity" — six attrs, one per mount
    option). A user naturally drops that generic prefix ("change the
    jacket magnetic mount quantity to 15") since it adds nothing
    discriminating — but the exact-phrase check rejected it entirely,
    silently falling through to "I didn't quite catch that" instead of
    recognizing a clearly-named change (confirmed live). Retries with up
    to `max_dropped_leading` leading words dropped, requiring at least half
    the label's own words to remain — bounded so a short label (e.g. two
    words) can't be matched by an almost-empty remainder.
    """
    return _label_mention_span(label_lower, q_lower, max_dropped_leading) is not None


def _label_mentioned_strict(label_lower: str, q_lower: str) -> bool:
    """Exact-phrase match, or a leading-word-dropped suffix that NEVER
    degrades to a single generic shared word (e.g. "Type"/"Package").

    Live-verified gap: `_label_mentioned`'s word-set fallback tier is
    explicitly safe only as a coarse pre-filter (its own docstring: "a
    false-positive span here costs an extra attr considered, never a
    wrongly-resolved value") because `detect_change_request` always
    requires a SEPARATE value-match (apply_answer/numeric extraction)
    before actually resolving anything — a loose label match alone never
    directly causes a wrong resolution there. `detect_attr_activation`/
    `detect_attr_clear` (docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md D2/D4)
    have no such secondary check: the label match itself IS the final
    decision. Confirmed live: "add surveillance package type" — meant for
    "Surveillance Package Type" — instead matched an unrelated "Customer
    Type" attr, because dropping "Customer" leaves the single word
    "type", which trivially appears in almost any message mentioning any
    "*Type"-suffixed attr. This helper keeps the same leading-word-drop
    tolerance for 3+-word labels (dropping down to 2+ remaining words is
    still discriminating) but requires the FULL label verbatim for a
    2-word label — no single-word degradation, ever.
    """
    if label_lower in q_lower:
        return True
    words = label_lower.split()
    if len(words) < 3:
        return False  # 2-word (or shorter) labels: exact phrase only
    for start in range(1, len(words) - 1):  # always leaves >= 2 words
        suffix = " ".join(words[start:])
        if suffix in q_lower:
            return True
    return False
