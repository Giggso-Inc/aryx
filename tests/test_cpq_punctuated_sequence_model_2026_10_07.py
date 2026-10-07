"""ws 1267 (2026-10-07): family sequence rows sit under punctuated codes ("X8/XE") that no hierarchy row names; the
family's displayCPQModel list bridges them. Added only when the family itself has no sequence rows."""
from __future__ import annotations

import pytest

from aryx.cpq.data_table import data_table_product as dtp

HIER = [
    {"cpqModelName": "THING8SERIES", "Product": "THING8",
     "displayCPQModel": "Thing 8, Thing 8H, Thing 8XE, Thing 8HXE, Thing 8HSRX"},
    {"cpqModelName": "OTHERSERIES", "Product": "OTHER1", "displayCPQModel": "Other 1"},
]


@pytest.fixture(autouse=True)
def _clear():
    dtp._clear_sequence_model_codes_cache()
    yield
    dtp._clear_sequence_model_codes_cache()


def _install(monkeypatch, models):
    seq = [{"CPQModel": m, "AttrName": "x"} for m in models]
    monkeypatch.setattr(dtp, "_load_all_tables", lambda *a, **k: ([], seq, list(HIER), [], []))


def test_punctuated_codes_are_bridged_from_the_display_list(monkeypatch):
    _install(monkeypatch, ["THING8/XE", "THING8H/HXE/H-SRX", "OTHER1", "OTHER1/LI"])
    assert dtp.resolve_punctuated_sequence_models("THING8", 1267) == ("THING8/XE", "THING8H/HXE/H-SRX")


def test_nothing_when_the_family_has_its_own_sequence_rows(monkeypatch):
    _install(monkeypatch, ["THING8SERIES", "THING8/XE"])
    assert dtp.resolve_punctuated_sequence_models("THING8", 1267) == ()


def test_plain_codes_are_never_picked_up(monkeypatch):
    _install(monkeypatch, ["THING8XE"])
    assert dtp.resolve_punctuated_sequence_models("THING8", 1267) == ()


def test_a_longer_numbered_family_is_not_claimed(monkeypatch):
    _install(monkeypatch, ["THING8/XE", "THING80/XE", "THING8/XE_BOM"])
    assert dtp.resolve_punctuated_sequence_models("THING8", 1267) == ("THING8/XE", "THING8/XE_BOM")
