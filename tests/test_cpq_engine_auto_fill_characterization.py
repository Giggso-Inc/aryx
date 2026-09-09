"""Phase-level golden-master characterization for `CpqEngine.auto_fill`
and `CpqEngine.evaluate_rules_loop` -- step 1, part 2 of Phase 4
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md "Phase 4 planning
analysis"). An earlier draft of that plan proposed these two as a
permanent stated exception to the 150-line rule; the user explicitly
overrode that ("in phase 4 these two files ... should be split in 150
lines there is no exception in this") and step 3 (the `FillContext`
refactor: P2/P3 extraction, the `FillContext` dataclass, the P1 loop
body rewired to read/write through `ctx.*` and renamed to
`_resolve_one_attr`) is the resulting decomposition work. This file
remains the safety net proving each move preserved behavior exactly.

Existing coverage survey done before writing anything here (per this
task's own instructions): auto_fill already has 32 test-file references,
evaluate_rules_loop has 18. Reading them (tests/test_cpq_model_pointer.py,
tests/test_cpq_auto_fill_data_table_tier.py, tests/test_cpq_auto_fill_
tier2_prefetch_gap.py, tests/test_cpq_recommendation_resync.py, tests/
test_cpq_recommendation_respects_active_constraint.py, tests/test_cpq_
rule_loop_oscillation_early_exit_2026_08_28.py, tests/test_cpq_
frequency_band_family_exclusions.py, tests/test_cpq_layout_visibility_
order.py, tests/test_cpq_stale_base_model_cascade_2026_08_20.py) found:

- Pointer-default resolution: already thoroughly, independently pinned
  (test_cpq_model_pointer.py) -- not duplicated here.
- Data-Table governance (the real ingested-data fallback tier, series-
  mapping exclusions, ungoverned-attr suppression, inconsistent-paired-
  value invalidation): already extremely thoroughly pinned, calling
  auto_fill directly with a fake RDB (test_cpq_auto_fill_data_table_tier.py,
  1,391 lines / dozens of cases) -- not duplicated here.
- Sibling-exclusivity enforcement: already thoroughly pinned directly
  against `exclusive_sibling_family_exclusions`/`enforce_exclusive_
  sibling_families` (test_cpq_frequency_band_family_exclusions.py).
  IMPORTANT FINDING from reading engine.py itself (grep confirmed): this
  mechanism is NOT invoked from inside auto_fill or evaluate_rules_loop at
  all -- its only call site is aryx/api/ask_api.py, applied as a separate
  post-processing step AFTER evaluate_rules_loop returns. It is not
  actually part of auto_fill's internal decision tree despite initially
  looking like a natural sixth branch; documented here so a future
  engineer splitting auto_fill doesn't go looking for it inside the
  method.
- Individual recommendation/constraint mechanics (resync, active-
  constraint respect, oscillation early-exit): each pinned narrowly, one
  or two rule types at a time.

The one gap this file actually closes: no existing test drives a SINGLE
evaluate_rules_loop call with all three rule types (hiding + recommendation
+ constraint) simultaneously active and targeting DIFFERENT attributes,
asserting each rule type's own contribution to the final visible/filled/
display_filled/constrained_opts state in one shot -- i.e. proof the whole
per-pass pipeline (auto-fill -> hide -> recommend -> constrain, iterated to
a fixed point) really does compose the way each rule type's own isolated
test implies, not just that each rule type works when it's the only one
loaded. Also adds: the documented-not-fixed sibling-exclusivity-is-not-
wired-into-auto_fill finding above (as a runnable proof, not just a
comment), and a multi-pass recommendation-cascade case (a value produced
by one recommendation rule on pass N becomes the condition value for a
SECOND recommendation rule that only resolves on pass N+1) -- proof the
"iterate to a fixed point" contract in evaluate_rules_loop's own docstring
actually holds across more than one pass, not just within a single pass.

As with all characterization work: nothing here is a specification of
"correct" behavior. Any inconsistency noticed while pinning it (e.g. the
`filled_source` tag differing between "rule" and "blind_pick_rule_governed"
for two attributes that look symmetric on paper) is recorded as an observed
fact in the relevant test's docstring, not resolved or fixed.
"""
from __future__ import annotations

import pytest

from aryx.cpq.data_table import data_table_loader
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption
from aryx.cpq.state_rules import ConstraintRule, HidingRule, RecommendationRule


def _menu(*vals: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(vals, start=1)]


def _attr(entity_id, vn, label=None, *, options=None, required=False,
          default="", select_type="single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=label or vn,
        required=required, default_value=default, options=options or [],
        select_type=select_type,
    )


def _three_rule_type_fixture():
    """One decision attr (`flavor`) plus one attr governed by each of the
    three rule types, mirroring the shape auto_fill's own docstring
    describes (priority order 1-6) and evaluate_rules_loop's documented
    per-pass pipeline (hide -> recommend -> constrain -> auto-fill,
    iterated)."""
    flavor = _attr(1, "flavor", "Flavor", options=_menu("A", "B"), required=True)
    hidden_target = _attr(2, "hiddenTarget", "Hidden Target", options=_menu("X", "Y"))
    rec_target = _attr(3, "recTarget", "Rec Target", options=_menu("X", "Y"))
    con_target = _attr(4, "conTarget", "Con Target", options=_menu("X", "Y"))
    attrs = [flavor, hidden_target, rec_target, con_target]

    # hiddenTarget is hidden only when flavor == A.
    hiding = HidingRule(rule_name="hide hiddenTarget when A", condition_attr_id=1,
                        condition_value="A", target_attr_id=2, hide=True)
    # recTarget is recommended "Y" only when flavor == B.
    rec = RecommendationRule(rule_name="recommend Y when B", condition_attr_id=1,
                              condition_value="B", target_attr_id=3, recommended_value="Y")
    # conTarget is constrained to exactly ["Y"] only when flavor == B.
    con = ConstraintRule(rule_name="constrain to Y when B", condition_attr_id=1,
                         condition_value="B", target_attr_id=4, allowed_values=["Y"])
    return attrs, hiding, rec, con


def test_evaluate_rules_loop_composes_all_three_rule_types_when_condition_is_met():
    """flavor=B: the hiding rule's condition (flavor==A) does NOT hold, so
    hiddenTarget stays visible; the recommendation rule's condition DOES
    hold, so recTarget is filled with its recommended value "Y" (tagged
    source "rule"); the constraint rule's condition DOES hold, so
    conTarget's constrained_opts narrows to exactly ["Y"], and — with
    exactly one option remaining — auto_fill's own step 6 blind-pick fills
    it too (tagged source "auto", per this engine's own step-6 tagging,
    NOT "rule" — pinned as observed, not asserted to be intentional)."""
    attrs, hiding, rec, con = _three_rule_type_fixture()
    eng = CpqEngine()
    filled: dict[str, str] = {}
    filled_source: dict[str, str] = {}
    visible, filled_out, display_out, constrained = eng.evaluate_rules_loop(
        attrs, {"flavor": "B"}, filled, [hiding], [rec], [con],
        filled_source=filled_source,
    )

    assert {a.variable_name for a in visible} == {
        "flavor", "hiddenTarget", "recTarget", "conTarget",
    }
    assert filled_out == {
        "flavor": "B", "hiddenTarget": "X", "recTarget": "Y", "conTarget": "Y",
    }
    assert display_out == filled_out  # no MenuOption.display_name diverges from item_value here
    assert constrained == {4: ["Y"]}
    assert filled_source["recTarget"] == "rule"
    assert filled_source["conTarget"] == "auto"


def test_evaluate_rules_loop_composes_all_three_rule_types_when_condition_is_not_met():
    """flavor=A (the mirror scenario): the hiding rule's condition DOES
    hold, so hiddenTarget is removed from `visible` and from
    `display_filled` (though its stale value is left in `filled` -- pinned
    exactly as observed, this loop does not clear filled for a newly-
    hidden attr); the recommendation and constraint rules' conditions do
    NOT hold, so recTarget/conTarget both fall through to auto_fill's
    unconstrained step-6 blind first-by-order pick ("X", the first menu
    option for both) -- and constrained_opts ends up empty since the
    constraint never activated."""
    attrs, hiding, rec, con = _three_rule_type_fixture()
    eng = CpqEngine()
    filled: dict[str, str] = {}
    filled_source: dict[str, str] = {}
    visible, filled_out, display_out, constrained = eng.evaluate_rules_loop(
        attrs, {"flavor": "A"}, filled, [hiding], [rec], [con],
        filled_source=filled_source,
    )

    assert {a.variable_name for a in visible} == {"flavor", "recTarget", "conTarget"}
    assert "hiddenTarget" not in {a.variable_name for a in visible}
    assert filled_out == {
        "flavor": "A", "hiddenTarget": "X", "recTarget": "X", "conTarget": "X",
    }
    assert "hiddenTarget" not in display_out
    assert constrained == {}


def test_multi_pass_recommendation_cascade_resolves_within_one_call():
    """evaluate_rules_loop's own docstring contract: "Iterates until
    neither the filled set nor the visible attr set changes." Proof this
    genuinely spans multiple internal passes, not just one: a2's
    recommendation fires off a1's value (pass 1), and a3's OWN
    recommendation rule is conditioned on a2's value -- which does not
    exist until pass 1 completes, so a3 can only resolve on pass 2. A
    single evaluate_rules_loop call must still resolve both without the
    caller looping externally."""
    a1 = _attr(1, "a1", "A1", options=_menu("P", "Q"), required=True)
    a2 = _attr(2, "a2", "A2", options=_menu("M", "N"))
    a3 = _attr(3, "a3", "A3", options=_menu("R", "S"))
    attrs = [a1, a2, a3]
    rec1 = RecommendationRule(rule_name="a1->a2", condition_attr_id=1,
                               condition_value="P", target_attr_id=2, recommended_value="N")
    rec2 = RecommendationRule(rule_name="a2->a3", condition_attr_id=2,
                               condition_value="N", target_attr_id=3, recommended_value="S")

    eng = CpqEngine()
    filled: dict[str, str] = {}
    filled_source: dict[str, str] = {}
    _visible, filled_out, _display, _constrained = eng.evaluate_rules_loop(
        attrs, {"a1": "P"}, filled, [], [rec1, rec2], [], filled_source=filled_source,
    )

    assert filled_out == {"a1": "P", "a2": "N", "a3": "S"}
    assert filled_source["a2"] == "rule"
    assert filled_source["a3"] == "rule"


def test_sibling_exclusivity_is_not_applied_by_evaluate_rules_loop_itself():
    """Documented finding, not a bug (see this file's module docstring):
    `enforce_exclusive_sibling_families`/`exclusive_sibling_family_
    exclusions` are called ONLY from aryx/api/ask_api.py, never from
    inside auto_fill or evaluate_rules_loop. Proof: a classic
    single/multi sibling-family collision (the exact shape tests/
    test_cpq_frequency_band_family_exclusions.py exercises directly)
    passed straight through evaluate_rules_loop is left completely
    unresolved -- both the weakly-sourced single-select value AND the
    multi-select sibling's absence survive the loop untouched, because
    nothing inside this loop's own pipeline (hide/recommend/constrain/
    auto-fill) knows about this cross-attribute concept at all."""
    single = _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands",
                    options=_menu("700/800 MHZ"), select_type="single")
    multi = _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band",
                   options=_menu("UHF", "VHF"), select_type="multi")
    attrs = [single, multi]

    eng = CpqEngine()
    filled: dict[str, str] = {}
    filled_multi: dict[str, list[str]] = {}
    filled_source: dict[str, str] = {}
    _visible, filled_out, _display, _constrained = eng.evaluate_rules_loop(
        attrs, {}, filled, [], [], [],
        filled_source=filled_source, filled_multi=filled_multi,
    )

    # single's own default-less blind-pick still fills it (no options
    # narrowing at all here beyond "exactly one option exists").
    assert filled_out.get("modelSelectionFrequencyBands_astro") == "700/800 MHZ"
    # the multi sibling this pairing SHOULD defer to is never touched --
    # evaluate_rules_loop has no sibling-exclusivity concept of its own.
    assert "modelSelectionFrequencyBandMsl_astro" not in filled_multi


def test_governed_ids_gate_extends_beyond_the_explicit_governed_ids_param():
    """Characterization of an internal wiring detail relevant to any future
    split: evaluate_rules_loop never receives (or passes down) an explicit
    `governed_ids` argument for auto_fill -- yet attrs targeted by a
    hiding/recommendation/constraint rule still get blind-picked via the
    rule-governed step 5/6 path (tagged "rule"/"blind_pick_rule_governed"),
    not left to the plain non-required "ask" path. This confirms
    evaluate_rules_loop (or auto_fill itself) derives governed_ids
    internally from the rule sets it's given, rather than requiring the
    caller to compute and pass rule_governed_ids() separately for this to
    work -- a caller of the bare `auto_fill` method directly (as many
    existing tests do) does NOT get this for free and must pass
    governed_ids explicitly (see test_cpq_auto_fill_data_table_tier.py's
    calls, which all pass governed_ids=... explicitly)."""
    hidden_target = _attr(2, "hiddenTarget", "Hidden Target", options=_menu("X", "Y"))
    flavor = _attr(1, "flavor", "Flavor", options=_menu("A", "B"), required=True)
    hiding = HidingRule(rule_name="hide when A", condition_attr_id=1,
                        condition_value="A", target_attr_id=2, hide=True)

    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    _visible, filled_out, _display, _constrained = eng.evaluate_rules_loop(
        [flavor, hidden_target], {"flavor": "B"}, {}, [hiding], [], [],
        filled_source=filled_source,
    )
    assert filled_out.get("hiddenTarget") == "X"
    assert filled_source.get("hiddenTarget") == "blind_pick_rule_governed"


def test_bare_auto_fill_call_requires_governed_ids_to_be_passed_explicitly():
    """The control case for the test above: calling `auto_fill` directly
    (bypassing evaluate_rules_loop) with the SAME hiding-rule-targeted attr
    but omitting governed_ids leaves it unfilled/pending instead of blind-
    picked -- proving evaluate_rules_loop's internal governed_ids
    derivation (not some property of auto_fill itself) is what made the
    prior test's blind-pick happen."""
    hidden_target = _attr(2, "hiddenTarget", "Hidden Target", options=_menu("X", "Y"))
    eng = CpqEngine()
    filled_out, _display, pending = eng.auto_fill([hidden_target], hints={})
    assert "hiddenTarget" not in filled_out
    assert [a.variable_name for a in pending] == ["hiddenTarget"]


# ---------------------------------------------------------------------------
# Part 3: auto_fill's OWN internal decision-tree branches, driven by direct
# `auto_fill` calls (not evaluate_rules_loop) -- the gap this file's own
# module docstring flagged as still open. Per that docstring's own survey:
# pointer-default resolution and Data-Table governance are ALREADY pinned
# thoroughly and directly against `auto_fill` elsewhere (test_cpq_model_
# pointer.py; test_cpq_auto_fill_data_table_tier.py, 1,391 lines / dozens of
# cases) -- the tests below add the specific distinguishing scenarios named
# by this session's own task, not a wholesale re-derivation of that existing
# coverage.
# ---------------------------------------------------------------------------


def test_pointer_default_resolves_from_the_referenced_attrs_value():
    """`_is_pointer_default` (engine.py ~8924): a default_value that is
    itself another attr's variable_name (not a literal) is a REFERENCE,
    resolved by auto_fill's post-pass (~10677-10685) once the referenced
    attr has a real value -- confirmed already, directly, by
    tests/test_cpq_model_pointer.py. Pinned again here, minimally, as the
    control case for the "no value yet" branch immediately below."""
    source_attr = _attr(1, "sourceAttr", "Source", options=_menu("ALPHA", "BETA"))
    pointer_attr = _attr(2, "pointerAttr", "Pointer", default="sourceAttr")
    eng = CpqEngine()
    filled_out, display_out, _pending = eng.auto_fill(
        [source_attr, pointer_attr], hints={},
        already_filled={"sourceAttr": "ALPHA"},
    )
    assert filled_out["pointerAttr"] == "ALPHA"
    assert display_out["pointerAttr"] == "ALPHA"


def test_pointer_default_stays_unfilled_when_the_referenced_attr_has_no_value():
    """The other half of the pointer-default branch: when the referenced
    attr never resolves (no options, no hint, nothing filled), the pointer
    token itself is NEVER shipped as data (per the post-pass's own comment)
    -- the pointer attr is simply absent from `filled`, not defaulted to
    the literal pointer string, and (since it has no options of its own)
    also never lands in `pending`."""
    source_attr = _attr(1, "sourceAttr", "Source", options=_menu("ALPHA", "BETA"))
    pointer_attr = _attr(2, "pointerAttr", "Pointer", default="sourceAttr")
    eng = CpqEngine()
    filled_out, _display, pending = eng.auto_fill(
        [source_attr, pointer_attr], hints={}, already_filled={},
    )
    assert "pointerAttr" not in filled_out
    # sourceAttr itself has real options and nothing (hint/default/rule)
    # resolves it, so it lands in `pending` as an ordinary ask -- pointer_attr
    # is simply absent from every returned collection, not defaulted or asked.
    assert [a.variable_name for a in pending] == ["sourceAttr"]


class _FakeSequenceRdb:
    """Minimal fake RDB serving only sequence-shaped ("AttrSequence")
    rows -- CPQModel/BaseModel/AttrName/Seq keys, per
    data_table_shapes._is_sequence_shaped -- matching the fake-RDB pattern
    tests/test_cpq_auto_fill_data_table_tier.py already established for
    this exact monkeypatch point (data_table_loader.get_cpq_rdb)."""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    def list_ontology_types(self, workspace_id):
        return ["AttrSequenceTest"]

    def fetch_entities_by_type(self, workspace_id, type_suffix, catalog_prefix=""):
        return [(i, r) for i, r in enumerate(self._rows, start=1)]

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        return [(i, r) for i, r in enumerate(self._rows, start=1)]


@pytest.fixture(autouse=True)
def _clear_dt_tables_cache():
    """Same test-isolation need as test_cpq_auto_fill_data_table_tier.py:
    _load_all_tables' module-level short-TTL cache must never leak one
    test's fake rows into another sharing the same (workspace_id,
    catalog_prefix) key."""
    data_table_loader._clear_tables_cache()
    yield
    data_table_loader._clear_tables_cache()


def test_dt_governed_attr_blind_picks_first_option_vs_never_governed_attr_stays_pending(
    monkeypatch,
):
    """Data-Table governance (`_dt_governed_vns` / `_dt_never_governed_
    anywhere`, engine.py ~9082-9109): two otherwise-identically-shaped
    ungoverned attrs (no rec/constraint rule, no default_value) reach very
    different outcomes once a real ingested attrSequence Data Table and a
    layout `display_order` map are both in play (§2c/§2f):

    - `dtGovernedTarget_astro` has a real attrSequence row for the current
      (CPQModel, BaseModel) -- confirmed governed for THIS base model --
      so it is blind-picked to its first real catalog option rather than
      asked (tagged "blind_pick_governed").
    - `neverGovernedTarget_astro` has ZERO attrSequence rows anywhere (any
      CPQModel, any base model) -- `_dt_never_governed_anywhere` is True --
      so §2c's "unknown, ask to be safe" safety net wins: it lands in
      `pending`, is NOT silently blind-picked, and is NOT silently dropped
      either (both would be a "real question never appears" regression).
    """
    monkeypatch.setattr(
        data_table_loader, "get_cpq_rdb",
        lambda: _FakeSequenceRdb([
            {"CPQModel": "APXNEXT", "BaseModel": "BM1",
             "AttrName": "dtGovernedTarget_astro", "Seq": "1"},
        ]),
    )
    base_model_attr = _attr(1, "modelSelectionbaseModel_astro", "Base Model")
    product_attr = _attr(2, "productSelectionProduct_all", "Product")
    dt_governed = _attr(3, "dtGovernedTarget_astro", "DT Governed",
                         options=_menu("X", "Y"))
    never_governed = _attr(4, "neverGovernedTarget_astro", "Never Governed",
                            options=_menu("P", "Q"))
    attrs = [base_model_attr, product_attr, dt_governed, never_governed]

    eng = CpqEngine()
    filled_out, display_out, pending = eng.auto_fill(
        attrs, hints={},
        already_filled={
            "modelSelectionbaseModel_astro": "BM1",
            "productSelectionProduct_all": "SOME UNMAPPED PRODUCT",
        },
        workspace_id=7,
        display_order={"dtGovernedTarget_astro": 0, "neverGovernedTarget_astro": 1},
    )

    assert filled_out.get("dtGovernedTarget_astro") == "X"
    assert display_out.get("dtGovernedTarget_astro") == "X"
    assert "neverGovernedTarget_astro" not in filled_out
    assert [a.variable_name for a in pending] == ["neverGovernedTarget_astro"]


def test_auto_fill_takes_the_hidden_flag_as_a_fixed_input_never_re_derives_it():
    """Hiding-rule interaction, part 1: `attr.hidden` (engine.py ~9348) is a
    plain boolean already set by the CALLER (evaluate_rules_loop's own,
    separate apply_hiding_rules pass) BEFORE auto_fill ever runs -- auto_fill
    itself has no HidingRule objects in scope for this check and never
    "re-hides" or "re-shows" an attr mid-call based on anything it decides
    in the SAME call. Pinned: a hidden attr with a valid default_value gets
    ONLY that default (never asked, never blind-picked); a hidden attr with
    no default_value is left completely unfilled -- and neither one EVER
    reaches `pending`, regardless of how many real options it has."""
    hidden_with_default = ConfigAttr(
        entity_id=1, variable_name="hiddenWithDefault", display_label="Hidden Default",
        required=False, default_value="Y", options=_menu("X", "Y"), hidden=True,
    )
    hidden_without_default = ConfigAttr(
        entity_id=2, variable_name="hiddenNoDefault", display_label="Hidden No Default",
        required=False, default_value="", options=_menu("X", "Y"), hidden=True,
    )
    eng = CpqEngine()
    filled_out, display_out, pending = eng.auto_fill(
        [hidden_with_default, hidden_without_default], hints={},
    )
    assert filled_out.get("hiddenWithDefault") == "Y"
    assert display_out.get("hiddenWithDefault") == "Y"
    assert "hiddenNoDefault" not in filled_out
    assert pending == []


def test_hiding_rules_param_warns_and_skips_a_target_gated_on_a_confirmed_missing_data_table():
    """Hiding-rule interaction, part 2 -- a genuinely different mechanism
    than the `attr.hidden` flag above: `hiding_rules` (engine.py ~9111-9121,
    ~10504-10536) is a real, separate parameter `auto_fill` itself accepts
    and evaluates via `_hiding_rule_needs_missing_data_table` -- an attr
    whose ONLY hiding rule's script references a data table confirmed
    absent (`_KNOWN_MISSING_DATA_TABLES` = ("UserGroupMapping",)) can never
    have that rule resolve, so auto_fill warns and skips it (no fill, no
    pending) rather than asking forever. `workspace_id=None` (the default
    here) makes every candidate table conservatively "missing", matching
    every caller that doesn't pass a workspace. A sibling attr targeted by
    an ordinary hiding rule (script naming no missing table) is unaffected
    -- ungoverned, no other resolution, it falls through to the normal
    ask-branch (`pending`) exactly as if `hiding_rules` had never been
    passed at all."""
    stuck_target = _attr(1, "stuckTarget", "Stuck", options=_menu("X", "Y"))
    normal_target = _attr(2, "normalTarget", "Normal", options=_menu("X", "Y"))
    stuck_rule = HidingRule(
        rule_name="hide via missing UserGroupMapping table",
        condition_attr_id=0, condition_value="", target_attr_id=1, hide=True,
        script="return UserGroupMapping.lookup(customerType)",
    )
    normal_rule = HidingRule(
        rule_name="hide via ordinary script", condition_attr_id=0,
        condition_value="", target_attr_id=2, hide=True,
        script="return customerType == 'FEDERAL'",
    )
    eng = CpqEngine()
    filled_out, _display, pending = eng.auto_fill(
        [stuck_target, normal_target], hints={},
        hiding_rules=[stuck_rule, normal_rule],
    )
    assert "stuckTarget" not in filled_out
    assert "stuckTarget" not in [a.variable_name for a in pending]
    assert "normalTarget" not in filled_out
    assert [a.variable_name for a in pending] == ["normalTarget"]


def test_auto_fill_own_recommendation_check_fires_when_condition_already_holds():
    """Recommendation-rule interaction, part 1 (step 2/`_satisfied_
    recommendation`, engine.py ~8938-9002, ~9482-9498) -- distinct from
    evaluate_rules_loop's own later `apply_recommendation_rules()` pass
    (which this file's own multi-pass-cascade test above already covers):
    a rec_rules entry whose condition is ALREADY true in the `already_filled`
    state passed straight into a BARE `auto_fill` call resolves the target
    attr right there, tagged source "rule" -- taking priority over the
    attr's own generic XML default_value (the "solutionTypeDevices_astro"
    bug this priority order exists to close, per auto_fill's own
    docstring)."""
    condition_attr = _attr(1, "conditionAttr", "Condition", options=_menu("A", "B"))
    rec_target = _attr(2, "recTarget", "Rec Target", options=_menu("DEFAULT_OPT", "REC_OPT"),
                        default="DEFAULT_OPT")
    rec = RecommendationRule(
        rule_name="recommend REC_OPT when A", condition_attr_id=1,
        condition_value="A", target_attr_id=2, recommended_value="REC_OPT",
    )
    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    filled_out, display_out, _pending = eng.auto_fill(
        [condition_attr, rec_target], hints={},
        already_filled={"conditionAttr": "A"},
        rec_rules=[rec], filled_source=filled_source,
    )
    assert filled_out["recTarget"] == "REC_OPT"
    assert display_out["recTarget"] == "REC_OPT"
    assert filled_source["recTarget"] == "rule"


def test_auto_fill_own_recommendation_check_falls_through_to_default_when_condition_unmet():
    """Recommendation-rule interaction, part 2 -- the mirror case: the same
    rule's condition does NOT hold (conditionAttr == "B"), so
    `_satisfied_recommendation` returns no match and recTarget instead
    falls through to the NEXT priority tier, its own XML default_value
    ("DEFAULT_OPT") -- proving the condition check genuinely gates the
    rule, it isn't applied unconditionally just because rec_rules was
    passed."""
    condition_attr = _attr(1, "conditionAttr", "Condition", options=_menu("A", "B"))
    rec_target = _attr(2, "recTarget", "Rec Target", options=_menu("DEFAULT_OPT", "REC_OPT"),
                        default="DEFAULT_OPT")
    rec = RecommendationRule(
        rule_name="recommend REC_OPT when A", condition_attr_id=1,
        condition_value="A", target_attr_id=2, recommended_value="REC_OPT",
    )
    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    filled_out, _display, _pending = eng.auto_fill(
        [condition_attr, rec_target], hints={},
        already_filled={"conditionAttr": "B"},
        rec_rules=[rec], filled_source=filled_source,
    )
    assert filled_out["recTarget"] == "DEFAULT_OPT"
    assert filled_source["recTarget"] == "default"


def test_constraint_narrowed_to_a_single_legal_value_is_auto_filled_as_auto_source():
    """Constraint-rule interaction, part 1 (the `len(valid_opts) == 1`
    "Stop and Wait" shortcut, engine.py ~9737-9785) -- distinct from
    evaluate_rules_loop's own constraint-application pass (this file's
    three-rule-type composition tests above already cover THAT level): a
    plain, ungoverned (not in governed_ids/rule_governed_ids) attr whose
    `constrained_opts` entry narrows its real menu down to EXACTLY ONE
    still-legal option is auto-filled with that one value -- tagged source
    "auto" (the initial/default source tag, NEVER reassigned by this
    branch), NOT "rule", even though a real ConstraintRule is what produced
    the narrowing -- pinned as observed, matching this same file's earlier
    note about "auto" vs "rule" tagging looking symmetric on paper but not
    being so in practice."""
    single_legal = _attr(5, "singleLegalAttr", "Single Legal",
                          options=_menu("X", "Y", "Z"))
    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    filled_out, display_out, pending = eng.auto_fill(
        [single_legal], hints={},
        constrained_opts={5: ["Y"]}, filled_source=filled_source,
    )
    assert filled_out["singleLegalAttr"] == "Y"
    assert display_out["singleLegalAttr"] == "Y"
    assert filled_source["singleLegalAttr"] == "auto"
    assert pending == []


def test_constraint_narrowed_to_two_or_more_legal_values_stays_pending():
    """Constraint-rule interaction, part 2 -- the mirror case: the SAME
    shape of ungoverned attr, but its `constrained_opts` entry narrows the
    real menu to TWO still-legal options instead of exactly one. Issue 6's
    "Stop and Wait" safeguard (NO EAGER EVALUATION for anything not
    rule-governed) means this is NOT auto-filled -- it stays unfilled and
    lands in `pending`, letting the customer pick between the two
    real remaining options rather than guessing either one."""
    two_legal = _attr(6, "twoLegalAttr", "Two Legal", options=_menu("X", "Y", "Z"))
    eng = CpqEngine()
    filled_out, _display, pending = eng.auto_fill(
        [two_legal], hints={}, constrained_opts={6: ["Y", "Z"]},
    )
    assert "twoLegalAttr" not in filled_out
    assert [a.variable_name for a in pending] == ["twoLegalAttr"]


def test_shared_default_fill_signature_cache_can_serve_a_stale_re_derivation():
    """`_default_fill_signatures` (engine.py docstring ~8730-8757, gate at
    ~9251-9295): a turn-scoped, mutate-in-place dict `evaluate_rules_loop`
    threads through every pass of ONE turn so a "default_first_available"
    multi-select guess is only RE-VALIDATED against a newly-active
    constraint when the signature (built from `filled`/`filled_multi`'s
    current contents plus the calling attrs' entity-id set) has changed
    since it was last (re)derived -- NOT on every call.

    Note: `already_filled_multi`/`filled_source` are mutated IN PLACE by
    auto_fill (per its own docstring) -- the values asserted below come
    from re-reading those caller-owned dicts after the call, not from the
    method's return value (which only ever carries single-select `filled`).

    Pinned here as an observed risk, not a bug fixed: a real ConstraintRule
    has just excluded "FIRST" from the legal set (`constrained_opts`), so a
    genuine re-derivation correctly drops the stale guess to empty. But if
    the SAME signature-cache dict is reused for a SECOND call whose input
    state is bit-for-bit identical to what produced the stored signature,
    the gate skips re-derivation entirely and the now-illegal "FIRST"
    value survives untouched -- exactly the "default_first_available
    locked in a wrong guess forever" failure class this cache's own
    surrounding comments describe (extendRangeTo762764MHz_astro). A FRESH
    (unshared) signature dict for that identical second call has no stored
    entry to match, so it always re-derives and correctly drops "FIRST"."""
    def _cached_attr() -> ConfigAttr:
        return _attr(10, "cachedAttr", "Cached", select_type="multi",
                     options=_menu("FIRST", "SECOND", "THIRD"))

    # A real rule targets this attr (required for `_no_real_fill_
    # justification` to be False and unlock the constrained-multi-select
    # branch at all -- an attr with NO required/default/rec-rule signal
    # never reaches this branch, see that helper's own definition), but
    # its condition never resolves here -- purely a vehicle to reach the
    # branch under test, not itself part of what's being pinned.
    _never_fires_rec = RecommendationRule(
        rule_name="never fires", condition_attr_id=999,
        condition_value="NEVER", target_attr_id=10, recommended_value="SECOND",
    )

    eng = CpqEngine()
    shared_sig: dict[str, tuple] = {}
    # A real, newly-active constraint that has just ruled "FIRST" out.
    new_constraint = {10: ["SECOND", "THIRD"]}

    # Call A: shared_sig starts empty -> always mismatches -> re-derives,
    # correctly dropping the now-illegal "FIRST" guess to empty (no rec
    # rule, no default_value, and no longer unconstrained -- falls to the
    # "leave empty" tier, tagged "default").
    state_a = {"cachedAttr": ["FIRST"]}
    source_a = {"cachedAttr": "default_first_available"}
    eng.auto_fill(
        [_cached_attr()], hints={},
        already_filled_multi=state_a, filled_source=source_a,
        constrained_opts=new_constraint, _default_fill_signatures=shared_sig,
        rec_rules=[_never_fires_rec],
    )
    assert state_a["cachedAttr"] == []
    assert "cachedAttr" in shared_sig

    # Call B: SAME shared_sig (now populated by call A), but a FRESH pair
    # of already_filled_multi/filled_source dicts carrying the SAME
    # original input state ("FIRST"/"default_first_available") that
    # produced the stored signature. The signature matches, so this call
    # trusts the cache and skips re-derivation -- "FIRST" survives even
    # though the identical new_constraint (still passed here) has already
    # ruled it out.
    state_b = {"cachedAttr": ["FIRST"]}
    source_b = {"cachedAttr": "default_first_available"}
    eng.auto_fill(
        [_cached_attr()], hints={},
        already_filled_multi=state_b, filled_source=source_b,
        constrained_opts=new_constraint, _default_fill_signatures=shared_sig,
    )
    assert state_b["cachedAttr"] == ["FIRST"]  # stale, no-longer-legal value kept

    # Control: identical inputs, but a FRESH (unshared) signature dict --
    # no stored entry to match, so this always re-derives and correctly
    # drops "FIRST" again.
    state_c = {"cachedAttr": ["FIRST"]}
    source_c = {"cachedAttr": "default_first_available"}
    eng.auto_fill(
        [_cached_attr()], hints={},
        already_filled_multi=state_c, filled_source=source_c,
        constrained_opts=new_constraint, _default_fill_signatures={},
        rec_rules=[_never_fires_rec],
    )
    assert state_c["cachedAttr"] == []


# ═══════════════════════════════════════════════════════════════════════
# "Cascade fill" post-pass (engine.py ~10304-10349, right after the
# pointer-default post-pass, run once after the main per-attribute loop):
# for any still-pending free-text (no-options) attr sharing a
# `_DECISION_REQUIRED_KEYS` fragment ("country"/"region") with an
# already-filled sibling, copy the sibling's value across directly. This
# is Phase 4 step 3's P3 (docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
# "FillContext Decomposition Design") -- no dedicated test previously
# pinned this specific post-pass in isolation (existing coverage of
# `auto_fill` as a whole doesn't specifically target it), added here
# before any code moves.
# ═══════════════════════════════════════════════════════════════════════

def test_cascade_fill_copies_value_from_filled_sibling_sharing_decision_key_fragment():
    """A free-text (no options), required, pending attr whose variable_name
    contains "region" cascades directly from an already-filled sibling
    whose variable_name also contains "region" -- exact value, exact
    display, source tagged "cascade"."""
    region_selector = _attr(1, "modelSelectionRegion_astro", "Region",
                             options=_menu("NA", "EMEA"), required=True)
    package_region = _attr(2, "packageRegion_astro", "Package Region", required=True)
    eng = CpqEngine()
    filled_out, display_out, pending = eng.auto_fill(
        [region_selector, package_region], hints={},
        already_filled={"modelSelectionRegion_astro": "NA"},
        filled_source={"modelSelectionRegion_astro": "user"},
    )
    assert filled_out["packageRegion_astro"] == "NA"
    assert display_out["packageRegion_astro"] == "NA"
    assert not any(a.variable_name == "packageRegion_astro" for a in pending)


def test_cascade_fill_leaves_attr_pending_when_no_matching_sibling_is_filled():
    """Same shape, but no sibling sharing the decision-key fragment is
    filled at all -- the pending free-text attr survives the post-pass
    untouched, still in `pending`, never defaulted or guessed."""
    package_region = _attr(1, "packageRegion_astro", "Package Region", required=True)
    eng = CpqEngine()
    filled_out, _display, pending = eng.auto_fill(
        [package_region], hints={}, already_filled={},
    )
    assert "packageRegion_astro" not in filled_out
    assert any(a.variable_name == "packageRegion_astro" for a in pending)


def test_cascade_fill_never_touches_a_pending_attr_that_has_real_options():
    """The post-pass's own first check (`if attr.options: still_pending;
    continue`) means an attr WITH options is never a cascade-fill
    candidate at all, even if its name matches a decision-key fragment
    and a same-fragment sibling is filled -- this pass is exclusively for
    free-text (no-options) attrs; menu-driven attrs stay exactly as the
    earlier per-attribute loop left them."""
    region_selector = _attr(1, "modelSelectionRegion_astro", "Region",
                             options=_menu("NA", "EMEA"), required=True)
    other_region_menu = _attr(2, "otherRegionChoice_astro", "Other Region Choice",
                               options=_menu("X", "Y", "Z"), required=True)
    eng = CpqEngine()
    filled_out, _display, pending = eng.auto_fill(
        [region_selector, other_region_menu], hints={},
        already_filled={"modelSelectionRegion_astro": "NA"},
        filled_source={"modelSelectionRegion_astro": "user"},
    )
    assert "otherRegionChoice_astro" not in filled_out
    assert any(a.variable_name == "otherRegionChoice_astro" for a in pending)


def test_cascade_fill_defaults_a_pending_boolean_to_false_never_via_the_generic_cascade():
    """A pending attr with `select_type == "boolean"` is special-cased
    BEFORE the decision-key-fragment match: it's always defaulted to
    "false"/"No" (source "default"), even when its own variable_name
    would otherwise match a decision-key fragment shared with a filled
    sibling -- the generic free-text cascade (which blindly copies the
    sibling's raw string) must never reach a boolean field (a live-
    confirmed contamination bug this special case exists to prevent, per
    the inline comment at this exact branch)."""
    region_selector = _attr(1, "modelSelectionRegion_astro", "Region",
                             options=_menu("NA", "EMEA"), required=True)
    is_region_locked = _attr(2, "isRegionLockedCA_astro", "Is Region Locked",
                              required=True, select_type="boolean")
    eng = CpqEngine()
    filled_out, display_out, pending = eng.auto_fill(
        [region_selector, is_region_locked], hints={},
        already_filled={"modelSelectionRegion_astro": "NA"},
        filled_source={"modelSelectionRegion_astro": "user"},
    )
    assert filled_out["isRegionLockedCA_astro"] == "false"
    assert display_out["isRegionLockedCA_astro"] == "No"
    assert not any(a.variable_name == "isRegionLockedCA_astro" for a in pending)


# ═══════════════════════════════════════════════════════════════════════
# Priority-cascade ORDER (auto_fill's own docstring, "Priority order
# (first match wins)", steps 1-6). Nothing previously pinned the ORDER
# itself -- individual tiers were each covered in isolation, so a
# mis-cut of the ladder during the upcoming `_resolve_one_attr`
# relocation/split could silently reorder two tiers with every existing
# test still green. Each test below sets up an attr for which TWO tiers
# would both produce a value, and asserts which one actually wins.
#
# Existing-coverage survey done before writing these (so none is a
# duplicate): tier 3-beats-tier-4 with options is already pinned by
# `test_auto_fill_own_recommendation_check_fires_when_condition_already_
# holds` above (rec_rules + default_value on the same attr -> "rule"),
# and tier 6's "exactly one remaining option" / "two remaining ->
# pending" pair is already pinned by `test_constraint_narrowed_to_a_
# single_legal_value_is_auto_filled_as_auto_source` /
# `test_constraint_narrowed_to_two_or_more_legal_values_stays_pending`.
# The two tests below covering those areas therefore pin the
# NOT-yet-covered halves of the same tiers (tier 3's `attr.options`
# gate; tier 6's is_decision_attr exclusion) instead of restating them.
# ═══════════════════════════════════════════════════════════════════════


def test_matching_nl_hint_beats_a_valid_xml_default_value():
    """Tier 2 (NL hint) beats tier 4 (XML default_value). The hint block
    (engine.py ~9030) runs before the default_value branch (~9182) and the
    latter is gated on `not value`, so a hint whose key FRAGMENT-matches the
    variable_name (underscores/case stripped, containment either way) and
    whose value exactly matches a real option wins outright -- the attr's
    own different default_value never gets a chance. Pins the real-world
    case of a customer explicitly naming a value the catalog's generic
    default disagrees with."""
    attr = _attr(1, "flavorChoice_astro", "Flavor Choice",
                 options=_menu("VANILLA", "CHOCOLATE"), default="VANILLA")
    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    filled_out, display_out, pending = eng.auto_fill(
        [attr], hints={"flavor": "CHOCOLATE"}, filled_source=filled_source,
    )
    assert filled_out["flavorChoice_astro"] == "CHOCOLATE"
    assert display_out["flavorChoice_astro"] == "CHOCOLATE"
    assert filled_source["flavorChoice_astro"] == "hint"
    assert pending == []


def test_satisfied_recommendation_loses_to_default_when_the_attr_has_no_options():
    """Tier 3's own gate, the not-yet-pinned half of the tier-3-beats-tier-4
    ordering (`test_auto_fill_own_recommendation_check_fires_when_condition_
    already_holds` above already pins the WITH-options case): the step-2
    recommendation check is guarded by `and attr.options` (engine.py ~9144),
    and `_satisfied_recommendation` can only ever return an option it MATCHED
    in `candidate_opts`. So for a free-text attr (no menu at all) a fully
    satisfied recommendation rule is silently skipped and the generic XML
    default_value claims the attr instead -- the exact inversion of the
    documented "targeted rule beats catalog-wide default" priority, observed
    and pinned here as-is, not fixed."""
    condition_attr = _attr(1, "conditionAttr", "Condition", options=_menu("A", "B"))
    free_text_target = _attr(2, "freeTextTarget_astro", "Free Text Target",
                             default="CATALOG_DEFAULT")
    rec = RecommendationRule(
        rule_name="recommend REC_OPT when A", condition_attr_id=1,
        condition_value="A", target_attr_id=2, recommended_value="REC_OPT",
    )
    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    filled_out, _display, _pending = eng.auto_fill(
        [condition_attr, free_text_target], hints={},
        already_filled={"conditionAttr": "A"},
        rec_rules=[rec], filled_source=filled_source,
    )
    assert filled_out["freeTextTarget_astro"] == "CATALOG_DEFAULT"
    assert filled_source["freeTextTarget_astro"] == "default"


def test_xml_default_value_beats_the_rule_governed_first_by_order_pick():
    """Tier 4 (XML default_value) beats tier 5 (rule-governed default-or-
    first). The whole tier-5/tier-6 block is entered only `if not value and
    attr.options` (engine.py ~9367), so once tier 4 has set a value from
    `default_value` the governed fallback is never reached at all -- pinned
    with a default_value that is deliberately NOT the first option by order,
    so a mis-cut ladder that ran tier 5 first would be caught by the value
    itself ("THIRD" vs "FIRST"), not just by the source tag."""
    governed_with_default = _attr(1, "governedWithDefault_astro", "Governed",
                                  options=_menu("FIRST", "SECOND", "THIRD"),
                                  default="THIRD")
    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    filled_out, display_out, pending = eng.auto_fill(
        [governed_with_default], hints={},
        governed_ids={1}, rule_governed_ids={1}, filled_source=filled_source,
    )
    assert filled_out["governedWithDefault_astro"] == "THIRD"
    assert display_out["governedWithDefault_astro"] == "THIRD"
    assert filled_source["governedWithDefault_astro"] == "default"
    assert pending == []


def test_governed_attr_is_filled_where_an_identically_shaped_ungoverned_attr_stays_pending():
    """Governance is what separates "fill it" from "ask it" for two attrs
    with an IDENTICAL shape (single-select, 3 real options, no default, not
    required, no constraint narrowing anything). Both are far from tier 6's
    "exactly one remaining option" bar, so only `governed_ids` membership
    can resolve them -- and it does, first-by-menu-order.

    Observed subtlety worth pinning before the split: the value does NOT
    come from tier 5's own first-by-order line (source == governed_source ==
    "rule"). For a NON-required attr with no default_value and no
    recommendation rule, `_no_real_fill_justification` is True, which shuts
    tier 5's blind pick off entirely; the attr falls all the way through to
    the LATE Group-2 rule-governed blind pick in the final ask-branch
    (engine.py ~10233-10305), tagged "blind_pick_rule_governed". So the
    governed/ungoverned split really lives in TWO places in this ladder, not
    one -- exactly the kind of detail a mis-cut file split could drop."""
    governed = _attr(1, "governedChoice_astro", "Governed Choice",
                     options=_menu("FIRST", "SECOND", "THIRD"))
    ungoverned = _attr(2, "plainChoice_astro", "Plain Choice",
                       options=_menu("FIRST", "SECOND", "THIRD"))
    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    filled_out, display_out, pending = eng.auto_fill(
        [governed, ungoverned], hints={},
        governed_ids={1}, rule_governed_ids={1}, filled_source=filled_source,
    )
    assert filled_out["governedChoice_astro"] == "FIRST"
    assert display_out["governedChoice_astro"] == "FIRST"
    assert filled_source["governedChoice_astro"] == "blind_pick_rule_governed"
    assert "plainChoice_astro" not in filled_out
    assert [a.variable_name for a in pending] == ["plainChoice_astro"]


def test_tier_five_first_by_order_fires_for_a_required_governed_attr_as_rule_source():
    """The other half of the test above -- the ONE shape that actually
    reaches tier 5's own first-by-order line (engine.py ~9695-9705): a
    governed attr that is `required`, which makes
    `_no_real_fill_justification` False and so unlocks the branch. Same
    inputs otherwise, but the fill is tagged with `governed_source`
    ("rule", since it's in rule_governed_ids) instead of the late
    "blind_pick_rule_governed" tag -- proof the two blind-pick sites are
    genuinely distinct code paths with distinct observable output, not
    interchangeable."""
    required_governed = _attr(1, "requiredGovernedChoice_astro", "Required Governed",
                              options=_menu("FIRST", "SECOND", "THIRD"), required=True)
    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    filled_out, _display, pending = eng.auto_fill(
        [required_governed], hints={},
        governed_ids={1}, rule_governed_ids={1}, filled_source=filled_source,
    )
    assert filled_out["requiredGovernedChoice_astro"] == "FIRST"
    assert filled_source["requiredGovernedChoice_astro"] == "rule"
    assert pending == []


def test_sole_remaining_option_shortcut_is_skipped_for_a_decision_attr():
    """Tier 6's not-yet-pinned exclusion (the fires/does-not-fire pair on
    option COUNT is already pinned by the two `test_constraint_narrowed_
    to_*` tests above): the `len(valid_opts) == 1` shortcut carries `and not
    is_decision_attr` (engine.py ~9399), so a decision-required attr
    (country/region fragment, hardware version, product, "selectmodel",
    "basemodel") narrowed by a real constraint to EXACTLY ONE legal option is
    still asked rather than auto-filled -- a constraint script can resolve a
    value with no literal menu match, making "exactly 1" a false positive.
    An otherwise identical non-decision attr in the same call, narrowed the
    same way, IS auto-filled -- the contrast is the point."""
    decision_attr = _attr(1, "modelSelectionRegion_astro", "Region",
                          options=_menu("NA", "EMEA"))
    plain_attr = _attr(2, "someChoice_astro", "Some Choice",
                       options=_menu("NA", "EMEA"))
    eng = CpqEngine()
    filled_out, _display, pending = eng.auto_fill(
        [decision_attr, plain_attr], hints={},
        constrained_opts={1: ["EMEA"], 2: ["EMEA"]},
    )
    assert "modelSelectionRegion_astro" not in filled_out
    assert [a.variable_name for a in pending] == ["modelSelectionRegion_astro"]
    assert filled_out["someChoice_astro"] == "EMEA"


def test_hidden_attr_takes_its_default_and_never_consults_a_matching_nl_hint():
    """The `attr.hidden` early-return (engine.py ~9009) sits ABOVE the
    entire cascade, including tier 2's hint block -- so a hidden attr gets
    ONLY its own XML default_value even when an NL hint fragment-matches its
    variable_name and names a different real option. Verified against the
    code, not assumed: the hidden branch's own comment says "never asked,
    never NL-hint-matched, never blind-first-picked", and it `return`s
    before `vn_flat`/the hints loop is ever reached. A hidden attr with a
    matching hint and NO default is left out of `filled` entirely, and
    neither hidden attr ever reaches `pending`. Complements
    `test_auto_fill_takes_the_hidden_flag_as_a_fixed_input_never_re_derives_
    it` above, which pins the same branch without any hints in play."""
    hidden_with_default = ConfigAttr(
        entity_id=1, variable_name="hiddenFlavorChoice", display_label="Hidden Flavor",
        required=False, default_value="VANILLA",
        options=_menu("VANILLA", "CHOCOLATE"), hidden=True,
    )
    hidden_without_default = ConfigAttr(
        entity_id=2, variable_name="hiddenFlavorOther", display_label="Hidden Flavor 2",
        required=False, default_value="",
        options=_menu("VANILLA", "CHOCOLATE"), hidden=True,
    )
    eng = CpqEngine()
    filled_source: dict[str, str] = {}
    filled_out, display_out, pending = eng.auto_fill(
        [hidden_with_default, hidden_without_default],
        hints={"flavor": "CHOCOLATE"}, filled_source=filled_source,
    )
    assert filled_out["hiddenFlavorChoice"] == "VANILLA"
    assert display_out["hiddenFlavorChoice"] == "VANILLA"
    assert filled_source["hiddenFlavorChoice"] == "default"
    assert "hiddenFlavorOther" not in filled_out
    assert pending == []


def test_constrained_ambiguous_optional_multi_select_defaults_to_empty_not_all():
    """The multi-select overselection guard (engine.py ~9815-10053) through
    the tier-precedence lens: an optional multi-select narrowed by a real
    constraint to SEVERAL (2 of 3) remaining options, with no satisfied
    recommendation and no default_value among them, resolves to an EMPTY
    list -- never to "all currently-legal options" (the original live bug:
    a near-universally-true constraint narrowing a menu to 9 of 11 is a
    MENU, not a recommendation to select all 9).

    Two observed preconditions this pins alongside the guard itself, both
    load-bearing for the branch to be reached at all: (a) the attr needs
    SOME fill justification (`_no_real_fill_justification` False -- here a
    real RecommendationRule targets it, whose condition never holds), else
    it skips every multi branch and simply lands in `pending`; (b) the
    empty list is written to the caller's `already_filled_multi` dict IN
    PLACE, tagged source "default", and the attr does NOT appear in
    `pending` -- the empty selection is treated as a settled answer.
    Distinct from `test_shared_default_fill_signature_cache_can_serve_a_
    stale_re_derivation` above, which reaches the same outcome only via
    re-validation of an ALREADY-filled guess; this one starts from nothing
    filled."""
    ambiguous_multi = _attr(10, "multiChoice_astro", "Multi Choice",
                            select_type="multi",
                            options=_menu("FIRST", "SECOND", "THIRD"))
    never_fires_rec = RecommendationRule(
        rule_name="never fires", condition_attr_id=999,
        condition_value="NEVER", target_attr_id=10, recommended_value="SECOND",
    )
    eng = CpqEngine()
    filled_multi: dict[str, list[str]] = {}
    filled_source: dict[str, str] = {}
    _filled, display_out, pending = eng.auto_fill(
        [ambiguous_multi], hints={},
        constrained_opts={10: ["SECOND", "THIRD"]},
        already_filled_multi=filled_multi, filled_source=filled_source,
        rec_rules=[never_fires_rec],
    )
    assert filled_multi == {"multiChoice_astro": []}
    assert display_out["multiChoice_astro"] == "(none)"
    assert filled_source["multiChoice_astro"] == "default"
    assert pending == []


def test_rule_governed_attr_whose_every_option_is_a_none_sentinel_lands_in_pending():
    """One of the two `pending.append(attr)` sites inside `_resolve_one_attr`
    that no existing test in this file exercised: the Group-2 rule-governed
    blind pick's own `else` (engine.py ~10304-10305). A rule-governed
    single-select attr with no default_value normally gets first-by-order
    blind-picked there, but when EVERY menu option is a `_NONE_VALUES`
    sentinel ("NONE", "N/A") `_valid` filters them all out, `_rg_opts` is
    empty, and the attr falls to `pending` rather than being silently
    dropped ("never silently drop the attr", per that branch's own comment)
    -- note it is asked even though there is nothing real to offer."""
    sentinel_only = _attr(1, "sentinelGovernedChoice_astro", "Sentinel Governed",
                          options=_menu("NONE", "N/A"))
    eng = CpqEngine()
    filled_out, _display, pending = eng.auto_fill(
        [sentinel_only], hints={}, governed_ids={1}, rule_governed_ids={1},
    )
    assert "sentinelGovernedChoice_astro" not in filled_out
    assert [a.variable_name for a in pending] == ["sentinelGovernedChoice_astro"]


def test_dt_governed_attr_whose_every_option_is_a_none_sentinel_lands_in_pending(
    monkeypatch,
):
    """The other previously-unexercised `pending.append(attr)` site: the
    `_dt_governed_vns` blind-pick's own `else` (engine.py ~10231-10232),
    checked BEFORE the rule-governed Group-2 branch above. Same setup as
    `test_dt_governed_attr_blind_picks_first_option_vs_never_governed_attr_
    stays_pending` (a real ingested attrSequence row confirming this attr
    governs the current base model), but every menu option is a
    `_NONE_VALUES` sentinel, so `_blind_opts` is empty and the attr is asked
    instead of blind-picked. Pins that the data-table branch's empty-options
    escape hatch exists and behaves like the rule-governed one -- both must
    survive the split as separate sites, since they tag their successful
    fills differently ("blind_pick_governed" vs
    "blind_pick_rule_governed")."""
    monkeypatch.setattr(
        data_table_loader, "get_cpq_rdb",
        lambda: _FakeSequenceRdb([
            {"CPQModel": "APXNEXT", "BaseModel": "BM1",
             "AttrName": "dtGovernedSentinel_astro", "Seq": "1"},
        ]),
    )
    base_model_attr = _attr(1, "modelSelectionbaseModel_astro", "Base Model")
    product_attr = _attr(2, "productSelectionProduct_all", "Product")
    dt_governed_sentinel = _attr(3, "dtGovernedSentinel_astro", "DT Governed Sentinel",
                                 options=_menu("NONE", "N/A"))
    eng = CpqEngine()
    filled_out, _display, pending = eng.auto_fill(
        [base_model_attr, product_attr, dt_governed_sentinel], hints={},
        already_filled={
            "modelSelectionbaseModel_astro": "BM1",
            "productSelectionProduct_all": "SOME UNMAPPED PRODUCT",
        },
        workspace_id=7,
    )
    assert "dtGovernedSentinel_astro" not in filled_out
    assert "dtGovernedSentinel_astro" in [a.variable_name for a in pending]
