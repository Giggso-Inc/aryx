"""Product-selector preference for extract_catalog_hints when one option
text is owned by several attributes (see product_selector_entries).
"""
from __future__ import annotations

from aryx.raven_log import raven_log, would_log


def product_selector_entries(
    entries: list[tuple[str, str]], discriminators: dict[str, frozenset[str]] | None = None,
) -> list[tuple[str, str]]:
    """The (variable_name, item_value) entries a matched phrase may hint.

    One owning attribute: all its entries, unchanged. Two or more owners
    normally means never guess -- except when one owner is the platform's
    product selector (catalog_profile.PRODUCT_LITERAL): a quote request
    names the product being quoted, so that phrase selects the product and
    the other owners (add-on pickers that depend on it) stay unhinted.
    Live case (ws 1267, Astro25Configdata, 2026-10-07): "APX 900" is the
    only "APX 900" option of productSelectionProduct_all (APX900FLASHPORT)
    and also an option of productSelectionDMSO_astro, the DMS service
    picker, so "I want a quote for APX 900" hinted nothing and Product was
    asked with ~300 options. Returns [] when there are several owners and
    none is the product selector (never guess). A selector with 2+ values
    for the phrase is still rejected by the caller's same-attr check.

    `discriminators` (base model narrowing, flag): {attribute: UPPER values} the product's model separates its base
    models by, read from the model's own whitelist rows. When no owner is the product selector, an owner whose value
    for this phrase is one of those values is preferred, but only if exactly ONE owner qualifies (ws 1267: "700/800
    MHz" is an option of the frequency-band attribute and of several antenna attributes, "Limited Keypad" of the keypad
    and the display-type attribute, so typing them hinted nothing and both were then guessed).
    """
    owners = {vn for vn, _iv in entries}
    if len(owners) == 1:
        return entries
    from aryx.cpq.catalog_profile import PRODUCT_LITERAL  # lazy: avoids an import cycle
    preferred = [e for e in entries if e[0] == PRODUCT_LITERAL]
    if not preferred and discriminators:
        by_model = [e for e in entries if e[1].strip().upper() in discriminators.get(e[0], ())]
        if len({vn for vn, _iv in by_model}) == 1:
            preferred = by_model
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ask.catalog_hint.multi_owner phrase owned by several attrs", context={
                    "selected_option": "model_discriminator", "available_options": ["model_discriminator", "skip"],
                    "reason_code": "MODEL_DISCRIMINATOR_OWNER", "owner_count": len(owners),
                    "discriminator_values": len(set(preferred))})
            return preferred
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.catalog_hint.multi_owner phrase owned by several attrs", context={
            "selected_option": "product_selector" if preferred else "skip",
            "available_options": ["product_selector", "skip"],
            "reason_code": "PRODUCT_SELECTOR_OWNER" if preferred else "MULTI_OWNER_NEVER_GUESS",
            "owner_count": len(owners), "product_selector_values": len(set(preferred))})
    return preferred
