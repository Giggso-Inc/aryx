"""Shared display-name resolution for all entity render paths.

Single source of truth for _NAME_KEYS and _GENERIC_NAMES — previously
duplicated (and diverged) across explore.py, falkor_store.py, and
ontology/rdf/model.py, causing the same entity to show different labels
depending on which code path rendered it.

Import:
    from aryx.display_name import display_name
"""
from __future__ import annotations

from typing import Any

# Priority-ordered attribute keys used to pick a human-readable display label.
# Order matters: first match wins. Domain-specific keys added after universal ones.
_NAME_KEYS: tuple[str, ...] = (
    # Universal / standard
    "name", "full_name", "title", "label", "ticket_ref", "ref",
    "sku", "code", "email", "username", "_text",
    # Domain-specific keys (government / procurement / config)
    "COMPANY", "COMPANY_NAME", "company", "company_name",
    "CAGE_CODE", "cage_code",
    "ITEM_NAME", "item_name",
    "LITERAL", "literal",
    "COLLOQUIAL_NAME", "colloquial_name",
    "FSC", "fsc",
    "NIIN", "niin",
    # XML / structured config fields
    "variable_name", "var_name", "bm_variable_name",
    "item_text", "item_value",
    "prop_value", "property_value", "prop_type",
    "bm_name", "func_name", "rule_name",
    "java_class_name", "file_name", "relative_path",
)

# Values that look like names but are placeholders — skip and fall through.
_GENERIC_NAMES: frozenset[str] = frozenset({
    "no item name available", "not available", "n/a", "none", "null",
    "unknown", "tbd", "to be determined", "see above", "see below",
    "no name", "no description", "no data",
    "########",  # Excel column-too-narrow placeholder (truncated dates)
})


def display_name(
    attributes: dict[str, Any] | None,
    entity_id: int | None = None,
    display_key: str | None = None,
) -> str:
    """Resolve a human-readable display label for an entity.

    Resolution order:
      1. display_key override (from attribute_schema) — if provided and non-empty
      2. Priority scan of _NAME_KEYS — _GENERIC_NAMES values are skipped
      3. Fallback: first short non-private non-numeric string value in attributes
      4. f"#{entity_id}" if entity_id provided, else ""

    Args:
        attributes: Entity attribute dict. None is treated as empty.
        entity_id:  Numeric entity ID — used only in the final fallback label.
        display_key: Attribute key configured per ontology type. When set and
                     the key resolves to a non-generic value, it wins over
                     _NAME_KEYS. Pass None (default) to skip this step.
    """
    attrs = attributes or {}

    # 1. Schema-configured display key takes priority
    if display_key:
        val = attrs.get(display_key)
        if val and str(val).lower() not in _GENERIC_NAMES:
            return str(val)

    # 2. Priority key scan
    for key in _NAME_KEYS:
        val = attrs.get(key)
        if val and str(val).lower() not in _GENERIC_NAMES:
            return str(val)

    # 3a. Fallback — first short non-private, non-numeric string value
    #     (numeric-string values are meaningful data IDs but poor display names;
    #      prefer "Acme Corp" over "12345" when neither key is in _NAME_KEYS)
    for key, val in attrs.items():
        if key.startswith("_"):
            continue
        if (isinstance(val, str) and 0 < len(val) <= 80
                and not val.isdigit()
                and val.lower() not in _GENERIC_NAMES):
            return val

    # 3b. Last resort — any short non-private string, including numeric-only
    for key, val in attrs.items():
        if key.startswith("_"):
            continue
        if isinstance(val, str) and 0 < len(val) <= 80 and val.lower() not in _GENERIC_NAMES:
            return val

    return f"#{entity_id}" if entity_id is not None else ""
