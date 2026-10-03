"""Integration of the two batch-2 flags: the Basemodeltoconfig display-name
resolver (#341) feeds the not-applicable pending prune (#362). Only the two
data loaders are faked; the resolver, the governance lookup and the prune run
for real."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.auto_fill.auto_fill_pending_prune import attrs_confirmed_not_applicable_for_hint
from aryx.cpq.state import ConfigAttr


def _attr(eid, vn, required=False):
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=vn, required=required,
        default_value="", options=[],
    )


PENDING = [
    _attr(1, "governedAttr_astro"),
    _attr(2, "neverGovernedAttr_astro"),
    _attr(3, "requiredAnchor_astro", required=True),
]
BASEMODEL_ROWS = [{"displayModel": "APX 900", "cpqModel": "APX900", "baseModel": "B1"}]
SEQUENCE_ROWS = [{"CPQModel": "APX900", "AttrName": "governedAttr_astro", "BaseModel": "B1", "Seq": "1"}]


def _run(display_flag: bool, hint="I want APX 900 for US"):
    cfg = MagicMock()
    cfg.return_value.cpq_basemodel_display_name_resolution_enabled = display_flag
    with patch("aryx.config.get_settings", cfg), \
            patch("aryx.cpq.data_table.data_table_inference._load_basemodel_to_config_rows",
                  return_value=BASEMODEL_ROWS), \
            patch("aryx.cpq.data_table.data_table_governance._load_all_tables",
                  return_value=([], SEQUENCE_ROWS, [], [], [])), \
            patch("aryx.cpq.data_table.data_table_product.resolve_product_cpq_models_from_rows",
                  return_value=()):
        return [a.variable_name for a in attrs_confirmed_not_applicable_for_hint(
            list(PENDING), hint, 1, "", {})]


def test_both_flags_on_resolver_feeds_prune_and_drops_only_never_governed_attr():
    kept = _run(True)
    assert "neverGovernedAttr_astro" not in kept
    assert "governedAttr_astro" in kept          # governed for APX900: stays
    assert "requiredAnchor_astro" in kept        # structural anchor: stays


def test_display_name_flag_off_resolver_returns_nothing_so_prune_is_a_noop():
    kept = _run(False)
    assert kept == ["governedAttr_astro", "neverGovernedAttr_astro", "requiredAnchor_astro"]


def test_unrelated_hint_resolves_no_device_so_prune_is_a_noop():
    kept = _run(True, hint="I want a radio for US")
    assert kept == ["governedAttr_astro", "neverGovernedAttr_astro", "requiredAnchor_astro"]
