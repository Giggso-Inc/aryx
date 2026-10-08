"""A Defaultinattr default breaks a tie the Whitelist leaves (flag `cpq_defaultinattr_resolves_ambiguity_enabled`).

ws 1267, APX 900: antenna type, carry type, package type and hazardous location were AMBIGUOUS_DISCARDED on every pass
(the Whitelist allows several values) and fell to a first-option guess, although Defaultinattr names the real default
for the resolved base model (Whip (Standard), 2.0 inch / 5.08 cm (Standard), Bulk, N/A). A guessed battery (2900 mAh)
then forced hazardous to TIA-4950 (UL) through the Whitelist."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.data_table_bridge import conflicts as conf
from aryx.cpq.state import MenuOption

ANT = "antennasType_astro"
HAZ = "modelSelectionHazardousLocation_astro"
BAT = "batteryType_astro"


def _opts(*values):
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _resolve(vn, options, legal_by_candidate, default, shape=True, ties=True, filled=None):
    """Run `_resolve_via_data_tables` with the data layer faked: `legal_by_candidate` is the Whitelist answer per
    candidate model (None = no rows), `default` the Defaultinattr default of the base model."""
    settings = SimpleNamespace(cpq_defaultinattr_shape_enabled=shape, cpq_defaultinattr_resolves_ambiguity_enabled=ties)
    models = list(legal_by_candidate)
    with patch.object(conf, "get_settings", return_value=settings), \
            patch.object(conf, "resolve_base_model_vn", return_value="base_vn"), \
            patch.object(conf, "_cpq_model_candidates", return_value=tuple(models)), \
            patch.object(conf, "_without_generic_non_primary", side_effect=lambda cands: cands), \
            patch.object(conf, "dt_resolve_whitelist_values",
                         side_effect=lambda cpq_model, *a, **k: legal_by_candidate[cpq_model]), \
            patch.object(conf, "resolve_defaultinattr_value", return_value=default), \
            patch.object(conf, "_log_lookup"):
        return conf._resolve_via_data_tables(vn, filled or {"base_vn": "H92WCH9PW7AN"}, options, 1267, "p", {})


def test_today_the_default_is_ignored_when_the_whitelist_leaves_several_values():
    got = _resolve(ANT, _opts("WHIP (STANDARD)", "STUBBY", "NO ANTENNA"),
                   {"APX900": ["WHIP (STANDARD)", "STUBBY", "NO ANTENNA"]}, "WHIP (STANDARD)", ties=False)
    assert got is None                                              # AMBIGUOUS_DISCARDED -> first-option guess later


def test_with_the_flag_the_default_among_the_legal_values_wins():
    got = _resolve(ANT, _opts("STUBBY", "WHIP (STANDARD)", "NO ANTENNA"),
                   {"APX900": ["WHIP (STANDARD)", "STUBBY", "NO ANTENNA"]}, "WHIP (STANDARD)")
    assert got is not None and got.item_value == "WHIP (STANDARD)"


def test_the_match_ignores_case_and_spacing():
    got = _resolve(HAZ, _opts("TIA4950(UL)", "N/A"), {"APX900": ["n/a ", "TIA4950(UL)"]}, "N/A")
    assert got is not None and got.item_value == "N/A"


def test_a_default_outside_the_legal_values_is_not_used():
    assert _resolve(ANT, _opts("STUBBY", "NO ANTENNA", "WHIP (STANDARD)"),
                    {"APX900": ["STUBBY", "NO ANTENNA"]}, "WHIP (STANDARD)") is None


def test_a_default_that_is_not_a_real_option_is_not_used():
    assert _resolve(ANT, _opts("STUBBY", "NO ANTENNA"), {"APX900": ["WHIP (STANDARD)", "STUBBY"]}, "WHIP (STANDARD)") is None


def test_a_single_legal_value_and_an_empty_legal_set_behave_as_before():
    single = _resolve(ANT, _opts("STUBBY", "WHIP (STANDARD)"), {"APX900": ["STUBBY"]}, "WHIP (STANDARD)")
    assert single is not None and single.item_value == "STUBBY"      # the Whitelist's one value, not the default
    assert _resolve(ANT, _opts("STUBBY", "WHIP (STANDARD)"), {"APX900": []}, "WHIP (STANDARD)") is None


def test_both_flags_are_needed_and_no_default_row_means_no_change():
    legal = {"APX900": ["WHIP (STANDARD)", "STUBBY"]}
    options = _opts("WHIP (STANDARD)", "STUBBY")
    assert _resolve(ANT, options, legal, "WHIP (STANDARD)", shape=False, ties=True) is None
    assert _resolve(ANT, options, legal, "WHIP (STANDARD)", shape=True, ties=False) is None
    assert _resolve(ANT, options, legal, None) is None


def test_an_attribute_without_whitelist_rows_still_takes_the_default_the_old_way():
    got = _resolve(ANT, _opts("WHIP (STANDARD)", "STUBBY"), {"APX900": None}, "WHIP (STANDARD)", ties=False)
    assert got is not None and got.item_value == "WHIP (STANDARD)"   # existing behaviour, flag-independent


def test_hazardous_is_decided_by_its_default_before_a_battery_guess_can_force_it():
    """The loop seen in the log: a guessed battery (2900 mAh) narrowed hazardous to TIA-4950 (UL). With the default,
    hazardous is N/A first, and the battery's legal values (asked of the Whitelist next) are the five N/A allows."""
    first = _resolve(HAZ, _opts("TIA4950(UL)", "N/A"), {"APX900": ["TIA4950(UL)", "N/A"]}, "N/A")
    assert first is not None and first.item_value == "N/A"
    battery_legal = ["LI-ION 2100 MAH (STANDARD)", "LI-ION 2800 MAH", "LI-ION 3000 MAH", "LI-ION 3000 MAH (STANDARD)", "NO BATTERY"]
    # no default row for the battery: still ambiguous, so it is not resolved here (and 2900 mAh is not among the legal values)
    assert _resolve(BAT, _opts(*battery_legal, "LI-ION 2900 MAH"), {"APX900": battery_legal}, None) is None
    assert "LI-ION 2900 MAH" not in battery_legal


def test_the_default_must_be_legal_under_every_ambiguous_candidate():
    options = _opts("WHIP (STANDARD)", "STUBBY", "NO ANTENNA")
    both = {"M1": ["WHIP (STANDARD)", "STUBBY"], "M2": ["whip (standard)", "NO ANTENNA"]}
    assert _resolve(ANT, options, both, "WHIP (STANDARD)").item_value == "WHIP (STANDARD)"
    narrower = {"M1": ["WHIP (STANDARD)", "STUBBY"], "M2": ["STUBBY", "NO ANTENNA"]}
    assert _resolve(ANT, options, narrower, "WHIP (STANDARD)") is None      # M2's Whitelist excludes the default


def test_a_candidate_with_nothing_legal_vetoes_the_tie_break():
    options = _opts("WHIP (STANDARD)", "STUBBY")
    assert _resolve(ANT, options, {"M1": ["WHIP (STANDARD)", "STUBBY"], "M2": []}, "WHIP (STANDARD)") is None


def test_a_non_string_default_does_not_raise():
    assert _resolve(ANT, _opts("1", "2"), {"M1": ["1", "2"]}, 1).item_value == "1"
