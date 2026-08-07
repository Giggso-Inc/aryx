"""Parse the individuals (instance data) out of an external RDF/OWL document.

``importer.py``/``importer_full.py`` only ever extract class-level schema
(owl:Class, properties, hierarchy, axioms) — by design, for bringing in a
vocabulary like schema.org or FIBO. They never look at ``owl:NamedIndividual``
triples or resource-valued predicates (the actual entities and relationships
in a document), so importing an exported Aryx workspace graph reconstructed
only its shape, never its data.

This module closes that gap: it walks the same parsed graph for individuals
and the edges between them, so ``ontology_browse.import_doc`` can turn a
published .ttl/.rdf/.jsonld/.nt file back into real entities + relationships,
not just proposed types.
"""
from __future__ import annotations

import logging
from typing import Any

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from aryx.ontology.rdf.importer import _label, _local_name
from aryx.ontology.rdf.model import FORMATS

logger = logging.getLogger(__name__)

# rdf:type objects that mark a *schema* declaration, not a data individual —
# a subject typed as one of these is metadata about the ontology itself.
_META_TYPES = {
    OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
    OWL.AnnotationProperty, OWL.Ontology, OWL.Restriction,
    RDF.Property, RDFS.Datatype,
}


def parse_instances(content: str, fmt: str) -> dict[str, Any]:
    """Extract individuals + the links between them from an RDF/OWL document.

    An "individual" is any subject with a non-meta rdf:type — this works
    whether the document declares formal owl:Class/owl:NamedIndividual
    schema (as Aryx's own Publish export does) or types resources only
    implicitly (no schema at all, just ``rdf:type`` pointing at a bare URI).

    Args:
        content: The RDF document text (Turtle, JSON-LD, RDF/XML, N-Triples).
        fmt: A FORMATS key identifying the serialisation.

    Returns:
        {"entities": [{"iri", "type", "attributes"}],
         "links": [{"source_iri", "target_iri", "name"}]}
        attributes always includes "name" and "_rdf_iri".

    Raises:
        ValueError: If fmt is unsupported or the document cannot be parsed.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unsupported format '{fmt}'; choose from {sorted(FORMATS)}")
    graph = Graph()
    try:
        graph.parse(data=content, format=FORMATS[fmt][0])
    except Exception as exc:  # noqa: BLE001 — surface parse errors to the caller
        raise ValueError(f"could not parse {fmt} document: {exc}") from exc

    class_iris: set[URIRef] = set()
    for pred in (OWL.Class, RDFS.Class):
        for subject in graph.subjects(RDF.type, pred):
            if isinstance(subject, URIRef):
                class_iris.add(subject)

    # One primary type per individual — prefer a type that's a declared
    # class over an incidental one (a resource can carry more than one
    # rdf:type, e.g. owl:NamedIndividual + the actual domain class).
    individual_type: dict[URIRef, URIRef] = {}
    for subject, obj in graph.subject_objects(RDF.type):
        if not isinstance(obj, URIRef) or obj in _META_TYPES:
            continue
        if subject in class_iris:
            continue  # a class describing itself isn't instance data
        if subject not in individual_type or obj in class_iris:
            individual_type[subject] = obj

    individuals = set(individual_type.keys())
    if not individuals:
        return {"entities": [], "links": []}

    entities: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    for iri in individuals:
        type_name = _label(graph, individual_type[iri])
        attrs: dict[str, Any] = {}
        name: str | None = None
        for pred, obj in graph.predicate_objects(iri):
            if pred == RDF.type:
                continue
            pname = _local_name(pred)
            if isinstance(obj, Literal):
                val = str(obj)
                if pred == RDFS.label or pname.lower() == "name":
                    name = name or val
                attrs.setdefault(pname, val)
            elif isinstance(obj, URIRef) and obj in individuals:
                links.append({"source_iri": str(iri), "target_iri": str(obj),
                             "name": pname})
            # BNode / class-valued objects are schema-level — skip.
        attrs["name"] = name or attrs.get("name") or _local_name(iri)
        attrs["_rdf_iri"] = str(iri)
        entities.append({"iri": str(iri), "type": type_name, "attributes": attrs})

    logger.info("rdf instance import format=%s entities=%d links=%d",
                fmt, len(entities), len(links))
    return {"entities": entities, "links": links}
