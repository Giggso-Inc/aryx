"""The ingested country -> region table is used by default; the built-in list stays the fallback (review N1)."""
from __future__ import annotations

from unittest.mock import patch

from aryx.config import Settings
from aryx.cpq.governance_and_sibling_exclusivity import region as region_mod
from aryx.cpq.state import ConfigAttr, MenuOption


def _region_attr(*codes):
    return ConfigAttr(
        entity_id=1, variable_name="modelSelectionRegion_astro", display_label="Region", required=False,
        default_value="", options=[MenuOption(item_value=c, display_name=c, order=1) for c in codes],
    )


def test_the_flag_defaults_to_on_so_no_per_table_switch_is_needed():
    assert Settings.model_fields["cpq_country_region_table_enabled"].default is True


def test_with_the_default_settings_a_missing_table_row_falls_back_to_the_built_in_list():
    attr = _region_attr("NA", "EA", "LA")
    with patch.object(region_mod, "resolve_country_region", return_value=None) as table:
        assert region_mod.derive_region("canada", attr, 7)[0] == "NA"        # table asked first, had no row: the constant
        table.assert_called_once()


def test_with_the_default_settings_a_table_row_wins_over_the_built_in_list():
    attr = _region_attr("NA", "EA", "LA")
    with patch.object(region_mod, "resolve_country_region", return_value="LA"):
        assert region_mod.derive_region("canada", attr, 7)[0] == "LA"
