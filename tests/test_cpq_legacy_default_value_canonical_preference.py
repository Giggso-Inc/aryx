"""Issue 5 root cause 3 (docs/config_consistency_issues_2026-07-30.md):
auto_fill's default_value step must prefer a same-display-name canonical
option over a legacy bare "YES"/"NO" option when the catalog's raw
default_value happens to be the deprecated boolean-era spelling.

Real incident: baselineReleaseSW_astro carries both a legacy pair
("YES"->"Baseline Release", "NO"->"Latest Release") and the current
canonical pair ("BASELINE RELEASE"->"Baseline Release",
"LATEST RELEASE"->"Latest Release"). The catalog's default_value is the
legacy "YES", so every default order shipped the deprecated spelling
instead of the canonical one a validated reference payload used. Generic
fix: no attribute names are hardcoded — this fires whenever a picked
default_value is a bare boolean literal AND a differently-spelled sibling
option shares its exact display_name.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def test_prefers_canonical_option_over_legacy_boolean_default():
    attr = ConfigAttr(
        entity_id=1, variable_name="baselineReleaseSW_astro",
        display_label="Baseline Release SW", required=False,
        default_value="YES", select_type="single",
        options=[
            MenuOption(item_value="YES", display_name="Baseline Release", order=1),
            MenuOption(item_value="NO", display_name="Latest Release", order=2),
            MenuOption(item_value="BASELINE RELEASE", display_name="Baseline Release", order=3),
            MenuOption(item_value="LATEST RELEASE", display_name="Latest Release", order=4),
        ],
    )
    eng = CpqEngine()
    filled, display_filled, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={1}, rule_governed_ids={1},
    )
    assert filled.get("baselineReleaseSW_astro") == "BASELINE RELEASE"
    assert display_filled.get("baselineReleaseSW_astro") == "Baseline Release"


def test_no_canonical_sibling_leaves_legacy_value_untouched():
    """Only acts when a genuine same-display-name sibling exists — never
    invents a value the catalog doesn't actually offer."""
    attr = ConfigAttr(
        entity_id=1, variable_name="someFlag_astro", display_label="Some Flag",
        required=False, default_value="YES", select_type="single",
        options=[
            MenuOption(item_value="YES", display_name="Enabled", order=1),
            MenuOption(item_value="NO", display_name="Disabled", order=2),
        ],
    )
    eng = CpqEngine()
    filled, display_filled, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={1}, rule_governed_ids={1},
    )
    assert filled.get("someFlag_astro") == "YES"


def test_non_boolean_default_value_is_unaffected():
    attr = ConfigAttr(
        entity_id=1, variable_name="regularAttr_astro", display_label="Regular Attr",
        required=False, default_value="GOLD", select_type="single",
        options=[
            MenuOption(item_value="GOLD", display_name="Gold", order=1),
            MenuOption(item_value="SILVER", display_name="Silver", order=2),
        ],
    )
    eng = CpqEngine()
    filled, display_filled, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={1}, rule_governed_ids={1},
    )
    assert filled.get("regularAttr_astro") == "GOLD"
