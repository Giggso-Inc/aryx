"""Regression coverage: Hardware Version belongs to the "Product Name"
summary category (always fully shown), not the "Associated Options"
fallback (which the LLM narrator is explicitly allowed to partially
cover, by design, to avoid hallucinated placeholders for omitted facts).

Live-verified gap (2026-07-24): a customer explicitly changed Hardware
Version via "change the hardware version to APX NEXT (4G LTE+5G)", and
the resulting "Configuration complete" summary never mentioned it at
all -- the JSON payload had it correctly, but hWVersion_astro matched no
_SUMMARY_CATEGORY_KEYS fragment, fell to the fallback category, and the
narrator silently dropped it from its partial-coverage prose.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine


def test_hardware_version_categorized_as_product_name():
    assert CpqEngine._summary_category("hWVersion_astro") == "Product Name"


def test_other_product_name_fragments_still_match():
    assert CpqEngine._summary_category("modelSelectionSelectModel_viSoln") == "Product Name"
    assert CpqEngine._summary_category("modelSelectionbaseModel_astro") == "Product Name"
    assert CpqEngine._summary_category("productSelectionProduct_all") == "Product Name"


def test_unrelated_attr_still_falls_to_associated_options():
    assert CpqEngine._summary_category("magneticCharger_viSoln") == "Associated Options"
