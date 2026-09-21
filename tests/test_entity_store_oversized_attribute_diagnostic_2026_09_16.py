"""Tests for _log_oversized_entity_attributes() -- the diagnostic added for
the 2026-09-16 confirm-job incident ("string too long to represent as
jsonb string", Postgres's 268435455-byte single-scalar-string limit).
Log-only: never raises, never truncates, never changes what gets saved.
"""
from __future__ import annotations

import logging

from aryx.store.entity_store import _ATTR_SIZE_WARN_BYTES, _log_oversized_entity_attributes


def test_small_attributes_log_nothing(caplog):
    with caplog.at_level(logging.WARNING):
        _log_oversized_entity_attributes("Product", {"name": "APX1000", "region": "NA"})
    assert not any("unusually large" in r.message for r in caplog.records)


def test_oversized_attribute_logs_the_offending_key(caplog):
    huge_value = "x" * (_ATTR_SIZE_WARN_BYTES + 1000)
    with caplog.at_level(logging.WARNING):
        _log_oversized_entity_attributes(
            "Product", {"name": "APX1000", "notes": huge_value},
        )
    warnings = [r for r in caplog.records if "unusually large" in r.message]
    assert len(warnings) == 1
    assert "largest_key='notes'" in warnings[0].message
    assert "ontology_type=Product" in warnings[0].message


def test_multiple_keys_reports_the_largest_one(caplog):
    with caplog.at_level(logging.WARNING):
        _log_oversized_entity_attributes("Product", {
            "small": "a" * 100,
            "medium": "b" * 1000,
            "biggest": "c" * (_ATTR_SIZE_WARN_BYTES + 1),
        })
    warnings = [r for r in caplog.records if "unusually large" in r.message]
    assert len(warnings) == 1
    assert "largest_key='biggest'" in warnings[0].message


def test_non_serializable_value_is_handled_without_raising(caplog):
    """A value json.dumps can't handle directly (e.g. bytes) must degrade
    gracefully via default=str -- this diagnostic must never be the thing
    that breaks a real save."""
    with caplog.at_level(logging.WARNING):
        _log_oversized_entity_attributes("Product", {"blob": b"\x00\x01\x02"})
    # No exception raised is the actual assertion here; small value logs nothing.
    assert not any("unusually large" in r.message for r in caplog.records)


def test_empty_attributes_does_not_raise(caplog):
    with caplog.at_level(logging.WARNING):
        _log_oversized_entity_attributes("Product", {})
    assert not any("unusually large" in r.message for r in caplog.records)
