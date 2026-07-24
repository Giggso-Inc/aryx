"""auto_fill pending gate: integration (noise) fields are never asked.

Issue 9 (docs/CPQ_PRODUCT_SWITCH_ISSUE.md): CRM_BILL_COUNTRY ("Bill
Country") — a CRM-integration field build_payload unconditionally excludes
— got promoted to a user question through the decision-required "country"
fragment in its name, and was asked FIRST after a product switch (a turn
whose message carries no country hint to fill it beforehand). Asking is
pure waste: the answer is collected, then silently dropped from the
payload. Noise vars must never pend, options or not.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def _free_text(entity_id: int, vn: str, label: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=label,
        required=False, default_value="", options=[],
    )


def test_noise_integration_field_with_decision_fragment_is_never_asked():
    attrs = [
        _free_text(1, "CRM_BILL_COUNTRY", "Bill Country"),
        _free_text(2, "CRM_SHIP_COUNTRY", "Ship Country"),
    ]
    _filled, _display, pending = CpqEngine().auto_fill(attrs, hints={})

    assert pending == [], (
        "integration fields (noise vars) must never become questions — "
        "build_payload drops them unconditionally, so any answer is wasted"
    )


def test_genuine_country_attr_still_pends():
    attrs = [_free_text(3, "ultimateDestinationCountry", "Ultimate Destination Country")]
    _filled, _display, pending = CpqEngine().auto_fill(attrs, hints={})

    assert [a.variable_name for a in pending] == ["ultimateDestinationCountry"], (
        "the real, lowercase-named country input must still be asked"
    )
