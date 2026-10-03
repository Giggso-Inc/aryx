"""Personal data must not reach the log: bind values, row values, OCI user id, customer text.

Each changed log line is exercised with a sentinel string; the sentinel must be absent
from the captured stdlib log output while the line's prefix and other fields remain.
A repo-wide AST lint also forbids passing the customer's message or reply straight
into a ``logger.*`` call.
"""
from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from aryx.log_safe import mask_ocid, params_shape, rows_shape, text_ref

SRC = Path(__file__).resolve().parents[1] / "src" / "aryx"
SENTINEL = "SENTINEL_PERSONAL_9137"


# ------------------------------------------------------------------- helpers

def test_text_ref_has_length_and_hash_but_never_the_text():
    ref = text_ref(f"Jane Doe {SENTINEL}")
    assert ref.startswith("len=") and " sha=" in ref and SENTINEL not in ref and "Jane" not in ref
    assert text_ref("same") == text_ref("same") and text_ref("a") != text_ref("b")
    assert text_ref(None) == "-" and text_ref("") == "-"
    assert text_ref(["x", SENTINEL]).startswith("len=") and SENTINEL not in text_ref([SENTINEL])


def test_mask_ocid_keeps_prefix_and_last_four():
    ocid = "ocid1.user.oc1..aaaaaaaaSENTINELMIDDLEzzzz1234"
    masked = mask_ocid(ocid)
    assert masked == "ocid1.user.oc1..***1234" and "SENTINEL" not in masked
    assert mask_ocid("short") == "***" and mask_ocid(None) == "-"
    assert mask_ocid("not-an-ocid-but-long-enough-9876").endswith("9876")


def test_shapes_describe_without_values():
    p = params_shape((SENTINEL, 5, None))
    assert SENTINEL not in p and "n=3" in p and "str" in p and "int" in p
    d = params_shape({"name": SENTINEL, "id": 3})
    assert SENTINEL not in d and "n=2" in d
    r = rows_shape([(SENTINEL, 1), (SENTINEL, 2)])
    assert SENTINEL not in r and "rows=2" in r
    assert rows_shape(None) == "none" and params_shape(None) == "none"


# ------------------------------------------------------------- oracle cursor

class _FailingCursor:
    def __init__(self):
        self.arraysize = 1

    def execute(self, sql, params=None):
        raise RuntimeError("ORA-01400: cannot insert NULL")

    def executemany(self, sql, seq):
        raise RuntimeError("ORA-01400: cannot insert NULL")

    def setinputsizes(self, *a, **k):
        return None

    def var(self, *a, **k):
        return SimpleNamespace(size=1, getvalue=lambda: [1])


@pytest.fixture
def fake_oracledb(monkeypatch):
    """A minimal stand-in for oracledb (not installed here); unknown names resolve to dummies."""
    mod = ModuleType("oracledb")
    mod.IntegrityError = type("IntegrityError", (Exception,), {})
    mod.DatabaseError = type("DatabaseError", (Exception,), {})
    mod.__getattr__ = lambda name: object()
    monkeypatch.setitem(sys.modules, "oracledb", mod)
    return mod


def _wrapper():
    from aryx.store.oracle_cursor import OracleCursorWrapper
    return OracleCursorWrapper(_FailingCursor())


def test_oracle_execute_failure_does_not_log_bind_values(caplog, fake_oracledb):
    caplog.set_level(logging.DEBUG, logger="aryx.store.oracle_cursor")
    with pytest.raises(RuntimeError):
        _wrapper().execute("INSERT INTO t (a, b) VALUES (%s, %s)", (SENTINEL, 42))
    text = caplog.text
    assert "execute failed" in text and "params=" in text
    assert SENTINEL not in text


def test_oracle_executemany_failure_does_not_log_row_values(caplog, fake_oracledb):
    caplog.set_level(logging.DEBUG, logger="aryx.store.oracle_cursor")
    with pytest.raises(RuntimeError):
        _wrapper().executemany("INSERT INTO t (a, b) VALUES (%s, %s)", [(SENTINEL, 1), (SENTINEL, 2)])
    text = caplog.text
    assert "executemany failed" in text and "row0=" in text
    assert SENTINEL not in text


# ---------------------------------------------------------------- oci client

def test_oci_client_logs_masked_user_ocid(caplog, monkeypatch):
    import aryx.oci_client as oc
    fake = ModuleType("oci")
    fake.config = SimpleNamespace(validate_config=lambda cfg: None)
    monkeypatch.setitem(sys.modules, "oci", fake)
    monkeypatch.setattr(oc, "_signer", None)
    monkeypatch.setenv("ARYX_OCI_USER_OCID", f"ocid1.user.oc1..{SENTINEL}abcd")
    monkeypatch.setenv("ARYX_OCI_TENANCY_OCID", "ocid1.tenancy.oc1..t")
    monkeypatch.setenv("ARYX_OCI_FINGERPRINT", "aa:bb")
    monkeypatch.setenv("ARYX_OCI_PRIVATE_KEY_CONTENT", "KEY")
    caplog.set_level(logging.INFO, logger="aryx.oci_client")
    oc._get_auth()
    assert "using env-var auth user=ocid1.user.oc1..***abcd" in caplog.text
    assert SENTINEL not in caplog.text


# ------------------------------------------------------ pending scope and guard

def test_pending_scope_lines_do_not_log_the_reply(caplog):
    from aryx.cpq.pending_scope import pending_scope_messages as m
    caplog.set_level(logging.INFO, logger=m.logger.name)
    m.log_scope_retained(run_id="r1", reply=f"my phone is {SENTINEL}", kind="family", n_candidates=3,
                         suggestions=["A", "B"], misses=1)
    m.log_scope_lost(run_id="r1", reply=f"my address is {SENTINEL}", reason="gone")
    assert "cpq_scope_retained" in caplog.text and "cpq_scope_lost" in caplog.text
    assert "reply=len=" in caplog.text
    assert SENTINEL not in caplog.text


def test_orphan_question_line_does_not_log_the_answer_text(caplog):
    from aryx.cpq.session_guard import session_guard_invariant as g
    caplog.set_level(logging.INFO, logger=g.logger.name)
    answer = f"Which keypad type do you want for {SENTINEL}?"
    g.assert_conversational_invariant(answer, {}, run_id="r9")
    if "answer=" in caplog.text:  # the violation path ran
        assert "answer=len=" in caplog.text
    assert SENTINEL not in caplog.text


# --------------------------------------------------------------- AST lint

_LOGGER_METHODS = {"info", "debug", "warning", "error", "exception", "critical"}
_TEXT_NAMES = {"user_answer", "user_text", "utterance"}


def _is_logger_call(node: ast.Call) -> bool:
    f = node.func
    if not (isinstance(f, ast.Attribute) and f.attr in _LOGGER_METHODS):
        return False
    base = f.value
    return (isinstance(base, ast.Name) and base.id == "logger") or (
        isinstance(base, ast.Attribute) and base.attr == "logger")


def _raw_text_arg(arg: ast.AST) -> bool:
    if isinstance(arg, ast.Attribute) and arg.attr == "question" and isinstance(arg.value, ast.Name) \
            and arg.value.id == "req":
        return True
    return isinstance(arg, ast.Name) and arg.id in _TEXT_NAMES


def test_no_logger_call_passes_raw_customer_text():
    offenders = []
    for path in SRC.rglob("*.py"):
        if ".raven" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_logger_call(node):
                for arg in node.args[1:]:
                    if _raw_text_arg(arg):
                        offenders.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    assert not offenders, "log calls pass raw customer text (wrap with text_ref): " + ", ".join(offenders)
