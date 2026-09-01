"""docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md

RC1: evaluate_rules_loop's fixed-point iteration always ran the full 8-pass
cap on every real turn observed, because auto_fill's own "default_first_
available" re-derivation deliberately re-opens EVERY pass (by design, per
its own comment -- a real narrowing might resolve later than an early
pass). `_fill_signature()` + the new `_default_fill_signatures` gate on
`auto_fill()` only actually re-derive such an attribute when something
relevant (any filled value, or the visible-attribute-id set) has genuinely
changed since it was last (re)derived -- suppressing the wasted, identical
re-guesses that were driving up pass count.

docs/CPQ_TURN_LATENCY_FIX_CORRECTNESS_RISK_2026_08_19.md required the
signature to be broad (all filled state, not one attribute's narrow
constrained-options snapshot) specifically to avoid silently missing a
real narrowing -- these tests verify both halves: the gate actually
suppresses redundant work, AND it does NOT suppress a genuine change.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine, _fill_signature
from aryx.cpq.state import ConfigAttr, ConstraintRule, MenuOption, RecommendationRule


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attr(vn: str, *values: str, select_type: str = "single") -> ConfigAttr:
    # required=False -- confirmed via test_cpq_layout_visibility_order.py's
    # own test_governed_single_select_blind_fills_first_option_* tests:
    # _no_real_fill_justification's "no real basis, but pick first anyway"
    # path is reached for a NON-required attr with no default_value and no
    # satisfied recommendation; a `required=True` attr with 2+ real options
    # is treated as a genuine decision and is NOT blindly guessed this way.
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=vn, required=False,
        default_value="", select_type=select_type, options=_menu(*values),
    )


# ── _fill_signature itself ───────────────────────────────────────────────

def test_fill_signature_identical_for_identical_state():
    sig_a = _fill_signature({"x": "A", "y": "B"}, {"m": ["1", "2"]}, {10, 20})
    sig_b = _fill_signature({"y": "B", "x": "A"}, {"m": ["2", "1"]}, {20, 10})
    assert sig_a == sig_b, "key/list order must not affect the signature"


def test_fill_signature_changes_when_a_filled_value_changes():
    base = _fill_signature({"x": "A"}, {}, {10})
    changed = _fill_signature({"x": "B"}, {}, {10})
    assert base != changed


def test_fill_signature_changes_when_filled_multi_changes():
    base = _fill_signature({}, {"m": ["1"]}, {10})
    changed = _fill_signature({}, {"m": ["1", "2"]}, {10})
    assert base != changed


def test_fill_signature_changes_when_visibility_changes():
    """A hiding-rule-driven visibility change can alter legal options even
    when no filled VALUE changed -- the signature must be sensitive to it,
    not just to `filled`/`filled_multi`."""
    base = _fill_signature({"x": "A"}, {}, {10, 20})
    changed = _fill_signature({"x": "A"}, {}, {10})
    assert base != changed


# ── auto_fill: default behavior unaffected (backward compatibility) ──────

def test_auto_fill_unaffected_when_signatures_param_omitted():
    """Every pre-existing call site (including every other test in this
    suite) doesn't pass `_default_fill_signatures` -- must be a complete
    no-op, identical to before this fix existed. `auto_fill` returns a
    fresh `filled` dict for single-select values (only `filled_source`/
    `already_filled_multi` are mutated in place) -- evaluate_rules_loop
    itself reassigns `filled` from the return value each pass, mirrored
    here."""
    attr = _attr("x", "A", "B", "C")
    eng = CpqEngine()
    filled: dict[str, str] = {}
    sources: dict[str, str] = {}

    filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0},
    )
    assert filled.get("x") == "A"
    first_source = sources.get("x")
    assert first_source is not None

    # Re-run exactly like evaluate_rules_loop's own repeated per-pass call,
    # still without the new param -- must still behave exactly as before
    # this fix, whatever that behavior is (value and source stable/
    # idempotent across repeated calls).
    filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0},
    )
    assert filled.get("x") == "A"
    assert sources.get("x") == first_source


# ── auto_fill: the gate actually suppresses redundant re-derivation ──────
#
# Technique: plant a sentinel value (not one of the attribute's real
# options, so it could never arise from a genuine blind-pick) into
# `filled` with source "default_first_available". A gate that correctly
# SKIPS re-derivation leaves the sentinel untouched; a gate that (wrongly)
# allows re-derivation through overwrites it with the real first-available
# option. This directly observes the skip/no-skip decision without
# depending on any specific downstream derivation outcome.

def test_default_first_available_singleselect_not_rederived_when_signature_unchanged():
    attr = _attr("x", "A", "B", "C")
    eng = CpqEngine()
    filled = {"x": "__SENTINEL_NEVER_A_REAL_OPTION__"}
    sources = {"x": "default_first_available"}
    sigs = {"x": _fill_signature(filled, {}, {1})}

    # Check both the input dict AND the returned one -- the skip path takes
    # an early `continue` without going through the "already answered, no
    # change" bookkeeping every other branch uses, so it's worth confirming
    # the value survives into whatever auto_fill actually returns too, not
    # just that the caller's own input dict was left alone.
    returned_filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0}, _default_fill_signatures=sigs,
    )
    assert filled["x"] == "__SENTINEL_NEVER_A_REAL_OPTION__", (
        "gate should have skipped re-derivation -- the pre-seeded signature "
        "already matches the current state"
    )
    assert returned_filled.get("x") == "__SENTINEL_NEVER_A_REAL_OPTION__", (
        "the skipped value must also survive into auto_fill's own returned "
        "filled dict, not just the caller's input dict"
    )


def test_default_first_available_singleselect_rederives_when_signature_changes():
    """Negative case: a signature that does NOT match the current state
    (simulating a genuine change since this attr was last derived) must
    let real re-derivation run -- proving the gate doesn't silently freeze
    a stale guess forever."""
    attr = _attr("x", "A", "B", "C")
    eng = CpqEngine()
    filled = {"x": "__SENTINEL_NEVER_A_REAL_OPTION__"}
    sources = {"x": "default_first_available"}
    # Deliberately mismatched -- represents "last derived against a
    # different state than the current one".
    sigs = {"x": _fill_signature({}, {}, set())}

    filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0}, _default_fill_signatures=sigs,
    )
    assert filled["x"] == "A", "a changed signature must allow real re-derivation to run"
    # Not asserting the exact resulting source tag -- real re-derivation can
    # legitimately land in a different branch (e.g. "blind_pick_rule_governed")
    # than the original guess. The value changing above is the actual proof
    # that re-derivation genuinely ran instead of being skipped.


def test_default_first_available_singleselect_first_pass_of_a_turn_always_rederives():
    """`evaluate_rules_loop` declares a FRESH, empty signatures dict once
    per turn -- so pass 0 of every new turn has no prior-pass signature to
    compare against and must always re-attempt derivation, exactly like
    today. Simulated here by passing an empty dict (no entry for "x" yet)."""
    attr = _attr("x", "A", "B", "C")
    eng = CpqEngine()
    filled = {"x": "__SENTINEL_NEVER_A_REAL_OPTION__"}
    sources = {"x": "default_first_available"}
    sigs: dict[str, tuple] = {}  # fresh, as evaluate_rules_loop declares each turn

    filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0}, _default_fill_signatures=sigs,
    )
    assert filled["x"] == "A"


# ── RC3 (2026-08-24): _signature_exclude_vns isolates a churning subset ──
#
# docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md -- a small subset of
# attributes proven non-convergent this turn (the same set re-invalidated
# by _invalidate_inconsistent_paired_values two passes running) must not
# perturb every OTHER default_first_available attribute's signature just
# because ITS value keeps changing pass over pass.

def test_signature_exclude_vns_keeps_the_gate_held_despite_an_unrelated_key_changing():
    """"y" stands in for a churning, non-convergent attribute (re-picked
    every pass by _invalidate_inconsistent_paired_values). Its value
    changed since "x"'s signature was last recorded, but with "y" excluded
    from the snapshot, "x"'s own gate must still hold."""
    attr = _attr("x", "A", "B", "C")
    eng = CpqEngine()
    filled = {"x": "__SENTINEL_NEVER_A_REAL_OPTION__", "y": "NEW"}
    sources = {"x": "default_first_available"}
    # Recorded against what the signature looks like with "y" excluded.
    sigs = {"x": _fill_signature({"x": "__SENTINEL_NEVER_A_REAL_OPTION__"}, {}, {1})}

    returned_filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0}, _default_fill_signatures=sigs,
        _signature_exclude_vns=frozenset({"y"}),
    )
    assert returned_filled.get("x") == "__SENTINEL_NEVER_A_REAL_OPTION__", (
        "excluding the churning key from the signature snapshot must keep "
        "the gate held for an unrelated attribute"
    )


def test_without_exclusion_the_same_unrelated_change_breaks_the_gate():
    """Negative control for the test above -- proves the exclusion is what
    holds the gate, not some other incidental difference. Identical setup,
    no `_signature_exclude_vns` -- "y"'s change must legitimately break the
    gate and let real re-derivation run, exactly like RC1's original
    broad-signature design intends for a real (non-churning) change."""
    attr = _attr("x", "A", "B", "C")
    eng = CpqEngine()
    filled = {"x": "__SENTINEL_NEVER_A_REAL_OPTION__", "y": "NEW"}
    sources = {"x": "default_first_available"}
    sigs = {"x": _fill_signature({"x": "__SENTINEL_NEVER_A_REAL_OPTION__"}, {}, {1})}

    returned_filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0}, _default_fill_signatures=sigs,
    )
    assert returned_filled.get("x") == "A", (
        "without the exclusion, y's change must legitimately break the gate"
    )


def test_signature_exclude_vns_none_is_a_complete_noop():
    """`None` (the default, and every pre-existing call site) must behave
    identically to omitting the parameter entirely."""
    attr = _attr("x", "A", "B", "C")
    eng = CpqEngine()
    filled = {"x": "__SENTINEL_NEVER_A_REAL_OPTION__"}
    sources = {"x": "default_first_available"}
    sigs = {"x": _fill_signature(filled, {}, {1})}

    returned_filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0}, _default_fill_signatures=sigs,
        _signature_exclude_vns=None,
    )
    assert returned_filled.get("x") == "__SENTINEL_NEVER_A_REAL_OPTION__"


# ── RC1 mandated regression test (docs/CPQ_TURN_LATENCY_FIX_CORRECTNESS_
# RISK_2026_08_19.md): "Add a dedicated regression test that replays the
# exact ICE-KIT/Package-Type scenario ... Do not ship the gating change
# without this test passing." ─────────────────────────────────────────────
#
# Real shape (engine.py's own comment at the extendRangeTo762764MHz_astro
# re-validation branch, and step 2's "_satisfied_recommendation" priority
# above generic default_value): a single-select, non-required attr gets
# blind-picked "default_first_available" on an early pass because no
# recommendation condition is satisfied yet. A LATER pass fills an
# upstream attribute (e.g. Base Model) that satisfies a `rec_rules`
# recommendation targeting THIS attr with a DIFFERENT value. Crucially,
# `constrained_opts` never restricts the stale guess away here (it's not
# a constraint-rule scenario) -- the ONLY thing that can catch this is the
# `_default_fill_signatures` gate correctly deciding "something relevant
# changed, re-derive" instead of "nothing changed, keep the guess".
#
# This is exactly the case the risk doc worried a NARROW, per-attribute
# signature would miss: the real narrowing signal here is an upstream
# attribute's own `filled` value becoming true, not anything scoped to
# THIS attribute. The broad, whole-`filled`-dict signature actually
# shipped catches it because that upstream value is itself a `filled`
# entry -- so the signature changes and the gate correctly does not
# suppress re-derivation.

_ICE_KIT_TARGET = _attr("extendRangeTo762764MHz_astro", "YES", "NO")
_ICE_KIT_BASE_MODEL = ConfigAttr(
    entity_id=2, variable_name="modelSelectionbaseModel_astro",
    display_label="Base Model", required=False, default_value="",
    options=_menu("H55TGT9PW8BN"),
)
_ICE_KIT_REC_RULE = RecommendationRule(
    rule_name="Force set Extend Range to 762-764 MHz to NO under certain conditions",
    condition_attr_id=2, condition_value="H55TGT9PW8BN",
    target_attr_id=1, recommended_value="NO",
)


def test_extend_range_ice_kit_scenario_stale_blind_guess_corrected_same_turn():
    """Pass 1: Base Model not filled yet, no recommendation satisfied ->
    blind guess "YES". Pass 2: Base Model resolves (a new `filled` entry),
    satisfying the real recommendation that forces "NO" -- the stale "YES"
    guess must be corrected within the same turn, not left stranded."""
    eng = CpqEngine()
    sigs: dict[str, tuple] = {}

    # Pass 1 -- Base Model unfilled, no recommendation satisfied -> blind
    # first-option guess.
    filled: dict[str, str] = {}
    sources: dict[str, str] = {}
    filled, _display, _ = eng.auto_fill(
        [_ICE_KIT_TARGET, _ICE_KIT_BASE_MODEL], hints={}, already_filled=filled,
        filled_source=sources, constrained_opts=None, governed_ids={1},
        rule_governed_ids={1}, rec_rules=[_ICE_KIT_REC_RULE],
        display_order={"extendRangeTo762764MHz_astro": 0, "modelSelectionbaseModel_astro": 1},
        _default_fill_signatures=sigs,
    )
    assert filled["extendRangeTo762764MHz_astro"] == "YES"

    # Pass 2 -- Base Model just resolved (a genuinely new `filled` entry,
    # standing in for the script/BML chain reaching this point), which
    # satisfies the real recommendation forcing "NO".
    filled["modelSelectionbaseModel_astro"] = "H55TGT9PW8BN"
    filled, _display, _ = eng.auto_fill(
        [_ICE_KIT_TARGET, _ICE_KIT_BASE_MODEL], hints={}, already_filled=filled,
        filled_source=sources, constrained_opts=None, governed_ids={1},
        rule_governed_ids={1}, rec_rules=[_ICE_KIT_REC_RULE],
        display_order={"extendRangeTo762764MHz_astro": 0, "modelSelectionbaseModel_astro": 1},
        _default_fill_signatures=sigs,
    )
    assert filled["extendRangeTo762764MHz_astro"] == "NO", (
        "the gate must not strand the stale blind guess once Base Model "
        "resolves and the real recommendation fires later in the same turn"
    )


def test_extend_range_ice_kit_scenario_a_narrow_signature_would_have_stranded_the_guess(monkeypatch):
    """Negative control proving broadness matters. Patches in a
    hypothetical NARROW signature -- one that only observes the target
    attribute's own value, exactly the "one attribute's narrow snapshot"
    shape the risk doc warned against -- which stays identical across the
    two passes because it's blind to the upstream Base Model key changing.
    Under that narrow signature the gate wrongly holds and the stale
    "YES" survives, proving why the shipped signature must be broad
    (all of `filled`, not a per-attribute snapshot)."""
    import aryx.cpq.engine as engine_module

    def _narrow_signature(filled, filled_multi, visible_ids):
        return (filled.get("extendRangeTo762764MHz_astro"),)

    monkeypatch.setattr(engine_module, "_fill_signature", _narrow_signature)

    eng = CpqEngine()
    filled = {"extendRangeTo762764MHz_astro": "YES"}
    sources = {"extendRangeTo762764MHz_astro": "default_first_available"}
    sigs = {"extendRangeTo762764MHz_astro": _narrow_signature(filled, {}, {1, 2})}

    # Base Model resolves -- invisible to the narrow signature above.
    filled["modelSelectionbaseModel_astro"] = "H55TGT9PW8BN"
    filled, _display, _ = eng.auto_fill(
        [_ICE_KIT_TARGET, _ICE_KIT_BASE_MODEL], hints={}, already_filled=filled,
        filled_source=sources, constrained_opts=None, governed_ids={1},
        rule_governed_ids={1}, rec_rules=[_ICE_KIT_REC_RULE],
        display_order={"extendRangeTo762764MHz_astro": 0, "modelSelectionbaseModel_astro": 1},
        _default_fill_signatures=sigs,
    )
    assert filled["extendRangeTo762764MHz_astro"] == "YES", (
        "sanity check on the negative control itself -- confirms a narrow "
        "signature strands the guess when it can't see the upstream change, "
        "which is exactly why the real signature must be broad"
    )


# ── RC6 (2026-08-24): apply_constraint_rules had NO caching of its own ───
#
# docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md -- live-confirmed
# apply_constraint_rules costs comparable magnitude to auto_fill on a heavy
# turn (16.5s pass 0, 12.6s pass 1 on a 392-attr catalog) yet had no
# signature-based gate at all before RC6. Same sentinel technique as the
# auto_fill tests above: seed _constraint_cache with a result that could
# never arise from real evaluation, and observe whether the gate returns it
# unchanged (cache held) or real evaluation overwrote it (cache missed).

def _con_attr(entity_id: int, vn: str, *values: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn,
        required=False, default_value="", options=_menu(*values),
    )


_CON_TARGET = _con_attr(10, "targetAttr_astro", "A", "B", "C")
_CON_SOURCE = _con_attr(20, "sourceAttr_astro", "TRIGGER")
_CON_FILLED = {"sourceAttr_astro": "TRIGGER"}
_CON_RULE = ConstraintRule(
    rule_name="test constraint", condition_attr_id=_CON_SOURCE.entity_id,
    condition_value="TRIGGER", target_attr_id=_CON_TARGET.entity_id,
    allowed_values=["A", "B"],
)
_CON_SENTINEL_RESULT = {_CON_TARGET.entity_id: ["__SENTINEL_NEVER_A_REAL_RESULT__"]}


def test_apply_constraint_rules_cache_hit_returns_cached_result_unchanged():
    eng = CpqEngine()
    sig = _fill_signature(_CON_FILLED, {}, {_CON_TARGET.entity_id, _CON_SOURCE.entity_id})
    cache = {"sig": sig, "result": _CON_SENTINEL_RESULT}

    result = eng.apply_constraint_rules(
        [_CON_TARGET, _CON_SOURCE], [_CON_RULE], _CON_FILLED,
        _constraint_cache=cache,
    )
    assert result == _CON_SENTINEL_RESULT, (
        "gate should have skipped real evaluation -- the pre-seeded "
        "signature already matches the current state"
    )


def test_apply_constraint_rules_cache_miss_runs_real_evaluation():
    """Negative case: a signature that does NOT match the current state
    must let real evaluation run and overwrite the cache -- proving the
    gate doesn't silently freeze a stale (and here, bogus) result forever."""
    eng = CpqEngine()
    mismatched_sig = _fill_signature({}, {}, set())
    cache = {"sig": mismatched_sig, "result": _CON_SENTINEL_RESULT}

    result = eng.apply_constraint_rules(
        [_CON_TARGET, _CON_SOURCE], [_CON_RULE], _CON_FILLED,
        _constraint_cache=cache,
    )
    assert result == {_CON_TARGET.entity_id: ["A", "B"]}, (
        "a changed signature must allow real evaluation to run"
    )
    assert cache["result"] == {_CON_TARGET.entity_id: ["A", "B"]}, (
        "the cache must be updated with the fresh result, not left stale"
    )


def test_apply_constraint_rules_cache_none_is_a_complete_noop():
    """`None` (the default, and every pre-existing call site) must behave
    identically to omitting the parameter entirely."""
    eng = CpqEngine()
    result = eng.apply_constraint_rules(
        [_CON_TARGET, _CON_SOURCE], [_CON_RULE], _CON_FILLED,
        _constraint_cache=None,
    )
    assert result == {_CON_TARGET.entity_id: ["A", "B"]}


def test_apply_constraint_rules_signature_exclude_vns_keeps_the_gate_held():
    """An unrelated key's value changing (simulating a churning,
    non-convergent attribute, RC5-style) does NOT break the gate when that
    key is excluded from the signature snapshot."""
    eng = CpqEngine()
    filled_with_churn = {**_CON_FILLED, "churningAttr": "NEW"}
    sig_excluding_churn = _fill_signature(
        _CON_FILLED, {}, {_CON_TARGET.entity_id, _CON_SOURCE.entity_id},
    )
    cache = {"sig": sig_excluding_churn, "result": _CON_SENTINEL_RESULT}

    result = eng.apply_constraint_rules(
        [_CON_TARGET, _CON_SOURCE], [_CON_RULE], filled_with_churn,
        _constraint_cache=cache, _signature_exclude_vns=frozenset({"churningAttr"}),
    )
    assert result == _CON_SENTINEL_RESULT, (
        "excluding the churning key from the signature snapshot must keep "
        "the gate held despite the unrelated key's value changing"
    )


def test_apply_constraint_rules_without_exclusion_the_same_change_breaks_the_gate():
    """Negative control for the test above -- proves the exclusion is what
    holds the gate, not some other incidental difference."""
    eng = CpqEngine()
    filled_with_churn = {**_CON_FILLED, "churningAttr": "NEW"}
    sig_excluding_churn = _fill_signature(
        _CON_FILLED, {}, {_CON_TARGET.entity_id, _CON_SOURCE.entity_id},
    )
    cache = {"sig": sig_excluding_churn, "result": _CON_SENTINEL_RESULT}

    result = eng.apply_constraint_rules(
        [_CON_TARGET, _CON_SOURCE], [_CON_RULE], filled_with_churn,
        _constraint_cache=cache,
    )
    assert result == {_CON_TARGET.entity_id: ["A", "B"]}, (
        "without the exclusion, the unrelated key's change must legitimately "
        "break the gate"
    )
