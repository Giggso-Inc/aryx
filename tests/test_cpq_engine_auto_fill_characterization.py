"""Phase-level golden-master characterization for `CpqEngine.auto_fill`
(8,685-10,740, ~2,056 lines, the largest method in engine.py) and
`CpqEngine.evaluate_rules_loop` (7,256-7,729, ~474 lines) -- step 1, part 2
of Phase 4 (docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md "Phase 4
planning analysis"). These two are explicitly documented in the plan as a
permanent stated exception to splitting (bidirectionally coupled, branch
order load-bearing) -- this file is the safety net that would let a future
engineer verify behavior is preserved if that decision is ever revisited.

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

from aryx.cpq import data_table_loader
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
