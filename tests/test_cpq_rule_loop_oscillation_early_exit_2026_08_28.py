"""Live-confirmed gap (2026-08-28): `evaluate_rules_loop`'s early-exit
break (engine.py) already existed and looked correct -- it checks
`not _resynced and not inconsistent_vns and <filled/visible unchanged>` --
but real production logs showed EVERY sampled turn (cheap and expensive
alike) always ran the full `_MAX_LOOPS = 8` passes, never fewer.

Root cause: the break condition checked raw `_resynced`/`inconsistent_vns`,
but `_oscillating_vns` (built specifically to track attributes already
PROVEN non-convergent by RC3/RC4/RC5, so their churn stops perturbing
everything else's signature -- see `_signature_exclude_vns` usage a few
lines above the break) was never applied to the break condition itself. A
single already-known-oscillating attribute silently blocked early exit on
every pass, forever, even once every other attribute had genuinely
stabilized.

Fix: exclude `_oscillating_vns` members from both the resynced and
inconsistent checks before evaluating the break -- a vn already proven to
never converge no longer counts as "still churning" for exit purposes,
while a vn not yet proven oscillating still correctly blocks the break
(pass 0->1 is unaffected, since oscillation can only be detected once a
vn repeats across two passes).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attr(entity_id: int, vn: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn,
        required=False, default_value="", options=_menu("A", "B"),
    )


def _install_controlled_pass_body(monkeypatch, eng, *, always_resync):
    """Patches every per-pass method evaluate_rules_loop calls (except the
    break condition itself) to a deterministic no-op, except optionally
    `resync_stale_recommendations`, which simulates one permanently
    non-convergent attribute ("churning_vn") when `always_resync=True`.
    Returns a list that records one entry per pass actually executed
    (via `apply_hiding_rules`, called exactly once near the top of every
    pass), so the test can assert on the real pass count.
    """
    pass_markers: list[int] = []

    def _fake_apply_hiding_rules(attrs, filled, hiding_rules, bml_eval=None, filled_multi=None, **kwargs):
        pass_markers.append(len(pass_markers))
        return attrs, [], set()

    def _fake_auto_fill(attrs, hints, **kwargs):
        already_filled = kwargs.get("already_filled", {})
        return dict(already_filled), {}, {}

    def _fake_resync_stale_recommendations(*args, **kwargs):
        if always_resync:
            return {"churning_vn": ("SAME_VALUE", "Same Value")}
        return {}

    monkeypatch.setattr(eng, "apply_hiding_rules", _fake_apply_hiding_rules)
    monkeypatch.setattr(eng, "auto_fill", _fake_auto_fill)
    monkeypatch.setattr(eng, "_compute_hidden_master_string", lambda *a, **k: None)
    monkeypatch.setattr(eng, "_invalidate_inconsistent_paired_values", lambda *a, **k: set())
    monkeypatch.setattr(eng, "resync_stale_recommendations", _fake_resync_stale_recommendations)
    monkeypatch.setattr(eng, "apply_constraint_rules", lambda *a, **k: {})
    monkeypatch.setattr(eng, "_apply_series_mapping_exclusions", lambda *a, **k: None)
    return pass_markers


def test_loop_exits_early_when_nothing_is_churning(monkeypatch):
    """Baseline sanity: with no churn source active at all, the loop must
    already exit well before the 8-pass cap (pass 0 sets up state, pass 1
    sees no change and breaks)."""
    eng = CpqEngine()
    attrs = [_attr(1, "x")]
    pass_markers = _install_controlled_pass_body(monkeypatch, eng, always_resync=False)

    eng.evaluate_rules_loop(
        attrs, hints={}, filled={}, hiding_rules=[], rec_rules=[], con_rules=[],
        bml_eval=None, filled_source={}, filled_multi={},
    )
    assert len(pass_markers) <= 2, (
        f"expected an early exit with no churn source, got {len(pass_markers)} passes"
    )


def test_loop_still_ran_all_8_passes_before_the_fix_is_understood(monkeypatch):
    """Reproduces the live-confirmed symptom: a single permanently
    oscillating attribute must not be allowed to block exit indefinitely.
    This is the actual regression test for the fix -- with `_oscillating_
    vns` now excluded from the break check, the loop must exit once it has
    been proven (after one repeat) that `churning_vn` is the only thing
    still moving, rather than exhausting all 8 passes."""
    eng = CpqEngine()
    attrs = [_attr(1, "x")]
    pass_markers = _install_controlled_pass_body(monkeypatch, eng, always_resync=True)

    eng.evaluate_rules_loop(
        attrs, hints={}, filled={}, hiding_rules=[], rec_rules=[], con_rules=[],
        bml_eval=None, filled_source={}, filled_multi={},
    )
    assert len(pass_markers) < 8, (
        "a single already-proven-oscillating attribute must not force the "
        "full 8-pass cap once every other attribute has stabilized -- got "
        f"{len(pass_markers)} passes, expected an early exit"
    )
    # Oscillation can only be detected once a vn repeats across two passes
    # (pass 0 has nothing to compare against) -- so at least 2 passes must
    # still run before the exclusion can kick in and let the loop exit.
    assert len(pass_markers) >= 2


def test_a_genuinely_new_change_each_pass_still_blocks_early_exit(monkeypatch):
    """Negative control: a DIFFERENT vn resyncing every pass (never
    repeating, so never proven oscillating) must keep legitimately
    blocking early exit for the full cap -- proving the fix doesn't turn
    into "ignore all churn," only "ignore PROVEN-oscillating churn"."""
    eng = CpqEngine()
    attrs = [_attr(1, "x")]
    pass_markers = _install_controlled_pass_body(monkeypatch, eng, always_resync=False)

    call_count = [0]

    def _fake_resync_always_new_vn(*args, **kwargs):
        call_count[0] += 1
        return {f"vn_{call_count[0]}": ("V", "V")}

    monkeypatch.setattr(eng, "resync_stale_recommendations", _fake_resync_always_new_vn)

    eng.evaluate_rules_loop(
        attrs, hints={}, filled={}, hiding_rules=[], rec_rules=[], con_rules=[],
        bml_eval=None, filled_source={}, filled_multi={},
    )
    assert len(pass_markers) == 8, (
        "a genuinely new (never-repeating) resync target every pass must "
        f"still run the full cap -- got {len(pass_markers)} passes"
    )
