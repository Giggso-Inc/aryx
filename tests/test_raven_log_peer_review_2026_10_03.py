"""Fixes from the peer review of PR #422: keyed digests, list scrubbing, rejected-key WARN, tolerated Oracle codes, forced overwrite level."""
from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace

import pytest

import aryx.log_safe as ls
import aryx.raven_log as m


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in list(__import__("os").environ):
        if name.startswith("ARYX_RAVEN_LOG_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ls, "_KEY", None)
    m.reload_config()
    yield
    m.reload_config()


def _lines(capsys):
    return [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]


def test_text_digest_is_keyed_not_plain_sha256(monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_HASH_KEY", "deployment-secret")
    plain = hashlib.sha256(b"yes").hexdigest()[:8]
    ref = ls.text_ref("yes")
    assert ref.startswith("len=3 sha=") and plain not in ref  # a guess hashed outside the deployment does not match
    assert ls.text_ref("yes") == ref  # equal text, equal digest
    assert ls.text_ref("no") != ref


def test_digest_key_from_env_is_stable_and_default_is_random_per_process(monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_HASH_KEY", "k1")
    a = ls.keyed_digest("x", 12)
    monkeypatch.setattr(ls, "_KEY", None)
    assert ls.keyed_digest("x", 12) == a  # same env key -> same digest (across pods)
    monkeypatch.delenv("ARYX_RAVEN_LOG_HASH_KEY")
    monkeypatch.setattr(ls, "_KEY", None)
    b = ls.keyed_digest("x", 12)
    monkeypatch.setattr(ls, "_KEY", None)
    assert b != a and ls.keyed_digest("x", 12) != b  # no key set: random per process, never guessable


def test_value_fields_free_text_uses_keyed_digest(monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_HASH_KEY", "deployment-secret")
    f = m.value_fields("NA", free_text=True)
    assert f["value_len"] == 2 and f["value_hash"] != hashlib.sha256(b"NA").hexdigest()[:12]
    assert "NA" not in json.dumps(f)


def test_scrub_redacts_forbidden_keys_inside_lists():
    out = m._scrub({"items": [{"token": "abc", "ok": 1}, {"fine": 2}], "tup": ({"password": "p"},)})
    assert out["items"][0] == {"token": "[redacted]", "ok": 1} and out["items"][1] == {"fine": 2}
    assert out["tup"][0] == {"password": "[redacted]"}
    clean = {"items": [{"a": 1}]}
    assert m._scrub(clean) is clean  # untouched input is returned as is


def test_rejected_key_warn_is_throttled_and_has_no_key_or_length(capsys, monkeypatch):
    from aryx.api import security
    monkeypatch.setattr(security, "_REJECTED", {"n": 0})
    for _ in range(security._REJECT_LOG_EVERY + 1):
        security._note_rejected_key()
    recs = [r for r in _lines(capsys) if r["error_code"] == "ARYX_AUTH_KEY_REJECTED"]
    assert [r["context"]["rejected_total"] for r in recs] == [1, security._REJECT_LOG_EVERY]
    assert all(r["level"] == "WARN" and "key_len" not in r["context"] for r in recs)


@pytest.mark.parametrize("ora,level,code", [
    ("ORA-00942: table or view does not exist", "WARN", "ARYX_DB_CALL_FAILED_TOLERATED"),
    ("ORA-00955: name is already used", "WARN", "ARYX_DB_CALL_FAILED_TOLERATED"),
    ("ORA-01400: cannot insert NULL", "ERROR", "ARYX_DB_CALL_FAILED"),
])
def test_oracle_failure_severity_by_ora_code(capsys, ora, level, code):
    from aryx.store.oracle_cursor import _log_stmt_failed
    _log_stmt_failed("DROP aryx_x", "execute", RuntimeError(ora), time.monotonic())
    rec = [r for r in _lines(capsys) if r["message"].startswith("db.oracle.call_failed")][0]
    assert rec["level"] == level and rec["error_code"] == code


def test_forced_overwrite_is_debug_and_plain_overwrite_is_warn(capsys, monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_LEVEL", "DEBUG")
    m.reload_config()
    from aryx.cpq.auto_fill_stages import fill_log
    attr = SimpleNamespace(select_type="single", options=[SimpleNamespace(item_value="A"), SimpleNamespace(item_value="B")])
    ctx = SimpleNamespace(filled={"v": "A"}, filled_multi={}, sources={"v": "rule"})
    fill_log.log_write(ctx, attr, "v", "B", "B", "rule", "site", force=True)
    fill_log.log_write(ctx, attr, "v", "B", "B", "rule", "site", force=False)
    recs = [r for r in _lines(capsys) if r["message"].startswith("ask.fill.overwritten")]
    assert [(r["level"], r["error_code"]) for r in recs] == [("DEBUG", ""), ("WARN", "ARYX_ASK_FILL_OVERWRITTEN")]
