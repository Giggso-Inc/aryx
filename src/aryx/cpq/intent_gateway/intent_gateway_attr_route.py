"""`attribute_search` route for the top-level /ask router (attribute-first discovery, phase 1).

A cold-start message can start from an attribute instead of a product
("I want a product that has ATT as a carrier", "Which products are
available for carrier selection"). classify_ask_route tags it
`attribute_search` and extracts the attribute label and optional value
the user typed, verbatim. Grounding that phrase against the catalog and
the product lookup live in cpq/attribute_search/ -- nothing here touches
the catalog.

Gated by ``ARYX_CPQ_ATTR_SEARCH_ENABLED`` (off by default). With the flag
off, classify_ask_route's prompt, schema, and parsing are unchanged.
"""
from __future__ import annotations

import copy
from typing import Any

ATTRIBUTE_SEARCH = "attribute_search"

_ATTR_PROPERTIES: dict[str, dict[str, Any]] = {
    "attribute_label": {
        "type": ["string", "null"],
        "description": (
            "route=attribute_search only: the attribute the user names, "
            "copied from the message (e.g. 'carrier'). Otherwise null."
        ),
    },
    "attribute_value": {
        "type": ["string", "null"],
        "description": (
            "route=attribute_search only: the value the user wants for that "
            "attribute, copied from the message (e.g. 'ATT'). Null when no "
            "value is stated. Never guess one."
        ),
    },
}

ROUTE_LINE = (
    "- attribute_search: wants a product but names NO product -- starts "
    "from an attribute and/or value instead (carrier, band, feature...)\n"
)

RULE_TEXT = (
    "7. attribute_search ONLY when no product, model, or product-family name "
    "appears in the message -- if one does, route=quote even when an "
    "attribute is also mentioned. Copy attribute_label/attribute_value as "
    "the user wrote them; leave attribute_value null when no value is given.\n"
)

FEW_SHOTS = """
ATTRIBUTE-FIRST examples:

A1) Q: "I want a product that has ATT as a carrier"
   → route=attribute_search, attribute_label="carrier", attribute_value="ATT"
   WHY: no product named; the user starts from a carrier value.

A2) Q: "Which products are available for carrier selection"
   → route=attribute_search, attribute_label="carrier selection", attribute_value=null
   WHY: asks which products offer an attribute, no value given yet.

A3) Q: "I want APX Next radios with ATT as the carrier"
   → route=quote
   WHY: a product (APX Next) is named -- the product wins over attribute search.
"""


def is_enabled(settings: Any) -> bool:
    """True only when the flag is literally ``True``.

    Strict identity check so a MagicMock settings object (common in tests)
    never switches the route on by accident.
    """
    return getattr(settings, "cpq_attr_search_enabled", False) is True


def extend_schema(base: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the route schema with attribute_search added."""
    schema = copy.deepcopy(base)
    schema["properties"]["route"]["enum"].append(ATTRIBUTE_SEARCH)
    schema["properties"].update(copy.deepcopy(_ATTR_PROPERTIES))
    return schema


def _clean(value: Any) -> str | None:
    """Stripped string, or None for anything empty or not a string."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def parse_attr_fields(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    """Type-check the model's attribute_label/attribute_value (fail closed to None).

    Raw, unvalidated model output -- grounding against the catalog is the
    caller's job, same split as quantity/country.
    """
    return _clean(raw.get("attribute_label")), _clean(raw.get("attribute_value"))


def resolve_attr_route(
    raw: dict[str, Any], route: str,
) -> tuple[str, str | None, str | None, dict[str, Any]]:
    """(route, attribute_label, attribute_value, raw) for _parse_route.

    Non-attribute routes pass through with no attribute fields. An
    attribute_search with no label becomes the quote it was before this
    route existed, with the reason noted in the rationale.
    """
    if route != ATTRIBUTE_SEARCH:
        return route, None, None, raw
    label, value = parse_attr_fields(raw)
    if label is None:
        note = f"attribute_search_missing_label; {raw.get('rationale') or ''}"
        return "quote", None, None, {**raw, "rationale": note}
    return route, label, value, raw
