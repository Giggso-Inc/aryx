"""ws 1267 (2026-10-07): OracleCpqRdb.fetch_rules named its placeholders :1, :3, :2 against (workspace_id, rule_type,
type_pattern). Bound by position of appearance, the pattern went into the rule_type test and the rule type into the LIKE:
no error and no row, so none of the 3,481 active rule_type=11 hiding rules loaded. Flag-gated fix: same order."""
from __future__ import annotations

import re
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aryx.cpq.rdb import rdb_oracle
from aryx.cpq.rdb.rdb_oracle import OracleCpqRdb

PATTERN = "astro25configdata%bmconfigrule"


class _Cursor:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, binds):
        self.sink.append((sql, binds))

    def fetchall(self):
        return []


def _run(flag: bool, **kw):
    calls: list = []

    @contextmanager
    def conn():
        yield SimpleNamespace(cursor=lambda: _Cursor(calls))

    rdb = OracleCpqRdb.__new__(OracleCpqRdb)
    with patch.object(OracleCpqRdb, "_connection", lambda self: conn()), patch.object(
            rdb_oracle, "get_settings", return_value=SimpleNamespace(cpq_oracle_fetch_rules_ordered_binds_enabled=flag)):
        rdb.fetch_rules(1267, "11", "Astro25Configdata", **kw)
    (sql, binds), = calls
    return sql, binds


def _by_appearance(sql, binds):
    """What the driver does with a tuple: the i-th placeholder to appear gets the i-th value."""
    names = list(dict.fromkeys(re.findall(r":(\d+)", sql)))
    return dict(zip(names, binds))


def _by_number(sql, binds):
    return {n: binds[int(n) - 1] for n in dict.fromkeys(re.findall(r":(\d+)", sql))}


def _like_and_type_values(sql, values):
    like = re.search(r"LIKE :(\d+)", sql).group(1)
    typ = re.search(r"'\$\.rule_type'\) = :(\d+)", sql).group(1)
    return values[like], values[typ]


@pytest.mark.parametrize("mapper", [_by_appearance, _by_number])
def test_with_the_flag_on_the_pattern_goes_to_the_like_and_the_type_to_the_type_test(mapper):
    sql, binds = _run(True)
    assert _like_and_type_values(sql, mapper(sql, binds)) == (PATTERN, "11")


def test_with_the_flag_off_the_legacy_placeholder_order_is_unchanged():
    sql, binds = _run(False)
    assert binds == (1267, "11", PATTERN) and "LIKE :3" in sql and "= :2" in sql


def test_the_legacy_order_mis_binds_when_bound_by_position_of_appearance():
    """Documents the bug the flag fixes."""
    sql, binds = _run(False)
    assert _like_and_type_values(sql, _by_appearance(sql, binds)) == ("11", PATTERN)


def test_the_status_filter_and_ref_id_column_still_compose_with_the_flag_on():
    sql, binds = _run(True, active_only=True, with_ref_id=True)
    assert "JSON_VALUE(attributes, '$.status') = '1'" in sql and "$.ref_id" in sql and len(binds) == 3
