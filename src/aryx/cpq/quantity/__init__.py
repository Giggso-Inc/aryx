"""CPQ quantity-parsing/detection package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_is_year_shaped_model_quantity": "quantity_hint_extraction",
    "_normalize_quantity_text": "quantity_word_numbers",
    "_substitute_number_words": "quantity_word_numbers",
    "_words_to_number": "quantity_word_numbers",
    "extract_quantity_decimal_hint": "quantity_hint_extraction",
    "extract_quantity_hint": "quantity_hint_extraction",
    "find_catalog_quantity_attrs": "quantity_turn_detection",
    "is_valid_product_quantity": "quantity_patterns",
    "quantity_turn_precheck": "quantity_turn_detection",
    "question_mentions_quantity": "quantity_turn_detection",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.quantity.{mod_name}")
    return getattr(mod, name)
