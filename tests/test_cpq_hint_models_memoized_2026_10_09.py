"""The device's candidate models are resolved once per wording and turn, not once per attribute (ws 1267, dev, 2026-10-09:
`stage_not_applicable_guard` took 87 of the 123 s of the first pass, 30 ms for each of 2,874 attributes)."""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.data_table import data_table_product as dtp

HINT = "I want to quote for APX 900 in US"


def _resolve(cache, hint=HINT, calls=None):
    with patch.object(dtp, "_resolve_product_cpq_models_from_hint_uncached",
                      side_effect=lambda *a, **k: (calls.append(a[0]) or ("APX900", "APX900_BOM"))):
        return dtp.resolve_product_cpq_models_from_hint(hint, 1267, "p", cache)


def test_the_answer_is_computed_once_per_wording_in_a_shared_cache():
    calls: list = []
    cache: dict = {}
    assert [_resolve(cache, calls=calls) for _ in range(5)] == [("APX900", "APX900_BOM")] * 5
    assert calls == [HINT]
    _resolve(cache, hint="quote for SRX 2200", calls=calls)
    assert calls == [HINT, "quote for SRX 2200"]                          # another wording is its own entry


def test_without_a_cache_nothing_is_remembered():
    calls: list = []
    for _ in range(3):
        _resolve(None, calls=calls)
    assert len(calls) == 3


def test_an_empty_answer_is_remembered_too():
    calls: list = []
    cache: dict = {}
    with patch.object(dtp, "_resolve_product_cpq_models_from_hint_uncached", side_effect=lambda *a, **k: (calls.append(1) or ())):
        for _ in range(4):
            assert dtp.resolve_product_cpq_models_from_hint("zzz", 1267, "p", cache) == ()
    assert len(calls) == 1


def test_the_guard_over_many_attributes_resolves_the_device_once():
    """2,874 attributes through `_named_attr_confirmed_not_applicable` -> one resolution (what the first pass paid per attribute)."""
    from aryx.cpq import engine as eng
    calls: list = []
    cache: dict = {}
    with patch.object(dtp, "_resolve_product_cpq_models_from_hint_uncached",
                      side_effect=lambda *a, **k: (calls.append(1) or ("APX900",))), \
            patch.object(eng, "dt_attr_ever_governed_for_cpq_model", return_value=True):
        for i in range(300):
            assert eng.CpqEngine._named_attr_confirmed_not_applicable(f"attr{i}_astro", HINT, 1267, "p", cache) is False
    assert len(calls) == 1
