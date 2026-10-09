"""A base model that owns the model's default configuration is derived when the Whitelist leaves 2+ (flag
`cpq_derive_base_model_default_owner_enabled`).

ws 281 / 1267, APX N70: three base models (VHF, 700/800 MHz, UHF) whose Whitelist rows each list every band, so a known
band narrows nothing and "country only" left the base model unknown (flashcode digits asked). The Defaultinattr rows
of the 700/800 MHz base model define 32 defaults (the band among them), the VHF and UHF ones 3 and 5."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq import base_model_defaults as bmd
from aryx.cpq import derive_base_model_default_owner as owner_mod
from aryx.cpq.data_table import data_table_derive_base_model as derive

BAND, KEYPAD, ANT, COUNTRY = ("modelSelectionFrequencyBands_astro", "modelSelectionKeypadType_astro",
                              "antennasType_astro", "ultimateDestinationCountry")
K, U, X = "H35KET9PW8AN", "H35UCT9PW8AN", "H35XDT9PW8AN"


def _wl(bm, attr, val):
    return {"CPQModel": "APXN70", "BaseModel": bm, "attr1": attr, "val1": val}


ROWS = [_wl(bm, BAND, band) for bm in (K, U, X) for band in ("VHF", "700/800 MHZ", "UHF")] + \
       [_wl(bm, COUNTRY, "US") for bm in (K, U, X)]


def _di(bm, **pairs):
    row = {"BaseModel": bm}
    for i, (attr, val) in enumerate(pairs.items(), start=1):
        row[f"attr{i}"], row[f"val{i}"] = attr, val
    return row


DEFAULTS = [_di(U, **{BAND: "700/800 MHZ", KEYPAD: "LIMITED KEYPAD", ANT: "STUBBY", "a_x": "1"}),
            _di(K, **{KEYPAD: "LIMITED KEYPAD", ANT: "WHIP"}), _di(X, **{KEYPAD: "LIMITED KEYPAD"})]


def _owner(filled=None, customer=(), rows=ROWS, defaults=DEFAULTS, flag=True):
    settings = SimpleNamespace(cpq_derive_base_model_default_owner_enabled=flag,
                               cpq_derive_discriminators_first_enabled=False)
    with patch.object(derive, "get_settings", return_value=settings), \
            patch.object(owner_mod, "get_settings", return_value=settings), \
            patch.object(derive, "_model_rows", return_value=rows), \
            patch.object(bmd, "_load_defaultinattr_rows", return_value=defaults):
        return owner_mod.default_owner_base_model("APXN70", {COUNTRY: "US", **(filled or {})}, 1, "p", {},
                                                  frozenset(), frozenset(customer))


def test_the_base_model_defining_the_most_defaults_is_derived():
    assert _owner() == U


def test_flag_off_derives_nothing():
    assert _owner(flag=False) is None


def test_a_customer_value_that_differs_from_its_default_blocks_it():
    """A customer who asked for another band must not be given the default band's base model."""
    assert _owner({BAND: "VHF"}, customer={BAND}) is None


def test_a_customer_value_equal_to_its_default_keeps_it():
    assert _owner({BAND: "700/800 MHz"}, customer={BAND}) == U


def test_an_engine_pick_that_differs_does_not_block_it():
    assert _owner({BAND: "VHF"}, customer=()) == U


def test_a_base_model_without_defaultinattr_rows_means_no_evidence():
    assert _owner(defaults=DEFAULTS[:2]) is None


def test_no_strict_superset_means_no_derivation():
    tied = [_di(U, **{KEYPAD: "LIMITED KEYPAD", ANT: "STUBBY"}), _di(K, **{KEYPAD: "LIMITED KEYPAD", BAND: "VHF"}),
            _di(X, **{KEYPAD: "LIMITED KEYPAD", ANT: "WHIP"})]
    assert _owner(defaults=tied) is None


def test_own_defaults_exclude_all_rows_and_are_cached():
    cache: dict = {}
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=DEFAULTS + [_di("ALL", **{"z_x": "9"})]) as load:
        first = bmd.base_model_own_defaults(U.lower(), 1, "p", cache)
        assert bmd.base_model_own_defaults(U, 1, "p", cache) is first
    assert set(first) == {BAND, KEYPAD, ANT, "a_x"} and load.call_count == 1


# --- review of #488 --------------------------------------------------------------------------------------------------
def _apx900_rows():
    """The APX 900 shape (#473): every base model holds ONE frequency band and ONE keypad type."""
    rows = []
    for bm, band, keypad in (("A", "700/800 MHZ", "FULL KEYPAD"), ("B", "VHF", "FULL KEYPAD"),
                             ("C", "700/800 MHZ", "LIMITED KEYPAD"), ("D", "VHF", "LIMITED KEYPAD")):
        rows.append({"CPQModel": "APXN70", "BaseModel": bm, "attr1": BAND, "val1": band,
                     "attr2": KEYPAD, "val2": keypad})
    return rows


def test_with_attributes_that_still_separate_the_base_models_nothing_is_derived():
    """Must-fix 1: the band and keypad are asked, even if one base model owns many more defaults than the others."""
    defaults = [_di("A", **{BAND: "700/800 MHZ", KEYPAD: "FULL KEYPAD", ANT: "WHIP", "a_x": "1"}),
                _di("B", **{KEYPAD: "FULL KEYPAD"}), _di("C", **{KEYPAD: "LIMITED KEYPAD"}),
                _di("D", **{KEYPAD: "LIMITED KEYPAD"})]
    assert _owner(rows=_apx900_rows(), defaults=defaults) is None


def test_the_same_data_without_separating_attributes_does_derive():
    """Control for the test above: the owner is picked only when nothing separates the base models."""
    assert _owner() == U


# the real stage, with the real derivation underneath
def _stage(filled, sources, flag=True, rows=ROWS, defaults=DEFAULTS):
    from aryx.cpq.auto_fill_stages import tier0_default_owner_recheck as stage_mod
    from aryx.cpq.state import MenuOption

    base_vn = "modelSelectionbaseModel_astro"
    options = [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate((K, U, X), start=1)]
    attr = SimpleNamespace(options=options)
    ctx = SimpleNamespace(filled=dict(filled), display_filled=dict(filled), sources=dict(sources), dt_cache={})
    scope = SimpleNamespace(workspace_id=1, catalog_prefix="p")
    state = SimpleNamespace(vn=base_vn, done=False)
    settings = SimpleNamespace(cpq_derive_base_model_default_owner_enabled=flag, cpq_derive_base_model_enabled=True,
                               cpq_derive_discriminators_first_enabled=False)
    with patch.object(derive, "get_settings", return_value=settings), \
            patch.object(owner_mod, "get_settings", return_value=settings), \
            patch("aryx.cpq.derive_base_model_pick.get_settings", return_value=settings), \
            patch.object(stage_mod, "resolve_base_model_vn", return_value=base_vn), \
            patch("aryx.cpq.derive_base_model_pick.resolved_model_first_candidates", return_value=["APXN70"]), \
            patch.object(derive, "_model_rows", return_value=rows), \
            patch.object(bmd, "_load_defaultinattr_rows", return_value=defaults):
        stage_mod.stage_default_owner_recheck(None, attr, ctx, scope, state)
    return ctx, base_vn


def test_the_default_owner_stays_while_nothing_changed():
    base_vn = "modelSelectionbaseModel_astro"
    ctx, _ = _stage({COUNTRY: "US", base_vn: U}, {COUNTRY: "user", base_vn: owner_mod.DEFAULT_OWNER_SOURCE})
    assert ctx.filled[base_vn] == U


def test_a_different_band_given_in_a_later_turn_reopens_the_base_model():
    """Must-fix 2: the customer's band no longer fits the default owner, so the base model is empty again."""
    base_vn = "modelSelectionbaseModel_astro"
    ctx, _ = _stage({COUNTRY: "US", BAND: "VHF", base_vn: U},
                    {COUNTRY: "user", BAND: "user", base_vn: owner_mod.DEFAULT_OWNER_SOURCE})
    assert base_vn not in ctx.filled and base_vn not in ctx.sources


def test_a_base_model_from_another_source_is_never_reopened():
    base_vn = "modelSelectionbaseModel_astro"
    ctx, _ = _stage({COUNTRY: "US", BAND: "VHF", base_vn: U},
                    {COUNTRY: "user", BAND: "user", base_vn: "derived_from_known_attrs"})
    assert ctx.filled[base_vn] == U


def test_the_recheck_does_nothing_with_the_flag_off():
    base_vn = "modelSelectionbaseModel_astro"
    ctx, _ = _stage({COUNTRY: "US", BAND: "VHF", base_vn: U},
                    {COUNTRY: "user", BAND: "user", base_vn: owner_mod.DEFAULT_OWNER_SOURCE}, flag=False)
    assert ctx.filled[base_vn] == U


def test_the_source_and_the_path_of_the_default_owner_are_recorded():
    from aryx.cpq import derive_base_model_pick as pick
    from aryx.cpq.state import MenuOption

    options = [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate((K, U, X), start=1)]
    settings = SimpleNamespace(cpq_derive_base_model_default_owner_enabled=True, cpq_derive_base_model_enabled=True,
                               cpq_derive_discriminators_first_enabled=False)
    logged = []
    with patch.object(derive, "get_settings", return_value=settings), \
            patch.object(owner_mod, "get_settings", return_value=settings), \
            patch.object(pick, "get_settings", return_value=settings), \
            patch.object(pick, "raven_log", side_effect=lambda *a, **k: logged.append(k.get("context", {}))), \
            patch.object(pick, "resolved_model_first_candidates", return_value=["APXN70"]), \
            patch.object(derive, "_model_rows", return_value=ROWS), \
            patch.object(bmd, "_load_defaultinattr_rows", return_value=DEFAULTS):
        choice = pick.derived_base_model_choice(options, {COUNTRY: "US"}, 1, "p", {}, sources={COUNTRY: "user"})
    assert choice is not None and choice[0].item_value == U and choice[1] == "DERIVED_FROM_DEFAULT_OWNER"
    assert logged and logged[-1]["reason_code"] == "DERIVED_FROM_DEFAULT_OWNER"


def test_the_recheck_stage_runs_before_already_filled_keeps_the_value():
    from aryx.cpq.auto_fill_stages import coordinator

    names = [f.__name__ for f in coordinator._STAGES]
    assert names.index("stage_default_owner_recheck") < names.index("stage_already_filled")


# --- a separating attribute with a Defaultinattr default (N50 / N30) -----------------------------------------------
def _n50_rows():
    """The N30 / N50 shape: each base model holds ONE frequency band (VHF / 700/800 / UHF)."""
    return [_wl(K, BAND, "VHF"), _wl(U, BAND, "700/800 MHZ"), _wl(X, BAND, "UHF")] + \
           [_wl(bm, COUNTRY, "US") for bm in (K, U, X)]


N50_DEFAULTS = [_di(U, **{BAND: "700/800 MHZ", KEYPAD: "LIMITED KEYPAD"}), _di(K, **{KEYPAD: "LIMITED KEYPAD"}),
                _di(X, **{KEYPAD: "LIMITED KEYPAD"})]


def test_a_separating_band_with_one_owning_default_is_taken_from_it():
    """N50: the band default 700/800 MHz is defined for one base model only, so country alone derives it."""
    assert _owner(rows=_n50_rows(), defaults=N50_DEFAULTS) == U


def test_a_separating_band_with_no_default_is_still_asked():
    """APX 900 shape: no base model defines a band default, so the band stays a question."""
    no_band_default = [_di(U, **{KEYPAD: "LIMITED KEYPAD"}), _di(K, **{KEYPAD: "LIMITED KEYPAD"}),
                       _di(X, **{KEYPAD: "LIMITED KEYPAD"})]
    assert _owner(rows=_n50_rows(), defaults=no_band_default) is None


def test_a_default_that_differs_from_what_the_base_model_holds_is_not_an_owner():
    wrong = [_di(U, **{BAND: "VHF"}), _di(K, **{KEYPAD: "LIMITED KEYPAD"}), _di(X, **{KEYPAD: "LIMITED KEYPAD"})]
    assert _owner(rows=_n50_rows(), defaults=wrong) is None


def test_two_separating_attributes_owned_by_different_base_models_derive_nothing():
    rows = _n50_rows() + [_wl(K, KEYPAD, "FULL KEYPAD"), _wl(U, KEYPAD, "LIMITED KEYPAD"), _wl(X, KEYPAD, "NO KEYPAD")]
    split = [_di(U, **{BAND: "700/800 MHZ"}), _di(K, **{KEYPAD: "FULL KEYPAD"}), _di(X, **{ANT: "WHIP"})]
    assert _owner(rows=rows, defaults=split) is None


def test_a_customer_band_that_differs_blocks_the_separating_owner_too():
    assert _owner({BAND: "VHF"}, customer={BAND}, rows=_n50_rows(), defaults=N50_DEFAULTS) is None
