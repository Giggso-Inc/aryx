"""Oracle ADB 26ai implementation of the backend-agnostic CPQ RDB accessor.

Split out of `cpq/rdb.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See rdb.py's module docstring for the dialect-split rationale.
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from aryx.config import get_settings
from aryx.cpq.rdb.rdb_function_scripts import CONTAINS
from aryx.cpq.rdb.rdb_helpers import _as_attrs, _as_int, _type_pattern
from aryx.cpq.rdb import rdb_workspace_tables
from aryx.cpq.rdb.rdb_postgres import PostgresCpqRdb, _warn_if_timeout
from aryx.raven_log import raven_log
from aryx.store.db_timeouts import oracle_call_timeout

if TYPE_CHECKING:
    from aryx.store.oracle_pool import OracleConnectionWrapper

logger = logging.getLogger(__name__)


def _read_failed(operation: str) -> None:
    """R7 -- an OracleCpqRdb fetch swallowed an error and returned empty: say so (ERROR P2).

    Call from inside the ``except`` block (reads the active exception)."""
    exc = sys.exc_info()[1]
    raven_log("ERROR", "P2", "ask.rdb.read_failed oracle CPQ rdb read failed, empty result returned",
              error_code="ARYX_ASK_RDB_READ_FAILED", context={
                  "dependency_name": "oracle_adb", "operation": operation, "result": "failed_empty_returned",
                  "error_class": type(exc).__name__ if exc is not None else "", "attempt": 1})


class OracleCpqRdb(PostgresCpqRdb):
    """Oracle ADB 26ai implementation — JSON_VALUE over the JSON column.

    Design-complete but not yet exercised by automated tests (the suite runs
    on FalkorDB + Postgres; see docs/CPQ_GRAPH_FIX_PLAN.md).
    """

    def _connection(self) -> Iterator["OracleConnectionWrapper"]:
        from aryx.store.oracle_pool import get_oracle_pool
        settings = get_settings()
        pool_cm = get_oracle_pool(settings.oci_adb_dsn).connection()
        if not settings.cpq_rdb_call_timeout_enabled:
            return pool_cm
        return self._bounded_oracle_connection(pool_cm, int(settings.cpq_rdb_call_timeout_ms))

    @staticmethod
    @contextmanager
    def _bounded_oracle_connection(pool_cm: Any, timeout_ms: int) -> Iterator["OracleConnectionWrapper"]:
        """Borrow a pooled connection with conn.call_timeout set; restore on exit."""
        with pool_cm as conn:
            with oracle_call_timeout(conn, timeout_ms):
                yield conn

    def fetch_entity_attributes(
        self, entity_ids: list[int], workspace_id: int,
    ) -> dict[int, dict[str, Any]]:
        if not entity_ids:
            return {}
        result: dict[int, dict[str, Any]] = {}
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    binds = ",".join(f":{i + 2}" for i in range(len(entity_ids)))
                    cur.execute(
                        f"SELECT id, attributes FROM aryx_entity "
                        f"WHERE workspace_id = :1 AND id IN ({binds})",
                        (workspace_id, *entity_ids),
                    )
                    for eid, attrs in cur.fetchall():
                        result[int(eid)] = _as_attrs(attrs)
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): attribute fetch failed", exc_info=True)
            _read_failed("fetch_entity_attributes")
        return result

    def fetch_entities_by_type(
        self, workspace_id: int, type_suffix: str, catalog_prefix: str = "",
    ) -> list[tuple[int, dict[str, Any]]]:
        rows: list[tuple[int, dict[str, Any]]] = []
        pattern = (
            _type_pattern(catalog_prefix, type_suffix.lower().replace("_", ""))
            if catalog_prefix else f"%{type_suffix.lower().replace('_', '')}"
        )
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, attributes FROM aryx_entity "
                        "WHERE workspace_id = :1 "
                        "AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2",
                        (workspace_id, pattern),
                    )
                    for eid, attrs in cur.fetchall():
                        rows.append((int(eid), _as_attrs(attrs)))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): type fetch failed", exc_info=True)
            _read_failed("fetch_entities_by_type")
        return rows or self._workspace_table_rows(workspace_id, type_suffix, suffix=True)

    def fetch_contained_entities(
        self, workspace_id: int, target_suffix: str, catalog_prefix: str = "",
    ) -> list[tuple[int, int, dict[str, Any]]]:
        """(source_id, target_id, target attributes) for CONTAINS links to a type."""
        pattern = _type_pattern(catalog_prefix, target_suffix)
        rows: list[tuple[int, int, dict[str, Any]]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT r.source_entity_id, r.target_entity_id, t.attributes "
                        "FROM aryx_relationship r JOIN aryx_entity t "
                        "ON t.workspace_id = r.workspace_id AND t.id = r.target_entity_id "
                        "WHERE r.workspace_id = :1 AND r.name = :2 "
                        "AND REPLACE(LOWER(t.ontology_type), '_', '') LIKE :3 "
                        "ORDER BY r.source_entity_id, r.target_entity_id",
                        (workspace_id, CONTAINS, pattern),
                    )
                    for src, tgt, attrs in cur.fetchall():
                        rows.append((int(src), int(tgt), _as_attrs(attrs)))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): contained fetch failed", exc_info=True)
            _read_failed("fetch_contained_entities")
        return rows

    def fetch_member_payloads(
        self, workspace_id: int, target_suffix: str, catalog_prefix: str = "",
    ) -> list[tuple[int, dict[str, Any]]] | None:
        """(entity_id, landed payload) per merged member record; None when the read fails."""
        pattern = _type_pattern(catalog_prefix, target_suffix)
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT m.entity_id, l.payload FROM aryx_entity_member m "
                        "JOIN aryx_entity e ON e.workspace_id = m.workspace_id AND e.id = m.entity_id "
                        "JOIN aryx_landed_record l ON l.id = m.landed_record_id "
                        "WHERE m.workspace_id = :1 "
                        "AND REPLACE(LOWER(e.ontology_type), '_', '') LIKE :2",
                        (workspace_id, pattern),
                    )
                    return [(int(eid), _as_attrs(payload)) for eid, payload in cur.fetchall()]
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): member payload fetch failed", exc_info=True)
            _read_failed("fetch_member_payloads")
            return None

    def fetch_entities_by_exact_type(
        self, workspace_id: int, ontology_type: str,
    ) -> list[tuple[int, dict[str, Any]]]:
        rows: list[tuple[int, dict[str, Any]]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, attributes FROM aryx_entity "
                        "WHERE workspace_id = :1 AND LOWER(ontology_type) = LOWER(:2)",
                        (workspace_id, ontology_type),
                    )
                    for eid, attrs in cur.fetchall():
                        rows.append((int(eid), _as_attrs(attrs)))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): exact type fetch failed", exc_info=True)
            _read_failed("fetch_entities_by_exact_type")
        return rows or self._workspace_table_rows(workspace_id, ontology_type, suffix=False)

    def _workspace_table_rows(
        self, workspace_id: int, logical: str, *, suffix: bool,
    ) -> list[tuple[int, dict[str, Any]]]:
        """No entity rows for this type: the CSV pipeline's ``ws<id>_<logical>`` table, if there is one (best effort)."""
        try:
            with self._connection() as conn:
                return rdb_workspace_tables.rows_for_type(conn, workspace_id, logical, suffix=suffix)
        except Exception as exc:  # noqa: BLE001  the engine treats missing table data as "no rows", never as an error
            _warn_if_timeout(exc, "oracle")
            logger.warning("cpq rdb(oracle): workspace table read failed ws=%s table=%r", workspace_id, logical, exc_info=True)
            _read_failed("fetch_workspace_table_rows")
            return []

    def fetch_workspace_table_groups(
        self, workspace_id: int, accept: Any, skip_types: Any = (),
    ) -> dict[str, list[tuple[int, dict[str, Any]]]]:
        """Rows of every CSV table loaded for this workspace whose columns satisfy ``accept`` (see rdb_workspace_tables)."""
        try:
            with self._connection() as conn:
                return rdb_workspace_tables.grouped_rows(conn, workspace_id, accept, skip_types)
        except Exception as exc:  # noqa: BLE001
            _warn_if_timeout(exc, "oracle")
            logger.warning("cpq rdb(oracle): workspace tables read failed ws=%s", workspace_id, exc_info=True)
            _read_failed("fetch_workspace_table_groups")
            return {}

    def fetch_all_entities_grouped_by_type(
        self, workspace_id: int,
    ) -> dict[str, list[tuple[int, dict[str, Any]]]]:
        """See PostgresCpqRdb.fetch_all_entities_grouped_by_type -- same
        contract, Oracle bind syntax. Confirmed live against workspace 704
        (109 types, ~300k entities): replaces the ~411s, 109-round-trip
        per-type scan with one query."""
        result: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT ontology_type, id, attributes FROM aryx_entity "
                        "WHERE workspace_id = :1",
                        (workspace_id,),
                    )
                    for otype, eid, attrs in cur.fetchall():
                        if not otype:
                            continue
                        result.setdefault(otype, []).append((int(eid), _as_attrs(attrs)))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): fetch_all_entities_grouped_by_type failed", exc_info=True)
            _read_failed("fetch_all_entities_grouped_by_type")
        return result

    def list_ontology_types(self, workspace_id: int) -> list[str]:
        types: list[str] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT DISTINCT ontology_type FROM aryx_entity "
                        "WHERE workspace_id = :1",
                        (workspace_id,),
                    )
                    types = [row[0] for row in cur.fetchall() if row[0]]
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): ontology type listing failed", exc_info=True)
            _read_failed("list_ontology_types")
        return types

    def fetch_rules(
        self, workspace_id: int, rule_type: str, catalog_prefix: str = "",
        active_only: bool = False, with_ref_id: bool = False,
    ) -> list[tuple]:
        """See the Postgres dialect; with_ref_id appends ref_id ("" if none)."""
        rows: list[tuple] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigrule")
        status_clause = (
            " AND JSON_VALUE(attributes, '$.status') = '1'" if active_only else ""
        )
        ref_col = (", JSON_VALUE(attributes, '$.ref_id')"
                   if with_ref_id else "")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id,
                               JSON_VALUE(attributes, '$.id'),
                               JSON_VALUE(attributes, '$.name'),
                               JSON_VALUE(attributes, '$.condition_function_id')""" + ref_col + """
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :3
                          AND JSON_VALUE(attributes, '$.rule_type') = :2
                        """ + status_clause,
                        (workspace_id, rule_type, type_pattern),
                    )
                    for row in cur.fetchall():
                        eid, src_id, name, fn_id = row[:4]
                        out = (int(eid), _as_int(src_id), name or "",
                               _as_int(fn_id) or -1)
                        rows.append(out + (str(row[4] or ""),) if with_ref_id else out)
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): rule fetch failed", exc_info=True)
            _read_failed("fetch_rules")
        return rows

    def fetch_value_rules(
        self, workspace_id: int, catalog_prefix: str = "",
        active_only: bool = False, with_ref_id: bool = False,
    ) -> list[tuple]:
        """See the Postgres dialect; with_ref_id appends ref_id ("" if none)."""
        rows: list[tuple] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigrule")
        status_clause = (
            " AND JSON_VALUE(attributes, '$.status') = '1'" if active_only else ""
        )
        ref_col = (", JSON_VALUE(attributes, '$.ref_id')"
                   if with_ref_id else "")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id,
                               JSON_VALUE(attributes, '$.id'),
                               JSON_VALUE(attributes, '$.name'),
                               JSON_VALUE(attributes, '$.rule_type'),
                               JSON_VALUE(attributes, '$.condition_function_id')""" + ref_col + """
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                          AND (JSON_VALUE(attributes, '$.rule_type') IS NULL
                               OR JSON_VALUE(attributes, '$.rule_type') != '11')
                        """ + status_clause,
                        (workspace_id, type_pattern),
                    )
                    for row in cur.fetchall():
                        eid, src_id, name, rule_type, fn_id = row[:5]
                        out = (int(eid), _as_int(src_id), name or "",
                               rule_type or "", _as_int(fn_id) or -1)
                        rows.append(out + (str(row[5] or ""),) if with_ref_id else out)
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): value-rule fetch failed", exc_info=True)
            _read_failed("fetch_value_rules")
        return rows

    def fetch_rule_inputs(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, str, str]]:
        """See the Postgres dialect's identical-contract docstring above for
        operator1's meaning and why it's now returned alongside value1."""
        rows: list[tuple[int, int, str, str]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigruleinput")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(JSON_VALUE(attributes, '$.bm_config_rule_id'),
                                        JSON_VALUE(attributes, '$.rule_id')),
                               JSON_VALUE(attributes, '$.attribute_id'),
                               JSON_VALUE(attributes, '$.value1'),
                               JSON_VALUE(attributes, '$.operator1')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, val, op in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, val or "", (op or "").strip()))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): rule-input fetch failed", exc_info=True)
            _read_failed("fetch_rule_inputs")
        return rows

    def fetch_rule_input_indexes(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, str, str, int]]:
        """BmConfigRuleInput rows with their ``rule_input_index``:
        (rule_id, condition_attr_id, value1, operator1, index). Used with
        ``fetch_rule_condition_expressions`` to evaluate a rule's
        ``condition_expression``; ``fetch_rule_inputs`` is unchanged."""
        rows: list[tuple[int, int, str, str, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigruleinput")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(JSON_VALUE(attributes, '$.bm_config_rule_id'),
                                        JSON_VALUE(attributes, '$.rule_id')),
                               JSON_VALUE(attributes, '$.attribute_id'),
                               JSON_VALUE(attributes, '$.value1'),
                               JSON_VALUE(attributes, '$.operator1'),
                               JSON_VALUE(attributes, '$.rule_input_index')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, val, op, idx in cur.fetchall():
                        rid_i, aid_i, idx_i = _as_int(rid), _as_int(aid), _as_int(idx)
                        if rid_i and aid_i and idx_i:
                            rows.append((rid_i, aid_i, val or "", (op or "").strip(), idx_i))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): rule-input index fetch failed", exc_info=True)
            _read_failed("fetch_rule_input_indexes")
        return rows

    def fetch_rule_condition_expressions(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> dict[int, str]:
        """BM-native rule id -> ``condition_expression`` (only non-empty)."""
        out: dict[int, str] = {}
        type_pattern = _type_pattern(catalog_prefix, "bmconfigrule")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT JSON_VALUE(attributes, '$.id'), JSON_VALUE(attributes, '$.condition_expression' RETURNING VARCHAR2(4000))
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, expr in cur.fetchall():
                        rid_i = _as_int(rid)
                        if rid_i and isinstance(expr, str) and expr.strip():
                            out[rid_i] = expr.strip()
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): rule-expression fetch failed", exc_info=True)
            _read_failed("fetch_rule_condition_expressions")
        return out

    def fetch_rule_actions(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, int, str, int, int, str]]:
        rows: list[tuple[int, int, int, str, int, int, str]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigruleaction")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(JSON_VALUE(attributes, '$.bm_config_rule_id'),
                                        JSON_VALUE(attributes, '$.rule_id')),
                               JSON_VALUE(attributes, '$.attribute_id'),
                               JSON_VALUE(attributes, '$.action_type'),
                               JSON_VALUE(attributes, '$.value1'),
                               JSON_VALUE(attributes, '$.function_id'),
                               JSON_VALUE(attributes, '$.set_type'),
                               JSON_VALUE(attributes, '$.comments')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, at, val, fn, st, comments in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, _as_int(at) or 0,
                                         val or "", _as_int(fn) or -1,
                                         _as_int(st) if _as_int(st) is not None else 0,
                                         comments or ""))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): rule-action fetch failed", exc_info=True)
            _read_failed("fetch_rule_actions")
        return rows

    def fetch_marked_attrs(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int]]:
        rows: list[tuple[int, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigmarkedattr")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(JSON_VALUE(attributes, '$.bm_config_rule_id'),
                                        JSON_VALUE(attributes, '$.rule_id')),
                               JSON_VALUE(attributes, '$.attribute_id')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): marked-attr fetch failed", exc_info=True)
            _read_failed("fetch_marked_attrs")
        return rows

    def fetch_rule_chain_links(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int]]:
        rows: list[tuple[int, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigruleassoc")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(JSON_VALUE(attributes, '$.bm_config_rule_id'),
                                        JSON_VALUE(attributes, '$.rule_id')),
                               JSON_VALUE(attributes, '$.child_rule_id')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, cid in cur.fetchall():
                        rid_i, cid_i = _as_int(rid), _as_int(cid)
                        if rid_i and cid_i:
                            rows.append((rid_i, cid_i))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): rule-chain fetch failed", exc_info=True)
            _read_failed("fetch_rule_chain_links")
        return rows

    def fetch_layout_attr_assoc(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, int]]:
        rows: list[tuple[int, int, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfiglayoutattrassoc")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT JSON_VALUE(attributes, '$.rule_id'),
                               JSON_VALUE(attributes, '$.attr_id'),
                               JSON_VALUE(attributes, '$.layout_model_id')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, lmid in cur.fetchall():
                        rid_i, aid_i, lmid_i = _as_int(rid), _as_int(aid), _as_int(lmid)
                        if aid_i and lmid_i:
                            rows.append((rid_i or 0, aid_i, lmid_i))
        except Exception as exc:
            _warn_if_timeout(exc, "oracle")
            logger.debug("cpq rdb(oracle): layout-attr-assoc fetch failed", exc_info=True)
            _read_failed("fetch_layout_attr_assoc")
        return rows
