"""Persistence + record loading for entity resolution (stage 7).

Reads a run's landed records (building match text from key attributes) and
writes resolved entities plus their provenance members. SQL lives in queries/.

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), the identity
sequence + JSON-encode helpers live in `store.entity_store_ids` and are
re-imported here so existing whitebox patches on
`aryx.store.entity_store._fetch_entity_ids`/`_dumps` keep working unchanged
(EntityStore's own methods call them by bare name, which resolves via this
module's namespace). EntityStore itself stays whole: its ~25 methods share
`self._pool`/`self._ws` and 5 test files patch `aryx.store.entity_store.
get_pool`/`get_settings`/`load` across dozens of call sites inside those
methods — splitting the class into separate files would require retargeting
every one of those patches with no reliable way to verify all sites by
inspection, so it is kept as a deliberate, documented exception.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from psycopg.types.json import Json

from aryx.models import (
    EntityMember,
    Relationship,
    ResolutionRecord,
    ResolvedEntity,
)
from aryx.config import get_settings
from aryx.raven_log import raven_log, would_log
from aryx.queries import load
from aryx.store.entity_store_ids import _dumps, _fetch_entity_ids
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)

Progress = Callable[[str, int, str], None]


def _safe_progress(on_progress: Progress | None, stage: str, pct: int, detail: str) -> None:
    """Call on_progress without letting a heartbeat failure affect the caller.

    PR review N4 (2026-10-04): save_relationships()'s on_progress call used
    to run INSIDE the same transaction as the inserts it was reporting on --
    a failure in the heartbeat itself (e.g. a job-row update error from a
    transient DB hiccup on a DIFFERENT connection/pool) would propagate out
    of the `with self._pool.connection()` block, rolling back every batch
    already committed-in-spirit within this call and failing an otherwise
    healthy save. A heartbeat is purely observational -- it must never be
    able to do that. Used by both save() and save_relationships().
    """
    if on_progress is None:
        return
    try:
        on_progress(stage, pct, detail)
    except Exception:  # noqa: BLE001 -- heartbeat is best-effort, never masks real work
        logger.warning("entity_store: on_progress heartbeat failed, continuing", exc_info=True)

# Diagnostic for the 2026-09-16 confirm-job incident: a documents-source
# confirm failed with Postgres's "string too long to represent as jsonb
# string" (a single JSONB scalar string over 268435455 bytes). Every per-
# record/per-merge path upstream (chunk_pages' hard character-count slicing,
# extract_mentions' per-chunk LLM payloads, both survivorship merge paths)
# was traced and proven bounded well under this by static analysis -- none
# of them explained it. The client holds the actual failing document, so
# this can't be reproduced locally; logging the real oversized attribute
# key at the point of failure (well before Postgres's hard limit) is the
# fastest way to find it without needing the file itself. Diagnostic only:
# logs and continues, never truncates or otherwise changes what gets saved.
_ATTR_SIZE_WARN_BYTES = 5 * 1024 * 1024


def _log_oversized_entity_attributes(ontology_type: str, attributes: dict[str, Any]) -> None:
    """PR #334 review (N2): this runs on every entity in every save batch,
    so the common case (small, string-valued attributes -- the overwhelming
    majority in this ingestion path) must stay cheap. A str/bytes value's
    own length is already a close-enough proxy for its json.dumps length
    (quoting/escaping adds a little, irrelevant at the MB-plus scale this
    diagnostic cares about) -- skip the full serialize for those, and only
    pay for an exact json.dumps once, on the actual largest value, if the
    cheap total already crossed the warn threshold.
    """
    try:
        total = 0
        worst_key: str | None = None
        worst_size = 0
        for key, value in attributes.items():
            size = len(value) if isinstance(value, (str, bytes)) else len(json.dumps(value, default=str))
            total += size
            if size > worst_size:
                worst_size, worst_key = size, key
        if total > _ATTR_SIZE_WARN_BYTES:
            worst_value = attributes.get(worst_key)
            exact_size = (
                len(worst_value) if isinstance(worst_value, (str, bytes))
                else len(json.dumps(worst_value, default=str))
            )
            logger.warning(
                "entity attributes unusually large: ontology_type=%s total_bytes=%d "
                "largest_key=%r largest_key_bytes=%d all_keys=%r",
                ontology_type, total, worst_key, exact_size, list(attributes.keys()),
            )
    except Exception:  # noqa: BLE001 -- diagnostic must never break a real save
        logger.debug("oversized-attribute diagnostic failed", exc_info=True)


class EntityStore:
    """Loads landed records and persists resolved entities + members."""

    def __init__(self, dsn: str, workspace_id: int = 1) -> None:
        """Acquire the shared connection pool for this DSN."""
        self._pool = get_pool(dsn)
        self._ws = workspace_id

    def landed_records(self, run_id: int, key_attrs: list[str]) -> list[ResolutionRecord]:
        """Read a run's landed records, building match text from key attributes.

        Args:
            run_id: The discovery run to load.
            key_attrs: Payload keys whose values form the match text.

        Returns:
            One ResolutionRecord per landed row.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_landed_by_run"), (run_id, self._ws))
                rows = cur.fetchall()
        records = []
        for record_id, payload, source_system, cleaned_at in rows:
            if isinstance(payload, str):
                payload = json.loads(payload)
            text = " ".join(str(payload.get(a, "")) for a in key_attrs).strip()
            records.append(ResolutionRecord(
                record_id=record_id, text=text, payload=payload,
                source_system=source_system, cleaned_at=cleaned_at,
            ))
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.resolve.records_loaded landed records loaded for resolve",
                      context={"task_id": run_id, "stage": "resolve", "workspace_id": self._ws,
                               "records": len(records), "match_key_attrs": list(key_attrs),
                               "empty_match_text": sum(1 for r in records if not r.text)})
        return records

    def entity_ids_by_run(self, run_id: int) -> dict[str, int]:
        """Map each landed record's original ``source_record_id`` to the
        resolved entity id it ended up a member of, for one run.

        Built for cpq_ingestion's raw-graph resolve/relate bridge: ``save()``
        only returns a count, not per-record entity ids, so this is the
        supported way to recover "which entity did record X resolve into"
        after the fact -- a plain join through ``aryx_entity_member``, scoped
        to one run so it stays cheap even in a workspace with a long
        ingestion history. Records that were dropped during resolution
        (e.g. rejected below ``er_review``) simply have no entry here.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_entity_ids_by_run"), (run_id, self._ws))
                rows = cur.fetchall()
        return {source_record_id: entity_id for source_record_id, entity_id in rows}

    def save(self, results: list[tuple[ResolvedEntity, list[EntityMember]]], *,
              on_progress: Progress | None = None, batch_size: int = 5000) -> int:
        """Persist resolved entities and their provenance members.

        Returns the number of entities written.

        on_progress (PR review N1, 2026-10-04): previously one unbatched
        call regardless of result-set size -- resolve_entities.py reports
        "Resolve" 58% right before calling this, then nothing until
        orchestrate.py's own 62% checkpoint once this returns. At the
        documented ~0.5ms/row landing rate, saving a tag's full 440k
        entities (the production file this was built against) is several
        minutes with no heartbeat at all, well inside the 10-minute
        heartbeat-sweep window this project already has reason to take
        seriously (see save_relationships' own docstring for the same
        concern). Chunked into batch_size-row groups -- each chunk still
        goes through the existing 2-3-round-trip bulk path
        (_save_batch/_save_batch_postgres), just over fewer rows at a time
        -- with a real done/total progress checkpoint between chunks,
        scaled into the 58-62% band orchestrate.py already reserves for
        this call. See _safe_progress's docstring (N4) for why the
        heartbeat itself can never fail this call.
        """
        if not results:
            raven_log("DEBUG", "P4", "ingest.resolve.save_skipped no entities to save",
                      context={"stage": "resolve", "workspace_id": self._ws, "selected_option": "skip",
                               "available_options": ["save", "skip"], "reason_code": "EMPTY_RESULTS"})
            return 0
        _backend = get_settings().effective_db_backend()
        total = len(results)
        raven_log("DEBUG", "P4", "ingest.resolve.save_batch entity save path chosen",
                  context={"stage": "resolve", "workspace_id": self._ws, "entities": total,
                           "members": sum(len(m) for _, m in results),
                           "selected_option": "oracle_batch" if _backend == "oci" else "postgres_batch",
                           "available_options": ["oracle_batch", "postgres_batch"],
                           "reason_code": "EFFECTIVE_DB_BACKEND_" + str(_backend).upper()})
        created = 0
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for start in range(0, total, batch_size):
                    chunk = results[start:start + batch_size]
                    if _backend == "oci":
                        created += self._save_batch(cur, chunk)
                    else:
                        created += self._save_batch_postgres(cur, chunk)
                    done = min(start + batch_size, total)
                    _safe_progress(on_progress, "Resolve", 58 + int(4 * done / total),
                                   f"{done}/{total} entities saved")
        return created

    def _save_batch(self, cur: Any, results: list[tuple[ResolvedEntity, list[EntityMember]]]) -> int:
        """Oracle path: 3 round-trips for any batch size.

        1. Fetch N IDs from the identity sequence (1 round-trip).
        2. Bulk-insert all entities with explicit IDs via executemany (1 round-trip).
        3. Bulk-insert all members via executemany (1 round-trip).
        Conflicts add 1 more round-trip only when present.
        """
        total = len(results)
        logger.info("entities save batch start count=%d", total)

        entity_ids = _fetch_entity_ids(cur, total)
        logger.info("entities ids fetched count=%d", total)

        entity_rows = []
        for eid, (entity, _) in zip(entity_ids, results):
            _log_oversized_entity_attributes(entity.ontology_type, entity.attributes)
            entity_rows.append((
                eid, self._ws, entity.ontology_type,
                Json(entity.attributes, dumps=_dumps), entity.confidence,
            ))
        if entity_rows:
            cur.executemany(load("insert_entity"), entity_rows)
        logger.info("entities inserted %d (bulk)", total)

        member_rows = [
            (self._ws, eid, m.landed_record_id, m.confidence)
            for eid, (_, members) in zip(entity_ids, results)
            for m in members
        ]
        if member_rows:
            cur.executemany(load("insert_entity_member"), member_rows)
            logger.info("members inserted %d", len(member_rows))

        conflict_rows = [
            (self._ws, eid, c["attribute"],
             Json(c["winning_value"], dumps=_dumps),
             Json(c["losing_values"], dumps=_dumps),
             c["strategy"])
            for eid, (entity, _) in zip(entity_ids, results)
            for c in (entity.conflicts or [])
        ]
        if conflict_rows:
            cur.executemany(load("insert_attribute_conflict"), conflict_rows)
            logger.info("conflicts inserted %d", len(conflict_rows))

        logger.info("entities save batch complete count=%d members=%d conflicts=%d",
                    total, len(member_rows), len(conflict_rows))
        return total

    def _save_batch_postgres(
        self, cur: Any, results: list[tuple[ResolvedEntity, list[EntityMember]]],
    ) -> int:
        """PostgreSQL path: 2 round-trips for any batch size (mirrors _save_batch).

        Previously this ran one execute() + fetchone() per entity, plus one
        more execute() per member/conflict — for a large batch (e.g. 300K+
        entities from a single tabular sheet) that's hundreds of thousands
        of individual round-trips, easily hours. Fetching N ids from the
        BIGSERIAL sequence in one round-trip, then bulk-inserting entities
        and members via executemany, removes that scaling wall entirely —
        cost no longer grows with row count beyond the executemany payload
        itself.

        1. Fetch N ids from aryx_entity's id sequence in one round-trip
           (pg_get_serial_sequence resolves the sequence name inline — no
           separate lookup+cache needed, unlike the Oracle path).
        2. Bulk-insert all entities with explicit ids via executemany.
        3. Bulk-insert all members via executemany.
        Conflicts add 1 more round-trip only when present.
        """
        total = len(results)
        logger.info("entities save batch start count=%d", total)

        cur.execute(load("select_next_entity_ids"), (total,))
        entity_ids = [row[0] for row in cur.fetchall()]
        logger.info("entities ids fetched count=%d", total)

        entity_rows = []
        for eid, (entity, _) in zip(entity_ids, results):
            _log_oversized_entity_attributes(entity.ontology_type, entity.attributes)
            entity_rows.append((
                eid, self._ws, entity.ontology_type,
                Json(entity.attributes, dumps=_dumps), entity.confidence,
            ))
        if entity_rows:
            cur.executemany(load("insert_entity_with_id"), entity_rows)
        logger.info("entities inserted %d (bulk)", total)

        member_rows = [
            (self._ws, eid, m.landed_record_id, m.confidence)
            for eid, (_, members) in zip(entity_ids, results)
            for m in members
        ]
        if member_rows:
            cur.executemany(load("insert_entity_member"), member_rows)
            logger.info("members inserted %d", len(member_rows))

        conflict_rows = [
            (self._ws, eid, c["attribute"],
             Json(c["winning_value"], dumps=_dumps),
             Json(c["losing_values"], dumps=_dumps),
             c["strategy"])
            for eid, (entity, _) in zip(entity_ids, results)
            for c in (entity.conflicts or [])
        ]
        if conflict_rows:
            cur.executemany(load("insert_attribute_conflict"), conflict_rows)
            logger.info("conflicts inserted %d", len(conflict_rows))

        logger.info("entities save batch complete count=%d members=%d conflicts=%d",
                    total, len(member_rows), len(conflict_rows))
        return total

    def save_relationships(self, relationships: list[Relationship], *,
                          on_progress: Progress | None = None,
                          batch_size: int = 5000) -> None:
        """Persist inferred relationships between entities (stage 8).

        on_progress (PR review, 2026-10-04): a large relationship set
        previously went through ONE unbatched executemany -- no heartbeat
        for however long that single call took. Combined with §0's
        heartbeat-sweep watchdog (JobStore.sweep_stale_heartbeat), that
        silence was long enough to get a perfectly healthy caller (e.g.
        cpq_ingestion's resolve_and_relate_raw_graph, after its last tag
        finishes) killed. Chunking into batch_size-row executemany calls
        with a checkpoint between each gives the same per-batch heartbeat
        cadence BatchSink's landing writes already have -- default
        batch_size chosen to match BatchSink's own executemany-cost
        profile, not because relationship rows are expensive individually.
        pct is real (done/total), unlike the indeterminate heartbeats
        elsewhere in this review round, since the total is known upfront.

        PR review N4 (2026-10-04): on_progress used to be called directly,
        inside the same transaction as the inserts -- a heartbeat failure
        (e.g. a transient error from the job-row update it typically
        triggers, on a completely different connection/pool) would
        propagate out of this method's `with self._pool.connection()`
        block and roll back every batch already inserted in this call,
        failing an otherwise-healthy save over a purely observational
        side effect. Routed through _safe_progress, which never lets an
        on_progress exception escape.
        """
        if not relationships:
            return
        total = len(relationships)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for start in range(0, total, batch_size):
                    batch = relationships[start:start + batch_size]
                    cur.executemany(
                        load("insert_relationship"),
                        [(self._ws, r.source_entity_id, r.target_entity_id,
                          r.name, r.confidence) for r in batch],
                    )
                    done = min(start + batch_size, total)
                    _safe_progress(on_progress, "Relate", int(100 * done / total),
                                   f"{done}/{total} relationships saved")

    def list_entities_typed_sample(self, n_per_type: int) -> list[tuple[int, str, dict]]:
        """Return up to *n_per_type* entities for EACH ontology type in the workspace.

        Uses a window function (PARTITION BY ontology_type) so every type is
        represented even when one type has millions of rows.  The caller gets
        a balanced sample suitable for cross-type relationship inference.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_entities_typed_sample"), (self._ws, n_per_type))
                return [(r[0], r[1], r[2]) for r in cur.fetchall()]

    def conflict_aliases(self, attribute: str) -> dict[str, int]:
        """Map every historical *losing* value of `attribute` to the entity
        that absorbed it during survivorship merge.

        Entity resolution can merge two records sharing a near-identical
        `attribute` value into one entity, keeping only one winner
        (aryx_attribute_conflict.winning_value) and discarding the rest as
        losing_values. Anything that referenced a since-discarded value by
        exact match (e.g. an FK column pointing at the old value) would
        silently fail to link post-merge without this — see link_by_attribute.
        """
        aliases: dict[str, int] = {}
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_conflict_losing_values"), (self._ws, attribute))
                for entity_id, losing_values in cur.fetchall():
                    for lv in losing_values or []:
                        val = lv.get("value") if isinstance(lv, dict) else None
                        if val:
                            aliases[str(val).strip().lower()] = entity_id
        return aliases

    def overview_inputs(
        self,
    ) -> tuple[list[tuple[int, str, dict[str, Any]]], list[tuple[int, int, str]], dict[str, Any]]:
        """Return brief, entities, and relationships for /graph/overview in one store path."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_workspace_brief"), (self._ws,))
                row = cur.fetchone()
                brief = (row[0] or {}) if row else {}

            with conn.cursor() as cur:
                cur.execute(load("select_entities"), (self._ws,))
                entities = [(r[0], r[1], r[2]) for r in cur.fetchall()]

            with conn.cursor() as cur:
                cur.execute(load("select_relationships"), (self._ws,))
                relationships = [(r[0], r[1], r[2]) for r in cur.fetchall()]

        return entities, relationships, brief

    def count_entities(self) -> int:
        """Return the total number of entities in this workspace."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("count_entities"), (self._ws,))
                return int(cur.fetchone()[0])

    def list_entities(self) -> Iterator[tuple[int, str, dict]]:
        """Yield (id, ontology_type, attributes) for graph projection.

        Server-side named cursor + generator: only one batch is held in Python
        memory at a time. Callers that need full-list semantics (len, indexing,
        multiple passes) must materialise explicitly: list(store.list_entities()).
        """
        batch_size = get_settings().batch_size
        with self._pool.connection() as conn:
            with conn.cursor(f"list_entities_cur_{self._ws}_{uuid.uuid4().hex[:8]}") as cur:
                cur.execute(load("select_entities"), (self._ws,))
                while batch := cur.fetchmany(batch_size):
                    yield from ((r[0], r[1], r[2]) for r in batch)

    def list_members_provenance(self) -> Iterator[tuple[int, str, str, str]]:
        """Yield (entity_id, system, dataset, record_id) provenance edges.

        See list_entities() for the streaming / materialise contract.
        """
        batch_size = get_settings().batch_size
        with self._pool.connection() as conn:
            with conn.cursor(f"list_provenance_cur_{self._ws}_{uuid.uuid4().hex[:8]}") as cur:
                cur.execute(load("select_members_provenance"), (self._ws,))
                while batch := cur.fetchmany(batch_size):
                    yield from ((r[0], r[1], r[2], r[3]) for r in batch)

    def list_source_payloads(
        self,
        source_system: str,
        source_dataset: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return landed payloads for one source dataset."""
        query_name = "select_landed_by_source_limited" if limit is not None else "select_landed_by_source"
        params: tuple[Any, ...]
        if limit is None:
            params = (self._ws, source_system, source_dataset)
        else:
            params = (self._ws, source_system, source_dataset, int(limit))
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load(query_name), params)
                rows = cur.fetchall()
        payloads: list[dict[str, Any]] = []
        for _record_id, payload, _system, _dataset, _source_record_id in rows:
            if isinstance(payload, str):
                payload = json.loads(payload)
            payloads.append(payload or {})
        return payloads

    def list_source_activity(self) -> dict[tuple[str, str], Any]:
        """Return the latest landed-record timestamp per source dataset."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_latest_source_activity"), (self._ws,))
                return {
                    (str(row[0]), str(row[1])): row[2]
                    for row in cur.fetchall()
                }

    def list_isolated_entities(self) -> list[tuple[int, str, dict]]:
        """Return entities that have no relationship edges (source or target).

        Single anti-join query — replaces the two-scan pattern of materialising
        all relationships then all entities and diffing in Python.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_isolated_entities"), (self._ws, self._ws))
                return [(r[0], r[1], r[2]) for r in cur.fetchall()]

    def list_relationships(self) -> Iterator[tuple[int, int, str]]:
        """Yield (source_entity_id, target_entity_id, name) edges.

        See list_entities() for the streaming / materialise contract.
        """
        batch_size = get_settings().batch_size
        with self._pool.connection() as conn:
            with conn.cursor(f"list_relationships_cur_{self._ws}_{uuid.uuid4().hex[:8]}") as cur:
                cur.execute(load("select_relationships"), (self._ws,))
                while batch := cur.fetchmany(batch_size):
                    yield from ((r[0], r[1], r[2]) for r in batch)

    def match_entities(self, when: dict) -> Iterator[dict[str, Any]]:
        """Yield entities matching a rule when-clause, pushes type+attr into SQL.

        Filters by ontology_type equality and attribute-key existence in the
        database so only candidate rows reach Python. The op/value comparison
        runs in the caller (_match) to preserve edge-case handling (TypeError,
        None values). Yields dicts with keys: id, type, attributes.

        See list_entities() for the streaming / materialise contract.
        """
        entity_type = when.get("type") or None
        attr = when.get("attr") or None
        batch_size = get_settings().batch_size
        with self._pool.connection() as conn:
            with conn.cursor(f"match_entities_cur_{self._ws}_{uuid.uuid4().hex[:8]}") as cur:
                cur.execute(
                    load("select_entities_matching"),
                    (self._ws, entity_type, entity_type, attr, attr),
                )
                while batch := cur.fetchmany(batch_size):
                    yield from (
                        {"id": r[0], "type": r[1], "attributes": r[2]}
                        for r in batch
                    )

    def clear_relationships(self) -> int:
        """Delete all relationships for this workspace; return rows removed.

        Makes re-deriving FK edges idempotent (link_by_attribute appends).
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("delete_relationships"), (self._ws,))
                return cur.rowcount

    def get_entity(self, entity_id: int) -> tuple[int, str, dict] | None:
        """Return (id, ontology_type, attributes) for one entity, or None."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_entity_by_id"), (entity_id, self._ws))
                row = cur.fetchone()
        return (int(row[0]), str(row[1]), row[2]) if row else None

    def create_entity(self, ontology_type: str, attributes: dict,
                      confidence: float = 1.0) -> int:
        """Insert a single entity and return its new id."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                if get_settings().effective_db_backend() == "oci":
                    # queries/oracle/insert_entity.sql takes an explicit id
                    # (5 params, no RETURNING) -- unlike the Postgres/generic
                    # 4-param RETURNING version, since Oracle's BIGSERIAL
                    # equivalent is fetched up front (same pattern as
                    # _save_batch's bulk path via _fetch_entity_ids).
                    entity_id = _fetch_entity_ids(cur, 1)[0]
                    cur.execute(
                        load("insert_entity"),
                        (entity_id, self._ws, ontology_type,
                         Json(attributes, dumps=_dumps), confidence),
                    )
                else:
                    cur.execute(
                        load("insert_entity"),
                        (self._ws, ontology_type, Json(attributes, dumps=_dumps), confidence),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise RuntimeError(f"insert_entity returned no row — workspace {self._ws}")
                    entity_id = int(row[0])
        logger.info("entity created ws=%s id=%s type=%s", self._ws, entity_id, ontology_type)
        return entity_id

    def update_entity(self, entity_id: int,
                      attributes: dict) -> tuple[str, dict] | None:
        """Replace attributes for one entity; return (ontology_type, stored_attributes) or None."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("update_entity_attributes"),
                    (Json(attributes, dumps=_dumps), entity_id, self._ws),
                )
                row = cur.fetchone()
        if not row:
            return None
        logger.info("entity updated ws=%s id=%s", self._ws, entity_id)
        # row: (id, ontology_type, attributes) — use stored value, not the input dict
        return (str(row[1]), row[2])

    def delete_entity(self, entity_id: int) -> bool:
        """Delete one entity and its aryx_entity_member rows; return True if the entity row was removed.

        Members deleted first, in the same transaction as the entity row
        (§5 of docs/ingestion/CPQ_XML_CONFIRM_RESOLVE_PERFORMANCE_ISSUES_
        2026-10-04.md -- previously left as permanent orphans referencing a
        now-nonexistent entity_id, consistent across this and the other two
        delete methods below). Postgres's aryx_entity_member.entity_id has a
        plain FK to aryx_entity (no ON DELETE CASCADE) -- deleting the
        entity row first would raise a foreign-key violation while member
        rows for it still exist, so members must go first regardless of
        backend (Oracle has no FK here, but the same order keeps both
        backends' behavior identical).
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("delete_entity_members_by_id"), (self._ws, entity_id))
                cur.execute(load("delete_entity_row"), (entity_id, self._ws))
                removed = cur.rowcount > 0
        if removed:
            logger.info("entity deleted ws=%s id=%s", self._ws, entity_id)
        return removed

    _DELETE_CHUNK_SIZE = 20_000

    def delete_entities(self, entity_ids: list[int]) -> int:
        """Delete several entities in chunked round-trips; returns the count removed.

        cpq_ingestion's raw-graph resolve/relate cancellation cleanup (PR
        #429 review N1) used to call delete_entity() once per id -- fine for
        a handful of entities, but a cancel after many tags on a large file
        could mean many individual round-trips, undermining the whole point
        of a prompt cancel. One DELETE with an id list, same %(entity_ids)s
        array-param pattern delete_impacted_entities.sql already uses
        (source_purge_repair.py), removes that per-id cost.

        Chunked at _DELETE_CHUNK_SIZE (PR #429 review N1 round 2): a single
        unbounded id list means one huge JSON/array bind and one
        long-running DELETE for the largest attempts this PR's cancellation
        support targets (the 5.85M-node upload) -- the same "cancel should
        be prompt, not eventually" concern driving this whole cleanup in
        the first place. Each chunk is its own round-trip so a slow cleanup
        is at least bounded per-chunk, not one unbreakable statement.
        """
        if not entity_ids:
            return 0
        ids = list(entity_ids)
        removed = 0
        for i in range(0, len(ids), self._DELETE_CHUNK_SIZE):
            chunk = ids[i:i + self._DELETE_CHUNK_SIZE]
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    # Members first, same chunk/transaction -- see
                    # delete_entity()'s docstring for why the order matters.
                    cur.execute(load("delete_entity_members_by_ids"), {
                        "workspace_id": self._ws, "entity_ids": chunk,
                    })
                    cur.execute(load("delete_entities_by_ids"), {
                        "workspace_id": self._ws, "entity_ids": chunk,
                    })
                    removed += cur.rowcount
        if removed:
            logger.info("entities deleted ws=%s count=%d", self._ws, removed)
        return removed

    def delete_entities_by_type(self, ontology_type: str) -> list[int]:
        """Delete all entities of a type and their aryx_entity_member rows; return the list of deleted ids.

        Always selects ids first now (previously only done on the Oracle
        branch, to work around python-oracledb rejecting fetchall() after a
        DELETE with DPY-1003 -- see the git history for that rationale).
        The id list is used only for the RETURN VALUE -- member cleanup
        (§5, then PR review round 4 N1, 2026-10-04) deletes by a subquery
        on the same workspace_id/ontology_type predicate instead of an id
        list, for two reasons the id-list approach got wrong: (1) a type
        with hundreds of thousands of entities meant one huge, unchunked
        ANY(array)/JSON_TABLE bind -- every other multi-id delete in this
        file chunks at _DELETE_CHUNK_SIZE for exactly this reason, and this
        was the one exception; (2) an entity of this type inserted
        concurrently, between the id SELECT above and the delete, would
        still match the final `DELETE ... WHERE ontology_type = ...` below
        (same predicate, evaluated fresh) but was never in the id list, so
        its members would have been silently left as orphans. A subquery
        re-evaluated at DELETE time against the live predicate has neither
        problem. Deleting members BEFORE the entities themselves, same
        transaction, for the same FK-ordering reason as delete_entity()'s
        docstring.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_entity_ids_by_type"), (self._ws, ontology_type))
                ids = [int(r[0]) for r in cur.fetchall()]
                cur.execute(load("delete_entity_members_by_type"),
                           (self._ws, self._ws, ontology_type))
                cur.execute(load("delete_entities_by_type"), (self._ws, ontology_type))
        logger.info("entities deleted ws=%s type=%s count=%d", self._ws, ontology_type, len(ids))
        return ids

    def close(self) -> None:
        """No-op: connections are managed by the shared pool (G12)."""
