"""FalkorStore's entity-node write methods (mixin).

Split out of `graph/falkor_store.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). No test patches individual FalkorStore methods (only the whole
class, or `FalkorDB` in `__init__`), so this mixin carries no patch-
retargeting risk — it relies on `self._graph`/`self._index_candidates`, set
up by `FalkorStore.__init__`.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aryx.graph.falkor_sanitize import _INDEX_PROP_RE, _display_name, _lift_props, _safe_labels


class _FalkorEntityWriteMixin:
    """add/remove entity-node methods for FalkorStore."""

    def add_entity(self, entity_id: int, ontology_type: str,
                   attributes: dict[str, Any],
                   labels: list[str] | None = None,
                   iri: str | None = None) -> None:
        """Create or update an entity node with its ontology type and ancestor labels.

        Args:
            entity_id: Stable numeric id from EntityStore.
            ontology_type: Canonical type name (also stored as attribute).
            attributes: Golden-record attributes for display-name derivation.
            labels: Optional ancestor type names (rdfs:subClassOf chain) to
                attach as additional Cypher labels. ``ontology_type`` is added
                automatically if it passes label validation.
            iri: Optional stable IRI to write as ``e.iri`` for self-describing
                nodes — frozen for the entity's lifetime (derived from
                workspace_id + entity_id by the projector).
        """
        chain = [ontology_type] + list(labels or [])
        safe = _safe_labels(chain)
        label_clause = "".join(f":{lbl}" for lbl in safe)
        # Attributes become individual node properties (parameter-bound map,
        # never string-interpolated) so Cypher can match and index them
        # natively — MATCH (e {variable_name: $v}) works. The RDB
        # (aryx_entity.attributes) stays the full-fidelity authoritative copy;
        # long non-key values are truncated here by _lift_props.
        props = _lift_props(attributes)
        for key in props:
            if _INDEX_PROP_RE.search(key):
                self._index_candidates.add(key)
        params: dict[str, Any] = {
            "id": entity_id, "type": ontology_type,
            "name": _display_name(attributes) or f"#{entity_id}",
            "props": props,
        }
        set_iri = ""
        if iri:
            params["iri"] = iri
            set_iri = ", e.iri = $iri"
        self._graph.query(
            f"MERGE (e:Entity{label_clause} {{id: $id}}) "
            f"SET e.type = $type, e.name = $name{set_iri}, e += $props",
            params,
        )

    def add_entities_batch(
        self,
        entities: list[tuple[int, str, dict[str, Any], list[str] | None, str | None]],
        batch_size: int = 500,
        on_batch: "Callable[[int], None] | None" = None,
        full_rebuild: bool = False,
    ) -> int:
        """Write multiple entity nodes in batched UNWIND queries.

        Each item is (entity_id, ontology_type, attributes, labels, iri) —
        same fields as add_entity(). Cypher labels must be static text in
        the query, not parameters, so rows are grouped by their exact
        label-set and one UNWIND is issued per group (a workspace has a
        few hundred distinct types at most, not one query per row).
        Measured 7.8x faster than per-call add_entity() on realistic
        ~20-key attribute payloads (docs/CPQ_INGESTION_PROJECTION_PERFORMANCE_PLAN.md).

        on_batch — optional callback invoked with the running total of
        rows written after each UNWIND batch, for sub-progress reporting.

        full_rebuild — accepted for call-site parity with
        OracleGraphStore.add_entities_batch (project_graph() always passes
        it) but unused here: FalkorDB's Cypher MERGE has no equivalent to
        the pathological executemany() MERGE cost that motivated Oracle's
        insert_graph_vertex fast path (docs/ingestion/SPARK_PARALLEL_
        MIGRATION_ANALYSIS_2026-09-23.md Phase 4 Part B follow-up).
        """
        groups: dict[tuple[str, ...], list[tuple[int, str, dict[str, Any], str | None]]] = {}
        for entity_id, ontology_type, attributes, labels, iri in entities:
            chain = [ontology_type] + list(labels or [])
            safe = tuple(_safe_labels(chain))
            groups.setdefault(safe, []).append((entity_id, ontology_type, attributes, iri))

        written = 0
        for safe_labels, rows in groups.items():
            label_clause = "".join(f":{lbl}" for lbl in safe_labels)
            for i in range(0, len(rows), batch_size):
                chunk = rows[i : i + batch_size]
                params = []
                for entity_id, ontology_type, attributes, iri in chunk:
                    props = _lift_props(attributes)
                    for key in props:
                        if _INDEX_PROP_RE.search(key):
                            self._index_candidates.add(key)
                    params.append({
                        "id": entity_id, "type": ontology_type,
                        "name": _display_name(attributes) or f"#{entity_id}",
                        "props": props, "iri": iri,
                    })
                self._graph.query(
                    f"UNWIND $rows AS r "
                    f"MERGE (e:Entity{label_clause} {{id: r.id}}) "
                    f"SET e.type = r.type, e.name = r.name, "
                    f"e.iri = CASE WHEN r.iri IS NOT NULL THEN r.iri ELSE e.iri END, "
                    f"e += r.props",
                    {"rows": params},
                )
                written += len(chunk)
                if on_batch is not None:
                    on_batch(written)
        return written

    def remove_entity(self, entity_id: int) -> None:
        """Tombstone one entity node and all its edges (incremental delete)."""
        self._graph.query(
            "MATCH (e:Entity {id: $id}) DETACH DELETE e", {"id": entity_id},
        )

    def remove_entities_by_type(self, ontology_type: str) -> None:
        """Delete all entity nodes of a given type and their edges."""
        self._graph.query(
            "MATCH (e:Entity {type: $type}) DETACH DELETE e",
            {"type": ontology_type},
        )
