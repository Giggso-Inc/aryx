"""PR #206 review (M3): unit coverage for the guards added alongside the
override-entity FK fallback in load_product_config.

Live-confirmed root cause (docs/CPQ_PRODUCT_XE_OPTION_GRAPH_INGESTION_GAP_
2026_08_17.md): a bm_config_att_override entity can have a real Postgres
row and real bm_menu_item children correctly linked via a `ref_id`
property, but zero outgoing graph edges via reader.neighbors() — the
existing override-merge logic silently dropped those menu items instead
of asking the customer or falling back. Three independent guards are
covered here:

1. `_no_real_fill_justification` — the dynamic (not hardcoded) check for
   whether an attribute has any real basis to be blind-filled.
2. `_sole_opt_out_option` — the catalog-agnostic "the menu itself declares
   a safe skip answer" detector.
3. `load_product_config`'s override FK fallback — when an override's
   graph neighbors are empty, its menu items are still found via a
   Postgres `ref_id` match instead of being silently dropped.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.cpq.engine import CpqEngine, _no_real_fill_justification, _sole_opt_out_option
from aryx.cpq.state import ConfigAttr, MenuOption


def _attr(**overrides) -> ConfigAttr:
    defaults = dict(
        entity_id=1, variable_name="sampleAttr_astro", display_label="Test Attr",
        required=False, default_value="", options=[], source_id=100,
    )
    defaults.update(overrides)
    return ConfigAttr(**defaults)


# ── _no_real_fill_justification ─────────────────────────────────────────────

def test_no_real_fill_justification_false_when_required():
    attr = _attr(required=True)
    assert _no_real_fill_justification(attr, {}) is False, (
        "a required attr always has a real basis to fill — it must be "
        "resolved one way or another"
    )


def test_no_real_fill_justification_false_when_default_value_valid():
    attr = _attr(default_value="US")
    assert _no_real_fill_justification(attr, {}) is False, (
        "a confirmed catalog default_value is a real, non-guessed basis"
    )


def test_no_real_fill_justification_false_when_recommendation_targets_entity_id():
    attr = _attr(entity_id=42, source_id=999)
    rec_by_target = {42: ["some recommendation rule"]}
    assert _no_real_fill_justification(attr, rec_by_target) is False, (
        "a satisfied recommendation targeting this attr's entity_id is a "
        "real basis to fill"
    )


def test_no_real_fill_justification_false_when_recommendation_targets_source_id():
    attr = _attr(entity_id=42, source_id=999)
    rec_by_target = {999: ["some recommendation rule"]}
    assert _no_real_fill_justification(attr, rec_by_target) is False, (
        "rules reference attrs by their BM-native source_id, not just the "
        "aryx entity_id — either must count as a real basis"
    )


def test_no_real_fill_justification_true_when_none_of_the_above():
    attr = _attr(required=False, default_value="", entity_id=1, source_id=2)
    assert _no_real_fill_justification(attr, {}) is True, (
        "not required, no default, no recommendation targeting it — "
        "nothing justifies picking a value for this attr"
    )


# ── _sole_opt_out_option ─────────────────────────────────────────────────────

def test_sole_opt_out_option_returns_the_single_match():
    opts = [
        MenuOption(item_value="YES", display_name="Yes, I need this"),
        MenuOption(item_value="NO", display_name="Not required"),
    ]
    result = _sole_opt_out_option(opts)
    assert result is not None and result.item_value == "NO"


def test_sole_opt_out_option_returns_none_when_zero_matches():
    opts = [
        MenuOption(item_value="A", display_name="Option A"),
        MenuOption(item_value="B", display_name="Option B"),
    ]
    assert _sole_opt_out_option(opts) is None


def test_sole_opt_out_option_returns_none_when_ambiguous():
    # 2+ options both declaring "opt out" phrasing — never guess which one.
    opts = [
        MenuOption(item_value="NA1", display_name="N/A - not applicable"),
        MenuOption(item_value="NA2", display_name="None required"),
    ]
    assert _sole_opt_out_option(opts) is None, (
        "2+ opt-out-phrased options means the menu's phrasing is "
        "ambiguous about which is the real opt-out — must fall through "
        "to asking rather than guessing between them"
    )


# ── load_product_config override FK fallback ────────────────────────────────

class _FakeOverrideReader:
    """Minimal reader double for one catalog with a single base attribute
    whose options come ONLY from a bm_config_att_override entity that has
    zero graph edges — the exact live-confirmed gap this fallback fixes.

    Graph layout:
      - 1 BmConfigAttr entity (id=10, native id "500019")
      - 1 BmConfigAttOverride entity (id=20, attribute_id="500019",
        native/src id "700001") with reader.neighbors() -> [] (the gap)
      - 2 BmMenuItem entities (ids 30, 31), NOT reachable via any graph
        edge, but their Postgres rows carry ref_id == "700001" (the
        override's own native id) — the property-based link the fallback
        must use instead of graph traversal.
    """

    def __init__(self):
        self.attr_ent = {"id": 10, "type": "TestBmConfigAttr", "name": "sampleAttr_astro"}
        self.override_ent = {"id": 20, "type": "TestBmConfigAttOverride", "name": "override"}
        self.menu_ents = [
            {"id": 30, "type": "TestBmMenuItem", "name": "Option One"},
            {"id": 31, "type": "TestBmMenuItem", "name": "Option Two"},
        ]

    def distinct_types(self):
        return ["TestBmConfigAttr", "TestBmConfigAttOverride", "TestBmMenuItem"]

    def find_entities(self, ontology_type=None, name=None, limit=50, offset=0):
        if offset:
            return []
        if ontology_type == "TestBmConfigAttr":
            return [self.attr_ent]
        if ontology_type == "TestBmConfigAttOverride":
            return [self.override_ent]
        if ontology_type == "TestBmMenuItem":
            return self.menu_ents
        return []

    def neighbors(self, entity_id):
        # Both the base attr (10) and the override (20) have zero graph
        # edges — mirrors the live-confirmed gap where the override's
        # menu-item edges were never created during ingestion.
        return []


def _fake_batch_fetch(monkeypatch):
    pg_rows = {
        10: {
            "id": "500019", "variable_name": "sampleAttr_astro",
            "name": "Test Attr", "required": "0", "default_value": "",
            "order_number": "1", "menu_type": "",
        },
        20: {
            "id": "700001", "attribute_id": "500019",
        },
        30: {
            "item_value": "OPT_ONE", "item_text": "Option One",
            "order_number": "1", "ref_id": "700001",
        },
        31: {
            "item_value": "OPT_TWO", "item_text": "Option Two",
            "order_number": "2", "ref_id": "700001",
        },
    }
    monkeypatch.setattr(
        type(api._cpq_engine), "_batch_fetch",
        lambda self, ids, ws: {i: pg_rows[i] for i in ids if i in pg_rows},
    )


def test_override_fk_fallback_finds_menu_items_via_ref_id_when_neighbors_empty(monkeypatch):
    eng = CpqEngine()
    _fake_batch_fetch(monkeypatch)
    monkeypatch.setattr(
        eng, "_load_rule_join_data", lambda workspace_id, catalog_prefix: (None, {}, {}, {}, {}),
    )
    reader = _FakeOverrideReader()

    attrs, _resolved = eng.load_product_config(reader, workspace_id=1, product_hint="Test")

    by_vn = {a.variable_name: a for a in attrs}
    assert "sampleAttr_astro" in by_vn, "the base attribute itself must still load"
    option_values = {o.item_value for o in by_vn["sampleAttr_astro"].options}
    assert option_values == {"OPT_ONE", "OPT_TWO"}, (
        "the override's real menu items (ref_id-linked in Postgres) must "
        "surface even though reader.neighbors() returns empty for both the "
        "base attribute and the override entity — dropping them here is "
        "the exact live-confirmed bug this fallback fixes"
    )
