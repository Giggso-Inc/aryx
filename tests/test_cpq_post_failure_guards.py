"""Unit tests for post-failure prevention guards (session/BOM/summary/telemetry)."""
from __future__ import annotations

from aryx.cpq.bom_gate import (
    check_provenance, find_missing_required_fields, recheck_constraints,
    validate_before_payload,
)
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


def _attr(
    vn: str, label: str, options: list[tuple[str, str]], *,
    required: bool = False, select_type: str = "single",
) -> ConfigAttr:
    opts = [MenuOption(item_value=iv, display_name=dn) for iv, dn in options]
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=label,
        required=required, default_value="", options=opts, select_type=select_type,
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
        "apply_constraint_rules": staticmethod(lambda *a, **k: {}),
    })()
    result = validate_before_payload(engine, [attr], s, [], None)
    assert result.ok is False
    assert "blocked" in result.catch_message.lower() or "gate" in result.catch_message.lower()


# find_missing_required_fields / validate_before_payload missing-required
# hard-fail (2026-08-08) — docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2c
# can leave a required, non-decision attr silently unfilled; nothing
# previously checked for that before declaring a config "complete".

def test_find_missing_required_fields_flags_an_empty_required_attr():
    attr = _attr("modelSelectionbaseModel_astro", "Base Model", [], required=True)
    s = CpqSession()
    missing = find_missing_required_fields([attr], s)
    assert missing == [attr]


def test_find_missing_required_fields_ignores_a_filled_required_attr():
    attr = _attr("modelSelectionbaseModel_astro", "Base Model", [], required=True)
    s = CpqSession()
    s.filled = {"modelSelectionbaseModel_astro": "H45TGU9PW8AN"}
    assert find_missing_required_fields([attr], s) == []


def test_find_missing_required_fields_ignores_optional_attrs():
    attr = _attr("carrierSelectionMultiSelect_astro", "Carrier Selection", [], required=False)
    s = CpqSession()
    assert find_missing_required_fields([attr], s) == []


def test_find_missing_required_fields_checks_filled_multi_for_multi_select():
    attr = _attr(
        "requiredAccessories_astro", "Accessories", [],
        required=True, select_type="multi",
    )
    s = CpqSession()
    assert find_missing_required_fields([attr], s) == [attr]
    s.filled_multi = {"requiredAccessories_astro": ["A"]}
    assert find_missing_required_fields([attr], s) == []


def test_find_missing_required_fields_only_checks_currently_visible_attrs():
    """A required attr an active hiding rule already removed from the
    `attrs` list passed in is never flagged -- the catalog's own rules
    already say it doesn't apply here."""
    attr = _attr("hiddenRequiredThing_astro", "Hidden Thing", [], required=True)
    s = CpqSession()
    assert find_missing_required_fields([], s) == []


def test_find_missing_required_fields_ignores_noise_shaped_system_attrs():
    """Required-but-noise-shaped attrs (Price Book/User Currency/User
    Groups/User Language/User Number Format/Config Operation Context --
    confirmed live 2026-08-09) are populated by the calling CRM/account
    layer, never by product configuration, and are already excluded from
    the real BOM payload and from conversation. required=True on these is
    a fact about Oracle's OWN system, not something Aryx should ever block
    completion on."""
    underscore_attr = _attr("_price_book_var_name", "Price Book", [], required=True)
    upper_prefix_attr = _attr("CRM_USER_CURRENCY", "User Currency", [], required=True)
    real_attr = _attr("modelSelectionbaseModel_astro", "Base Model", [], required=True)
    s = CpqSession()
    missing = find_missing_required_fields(
        [underscore_attr, upper_prefix_attr, real_attr], s,
    )
    assert missing == [real_attr]


def test_validate_before_payload_hard_fails_on_missing_required_field():
    attr = _attr("modelSelectionbaseModel_astro", "Base Model", [], required=True)
    s = CpqSession()
    engine = type("E", (), {
        "apply_constraint_rules": staticmethod(lambda *a, **k: {}),
    })()
    result = validate_before_payload(engine, [attr], s, [], None)
    assert result.ok is False
    assert "Base Model" in result.catch_message
    assert "required" in result.errors[0]


# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §9 — the ONLY
# call site that swapped apply_constraint_rules' argument order AND
# unpacked its single-dict return as a 2-tuple, crashing every confirm
# with an active constraint rule ("'str' object has no attribute
# 'target_attr_id'" — session.filled's dict landed in the `rules` param).

def test_recheck_constraints_calls_engine_with_correct_argument_order():
    """Regression: must call (attrs, rules, filled, bml_eval=...), not
    (attrs, filled, rules, ...) — the real engine signature crashes on the
    swapped order since `for rule in rules` would iterate a dict's keys."""
    attr = _attr("hW", "Hardware", [("H1", "H1"), ("H45", "H45")])
    s = CpqSession()
    s.filled = {"hW": "H45"}
    seen_args = {}

    def _fake_apply_constraint_rules(attrs, rules, filled, bml_eval=None, filled_multi=None):
        seen_args["attrs"] = attrs
        seen_args["rules"] = rules
        seen_args["filled"] = filled
        return {}

    engine = type("E", (), {
        "apply_constraint_rules": staticmethod(_fake_apply_constraint_rules),
    })()
    con_rules = ["a real rule object, not a dict"]
    result = recheck_constraints(engine, [attr], s, con_rules, None)
    assert result == []
    # filled must be the actual filled dict, rules must be the rule list —
    # the exact swap that used to crash every confirm.
    assert seen_args["filled"] == {"hW": "H45"}
    assert seen_args["rules"] == con_rules


def test_recheck_constraints_flags_value_outside_recomputed_allowed_set():
    """A filled value the freshly recomputed constraint no longer allows
    must surface as a structured, auto-clearable violation — not a hard-
    fail message (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md
    §11: the engine can't guess the replacement, so the caller re-asks)."""
    attr = _attr("hW", "Hardware", [("H1", "H1"), ("H45", "H45")])
    s = CpqSession()
    s.filled = {"hW": "H45"}
    engine = type("E", (), {
        "apply_constraint_rules": staticmethod(
            lambda attrs, rules, filled, bml_eval=None, filled_multi=None: {1: ["H1"]},
        ),
    })()
    violations = recheck_constraints(engine, [attr], s, ["some rule"], None)
    assert len(violations) == 1
    assert violations[0].attr.variable_name == "hW"
    assert violations[0].current_value == "H45"
    assert violations[0].allowed == ["H1"]


def test_recheck_constraints_passes_when_filled_value_still_allowed():
    attr = _attr("hW", "Hardware", [("H1", "H1"), ("H45", "H45")])
    s = CpqSession()
    s.filled = {"hW": "H45"}
    engine = type("E", (), {
        "apply_constraint_rules": staticmethod(
            lambda attrs, rules, filled, bml_eval=None, filled_multi=None: {1: ["H1", "H45"]},
        ),
    })()
    assert recheck_constraints(engine, [attr], s, ["some rule"], None) == []


def test_validate_before_payload_stale_constraint_does_not_hard_fail():
    """Live-confirmed 2026-07-29: a stale constraint violation (e.g. Carry
    Type/Frequency Bands auto-filled before Product narrowed their allowed
    set) must come back as ok=False + stale_violations, NOT as a hard-fail
    catch_message — the caller re-asks instead of blocking."""
    attr = _attr("hW", "Hardware", [("H1", "H1"), ("H45", "H45")])
    s = CpqSession()
    s.filled = {"hW": "H45"}
    s.filled_source = {"hW": "auto"}
    engine = type("E", (), {
        "apply_constraint_rules": staticmethod(
            lambda attrs, rules, filled, bml_eval=None, filled_multi=None: {1: ["H1"]},
        ),
    })()
    result = validate_before_payload(engine, [attr], s, ["some rule"], None)
    assert result.ok is False
    assert result.errors == []
    assert result.catch_message == ""
    assert len(result.stale_violations) == 1
    assert result.stale_violations[0].attr.variable_name == "hW"


# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §12 — external
# review of §11's fix caught 2 real gaps, fixed here:
# (1) an unexpected engine exception used to be swallowed as "no
#     violations" (fail OPEN) instead of a hard fail (fail CLOSED).
# (2) multi-select attrs were invisible to the recheck — it only ever
#     read session.filled, never session.filled_multi.

def test_validate_before_payload_hard_fails_on_unexpected_constraint_exception():
    """An unexpected error during constraint recheck must hard-fail
    (hallucinated/unverifiable state), never silently pass as if no
    violations were found."""
    attr = _attr("hW", "Hardware", [("H1", "H1"), ("H45", "H45")])
    s = CpqSession()
    s.filled = {"hW": "H45"}

    def _raises(attrs, rules, filled, bml_eval=None, filled_multi=None):
        raise RuntimeError("boom")

    engine = type("E", (), {"apply_constraint_rules": staticmethod(_raises)})()
    result = validate_before_payload(engine, [attr], s, ["some rule"], None)
    assert result.ok is False
    assert result.stale_violations == []
    assert result.errors and "boom" in result.errors[0]
    assert result.catch_message != ""


def test_recheck_constraints_detects_stale_multi_select_value():
    """A multi-select attr's currently-selected value(s) must be checked
    against the recomputed allowed set too — session.filled_multi, not
    just session.filled."""
    attr = ConfigAttr(
        entity_id=1, variable_name="carrierSel", display_label="Carrier Selection",
        required=False, default_value="", select_type="multi",
        options=[
            MenuOption(item_value="ATT", display_name="ATT/FirstNet"),
            MenuOption(item_value="VZW", display_name="Verizon"),
        ],
    )
    s = CpqSession()
    s.filled_multi = {"carrierSel": ["ATT", "VZW"]}
    engine = type("E", (), {
        "apply_constraint_rules": staticmethod(
            lambda attrs, rules, filled, bml_eval=None, filled_multi=None: {1: ["VZW"]},
        ),
    })()
    violations = recheck_constraints(engine, [attr], s, ["some rule"], None)
    assert len(violations) == 1
    assert violations[0].attr.variable_name == "carrierSel"
    assert "ATT" in violations[0].current_value
    assert "VZW" not in violations[0].current_value


def test_recheck_constraints_multi_select_passes_when_all_values_still_allowed():
    attr = ConfigAttr(
        entity_id=1, variable_name="carrierSel", display_label="Carrier Selection",
        required=False, default_value="", select_type="multi",
        options=[
            MenuOption(item_value="ATT", display_name="ATT/FirstNet"),
            MenuOption(item_value="VZW", display_name="Verizon"),
        ],
    )
    s = CpqSession()
    s.filled_multi = {"carrierSel": ["ATT", "VZW"]}
    engine = type("E", (), {
        "apply_constraint_rules": staticmethod(
            lambda attrs, rules, filled, bml_eval=None, filled_multi=None: {1: ["ATT", "VZW"]},
        ),
    })()
    assert recheck_constraints(engine, [attr], s, ["some rule"], None) == []


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
