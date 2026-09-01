"""SVX Mounting Type (Array): the customer needs to be able to add SEVERAL
mount rows across turns, not just the first one they name.

Live-observed gap, 2026-08-25: replying "Shirt Magnetic Mount" to the
narrowed "Mounting Type (Array) — choose one: 1..6" prompt got its
quantity asked, then the configuration was declared COMPLETE — the other
4-5 still-legal, still-unpicked mounting types were never offered again.
For a model narrowed to only 2 legal mounts, the customer could never
provide the second one at all without re-triggering the question some
other way.

Root cause: `auto_fill`'s per-attr loop treated ANY non-empty
`filled_multi[vn]` as "fully answered" for every select_type=="multi"
attr, including grid selectors (resolve_array_grid_links' own structural
signal — a menu-backed multi-select attr whose options link to hidden
per-row *Quantity* companion attrs). Fix: a grid selector with 1+ picks
stays in `pending` as long as any currently-valid (constraint/rec-rule-
narrowed) option remains unpicked, until either every valid option is
picked or the customer explicitly declines further rows.

Structural, not hardcoded: gated only on `resolve_array_grid_links`'
existing detection (a real hidden *Quantity* companion attr) and
`constrained_opts`/`filled_multi` state -- no attribute name, catalog
name, or regex anywhere in the new code. Proven generic below via a
second, differently-named "APX Next"-shaped fixture, and proven inert for
an ordinary (non-grid) optional multi-select with no quantity companion.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _svx_mount_attr(*options: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi", options=_menu(*options),
    )


def _svx_qty_attrs() -> list[ConfigAttr]:
    """Hidden *Quantity*-named companions -- resolve_array_grid_links'
    real, structural grid-selector signal (same mechanism
    test_cpq_grid_decline.py's `_qty_attr` uses)."""
    names = [
        "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
        "Jacket Clip Mount", "Locking Molle Mount", "TEK-LOK Belt Mount",
    ]
    return [
        ConfigAttr(
            entity_id=100 + i, variable_name=f"mountingType{n.replace(' ', '')}Quantity_viSoln",
            display_label=f"{n} Quantity", required=False, default_value="",
            select_type="single", options=[], hidden=True,
        )
        for i, n in enumerate(names)
    ]


def _apx_item_type_attr(*options: str) -> ConfigAttr:
    """A completely differently-named grid selector -- proves the fix is
    not SVX/Mounting-Type-specific."""
    return ConfigAttr(
        entity_id=1, variable_name="itemTypeVX650_astro", display_label="VX650 Item Type",
        required=False, default_value="", select_type="multi", options=_menu(*options),
    )


def _apx_qty_attrs(*options: str) -> list[ConfigAttr]:
    return [
        ConfigAttr(
            entity_id=200 + i, variable_name=f"quantity{opt.replace(' ', '')}VX650ItemType_astro",
            display_label=f"{opt} Quantity", required=False, default_value="",
            select_type="single", options=[], hidden=True,
        )
        for i, opt in enumerate(options)
    ]


class TestGridSelectorRemainingOptions:
    def test_no_picks_yet_all_options_remain(self):
        attr = _svx_mount_attr(
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount")
        remaining = CpqEngine.grid_selector_remaining_options(attr, {}, None)
        assert {o.item_value for o in remaining} == {
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount"}

    def test_picked_options_are_excluded(self):
        attr = _svx_mount_attr(
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount")
        filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]}
        remaining = CpqEngine.grid_selector_remaining_options(attr, filled_multi, None)
        assert {o.item_value for o in remaining} == {"Jacket Magnetic Mount", "Shirt Clip Mount"}

    def test_narrowed_constraint_set_respected(self):
        """A model constrained to only 2 legal options must show exactly
        those 2 as remaining, even though the catalog carries 6."""
        attr = _svx_mount_attr(*[
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
            "Jacket Clip Mount", "Locking Molle Mount", "TEK-LOK Belt Mount",
        ])
        constrained_opts = {1: ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
        remaining = CpqEngine.grid_selector_remaining_options(attr, {}, constrained_opts)
        assert {o.item_value for o in remaining} == {"Shirt Magnetic Mount", "Jacket Magnetic Mount"}

    def test_fully_picked_narrowed_set_leaves_nothing_remaining(self):
        attr = _svx_mount_attr("Shirt Magnetic Mount", "Jacket Magnetic Mount")
        constrained_opts = {1: ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
        filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
        remaining = CpqEngine.grid_selector_remaining_options(attr, filled_multi, constrained_opts)
        assert remaining == []


class TestAutoFillReAsksGridSelector:
    def test_one_pick_of_six_stays_pending_for_the_rest(self):
        attr = _svx_mount_attr(*[
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
            "Jacket Clip Mount", "Locking Molle Mount", "TEK-LOK Belt Mount",
        ])
        attrs = [attr, *_svx_qty_attrs()]
        engine = CpqEngine()
        filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]}
        sources = {"mountingTypeArray_viSoln": "user"}

        _filled, _display, pending = engine.auto_fill(
            attrs, hints={}, already_filled_multi=filled_multi, filled_source=sources)

        assert "mountingTypeArray_viSoln" in [a.variable_name for a in pending], (
            "5 more legal mounting types remain unpicked -- must stay pending"
        )
        assert filled_multi["mountingTypeArray_viSoln"] == ["Shirt Magnetic Mount"], (
            "the existing pick must survive untouched"
        )

    def test_two_option_model_stays_pending_after_first_pick(self):
        """The user's own reported case: a model narrowed to only 2 legal
        mounts must still offer the second one after the first is picked."""
        attr = _svx_mount_attr("Shirt Magnetic Mount", "Jacket Magnetic Mount")
        attrs = [attr, *_svx_qty_attrs()]
        engine = CpqEngine()
        constrained_opts = {1: ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
        filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]}
        sources = {"mountingTypeArray_viSoln": "user"}

        _filled, _display, pending = engine.auto_fill(
            attrs, hints={}, already_filled_multi=filled_multi, filled_source=sources,
            constrained_opts=constrained_opts)

        assert [a.variable_name for a in pending] == ["mountingTypeArray_viSoln"]

    def test_settles_once_every_narrowed_option_is_picked(self):
        attr = _svx_mount_attr("Shirt Magnetic Mount", "Jacket Magnetic Mount")
        attrs = [attr, *_svx_qty_attrs()]
        engine = CpqEngine()
        constrained_opts = {1: ["Shirt Magnetic Mount", "Jacket Magnetic Mount"]}
        filled_multi = {
            "mountingTypeArray_viSoln": ["Shirt Magnetic Mount", "Jacket Magnetic Mount"],
        }
        sources = {"mountingTypeArray_viSoln": "user"}

        _filled, _display, pending = engine.auto_fill(
            attrs, hints={}, already_filled_multi=filled_multi, filled_source=sources,
            constrained_opts=constrained_opts)

        assert "mountingTypeArray_viSoln" not in [a.variable_name for a in pending], (
            "every legal option is already picked -- must settle, not loop forever"
        )

    def test_explicit_decline_overrides_remaining_options(self):
        """grid_declined_vns is the customer's own escape hatch -- once
        set, stop re-asking even though options remain unpicked."""
        attr = _svx_mount_attr(*[
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
        ])
        attrs = [attr, *_svx_qty_attrs()]
        engine = CpqEngine()
        filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]}
        sources = {"mountingTypeArray_viSoln": "user"}

        _filled, _display, pending = engine.auto_fill(
            attrs, hints={}, already_filled_multi=filled_multi, filled_source=sources,
            grid_declined_vns=frozenset({"mountingTypeArray_viSoln"}))

        assert "mountingTypeArray_viSoln" not in [a.variable_name for a in pending]

    def test_grid_declined_vns_is_a_no_op_by_default(self):
        """Every pre-existing caller (doesn't pass this param) is unaffected."""
        attr = _svx_mount_attr("Shirt Magnetic Mount", "Jacket Magnetic Mount")
        attrs = [attr, *_svx_qty_attrs()]
        engine = CpqEngine()
        filled_multi = {"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]}
        sources = {"mountingTypeArray_viSoln": "user"}

        _filled, _display, pending = engine.auto_fill(
            attrs, hints={}, already_filled_multi=filled_multi, filled_source=sources)

        assert [a.variable_name for a in pending] == ["mountingTypeArray_viSoln"]

    def test_generic_across_a_completely_different_catalog_shape(self):
        """APX Next's itemTypeVX650_astro/quantity*VX650ItemType_astro --
        proves the mechanism isn't keyed to SVX/mounting-type names at all."""
        attr = _apx_item_type_attr("Battery Pack", "Solar Panel", "Charging Cable")
        attrs = [attr, *_apx_qty_attrs("Battery Pack", "Solar Panel", "Charging Cable")]
        engine = CpqEngine()
        filled_multi = {"itemTypeVX650_astro": ["Battery Pack"]}
        sources = {"itemTypeVX650_astro": "user"}

        _filled, _display, pending = engine.auto_fill(
            attrs, hints={}, already_filled_multi=filled_multi, filled_source=sources)

        assert [a.variable_name for a in pending] == ["itemTypeVX650_astro"], (
            "the SAME structural mechanism must re-ask for APX Next's own "
            "grid selector, using zero SVX-specific code"
        )

    def test_ordinary_multi_select_without_quantity_companion_is_unaffected(self):
        """A ManageEngine-style plain optional multi-select with NO hidden
        *Quantity* companion is not a grid selector at all -- must keep
        today's behavior (settle immediately, never re-pend) untouched."""
        attr = ConfigAttr(
            entity_id=1, variable_name="ordinaryFeatureFlags_astro",
            display_label="Feature Flags", required=False, default_value="",
            select_type="multi", options=_menu("Flag A", "Flag B", "Flag C"),
        )
        engine = CpqEngine()
        filled_multi = {"ordinaryFeatureFlags_astro": ["Flag A"]}
        sources = {"ordinaryFeatureFlags_astro": "user"}

        _filled, _display, pending = engine.auto_fill(
            [attr], hints={}, already_filled_multi=filled_multi, filled_source=sources)

        assert pending == [], (
            "a non-grid multi-select must settle after any pick, exactly as before"
        )
        assert filled_multi["ordinaryFeatureFlags_astro"] == ["Flag A"]


class TestNextQuestionPromptAlreadySelected:
    def test_already_selected_options_are_excluded_from_the_reask(self):
        attr = _svx_mount_attr(
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount")
        attrs = [attr, *_svx_qty_attrs()]
        engine = CpqEngine()
        prompt = engine.next_question_prompt(
            attr, constrained_item_values=None,
            already_selected=["Shirt Magnetic Mount"], attrs=attrs,
        )
        assert "Jacket Magnetic Mount" in prompt
        assert "Shirt Clip Mount" in prompt
        assert "1. Shirt Magnetic Mount" not in prompt

    def test_multi_select_phrasing_invites_more_than_one_for_a_real_grid_selector(self):
        attr = _svx_mount_attr("Shirt Magnetic Mount", "Jacket Magnetic Mount")
        attrs = [attr, *_svx_qty_attrs()]
        engine = CpqEngine()
        prompt = engine.next_question_prompt(attr, attrs=attrs)
        assert "choose one" in prompt.lower()
        assert "more" in prompt.lower()

    def test_already_selected_is_a_no_op_by_default(self):
        """Every pre-existing caller (doesn't pass this param) sees the
        exact same option list as before."""
        attr = _svx_mount_attr("Shirt Magnetic Mount", "Jacket Magnetic Mount")
        attrs = [attr, *_svx_qty_attrs()]
        engine = CpqEngine()
        prompt = engine.next_question_prompt(attr, attrs=attrs)
        assert "1. Shirt Magnetic Mount" in prompt
        assert "2. Jacket Magnetic Mount" in prompt

    def test_plain_multi_select_without_attrs_context_keeps_original_phrasing(self):
        """Raven review, PR #277 (medium): a caller that doesn't pass
        `attrs` at all can't be structurally confirmed as a grid selector
        -- must fall back to the plain, pre-existing "choose one:" text
        rather than guessing."""
        attr = _svx_mount_attr("Shirt Magnetic Mount", "Jacket Magnetic Mount")
        engine = CpqEngine()
        prompt = engine.next_question_prompt(attr)
        assert "choose one:" in prompt.lower()
        assert "or more" not in prompt.lower()

    def test_ordinary_multi_select_keeps_plain_choose_one_phrasing(self):
        """Raven review, PR #277 (medium): the grid phrasing must be
        gated on the STRUCTURAL signal (resolve_array_grid_links), not
        merely select_type=="multi" -- an ordinary multi-select with no
        hidden *Quantity companion, even when `attrs` IS supplied, must
        keep the original "choose one:" text, not the grid wording."""
        attr = ConfigAttr(
            entity_id=1, variable_name="ordinaryFeatureFlags_astro",
            display_label="Feature Flags", required=False, default_value="",
            select_type="multi", options=_menu("Flag A", "Flag B", "Flag C"),
        )
        engine = CpqEngine()
        prompt = engine.next_question_prompt(attr, attrs=[attr])
        assert "choose one:" in prompt.lower()
        assert "or more" not in prompt.lower()
