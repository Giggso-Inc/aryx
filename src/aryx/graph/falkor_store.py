"""FalkorDB writer for the knowledge-graph projection (stage 5d).

The graph is a rebuildable projection of the RDB (the source of truth), so the
writer always wipes and rebuilds. Entity nodes carry their ontology type;
provenance edges link entities to source records; REL edges connect entities.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from falkordb import FalkorDB

from aryx.config import get_settings
from aryx.display_name import _GENERIC_NAMES, _NAME_KEYS, display_name as _dn

logger = logging.getLogger(__name__)

_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_LABELS = 6  # cap to avoid label-bloat on deep hierarchies

# Property names reserved by the projection itself — attribute keys with these
# names must never overwrite the canonical lifted fields.
_RESERVED_PROPS = frozenset({"id", "type", "name", "iri"})

# Key-like attribute names are exempt from value truncation: a truncated
# identifier silently breaks exact-match joins (the graph would store a value
# that equals nothing in the source data). Matches id/guid/uuid/key/code/ref
# suffixes and variable_name-style CPQ keys.
_KEY_PROP_RE = re.compile(
    r"(^|_)(id|guid|uuid|key|code|ref|num|no)$|^variable_name$|_name$", re.IGNORECASE
)

# Sanity bound for exempt key values — a "key" longer than this is almost
# certainly not a key; warn and truncate anyway to protect the graph.
_KEY_SANITY_MAX = 4096

# Properties worth indexing for exact-match lookups. Deliberately narrower
# than the truncation exemption: *_name display fields are searched with
# CONTAINS (no index benefit in FalkorDB), while these are joined on equality.
_INDEX_PROP_RE = re.compile(
    r"(^|_)(id|guid|uuid|key|code)$|^variable_name$", re.IGNORECASE
)


def _lift_props(attributes: dict[str, Any]) -> dict[str, Any]:
    """Build the native-property map for a node from entity attributes.

    Scalars pass through natively so they are individually queryable and
    indexable in Cypher; nested dicts/lists are JSON-stringified per key (or
    skipped, per ARYX_GRAPH_LIFT_NESTED); long strings are truncated to
    ARYX_GRAPH_ATTR_VALUE_CAP except key-like fields, which must stay intact
    for exact-match joins. The RDB keeps the full-fidelity copy.
    """
    settings = get_settings()
    if settings.graph_lift_mode == "off":
        return {}
    cap = settings.graph_attr_value_cap
    out: dict[str, Any] = {}
    for key, val in attributes.items():
        if val is None:
            continue
        if key in _RESERVED_PROPS:
            # Source data legitimately carries its own id/name/type (e.g. the
            # BigMachines-native `id` that rules join on). Those must stay
            # queryable — store them under a src_ prefix instead of letting
            # the projection's canonical fields shadow them.
            key = f"src_{key}"
        if not _LABEL_RE.match(key):
            logger.debug("skipping attr %r: not a safe property name", key)
            continue
        if isinstance(val, bool) or isinstance(val, (int, float)):
            out[key] = val
            continue
        if isinstance(val, (dict, list)):
            if not settings.graph_lift_nested:
                continue
            val = json.dumps(val, default=str)
        elif not isinstance(val, str):
            val = str(val)
        if _KEY_PROP_RE.search(key):
            if len(val) > _KEY_SANITY_MAX:
                logger.warning(
                    "key-like attr %r exceeds sanity bound (%d > %d chars), "
                    "truncating — exact-match joins on it will not work",
                    key, len(val), _KEY_SANITY_MAX)
                val = val[:_KEY_SANITY_MAX]
        elif len(val) > cap:
            val = val[:cap] + "…"
        out[key] = val
    return out


def _safe_labels(labels: list[str] | None) -> list[str]:
    """Filter labels to safe Cypher identifiers and cap depth.

    FalkorDB does not support parameter-bound labels, so the label list is
    spliced into the query string — every entry must be a strict identifier
    or it gets dropped (with a warning) to prevent Cypher injection.
    """
    out: list[str] = []
    for raw in labels or []:
        if not raw:
            continue
        if not _LABEL_RE.match(raw):
            logger.warning("dropping invalid label %r (not a Cypher identifier)", raw)
            continue
        if raw in out:
            continue
        out.append(raw)
        if len(out) >= _MAX_LABELS:
            break
    return out


def _display_name(attributes: dict[str, Any]) -> str:
    return _dn(attributes)


class FalkorStore:
    """Writes entity / provenance / relationship graph elements to FalkorDB."""

    def __init__(self, url: str, graph: str = "aryx") -> None:
        """Connect from a redis:// URL and select a named graph.

        Args:
            url: FalkorDB connection URL, e.g. redis://falkordb:6379.
            graph: Graph key to write into.
        """
        parsed = urlparse(url)
        self._db = FalkorDB(host=parsed.hostname or "localhost",
                            port=parsed.port or 6379)
        self._graph = self._db.select_graph(graph)
        # Index-worthy property names observed while writing entities; flushed
        # to CREATE INDEX statements by ensure_indexes().
        self._index_candidates: set[str] = set()

    def clear(self) -> None:
        """Delete the whole graph for a clean rebuild.

        Re-creates the index on Entity.id immediately after — delete() wipes
        it along with everything else, and every add_entity() MERGE matches
        on {id: $id}. Without the index, that MERGE does a full label scan
        per call, so the entity-write loop degrades from O(1) to O(n) per
        write (O(n^2) overall) as the graph grows — this is a pure write-
        performance fix, not a behavior/correctness change.
        """
        try:
            self._graph.delete()
        except Exception:  # graph may not exist yet  # noqa: BLE001
            pass
        try:
            self._graph.query("CREATE INDEX FOR (e:Entity) ON (e.id)")
        except Exception as exc:  # noqa: BLE001 — perf optimization only; MERGE still works without it
            logger.warning("falkor: failed to create index on Entity.id, "
                           "writes will fall back to full-scan MERGE: %s", exc)
        try:
            # Same fix as Entity.id above, for the SAME reason — add_provenance's
            # MERGE (s:Source {system, dataset, record_id}) had no index, so
            # every call label-scanned every Source node written so far this
            # run: O(1) per write growing to O(n), O(n^2) overall. Confirmed
            # live (docs/CPQ_INGESTION_PROJECTION_PERFORMANCE_PLAN.md): this
            # was the dominant cost of the "slow after 90%" symptom — ~69 of
            # ~70 minutes in the Project stage on an 83k-entity workspace,
            # and severe enough that an external timeout watchdog marked a
            # genuinely-still-working ingestion job "failed" mid-run.
            self._graph.query("CREATE INDEX FOR (s:Source) ON (s.record_id)")
        except Exception as exc:  # noqa: BLE001 — perf optimization only
            logger.warning("falkor: failed to create index on Source.record_id, "
                           "provenance writes will fall back to full-scan MERGE: %s", exc)

    def ensure_indexes(self) -> int:
        """Create exact-match indexes for Entity lookups (idempotent).

        Indexes ``type``, ``name`` and every key-like lifted property observed
        during entity writes (``*_id``, ``guid``, ``variable_name``, ...).
        FalkorDB errors on duplicate index creation, so each statement is
        attempted independently and failures are treated as already-exists.
        ``id`` is indexed by clear(). Returns the number of CREATE INDEX
        statements that succeeded.
        """
        created = 0
        for prop in sorted({"type", "name"} | self._index_candidates):
            if not _LABEL_RE.match(prop):
                continue
            try:
                self._graph.query(f"CREATE INDEX FOR (e:Entity) ON (e.{prop})")
                created += 1
            except Exception as exc:  # noqa: BLE001 — duplicate index or unsupported
                logger.debug("falkor: index on Entity.%s not created: %s", prop, exc)
        logger.info("falkor: ensure_indexes created=%d candidates=%d",
                    created, len(self._index_candidates))
        return created

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

    def add_provenance(self, entity_id: int, system: str, dataset: str,
                       record_id: str) -> None:
        """Link an entity to the source record it was discovered in."""
        self._graph.query(
            "MERGE (s:Source {system: $sys, dataset: $ds, record_id: $rid}) "
            "WITH s MATCH (e:Entity {id: $id}) MERGE (e)-[:FROM]->(s)",
            {"sys": system, "ds": dataset, "rid": record_id, "id": entity_id},
        )

    def add_provenance_batch(
        self,
        rows: list[tuple[int, str, str, str]],
        batch_size: int = 500,
        on_batch: "Callable[[int], None] | None" = None,
    ) -> int:
        """Write multiple provenance links in batched UNWIND queries.

        Mirrors add_relationships_batch's UNWIND pattern (N/batch_size
        round-trips instead of N) and mirrors the Oracle graph store's
        existing add_provenance_batch — this was previously a
        FalkorDB-specific gap, not a deliberate cross-backend design
        choice. Combined with the Source.record_id index added in
        clear(), this is what actually closes the ~69-minute quadratic
        tail documented in docs/CPQ_INGESTION_PROJECTION_PERFORMANCE_PLAN.md
        — the index alone fixes the growth curve; batching removes the
        remaining per-row round-trip overhead on top of that.

        on_batch — optional callback invoked with the running total of rows
        written after each batch, for sub-progress reporting (see
        project.py's use of this in project_graph/project_incremental).
        """
        written = 0
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            params = [
                {"sys": sys_, "ds": ds, "rid": rid, "id": eid}
                for eid, sys_, ds, rid in chunk
            ]
            self._graph.query(
                "UNWIND $rows AS r "
                "MERGE (s:Source {system: r.sys, dataset: r.ds, record_id: r.rid}) "
                "WITH s, r MATCH (e:Entity {id: r.id}) MERGE (e)-[:FROM]->(s)",
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

    def add_relationship(self, source_id: int, target_id: int, name: str) -> None:
        """Create a typed edge between two entities."""
        self._graph.query(
            "MATCH (a:Entity {id: $src}), (b:Entity {id: $tgt}) "
            "MERGE (a)-[:REL {name: $name}]->(b)",
            {"src": source_id, "tgt": target_id, "name": name},
        )

    def add_relationships_batch(
        self,
        rels: list[tuple[int, int, str]],
        batch_size: int = 500,
    ) -> int:
        """Write multiple relationships in batched UNWIND queries.

        Uses UNWIND so N relationships cost ceil(N/batch_size) round-trips
        instead of N. Returns count of relationships written.
        """
        written = 0
        for i in range(0, len(rels), batch_size):
            chunk = rels[i : i + batch_size]
            params = [{"src": s, "tgt": t, "name": n} for s, t, n in chunk]
            self._graph.query(
                "UNWIND $rels AS rel "
                "MATCH (a:Entity {id: rel.src}), (b:Entity {id: rel.tgt}) "
                "MERGE (a)-[:REL {name: rel.name}]->(b)",
                {"rels": params},
            )
            written += len(chunk)
        return written
