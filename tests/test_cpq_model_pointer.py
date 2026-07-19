"""Issue 11: pointer-defaults are references, never literals.

Live finding (docs/CPQ_PRODUCT_SWITCH_ISSUE.md Issue 11): `modelname_all`
is a hidden attr whose XML default_value is the literal string
"_bm_model_variable_name" — a POINTER to the runtime model-context attr
BigMachines injects at punch-in (its own "Set Model Name..." rule copies
that attr into modelname_all at runtime). Exports never carry the runtime
context, so Aryx shipped the pointer token itself as payload data:
'"modelname_all": "_bm_model_variable_name"'.

An exhaustive survey of every ingested catalog found exactly ONE
pointer-default pattern (modelname_all -> _bm_model_variable_name, both
exports) and zero coincidental literal defaults equal to an attr name.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def _attr(entity_id, vn, *, hidden=False, default=""):
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn,
        required=False, default_value=default, options=[], hidden=hidden,
    )


def _pointer_pair():
    return [
        _attr(1, "modelname_all", hidden=True, default="_bm_model_variable_name"),
        _attr(2, "_bm_model_variable_name"),
    ]


def test_pointer_token_is_never_filled_as_a_literal():
    attrs = _pointer_pair()
    filled, _display, _pending = CpqEngine().auto_fill(attrs, hints={})

    assert "modelname_all" not in filled, (
        "a default equal to another attr's variable name is a reference, "
        "not data — the token must never enter filled"
    )


def test_pointer_resolves_when_referenced_attr_fills():
    attrs = _pointer_pair()
    filled, _display, _pending = CpqEngine().auto_fill(
        attrs, hints={"_bm_model_variable_name": "vX650_BOM"})

    assert filled.get("_bm_model_variable_name") == "vX650_BOM"
    assert filled.get("modelname_all") == "vX650_BOM", (
        "the pointer attr must inherit the referenced attr's value — "
        "what BM's own 'Set Model Name...' runtime rule does"
    )


def test_payload_ships_resolved_model_and_never_the_token():
    engine = CpqEngine()
    attrs = _pointer_pair()
    filled, _display, _pending = engine.auto_fill(
        attrs, hints={"_bm_model_variable_name": "vX650_BOM"})
    payload = engine.build_payload(
        filled, {k: "cascade" for k in filled}, {}, attrs)
    data = payload[next(iter(payload))]  # root key (configData)

    assert data.get("modelname_all") == "vX650_BOM"
    assert "_bm_model_variable_name" not in data, (
        "the runtime-context attr itself is noise-prefixed and never POSTed"
    )


def test_unresolvable_pointer_stays_out_of_payload():
    engine = CpqEngine()
    attrs = _pointer_pair()
    filled, _display, _pending = engine.auto_fill(attrs, hints={})
    payload = engine.build_payload(
        filled, {k: "default" for k in filled}, {}, attrs)
    data = payload[next(iter(payload))]

    assert "modelname_all" not in data, (
        "APX-style ambiguity: referenced attr never fills -> pointer attr "
        "is absent from the payload, never the placeholder token"
    )


def test_legitimate_literal_default_still_fills():
    attrs = [
        _attr(3, "batteryKind", hidden=True, default="STANDARD"),
        _attr(4, "someOtherAttr"),
    ]
    filled, _display, _pending = CpqEngine().auto_fill(attrs, hints={})

    assert filled.get("batteryKind") == "STANDARD", (
        "a default that matches NO attr name is a normal literal"
    )


def test_stale_session_token_is_scrubbed_at_payload_time():
    """A session filled on an older build carries the literal token in its
    saved state — build_payload must scrub it even without auto_fill."""
    engine = CpqEngine()
    attrs = _pointer_pair()
    stale_filled = {"modelname_all": "_bm_model_variable_name"}
    payload = engine.build_payload(
        stale_filled, {"modelname_all": "default"}, {}, attrs)
    data = payload[next(iter(payload))]

    assert "modelname_all" not in data


def test_resolved_model_value_survives_payload_scrub():
    """The scrub only targets the attr's OWN pointer token — a properly
    resolved value ships."""
    engine = CpqEngine()
    attrs = _pointer_pair()
    payload = engine.build_payload(
        {"modelname_all": "vX650_BOM"}, {"modelname_all": "cascade"}, {}, attrs)
    data = payload[next(iter(payload))]

    assert data.get("modelname_all") == "vX650_BOM"


def test_model_context_mirrors_detected_structurally():
    attrs = _pointer_pair() + [
        _attr(5, "ordinaryAttr", default="STANDARD"),
    ]
    assert CpqEngine.model_context_mirror_vns(attrs) == {"modelname_all"}


def test_product_flow_excludes_mirrors_model_flow_excludes_product(monkeypatch):
    """Mutual exclusivity: the flow signal is resolve_always_ask_skips —
    non-empty (native UI hides the product selector) means model flow."""
    engine = CpqEngine()
    attrs = _pointer_pair()

    # Product flow: no skips resolved -> mirrors excluded from the payload.
    monkeypatch.setattr(
        engine, "resolve_always_ask_skips", lambda ws, cp, a: set())
    assert engine.payload_flow_exclusions(1, "Any", attrs) == {"modelname_all"}

    # Model flow: product selector skipped -> that exclusion set is used
    # as-is and the mirrors ship.
    monkeypatch.setattr(
        engine, "resolve_always_ask_skips",
        lambda ws, cp, a: {"productSelectionProduct_all"})
    assert engine.payload_flow_exclusions(1, "Any", attrs) == {
        "productSelectionProduct_all"}


class _FakeTreeReader:
    def __init__(self, nodes):
        # nodes: list of (aryx_id, native_id, parent_id, name)
        self._nodes = nodes

    def find_entities(self, ontology_type=None, name=None, limit=50, offset=0):
        if ontology_type != "SvxBmCatalog":
            return []
        return [{"id": i, "type": ontology_type, "name": nm}
                for i, _nat, _par, nm in self._nodes]


def _tree_engine(monkeypatch, nodes):
    engine = CpqEngine()
    fetched = {i: {"id": nat, "parent_id": par, "name": nm}
               for i, nat, par, nm in nodes}
    monkeypatch.setattr(
        engine, "_batch_fetch", lambda ids, ws: {i: fetched[i] for i in ids})
    return engine


def test_single_leaf_tree_resolves_the_model(monkeypatch):
    nodes = [(1, "100", "-1", "mobile_BOM"), (2, "101", "100", "vX650_BOM")]
    engine = _tree_engine(monkeypatch, nodes)

    assert engine.single_model_variable_name(
        _FakeTreeReader(nodes), 1, "Svx") == "vX650_BOM"


def test_multi_leaf_tree_never_guesses(monkeypatch):
    nodes = [
        (1, "200", "-1", "aSTRODevices_BOM"),
        (2, "201", "200", "aPXNext_BOM"),
        (3, "202", "200", "aPXN70_BOM"),
    ]
    engine = _tree_engine(monkeypatch, nodes)

    assert engine.single_model_variable_name(
        _FakeTreeReader(nodes), 1, "Svx") == ""
