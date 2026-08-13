"""Night 1 Protege-parity tests — exercises the in-memory layers only.

The Postgres / FalkorDB layers are mocked or bypassed so this test file runs
without a live stack. End-to-end coverage lives in the integration suite that
spins up docker-compose.
"""
from __future__ import annotations

from rdflib.namespace import OWL, RDFS

from aryx.graph.falkor_store import _lift_props, _safe_labels
from aryx.models import OntologyType
from aryx.ontology.rdf import GraphBundle
from aryx.ontology.rdf.exporter import build_graph
from aryx.project import _entity_iri
from aryx.reasoning import edge_axioms as reng


# ---------- Phase 1: label safety ----------

def test_safe_labels_accepts_identifiers() -> None:
    assert _safe_labels(["Vehicle", "Car", "Sedan"]) == ["Vehicle", "Car", "Sedan"]


def test_safe_labels_sanitizes_instead_of_dropping() -> None:
    out = _safe_labels(["Car", "Foo) DELETE n //", "Bar Baz", "Ok_2"])
    assert out == ["Car", "Foo__DELETE_n___", "Bar_Baz", "Ok_2"]


def test_safe_labels_dedupes_and_caps() -> None:
    out = _safe_labels(["A", "A", "B", "C", "D", "E", "F", "G"])
    assert out == ["A", "B", "C", "D", "E", "F"]  # cap = 6


def test_safe_labels_suffixes_sanitized_collision() -> None:
    # "Product-Type" and "Product:Type" both sanitize to "Product_Type" —
    # they must not collapse into one label and silently drop the second.
    out = _safe_labels(["Product-Type", "Product:Type"])
    assert out == ["Product_Type", "Product_Type_2"]


def test_safe_labels_exact_duplicate_still_dedupes() -> None:
    # A raw label repeated verbatim is an intentional, lossless dedup — no
    # suffix — distinct from a sanitized collision between different labels.
    out = _safe_labels(["Product-Type", "Product-Type"])
    assert out == ["Product_Type"]


# ---------- Phase 1: property-key safety ----------

def test_lift_props_sanitizes_instead_of_dropping(caplog) -> None:
    # "attr:1" isn't a safe Cypher identifier — it must survive under a
    # sanitized name (with a warning), not vanish like the original bug.
    with caplog.at_level("WARNING"):
        out = _lift_props({"attr:1": "v"})
    assert out == {"attr_1": "v"}
    assert any("attr_1" in r.message for r in caplog.records)


def test_lift_props_suffixes_sanitized_collision() -> None:
    # "attr-1" and "attr:1" both sanitize to "attr_1" — two distinct source
    # keys must not collapse into one write silently overwriting the other.
    out = _lift_props({"attr-1": "first", "attr:1": "second"})
    assert out == {"attr_1": "first", "attr_1_2": "second"}


def test_lift_props_sanitized_collision_with_already_safe_key() -> None:
    # A sanitized key can also collide with a distinct key that was already
    # a safe identifier as-is — same suffix protection applies.
    out = _lift_props({"attr_1": "first", "attr:1": "second"})
    assert out == {"attr_1": "first", "attr_1_2": "second"}


# ---------- Phase 1: stable IRI ----------

def test_entity_iri_is_deterministic() -> None:
    a = _entity_iri("https://aryx.local/", workspace_id=1, entity_id=42)
    b = _entity_iri("https://aryx.local/", workspace_id=1, entity_id=42)
    assert a == b == "https://aryx.local/entity/1/42"


def test_entity_iri_handles_missing_trailing_slash_and_workspace() -> None:
    assert (
        _entity_iri("https://aryx.local", workspace_id=None, entity_id=7)
        == "https://aryx.local/entity/0/7"
    )


# ---------- Phase 4: exporter emits rdfs:subClassOf ----------

def test_exporter_emits_subclass_of() -> None:
    bundle = GraphBundle(
        types=[
            OntologyType(name="Vehicle"),
            OntologyType(name="Car", parent_type="Vehicle"),
            OntologyType(name="Sedan", parent_type="Car"),
        ],
        entities=[],
        relationships=[],
        provenance=[],
    )
    g = build_graph(bundle, base_uri="https://aryx.local/", include_provenance=False)
    subclass_triples = list(g.triples((None, RDFS.subClassOf, None)))
    assert len(subclass_triples) == 2  # Car->Vehicle, Sedan->Car
    pairs = {(str(s).rsplit("#", 1)[-1], str(o).rsplit("#", 1)[-1])
             for s, _, o in subclass_triples}
    assert ("Car", "Vehicle") in pairs
    assert ("Sedan", "Car") in pairs


def test_exporter_no_subclass_when_no_parent() -> None:
    bundle = GraphBundle(types=[OntologyType(name="Standalone")])
    g = build_graph(bundle, base_uri="https://aryx.local/", include_provenance=False)
    assert list(g.triples((None, RDFS.subClassOf, None))) == []


# ---------- Phase 3: reasoner edge axioms ----------

class _FakeGraph:
    """Capture Cypher writes for assertion without a live FalkorDB."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, params: dict | None = None) -> None:
        self.calls.append((query, params or {}))


def test_apply_inverse_runs_one_merge() -> None:
    g = _FakeGraph()
    reng.apply_inverse(g, "works_for", "employs")
    assert len(g.calls) == 1
    q, p = g.calls[0]
    assert "MERGE" in q and p == {"fwd": "works_for", "inv": "employs"}


def test_apply_symmetric_runs_one_merge() -> None:
    g = _FakeGraph()
    reng.apply_symmetric(g, "sibling_of")
    assert len(g.calls) == 1
    assert g.calls[0][1] == {"name": "sibling_of"}


def test_apply_transitive_walks_capped_depth() -> None:
    g = _FakeGraph()
    reng.apply_transitive(g, "located_in", depth=10)  # asks for 10, capped to 4
    # hops 2..4 inclusive = 3 queries
    assert len(g.calls) == 3


def test_apply_edge_axiom_dispatch_combines() -> None:
    g = _FakeGraph()
    fired = reng.apply_edge_axiom(
        g, "located_in", {"transitive": True, "max_depth": 3},
    )
    assert fired == 1
    assert len(g.calls) == 2  # hops 2..3


