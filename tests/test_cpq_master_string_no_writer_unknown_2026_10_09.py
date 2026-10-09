"""Flag `cpq_master_string_no_writer_unknown_enabled`: when no master-string writer fired, the empty master is unknown, not a
reason to hide (ws 1267 APX 900: Encryption Type hidden by 'Hide Secure Attributes If No Values Available (Mobile)')."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

from tests.test_cpq_master_string_hide_2026_10_05 import BASE, _flag, _hide_rule, _run
from aryx.cpq.hiding_rules import master_string


@contextmanager
def _unknown(on: bool):
    with patch.object(master_string, "_no_writer_fired_is_unknown", return_value=on):
        yield


def test_flag_off_empty_master_still_hides():
    with _flag(True), _unknown(False):
        assert _run(dict(BASE)) == {"widgetAttr"}


def test_flag_on_no_writer_fired_keeps_the_attribute():
    with _flag(True), _unknown(True):
        assert _run(dict(BASE)) == set()


def test_flag_on_writer_fired_still_decides():
    with _flag(True), _unknown(True):
        assert _run({**BASE, "countryVar": "ZZ"}) == set()                                   # attribute in master: shown
        assert _run({"modelVar": "M1", "baseVar": "B2", "countryVar": "ZZ"}) == {"widgetAttr"}  # absent: hidden


def test_reason_is_reported():
    why: list[str] = []
    with _flag(True), _unknown(True):
        from aryx.cpq.hiding_rules.master_string import _hide_with_master_string
        from tests.test_cpq_master_string_hide_2026_10_05 import _attrs
        rule = _hide_rule()
        by_rule_id = {a.entity_id: a for a in _attrs()}
        assert _hide_with_master_string(rule, _attrs(), by_rule_id, dict(BASE), {}, 1, "", None, why) is None
    assert why == ["NO_WRITER_FIRED"]
