"""Ground a user's attribute phrase onto the catalog's real attribute labels.

The router copies the attribute as the user typed it ("carrier"), but the
Data Table is keyed by exact labels ("Carrier Selection", "Wireless
Carrier"). Matching is word-based and deterministic -- no LLM:

  3  same words as the label            "carrier selection" -> "Carrier Selection"
  2  every phrase word is in the label  "carrier" -> "Carrier Selection"
  1  every label word is in the phrase  "region code" -> "Region"

Only the labels at the best score are returned, so an exact match never
drags in looser ones. Case, plurals and filler words are ignored.
"""
from __future__ import annotations

import re

_FILLER = frozenset({"a", "an", "the", "of", "for", "as", "with"})
_MAX_LABELS = 5


def _words(text: str) -> frozenset[str]:
    """Lower-cased, singularised content words of `text`."""
    out = set()
    for word in re.findall(r"[0-9a-z]+", text.casefold()):
        if word in _FILLER:
            continue
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        out.add(word)
    return frozenset(out)


def _score(phrase: frozenset[str], label: frozenset[str]) -> int:
    """How well `label` matches `phrase` (0 = not at all)."""
    if not phrase or not label:
        return 0
    if phrase == label:
        return 3
    if phrase <= label:
        return 2
    if label <= phrase:
        return 1
    return 0


def ground_attribute_label(phrase: str, labels: list[str]) -> list[str]:
    """Real labels that best match `phrase`, in `labels` order (at most 5).

    Args:
        phrase: Attribute as the user typed it, e.g. "carrier".
        labels: The catalog's real attribute labels.

    Returns:
        The labels sharing the best non-zero score, or [] when none match.
    """
    phrase_words = _words(phrase or "")
    scored = [(_score(phrase_words, _words(label)), label) for label in labels]
    best = max((s for s, _ in scored), default=0)
    if best == 0:
        return []
    return [label for s, label in scored if s == best][:_MAX_LABELS]


def value_variants(value: str) -> list[str]:
    """Spellings to search for `value`: as typed, plus without punctuation.

    "AT&T" -> ["AT&T", "ATT"], so it still matches a stored "ATT/FIRSTNET".
    """
    raw = (value or "").strip()
    if not raw:
        return []
    variants = [raw]
    bare = re.sub(r"[^0-9A-Za-z]", "", raw)
    if bare and bare != raw:
        variants.append(bare)
    return variants
