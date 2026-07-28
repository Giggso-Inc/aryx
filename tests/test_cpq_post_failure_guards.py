"""Unit tests for post-failure prevention guards (session/BOM/summary/telemetry)."""
from __future__ import annotations

from aryx.cpq.bom_gate import check_provenance, validate_before_payload
from aryx.cpq.session_guard import (
    CLARIFY_STREAK_MAX,
    HISTORY_CAP,
    detect_undo,
    note_clarify,
    push_snapshot,
    restore_last_snapshot,
    should_force_numbered_options,
    should_offer_guided_mode,
)
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption
from aryx.cpq.summary_guard import (
    fields_missing_from_summary,
    raw_state_table,
    validate_or_fallback,
)
from aryx.cpq.telemetry import (
    DivergenceRecord,
    disagreement_rate,
    log_divergence,
    reset_telemetry,
)


def _attr(vn: str, label: str, options: list[tuple[str, str]]) -> ConfigAttr:
    opts = [MenuOption(item_value=iv, display_name=dn) for iv, dn in options]
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=label,
        required=False, default_value="", options=opts,
    )


def test_detect_undo_phrases():
    assert detect_undo("undo")
    assert detect_undo("please roll back")
    assert detect_undo("go back to previous state")
    assert not detect_undo("change hardware")


def test_snapshot_cap_and_undo():
    s = CpqSession()
    s.run_id = "r1"
    for i in range(12):
        s.filled = {"a": str(i)}
        push_snapshot(s, reason="t")
    assert len(s.history) == HISTORY_CAP
    s.filled = {"a": "final"}
    assert restore_last_snapshot(s)
    # last snapshot was taken when filled was "11" (before 12th push of 11)
    assert s.filled["a"] in {str(i) for i in range(12)}
    assert s.run_id == "r1"


def test_clarify_streak_forces_numbered_options():
    s = CpqSession()
    for _ in range(CLARIFY_STREAK_MAX):
        note_clarify(s, "hWVersion_astro")
    assert should_force_numbered_options(s, "hWVersion_astro")


def test_unresolved_offers_guided_mode():
    s = CpqSession()
    for _ in range(5):
        note_clarify(s, None)
    assert should_offer_guided_mode(s)


def test_provenance_accepts_catalog_option():
    attr = _attr("hW", "Hardware", [("H1", "H1"), ("H45", "H45")])
    s = CpqSession()
    s.filled = {"hW": "H45"}
    s.filled_source = {"hW": "user"}
    s.display_filled = {"hW": "H45"}
    assert check_provenance([attr], s) == []


def test_provenance_rejects_invented_value():
    attr = _attr("hW", "Hardware", [("H1", "H1"), ("H45", "H45")])
    s = CpqSession()
    s.filled = {"hW": "HALLUCINATED"}
    s.filled_source = {"hW": "rule"}
    s.display_filled = {"hW": "HALLUCINATED"}
    errs = check_provenance([attr], s)
    assert errs and "HALLUCINATED" in errs[0]


def test_bom_gate_hard_fail_never_ok_on_bad_value():
    attr = _attr("hW", "Hardware", [("H1", "H1")])
    s = CpqSession()
    s.filled = {"hW": "NOPE"}
    s.filled_source = {"hW": "auto"}
    engine = type("E", (), {
        "apply_constraint_rules": staticmethod(lambda *a, **k: ({}, [])),
    })()
    result = validate_before_payload(engine, [attr], s, [], None)
    assert result.ok is False
    assert "blocked" in result.catch_message.lower() or "gate" in result.catch_message.lower()


def test_summary_missing_fields_detected():
    missing = fields_missing_from_summary(
        "Your configuration is complete.",
        {"hW": "Hardware 45", "country": "United States"},
        [_attr("hW", "Hardware Version", [("H45", "Hardware 45")])],
    )
    assert missing


def test_summary_fallback_to_raw_table():
    s = CpqSession()
    s.display_filled = {"hW": "Hardware 45"}
    s.filled_source = {"hW": "user"}
    attrs = [_attr("hW", "Hardware Version", [("H45", "Hardware 45")])]
    text, used_raw = validate_or_fallback(
        "All good.", s, attrs, regenerate=lambda: "Still wrong.",
    )
    assert used_raw is True
    assert "Hardware Version" in text or "Hardware 45" in text


def test_telemetry_disagreement_rate():
    reset_telemetry()
    for _ in range(8):
        log_divergence(DivergenceRecord(
            run_id="r", llm_intent="change_request",
            deterministic_intent="change_request", agreement=True, model_id="m",
        ))
    for _ in range(2):
        log_divergence(DivergenceRecord(
            run_id="r", llm_intent="change_request",
            deterministic_intent=None, agreement=False, model_id="m",
        ))
    rate = disagreement_rate()
    assert 0.15 <= rate <= 0.25
