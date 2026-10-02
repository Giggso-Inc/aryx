"""Tests for aryx.raven_log: level filter, kill switch, fail-open, ids, sinks, S3 batching."""
from __future__ import annotations

import json
import sys
import types
from concurrent.futures import ThreadPoolExecutor

import pytest

import aryx.raven_log as m

REQUIRED = ["schema_version", "timestamp", "level", "criticality", "service", "env", "trace_id",
            "span_id", "principal", "error_code", "message", "context", "sample_payload", "project"]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in list(__import__("os").environ):
        if name.startswith("ARYX_RAVEN_LOG_"):
            monkeypatch.delenv(name, raising=False)
    m.reload_config()
    m._warned.clear()
    yield
    m.bind_run_id("")
    m.reload_config()


def _lines(capsys):
    return [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]


def _log(level="INFO", **kw):
    kw.setdefault("criticality", "P4")
    if level in ("WARN", "ERROR"):
        kw.setdefault("error_code", "TEST_CODE")
    return m.raven_log(level, kw.pop("criticality"), "msg", **kw)


def _valid(rec):
    assert all(f in rec for f in REQUIRED)
    assert rec["level"] in ("ERROR", "WARN", "INFO", "DEBUG")
    assert rec["criticality"] in ("P1", "P2", "P3", "P4")
    assert rec["trace_id"] and rec["project"] and rec["principal"] and rec["service"]
    if rec["level"] in ("ERROR", "WARN"):
        assert rec["error_code"]


def test_default_level_info_drops_debug_keeps_info_warn_error(capsys):
    for lv in ("DEBUG", "INFO", "WARN", "ERROR"):
        _log(lv)
    out = _lines(capsys)
    assert [r["level"] for r in out] == ["INFO", "WARN", "ERROR"]
    for r in out:
        _valid(r)


def test_level_debug_emits_everything(capsys, monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_LEVEL", "DEBUG")
    m.reload_config()
    for lv in ("DEBUG", "INFO", "WARN", "ERROR"):
        _log(lv)
    assert [r["level"] for r in _lines(capsys)] == ["DEBUG", "INFO", "WARN", "ERROR"]


def test_level_warn_only_warn_and_error(capsys, monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_LEVEL", "warn")
    m.reload_config()
    for lv in ("DEBUG", "INFO", "WARN", "ERROR"):
        _log(lv)
    assert [r["level"] for r in _lines(capsys)] == ["WARN", "ERROR"]


def test_would_log_matches_filter(monkeypatch):
    assert m.would_log("INFO") and not m.would_log("DEBUG")
    monkeypatch.setenv("ARYX_RAVEN_LOG_LEVEL", "DEBUG")
    m.reload_config()
    assert m.would_log("DEBUG")


def test_disabled_is_noop(capsys, monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_ENABLED", "false")
    m.reload_config()
    assert _log("ERROR") == {}
    assert _lines(capsys) == []


def test_bad_calls_never_raise(capsys):
    assert m.raven_log("INFO", "P9", "x") == {}
    assert m.raven_log("WARN", "P3", "x") == {}  # WARN without error_code
    assert m.raven_log("LOUD", "P3", "x") == {}
    assert _lines(capsys) == []


def test_bad_env_values_fall_back(monkeypatch, capsys):
    monkeypatch.setenv("ARYX_RAVEN_LOG_LEVEL", "LOUD")
    monkeypatch.setenv("ARYX_RAVEN_LOG_SINK", "kafka")
    m.reload_config()
    _log("INFO")
    assert len(_lines(capsys)) == 1


def test_trace_id_uses_bound_id_else_random(capsys):
    _log("INFO")
    m.bind_run_id("job-123")
    _log("INFO")
    _log("INFO", trace_id="explicit")
    a, b, c = _lines(capsys)
    assert a["trace_id"] != "job-123" and len(a["trace_id"]) > 8
    assert b["trace_id"] == "job-123"
    assert c["trace_id"] == "explicit"


def test_cpq_run_id_is_read_lazily_from_cpq_module(capsys, monkeypatch):
    fake = types.SimpleNamespace(get_run_id=lambda: "cpq-run-9")
    monkeypatch.setitem(sys.modules, "aryx.cpq.logging_context", fake)
    _log("INFO")
    assert _lines(capsys)[0]["trace_id"] == "cpq-run-9"
    m.bind_run_id("job-1")  # an ingestion id wins over the CPQ one
    _log("INFO")
    assert _lines(capsys)[0]["trace_id"] == "job-1"


def test_submit_ctx_carries_bound_id_into_pool_worker(capsys):
    m.bind_run_id("job-77")
    with ThreadPoolExecutor(max_workers=1) as pool:
        plain = pool.submit(m.current_run_id).result()
        carried = m.submit_ctx(pool, m.current_run_id).result()
    assert plain == ""
    assert carried == "job-77"


def test_context_scrub_redacts_forbidden_keys(capsys):
    _log("INFO", context={"params": [1, 2], "ok": 1, "nested": {"Prompt": "secret words", "n": 2},
                          "token": "abc"})
    ctx = _lines(capsys)[0]["context"]
    assert ctx["params"] == "[redacted]" and ctx["token"] == "[redacted]"
    assert ctx["nested"] == {"Prompt": "[redacted]", "n": 2}
    assert ctx["ok"] == 1


def test_value_fields_enumerated_numeric_free_text():
    assert m.value_fields("WHIP (STANDARD)") == {"value_kind": "enumerated", "value": "WHIP (STANDARD)"}
    assert m.value_fields(3) == {"value_kind": "numeric", "value": 3}
    assert m.value_fields(["B", "A"]) == {"value_kind": "enumerated_multi", "value": ["A", "B"]}
    assert m.value_fields(None) == {"value_kind": "none"}
    ft = m.value_fields("Jane Doe, 12 Main St", free_text=True)
    assert ft["value_kind"] == "free_text" and ft["value_len"] == 20 and len(ft["value_hash"]) == 12
    assert "Jane" not in json.dumps(ft)


def test_works_without_the_sdk(capsys, monkeypatch):
    monkeypatch.setattr(m, "_SDK", False)
    rec = _log("WARN")
    _valid(rec)
    assert _lines(capsys)[0]["error_code"] == "TEST_CODE"
    assert m.raven_log("WARN", "P3", "x") == {}  # still validated, still no raise


def test_s3_sink_with_incomplete_settings_falls_back_to_stdout(capsys, monkeypatch):
    monkeypatch.setenv("ARYX_RAVEN_LOG_SINK", "s3")
    monkeypatch.setenv("ARYX_RAVEN_LOG_S3_PATH", "s3://bucket/p/")
    m.reload_config()  # no id / token / region
    _log("INFO")
    assert len(_lines(capsys)) == 1


class FakeS3:
    def __init__(self, fail=False):
        self.puts, self.fail = [], fail

    def put_object(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        self.puts.append(kw)


def _s3_cfg(monkeypatch, **extra):
    env = {"ARYX_RAVEN_LOG_SINK": "s3", "ARYX_RAVEN_LOG_S3_PATH": "s3://my-bucket/raven/logs/",
           "ARYX_RAVEN_LOG_S3_ACCESS_ID": "id", "ARYX_RAVEN_LOG_S3_ACCESS_TOKEN": "tok",
           "ARYX_RAVEN_LOG_S3_REGION": "us-chicago-1", "ARYX_RAVEN_LOG_LEVEL": "DEBUG",
           "ARYX_RAVEN_LOG_S3_FLUSH_SECONDS": "3600", "ARYX_RAVEN_LOG_S3_BATCH_MAX": "1000"}
    env.update(extra)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    m.reload_config()
    return m._cfg()


def _rec(level, n=0):
    return {"level": level, "timestamp": f"2026-10-02T00:00:{n:02d}+00:00", "message": f"{level}{n}"}


def test_s3_batches_to_one_jsonl_object_on_close(monkeypatch):
    fake = FakeS3()
    em = m._S3BatchEmitter(_s3_cfg(monkeypatch), client=fake)
    for i, lv in enumerate(("INFO", "DEBUG", "ERROR")):
        em(_rec(lv, i))
    em.close()
    assert len(fake.puts) == 1
    put = fake.puts[0]
    assert put["Bucket"] == "my-bucket" and put["Key"].startswith("raven/logs/20")
    assert put["Key"].endswith(".jsonl") and put["ContentType"] == "application/x-ndjson"
    body = put["Body"].decode().splitlines()
    assert [json.loads(x)["message"] for x in body] == ["INFO0", "DEBUG1", "ERROR2"]  # time order


def test_s3_overflow_evicts_lowest_level_and_reports_drops(monkeypatch):
    fake = FakeS3()
    em = m._S3BatchEmitter(_s3_cfg(monkeypatch, ARYX_RAVEN_LOG_S3_QUEUE_MAX="3"), client=fake)
    em(_rec("DEBUG", 1)); em(_rec("DEBUG", 2)); em(_rec("INFO", 3))
    em(_rec("ERROR", 4))   # full: evicts the oldest DEBUG
    em(_rec("DEBUG", 5))   # full, not more important than DEBUG already queued: dropped
    em.close()
    recs = [json.loads(x) for x in fake.puts[0]["Body"].decode().splitlines()]
    assert sorted(r["message"] for r in recs if r["level"] != "WARN") == ["DEBUG2", "ERROR4", "INFO3"]
    drop = [r for r in recs if r.get("error_code") == "ARYX_RAVEN_LOG_DROPPED"]
    assert len(drop) == 1 and drop[0]["context"]["dropped_by_level"] == {"DEBUG": 2}
    _valid(drop[0])


def test_s3_upload_failure_is_swallowed(monkeypatch):
    em = m._S3BatchEmitter(_s3_cfg(monkeypatch), client=FakeS3(fail=True))
    em(_rec("ERROR", 1))
    em.close()  # must not raise


def test_s3_requires_region_and_s3_scheme(monkeypatch):
    cfg = _s3_cfg(monkeypatch, ARYX_RAVEN_LOG_S3_REGION="")
    with pytest.raises(ValueError, match="REGION"):
        m._S3BatchEmitter(cfg, client=FakeS3())
    cfg = _s3_cfg(monkeypatch, ARYX_RAVEN_LOG_S3_PATH="bucket/p")
    with pytest.raises(ValueError, match="s3://"):
        m._S3BatchEmitter(cfg, client=FakeS3())


def test_sink_both_writes_stdout_and_s3(monkeypatch, capsys):
    fake = FakeS3()
    cfg = _s3_cfg(monkeypatch, ARYX_RAVEN_LOG_SINK="both")
    monkeypatch.setattr(m, "_make_s3_client", lambda c: fake)
    m.reload_config()
    _log("INFO")
    assert len(_lines(capsys)) == 1
    m.flush()
    assert len(fake.puts) == 1
    assert cfg.sink == "both"
