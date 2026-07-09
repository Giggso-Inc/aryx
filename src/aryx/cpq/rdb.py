"""Backend-agnostic RDB access for the CPQ engine (Postgres + Oracle ADB).

The CPQ engine reads entity attributes and rule definitions from the
relational store. Postgres stores them in a JSONB column queried with
``attributes->>'key'``; Oracle ADB 23ai stores a JSON column queried with
``JSON_VALUE(attributes, '$.key')``. This module hides that dialect split so
no raw backend-specific SQL lives in ``cpq/``.

All methods return plain Python data; JSON decoding and type coercion happen
here. Failures are logged and surface as empty results — the CPQ engine
treats missing rule data as "no rules", never as a hard error.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from aryx.config import get_settings

logger = logging.getLogger(__name__)


def _as_int(val: Any) -> int | None:
    """Coerce a JSON-extracted value to int, or None."""
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return None


def _as_attrs(raw: Any) -> dict[str, Any]:
    """Coerce a JSON/JSONB column value to a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes)):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return {}


class PostgresCpqRdb:
    """Postgres implementation — JSONB operators over aryx_entity."""

    def _connection(self):
        from aryx.store.pool import get_pool
        return get_pool(get_settings().rdb_dsn).connection()

    def fetch_entity_attributes(
        self, entity_ids: list[int], workspace_id: int,
    ) -> dict[int, dict[str, Any]]:
        """Batch-fetch attribute JSON for the given aryx entity ids."""
        if not entity_ids:
            return {}
        result: dict[int, dict[str, Any]] = {}
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, attributes FROM aryx_entity "
                        "WHERE id = ANY(%s) AND workspace_id = %s",
                        (entity_ids, workspace_id),
                    )
                    for eid, attrs in cur.fetchall():
                        result[int(eid)] = _as_attrs(attrs)
        except Exception:
            logger.debug("cpq rdb: attribute fetch failed", exc_info=True)
        return result

    def fetch_entities_by_type(
        self, workspace_id: int, type_suffix: str,
    ) -> list[tuple[int, dict[str, Any]]]:
        """All entities whose ontology_type ends with type_suffix (normalized).

        Normalization strips underscores and lowercases, so ``bmfunction``
        matches both ``BmFunction`` and ``ApxNextConfigBmFunction``.
        """
        rows: list[tuple[int, dict[str, Any]]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, attributes FROM aryx_entity "
                        "WHERE workspace_id = %s "
                        "AND replace(lower(ontology_type), '_', '') LIKE %s",
                        (workspace_id, f"%{type_suffix.lower().replace('_', '')}"),
                    )
                    for eid, attrs in cur.fetchall():
                        rows.append((int(eid), _as_attrs(attrs)))
        except Exception:
            logger.debug("cpq rdb: type fetch failed for %s", type_suffix, exc_info=True)
        return rows

    def fetch_rules(
        self, workspace_id: int, rule_type: str,
    ) -> list[tuple[int, int | None, str, int]]:
        """All BmConfigRule entities of one rule_type.

        Returns (entity_id, source_rule_id, rule_name, condition_function_id).
        source_rule_id is the BM-native rule id from the entity's own attrs —
        BmConfigRuleInput/Action rows reference rules by THAT id, not by the
        aryx entity id, so joins must go through it. fn_id is -1 for
        declarative rules and the BML function reference otherwise.
        Script-backed rules are INCLUDED; callers route them to the BML
        evaluator instead of silently dropping them.
        """
        rows: list[tuple[int, int | None, str, int]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id,
                               attributes->>'id',
                               attributes->>'name',
                               attributes->>'condition_function_id'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE '%%bmconfigrule'
                          AND (attributes->>'rule_type') = %s
                        """,
                        (workspace_id, rule_type),
                    )
                    for eid, src_id, name, fn_id in cur.fetchall():
                        rows.append((int(eid), _as_int(src_id), name or "",
                                     _as_int(fn_id) or -1))
        except Exception:
            logger.debug("cpq rdb: rule fetch failed", exc_info=True)
        return rows

    def fetch_rule_inputs(
        self, workspace_id: int,
    ) -> list[tuple[int, int, str]]:
        """All BmConfigRuleInput rows: (rule_id, condition_attr_id, value1)."""
        rows: list[tuple[int, int, str]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(attributes->>'bm_config_rule_id',
                                        attributes->>'rule_id'),
                               attributes->>'attribute_id',
                               attributes->>'value1'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE '%%bmconfigruleinput'
                        """,
                        (workspace_id,),
                    )
                    for rid, aid, val in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, val or ""))
        except Exception:
            logger.debug("cpq rdb: rule-input fetch failed", exc_info=True)
        return rows

    def fetch_rule_actions(
        self, workspace_id: int,
    ) -> list[tuple[int, int, int, str, int]]:
        """All BmConfigRuleAction rows.

        Returns (rule_id, target_attr_id, action_type, value1, function_id) —
        function_id is -1 unless the action's logic lives in a BML function.
        """
        rows: list[tuple[int, int, int, str, int]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(attributes->>'bm_config_rule_id',
                                        attributes->>'rule_id'),
                               attributes->>'attribute_id',
                               attributes->>'action_type',
                               attributes->>'value1',
                               attributes->>'function_id'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE '%%bmconfigruleaction'
                        """,
                        (workspace_id,),
                    )
                    for rid, aid, at, val, fn in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, _as_int(at) or 0,
                                         val or "", _as_int(fn) or -1))
        except Exception:
            logger.debug("cpq rdb: rule-action fetch failed", exc_info=True)
        return rows

    def fetch_marked_attrs(self, workspace_id: int) -> list[tuple[int, int]]:
        """All BmConfigMarkedAttr rows: (rule_id, attribute_id).

        This is the real target-linkage table for many declarative hiding
        rules — verified against real data where ``BmConfigRuleAction`` and
        the rule's own ``attr_id`` field both carry no target at all. One
        rule can mark multiple attributes (one row per marked attribute).
        """
        rows: list[tuple[int, int]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(attributes->>'bm_config_rule_id',
                                        attributes->>'rule_id'),
                               attributes->>'attribute_id'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE '%%bmconfigmarkedattr'
                        """,
                        (workspace_id,),
                    )
                    for rid, aid in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i))
        except Exception:
            logger.debug("cpq rdb: marked-attr fetch failed", exc_info=True)
        return rows

    def fetch_rule_chain_links(self, workspace_id: int) -> list[tuple[int, int]]:
        """All BmConfigRuleAssoc rows: (rule_id, child_rule_id).

        Some rules chain to another rule rather than declaring their own
        target — the terminal rule in the chain is where the target
        (BmConfigRuleAction or BmConfigMarkedAttr) actually lives.
        """
        rows: list[tuple[int, int]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(attributes->>'bm_config_rule_id',
                                        attributes->>'rule_id'),
                               attributes->>'child_rule_id'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE '%%bmconfigruleassoc'
                        """,
                        (workspace_id,),
                    )
                    for rid, cid in cur.fetchall():
                        rid_i, cid_i = _as_int(rid), _as_int(cid)
                        if rid_i and cid_i:
                            rows.append((rid_i, cid_i))
        except Exception:
            logger.debug("cpq rdb: rule-chain fetch failed", exc_info=True)
        return rows

    def fetch_function_scripts(self, workspace_id: int) -> dict[int, str]:
        """Map BM-native function id → raw BML script text.

        Scripts are read from the RDB (never the graph) because the graph
        projection truncates long string values by design. The BM-native id
        comes from the function entity's own attrs, since rules reference
        functions by that id.
        """
        scripts: dict[int, str] = {}
        for _eid, attrs in self.fetch_entities_by_type(workspace_id, "bmfunction"):
            fn_id = _as_int(attrs.get("id") or attrs.get("bm_function_id"))
            script = attrs.get("script_text") or attrs.get("script") or ""
            if fn_id and isinstance(script, str) and script.strip():
                scripts[fn_id] = script
        return scripts


class OracleCpqRdb(PostgresCpqRdb):
    """Oracle ADB 23ai implementation — JSON_VALUE over the JSON column.

    Design-complete but not yet exercised by automated tests (the suite runs
    on FalkorDB + Postgres; see docs/CPQ_GRAPH_FIX_PLAN.md).
    """

    def _connection(self):
        from aryx.store.oracle_pool import get_oracle_pool
        settings = get_settings()
        return get_oracle_pool(settings.oci_adb_dsn).connection()

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
        except Exception:
            logger.debug("cpq rdb(oracle): attribute fetch failed", exc_info=True)
        return result

    def fetch_entities_by_type(
        self, workspace_id: int, type_suffix: str,
    ) -> list[tuple[int, dict[str, Any]]]:
        rows: list[tuple[int, dict[str, Any]]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, attributes FROM aryx_entity "
                        "WHERE workspace_id = :1 "
                        "AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2",
                        (workspace_id, f"%{type_suffix.lower().replace('_', '')}"),
                    )
                    for eid, attrs in cur.fetchall():
                        rows.append((int(eid), _as_attrs(attrs)))
        except Exception:
            logger.debug("cpq rdb(oracle): type fetch failed", exc_info=True)
        return rows

    def fetch_rules(
        self, workspace_id: int, rule_type: str,
    ) -> list[tuple[int, int | None, str, int]]:
        rows: list[tuple[int, int | None, str, int]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id,
                               JSON_VALUE(attributes, '$.id'),
                               JSON_VALUE(attributes, '$.name'),
                               JSON_VALUE(attributes, '$.condition_function_id')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE '%bmconfigrule'
                          AND JSON_VALUE(attributes, '$.rule_type') = :2
                        """,
                        (workspace_id, rule_type),
                    )
                    for eid, src_id, name, fn_id in cur.fetchall():
                        rows.append((int(eid), _as_int(src_id), name or "",
                                     _as_int(fn_id) or -1))
        except Exception:
            logger.debug("cpq rdb(oracle): rule fetch failed", exc_info=True)
        return rows

    def fetch_rule_inputs(
        self, workspace_id: int,
    ) -> list[tuple[int, int, str]]:
        rows: list[tuple[int, int, str]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(JSON_VALUE(attributes, '$.bm_config_rule_id'),
                                        JSON_VALUE(attributes, '$.rule_id')),
                               JSON_VALUE(attributes, '$.attribute_id'),
                               JSON_VALUE(attributes, '$.value1')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE '%bmconfigruleinput'
                        """,
                        (workspace_id,),
                    )
                    for rid, aid, val in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, val or ""))
        except Exception:
            logger.debug("cpq rdb(oracle): rule-input fetch failed", exc_info=True)
        return rows

    def fetch_rule_actions(
        self, workspace_id: int,
    ) -> list[tuple[int, int, int, str, int]]:
        rows: list[tuple[int, int, int, str, int]] = []
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
                               JSON_VALUE(attributes, '$.function_id')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE '%bmconfigruleaction'
                        """,
                        (workspace_id,),
                    )
                    for rid, aid, at, val, fn in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, _as_int(at) or 0,
                                         val or "", _as_int(fn) or -1))
        except Exception:
            logger.debug("cpq rdb(oracle): rule-action fetch failed", exc_info=True)
        return rows

    def fetch_marked_attrs(self, workspace_id: int) -> list[tuple[int, int]]:
        rows: list[tuple[int, int]] = []
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
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE '%bmconfigmarkedattr'
                        """,
                        (workspace_id,),
                    )
                    for rid, aid in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i))
        except Exception:
            logger.debug("cpq rdb(oracle): marked-attr fetch failed", exc_info=True)
        return rows

    def fetch_rule_chain_links(self, workspace_id: int) -> list[tuple[int, int]]:
        rows: list[tuple[int, int]] = []
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
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE '%bmconfigruleassoc'
                        """,
                        (workspace_id,),
                    )
                    for rid, cid in cur.fetchall():
                        rid_i, cid_i = _as_int(rid), _as_int(cid)
                        if rid_i and cid_i:
                            rows.append((rid_i, cid_i))
        except Exception:
            logger.debug("cpq rdb(oracle): rule-chain fetch failed", exc_info=True)
        return rows


def get_cpq_rdb() -> PostgresCpqRdb:
    """Return the RDB accessor matching the configured backend."""
    if get_settings().effective_db_backend() == "oci":
        return OracleCpqRdb()
    return PostgresCpqRdb()
