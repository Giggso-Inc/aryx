"""Answer wording for the /ask attribute_search route.

Kept apart from the handler so ask_attribute_search.py and
ask_attribute_handoff.py share one set of phrasings.
"""

from __future__ import annotations

from aryx.cpq.attribute_search.lookup import AttributeSearchResult

_MAX_LISTED_PRODUCTS = 20
_MAX_LISTED_VALUES = 10


def _listed(items: list[str], cap: int) -> str:
    """Comma-joined `items`, truncated to `cap` with an "and N more" tail."""
    shown = ", ".join(items[:cap])
    extra = len(items) - cap
    return f"{shown} and {extra} more" if extra > 0 else shown


def _joined(labels: list[str], word: str) -> str:
    """"A", "A and B", "A, B or C" -- `word` is "and" or "or"."""
    if len(labels) <= 1:
        return "".join(labels)
    return f"{', '.join(labels[:-1])} {word} {labels[-1]}"


def _format_answer(res: AttributeSearchResult) -> str:
    """Plain-language answer for an attribute search result."""
    label = _joined(res.labels, "or")
    if res.feature_only:
        models = [p["model"] for p in res.products]
        if len(models) == 1:
            text = f"{models[0]} offers {_joined(res.products[0]['labels'], 'and')}"
            return text if text[-1] in "?.!" else text + "."
        return f"{len(models)} products offer {label}: {_listed(models, _MAX_LISTED_PRODUCTS)}."
    if res.value is None:
        if not res.offered_values:
            return f"I couldn't find any product that offers {label}."
        return (
            f"Products offer these {label} options: "
            f"{_listed(res.offered_values, _MAX_LISTED_VALUES)}. Which one do you need?"
        )
    models = [p["model"] for p in res.products]
    if not models:
        return f"I couldn't find any product with {label} '{res.value}'."
    if len(models) == 1:
        only = res.products[0]
        values = " / ".join(only["values"]) or res.value
        return f"{only['model']} offers {_joined(only['labels'], 'and')}: {values}."
    return (
        f"{len(models)} products offer {label} '{res.value}': "
        f"{_listed(models, _MAX_LISTED_PRODUCTS)}."
    )


def _criteria(res: AttributeSearchResult) -> str:
    """What was searched for, e.g. "Carrier Selection 'ATT'" or "TAA Compliant"."""
    label = _joined(res.labels, "or")
    return label if res.feature_only or res.value is None else f"{label} '{res.value}'"
