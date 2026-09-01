"""Multi-target pending_intent_queue + intent-conservation guardrail."""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.session_guard import (
    INTENT_QUEUE_CAP,
    audit_intent_conservation,
    enqueue_intent_targets,
    format_dropped_intent_notice,
    format_queue_overflow_notice,
    pop_intent_queue_head,
    reset_intent_dropped_count,
)
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _attr(vn: str, label: str, eid: int = 1) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid,
        variable_name=vn,
        display_label=label,
        required=False,
        default_value="",
        select_type="single",
        options=[MenuOption(item_value="a", display_name="A", order=1)],
    )


def test_from_dict_migrates_legacy_multi_intent_vn() -> None:
    s = CpqSession.from_dict({
        "mode": "cpq",
        "pending_multi_intent_vn": "serviceType_astro",
        "filled": {"serviceType_astro": "x"},
    })
    assert s.pending_intent_queue == ["serviceType_astro"]
    assert s.pending_multi_intent_vn == "serviceType_astro"


def test_compat_property_setter_and_clear() -> None:
    s = CpqSession()
    s.pending_multi_intent_vn = "a"
    s.pending_multi_intent_vn = "b"
    assert s.pending_intent_queue[0] == "b"
    assert "a" in s.pending_intent_queue
    s.pending_multi_intent_vn = ""
    assert s.pending_intent_queue[0] == "a"


def test_enqueue_dedupe_and_cap() -> None:
    s = CpqSession()
    overflow = enqueue_intent_targets(
        s, [f"v{i}" for i in range(12)], cap=INTENT_QUEUE_CAP,
    )
    assert len(s.pending_intent_queue) == INTENT_QUEUE_CAP
    assert len(overflow) == 2
    assert overflow == ["v10", "v11"]


def test_detect_all_change_targets_appearance_order() -> None:
    eng = CpqEngine()
    attrs = [
        _attr("hWVersion_astro", "Hardware Version", 1),
        _attr("serviceType_astro", "Primary Service Type", 2),
        _attr("activationDelay_astro", "Activation Delay", 3),
    ]
    filled = {a.variable_name: "x" for a in attrs}
    q = "change hardware version, service type and activation delay"
    found = eng.detect_all_change_targets_without_value(q, attrs, filled)
    vns = [a.variable_name for a in found]
    assert "hWVersion_astro" in vns
    assert "serviceType_astro" in vns or any("service" in v.lower() for v in vns)
    # First by appearance should be hardware
    assert found[0].variable_name == "hWVersion_astro"


def test_audit_ok_when_all_queued_or_handled() -> None:
    reset_intent_dropped_count()
    s = CpqSession(run_id="t", turn=1)
    s.pending_intent_queue = ["b", "c"]
    s.pending_change_no_value_vn = "a"
    r = audit_intent_conservation(
        "change a b c", ["a", "b", "c"], [], s, log=False,
    )
    assert r.ok
    assert r.dropped == []


def test_audit_detects_dropped() -> None:
    reset_intent_dropped_count()
    s = CpqSession(run_id="t", turn=2)
    r = audit_intent_conservation(
        "change a b c", ["a", "b", "c"], ["a"], s, log=False,
    )
    assert not r.ok
    assert set(r.dropped) == {"b", "c"}
    assert "cpq_intent_dropped" in r.message
    notice = format_dropped_intent_notice(r.dropped)
    assert "couldn't process" in notice.lower()


def test_overflow_notice() -> None:
    msg = format_queue_overflow_notice(["x", "y"])
    assert str(INTENT_QUEUE_CAP) in msg
    assert "re-ask" in msg.lower()


def test_pop_queue_head() -> None:
    s = CpqSession()
    s.pending_intent_queue = ["a", "b"]
    assert pop_intent_queue_head(s) == "a"
    assert s.pending_intent_queue == ["b"]
