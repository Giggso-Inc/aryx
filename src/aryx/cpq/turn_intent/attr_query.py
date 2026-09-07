"""``detect_attr_query`` -- resolve an options-query to a specific
attribute (Phase 4 step 2 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Stateless -- needs no
engine-instance callback.
"""

from __future__ import annotations

from aryx.cpq.engine import _variable_words
from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.patterns2 import _OPTIONS_KEYWORDS


def detect_attr_query(question: str, attrs: list[ConfigAttr],
) -> ConfigAttr | None:
    """If the question asks about options for a specific attribute, return it.

    Detection: question contains an attribute's variable_name AND any
    option-query keyword. Reads options from already-loaded attrs — no DB
    call, no hardcoding.

    When more than one attr matches (e.g. "Hardware" and "Hardware
    Version" both appear in the same attribute list — confirmed live
    once two catalogs share a workspace), the LONGEST/most specific
    match wins rather than whichever happens to come first in list
    order, so a shorter, coincidentally-matching label can't shadow the
    attribute the user actually meant.

    Word-overlap fallback: BigMachines attributes are frequently exported
    with a near-useless leaf display_label (e.g. "Type") while the actual
    UI grouping the customer names ("Carry Solutions") only lives inside
    the variable_name itself ("carrySolutionsType_apcr"). When neither the
    exact-substring nor display_label check matches, fall back to scoring
    attrs by how many of their significant camelCase-split variable_name
    words appear in the question — requires at least 2 matching words (a
    single generic word must never hijack an unrelated question) and
    picks the attr with the most matched words.
    """
    q_lower = question.lower()
    has_options_keyword = any(kw in q_lower for kw in _OPTIONS_KEYWORDS)
    if not has_options_keyword:
        return None
    q_flat = q_lower.replace("_", "")
    # Match by variable_name (case-insensitive, underscore-tolerant)
    vn_matches = [
        attr for attr in attrs
        if attr.variable_name.lower().replace("_", "") in q_flat
        or attr.variable_name.lower() in q_lower
    ]
    if vn_matches:
        return max(vn_matches, key=lambda a: len(a.variable_name))
    # Fallback: match by display_label
    label_matches = [attr for attr in attrs if attr.display_label.lower() in q_lower]
    if label_matches:
        return max(label_matches, key=lambda a: len(a.display_label))
    # Fallback: word-overlap against the camelCase-split variable_name.
    # Trailing tokens shared by many attrs in this list (e.g. "_apcr",
    # "_astro") are catalog/product-line codes, not customer-facing
    # words — computed here from the actual attrs rather than
    # hardcoded, so a future catalog's own suffix convention is picked
    # up automatically instead of needing a new hardcoded name.
    suffix_counts: dict[str, int] = {}
    for a in attrs:
        _, _, tail = a.variable_name.rpartition("_")
        if tail and tail.isalpha() and tail.islower() and len(tail) <= 8:
            suffix_counts[tail] = suffix_counts.get(tail, 0) + 1
    catalog_suffixes = {s for s, c in suffix_counts.items() if c >= 5}

    q_words = set(q_lower.replace("_", " ").split())
    best_attr: ConfigAttr | None = None
    best_score = 1  # require > 1 matched word
    for attr in attrs:
        vn = attr.variable_name
        base, _, tail = vn.rpartition("_")
        if base and tail in catalog_suffixes:
            vn = base
        words = _variable_words(vn)
        if len(words) < 2:
            continue
        score = sum(1 for w in words if w in q_words)
        if score == len(words) and score > best_score:
            best_score = score
            best_attr = attr
    return best_attr
