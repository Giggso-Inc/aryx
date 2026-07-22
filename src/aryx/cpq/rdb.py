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


def _type_pattern(catalog_prefix: str, suffix: str) -> str:
    """Normalized-ontology-type LIKE pattern for a rule/function query.

    suffix is the lowercase, no-underscore tag stem (e.g. "bmconfigrule").
    catalog_prefix, when set, restricts the match to ontology types from one
    ingested source (see CpqEngine._catalog_prefix) — needed whenever a
    workspace holds more than one product's XML export, since BM-native ids
    (rule/function/attribute ids from the source system) are only unique
    WITHIN one export and do collide across catalogs sharing a workspace.
    Empty catalog_prefix preserves the original workspace-wide match.
    """
    return f"{catalog_prefix.lower()}%{suffix}" if catalog_prefix else f"%{suffix}"


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
        self, workspace_id: int, type_suffix: str, catalog_prefix: str = "",
    ) -> list[tuple[int, dict[str, Any]]]:
        """All entities whose ontology_type ends with type_suffix (normalized).

        Normalization strips underscores and lowercases, so ``bmfunction``
        matches both ``BmFunction`` and ``ApxNextConfigBmFunction``.

        catalog_prefix — when set, restricts to ontology types beginning
        with this source-derived prefix (see _type_pattern) instead of any
        source ending in type_suffix.
        """
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
                        "WHERE workspace_id = %s "
                        "AND replace(lower(ontology_type), '_', '') LIKE %s",
                        (workspace_id, pattern),
                    )
                    for eid, attrs in cur.fetchall():
                        rows.append((int(eid), _as_attrs(attrs)))
        except Exception:
            logger.debug("cpq rdb: type fetch failed for %s", type_suffix, exc_info=True)
        return rows

    def fetch_rules(
        self, workspace_id: int, rule_type: str, catalog_prefix: str = "",
        active_only: bool = False,
    ) -> list[tuple[int, int | None, str, int]]:
        """All BmConfigRule entities of one rule_type.

        Returns (entity_id, source_rule_id, rule_name, condition_function_id).
        source_rule_id is the BM-native rule id from the entity's own attrs —
        BmConfigRuleInput/Action rows reference rules by THAT id, not by the
        aryx entity id, so joins must go through it. fn_id is -1 for
        declarative rules and the BML function reference otherwise.
        Script-backed rules are INCLUDED; callers route them to the BML
        evaluator instead of silently dropping them.

        catalog_prefix — see _type_pattern; restricts to one ingested
        catalog when the workspace holds more than one product's export.

        active_only — when True, restricts to status='1' (active) rules.
        Defaults to False so existing callers (hiding rules, rule_type="11")
        are byte-for-byte unaffected; only rule_type="6" configuration-flow
        callers opt in (docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md
        §5) — BigMachines exports routinely carry dead/superseded flow rules
        (status=3) alongside the live one, and without this filter a
        disabled flow is indistinguishable from an active one.
        """
        rows: list[tuple[int, int | None, str, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigrule")
        status_clause = " AND (attributes->>'status') = '1'" if active_only else ""
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
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                          AND (attributes->>'rule_type') = %s
                        """ + status_clause,
                        (workspace_id, type_pattern, rule_type),
                    )
                    for eid, src_id, name, fn_id in cur.fetchall():
                        rows.append((int(eid), _as_int(src_id), name or "",
                                     _as_int(fn_id) or -1))
        except Exception:
            logger.debug("cpq rdb: rule fetch failed", exc_info=True)
        return rows

    def fetch_value_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int | None, str, str, int]]:
        """All BmConfigRule entities EXCEPT hiding rules (rule_type=11).

        Returns (entity_id, source_rule_id, rule_name, rule_type,
        condition_function_id). Recommendation/constraint rules can't be
        reliably selected by rule_type — that field is tenant/catalog-
        specific numbering (confirmed: two different ingested catalogs use
        different rule_type codes for the same semantic rule categories,
        and some codes appear in only one of them). rule_type=11 (hiding) is
        the one code that HAS proven consistent across catalogs and is
        handled separately by fetch_rules(); everything else is fetched
        here and classified downstream by inspecting each rule's actions
        (see CpqEngine._load_value_rules).
        """
        rows: list[tuple[int, int | None, str, str, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigrule")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id,
                               attributes->>'id',
                               attributes->>'name',
                               attributes->>'rule_type',
                               attributes->>'condition_function_id'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                          AND (attributes->>'rule_type') IS DISTINCT FROM '11'
                        """,
                        (workspace_id, type_pattern),
                    )
                    for eid, src_id, name, rule_type, fn_id in cur.fetchall():
                        rows.append((int(eid), _as_int(src_id), name or "",
                                     rule_type or "", _as_int(fn_id) or -1))
        except Exception:
            logger.debug("cpq rdb: value-rule fetch failed", exc_info=True)
        return rows

    def fetch_rule_inputs(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, str]]:
        """All BmConfigRuleInput rows: (rule_id, condition_attr_id, value1)."""
        rows: list[tuple[int, int, str]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigruleinput")
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
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, val in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, val or ""))
        except Exception:
            logger.debug("cpq rdb: rule-input fetch failed", exc_info=True)
        return rows

    def fetch_rule_actions(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, int, str, int, int]]:
        """All BmConfigRuleAction rows.

        Returns (rule_id, target_attr_id, action_type, value1, function_id,
        set_type). function_id is -1 unless the action's logic lives in a
        BML function. set_type is the reliable signal for whether a
        declarative action restricts values (-1) or assigns one (any other
        value) — see CpqEngine._load_value_rules; action_type itself only
        ever takes the values 1/2 in real exports and does not distinguish
        these two cases.
        """
        rows: list[tuple[int, int, int, str, int, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigruleaction")
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
                               attributes->>'function_id',
                               attributes->>'set_type'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, at, val, fn, st in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, _as_int(at) or 0,
                                         val or "", _as_int(fn) or -1,
                                         _as_int(st) if _as_int(st) is not None else 0))
        except Exception:
            logger.debug("cpq rdb: rule-action fetch failed", exc_info=True)
        return rows

    def fetch_marked_attrs(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int]]:
        """All BmConfigMarkedAttr rows: (rule_id, attribute_id).

        This is the real target-linkage table for many declarative hiding
        rules — verified against real data where ``BmConfigRuleAction`` and
        the rule's own ``attr_id`` field both carry no target at all. One
        rule can mark multiple attributes (one row per marked attribute).
        """
        rows: list[tuple[int, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigmarkedattr")
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
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i))
        except Exception:
            logger.debug("cpq rdb: marked-attr fetch failed", exc_info=True)
        return rows

    def fetch_rule_chain_links(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int]]:
        """All BmConfigRuleAssoc rows: (rule_id, child_rule_id).

        Some rules chain to another rule rather than declaring their own
        target — the terminal rule in the chain is where the target
        (BmConfigRuleAction or BmConfigMarkedAttr) actually lives.
        """
        rows: list[tuple[int, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigruleassoc")
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
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, cid in cur.fetchall():
                        rid_i, cid_i = _as_int(rid), _as_int(cid)
                        if rid_i and cid_i:
                            rows.append((rid_i, cid_i))
        except Exception:
            logger.debug("cpq rdb: rule-chain fetch failed", exc_info=True)
        return rows

    def fetch_function_scripts(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> dict[int, str]:
        """Map BM-native function id → raw BML script text.

        Scripts are read from the RDB (never the graph) because the graph
        projection truncates long string values by design. The BM-native id
        comes from the function entity's own attrs, since rules reference
        functions by that id — and, like rule ids, function ids are only
        unique WITHIN one ingested export (confirmed colliding across
        catalogs sharing a workspace), so catalog_prefix must be passed
        whenever more than one product's XML is ingested into one workspace.
        """
        scripts: dict[int, str] = {}
        for _eid, attrs in self.fetch_entities_by_type(workspace_id, "bmfunction", catalog_prefix):
            fn_id = _as_int(attrs.get("id") or attrs.get("bm_function_id"))
            script = attrs.get("script_text") or attrs.get("script") or ""
            if fn_id and isinstance(script, str) and script.strip():
                scripts[fn_id] = script
        return scripts

    def fetch_attr_set_assoc(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> dict[int, dict[str, Any]]:
        """BigMachines "array set" definitions (docs/CPQ_ARRAY_SET_PAYLOAD_
        PLAN.md): set_id -> {"driver_attr_id": int, "variable_name": str,
        "members": [(attr_id, order), ...]} (members sorted by order).

        A composite array-set models a repeating multi-column row (e.g. one
        mount option + its own quantity) as a driver/control attribute
        (``bm_config_attr_set.size_attr_id``) plus ordered member columns
        (``bm_config_attr_set_assoc``). Both ontology types are fetched via
        ``fetch_entities_by_type`` — dialect-agnostic, so this single
        implementation serves Postgres and Oracle alike through inheritance
        (same pattern as ``fetch_function_scripts``).

        Most ``bm_config_attr_set`` rows are trivial 1-attribute self-wraps
        with `size_attr_id=-1` — NOT real array-sets (confirmed live,
        docs/CPQ_RULE_TOOL_FLOW_PLAN.md §15c) — those are skipped here, so
        only genuine driver rows populate the returned dict.

        BigMachines ALSO emits a redundant internal "array key" set
        alongside every real one — a 1-member self-referential row named
        ``_array_key_{ControlAttrName}`` sharing the SAME ``size_attr_id``
        as the real, multi-column business set (confirmed live across both
        SVX and APX NEXT/DM4400: every real driver has exactly one such
        counterpart, e.g. ``vX650EnergySolutions_astro`` (4 real members)
        vs. ``_array_key_vX650ItemTypeArrayControl_astro`` (1 member, pure
        bookkeeping) — both size_attr_id=19435387207). Without filtering
        these out, whichever set happens to be fetched last would silently
        win the driver_attr_id -> set_id mapping — non-deterministic and
        occasionally wrong. Skipped by the stable, universal ``_array_key_``
        variable_name prefix, not by member count (a real set could in
        principle also have just 1 member).
        """
        sets: dict[int, dict[str, Any]] = {}
        for _eid, attrs in self.fetch_entities_by_type(
            workspace_id, "bmconfigattrset", catalog_prefix,
        ):
            set_id = _as_int(attrs.get("id"))
            driver_attr_id = _as_int(attrs.get("size_attr_id"))
            var_name = str(attrs.get("variable_name") or "").strip()
            if not set_id or not driver_attr_id or driver_attr_id <= 0 or not var_name:
                continue
            if var_name.startswith("_array_key_"):
                continue
            sets[set_id] = {
                "driver_attr_id": driver_attr_id,
                "variable_name": var_name,
                "members": [],
            }
        for _eid, attrs in self.fetch_entities_by_type(
            workspace_id, "bmconfigattrsetassoc", catalog_prefix,
        ):
            set_id = _as_int(attrs.get("set_id"))
            attr_id = _as_int(attrs.get("attr_id") or attrs.get("bm_config_attr_id"))
            order = _as_int(attrs.get("display_order_number")) or 999
            if set_id in sets and attr_id:
                sets[set_id]["members"].append((attr_id, order))
        for sdef in sets.values():
            sdef["members"].sort(key=lambda t: t[1])
        return sets

    def fetch_layout_attr_assoc(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, int]]:
        """All BmConfigLayoutAttrAssoc rows: (rule_id, attr_id, layout_model_id).

        rule_id is the BM-native id of the governing flow/rule (see
        docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md §1) — a row's presence is
        the only signal that an attribute is placed on SOME screen at all.
        One attribute can carry multiple rows (one per flow it appears in
        under), so callers scope to one rule_id, never aggregate blindly
        across rows.
        """
        rows: list[tuple[int, int, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfiglayoutattrassoc")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT attributes->>'rule_id',
                               attributes->>'attr_id',
                               attributes->>'layout_model_id'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, lmid in cur.fetchall():
                        rid_i, aid_i, lmid_i = _as_int(rid), _as_int(aid), _as_int(lmid)
                        if aid_i and lmid_i:
                            rows.append((rid_i or 0, aid_i, lmid_i))
        except Exception:
            logger.debug("cpq rdb: layout-attr-assoc fetch failed", exc_info=True)
        return rows

    def fetch_layout_model_nodes(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> dict[int, tuple[int | None, str, int]]:
        """Map BmLayoutModel node id → (parent_id, label, order_number).

        A plain parent-pointer hierarchy (docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md
        §4) — parent_id groups a node with its siblings under one screen
        section/tab; order_number is the real on-screen display order within
        that group. parent_id of -1 marks the tree root (a tab).
        """
        nodes: dict[int, tuple[int | None, str, int]] = {}
        for _eid, attrs in self.fetch_entities_by_type(workspace_id, "bmlayoutmodel", catalog_prefix):
            node_id = _as_int(attrs.get("id"))
            if not node_id:
                continue
            parent_id = _as_int(attrs.get("parent_id"))
            label = (attrs.get("label") or "").strip()
            order_number = _as_int(attrs.get("order_number")) or 0
            nodes[node_id] = (parent_id, label, order_number)
        return nodes


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
        except Exception:
            logger.debug("cpq rdb(oracle): type fetch failed", exc_info=True)
        return rows

    def fetch_rules(
        self, workspace_id: int, rule_type: str, catalog_prefix: str = "",
        active_only: bool = False,
    ) -> list[tuple[int, int | None, str, int]]:
        rows: list[tuple[int, int | None, str, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigrule")
        status_clause = (
            " AND JSON_VALUE(attributes, '$.status') = '1'" if active_only else ""
        )
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
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :3
                          AND JSON_VALUE(attributes, '$.rule_type') = :2
                        """ + status_clause,
                        (workspace_id, rule_type, type_pattern),
                    )
                    for eid, src_id, name, fn_id in cur.fetchall():
                        rows.append((int(eid), _as_int(src_id), name or "",
                                     _as_int(fn_id) or -1))
        except Exception:
            logger.debug("cpq rdb(oracle): rule fetch failed", exc_info=True)
        return rows

    def fetch_value_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int | None, str, str, int]]:
        rows: list[tuple[int, int | None, str, str, int]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigrule")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id,
                               JSON_VALUE(attributes, '$.id'),
                               JSON_VALUE(attributes, '$.name'),
                               JSON_VALUE(attributes, '$.rule_type'),
                               JSON_VALUE(attributes, '$.condition_function_id')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                          AND (JSON_VALUE(attributes, '$.rule_type') IS NULL
                               OR JSON_VALUE(attributes, '$.rule_type') != '11')
                        """,
                        (workspace_id, type_pattern),
                    )
                    for eid, src_id, name, rule_type, fn_id in cur.fetchall():
                        rows.append((int(eid), _as_int(src_id), name or "",
                                     rule_type or "", _as_int(fn_id) or -1))
        except Exception:
            logger.debug("cpq rdb(oracle): value-rule fetch failed", exc_info=True)
        return rows

    def fetch_rule_inputs(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, str]]:
        rows: list[tuple[int, int, str]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigruleinput")
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
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, val in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, val or ""))
        except Exception:
            logger.debug("cpq rdb(oracle): rule-input fetch failed", exc_info=True)
        return rows

    def fetch_rule_actions(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, int, str, int, int]]:
        rows: list[tuple[int, int, int, str, int, int]] = []
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
                               JSON_VALUE(attributes, '$.set_type')
                        FROM aryx_entity
                        WHERE workspace_id = :1
                          AND REPLACE(LOWER(ontology_type), '_', '') LIKE :2
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, at, val, fn, st in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, _as_int(at) or 0,
                                         val or "", _as_int(fn) or -1,
                                         _as_int(st) if _as_int(st) is not None else 0))
        except Exception:
            logger.debug("cpq rdb(oracle): rule-action fetch failed", exc_info=True)
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
        except Exception:
            logger.debug("cpq rdb(oracle): marked-attr fetch failed", exc_info=True)
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
        except Exception:
            logger.debug("cpq rdb(oracle): rule-chain fetch failed", exc_info=True)
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
        except Exception:
            logger.debug("cpq rdb(oracle): layout-attr-assoc fetch failed", exc_info=True)
        return rows


def get_cpq_rdb() -> PostgresCpqRdb:
    """Return the RDB accessor matching the configured backend."""
    if get_settings().effective_db_backend() == "oci":
        return OracleCpqRdb()
    return PostgresCpqRdb()
