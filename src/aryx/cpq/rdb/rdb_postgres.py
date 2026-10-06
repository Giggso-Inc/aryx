"""Postgres implementation of the backend-agnostic CPQ RDB accessor.

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
from aryx.cpq.rdb.rdb_helpers import _as_attrs, _as_int, _type_pattern
from aryx.raven_log import raven_log
from aryx.store.db_timeouts import log_if_timeout

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)


def _read_failed(operation: str) -> None:
    """A PostgresCpqRdb fetch swallowed an error and returned empty: say so (ERROR P2).

    Call from inside the ``except`` block (reads the active exception). Mirrors
    the Oracle helper of the same name so an outage is not an invisible "no rules"."""
    exc = sys.exc_info()[1]
    raven_log("ERROR", "P2", "ask.rdb.read_failed postgres CPQ rdb read failed, empty result returned",
              error_code="ARYX_ASK_RDB_READ_FAILED", context={
                  "dependency_name": "postgres", "operation": operation, "result": "failed_empty_returned",
                  "error_class": type(exc).__name__ if exc is not None else "", "attempt": 1})


def _warn_if_timeout(exc: BaseException, tag: str) -> None:
    """Flag-gated: WARN when a swallowed rdb error is a call timeout."""
    if get_settings().cpq_rdb_call_timeout_enabled:
        log_if_timeout(exc, f"cpq rdb({tag})")


class PostgresCpqRdb:
    """Postgres implementation — JSONB operators over aryx_entity."""

    def _connection(self) -> Iterator["psycopg.Connection"]:
        from aryx.store.pool import get_pool
        settings = get_settings()
        pool_cm = get_pool(settings.effective_dsn()).connection()
        if not settings.cpq_rdb_call_timeout_enabled:
            return pool_cm
        return self._bounded_connection(pool_cm, int(settings.cpq_rdb_call_timeout_ms))

    @staticmethod
    @contextmanager
    def _bounded_connection(pool_cm: Any, timeout_ms: int) -> Iterator["psycopg.Connection"]:
        """Borrow a pooled connection with statement_timeout set, reset on exit.

        The value is an int literal, never a bind parameter: ``SET`` does not
        accept parameters (the dev-rv-msi #370 bug).
        """
        with pool_cm as conn:
            try:
                conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
            except Exception:
                logger.warning("cpq rdb: SET statement_timeout failed; continuing unbounded", exc_info=True)
            try:
                yield conn
            finally:
                try:
                    conn.execute("SET statement_timeout = DEFAULT")
                except Exception:
                    logger.warning("cpq rdb: statement_timeout reset failed", exc_info=True)

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
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: attribute fetch failed", exc_info=True)
            _read_failed("fetch_entity_attributes")
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
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: type fetch failed for %s", type_suffix, exc_info=True)
            _read_failed("fetch_entities_by_type")
        return rows

    def fetch_entities_by_exact_type(
        self, workspace_id: int, ontology_type: str,
    ) -> list[tuple[int, dict[str, Any]]]:
        """All entities whose ontology_type EQUALS `ontology_type` exactly
        (case-insensitive) -- unlike fetch_entities_by_type's suffix LIKE
        match, which is the right tool for finding "any source's
        BmConfigRule" but the wrong one for looking up a single, already-
        known-exact ingested Data Table type: two real ingested types can
        share a suffix (confirmed live: "Whitelist" and "Advancedwhitelist"
        both end in "whitelist" — the LIKE pattern for one silently pulled
        in the other's differently-shaped rows too). Callers that already
        have the exact type string (e.g. from list_ontology_types) should
        use this, not fetch_entities_by_type.
        """
        rows: list[tuple[int, dict[str, Any]]] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, attributes FROM aryx_entity "
                        "WHERE workspace_id = %s AND lower(ontology_type) = lower(%s)",
                        (workspace_id, ontology_type),
                    )
                    for eid, attrs in cur.fetchall():
                        rows.append((int(eid), _as_attrs(attrs)))
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: exact type fetch failed for %s", ontology_type, exc_info=True)
            _read_failed("fetch_entities_by_exact_type")
        return rows

    def fetch_all_entities_grouped_by_type(
        self, workspace_id: int,
    ) -> dict[str, list[tuple[int, dict[str, Any]]]]:
        """Every entity in this workspace, in ONE round trip, grouped by its
        exact ontology_type.

        CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T2/data-table-resolution
        follow-up (real-data testing against workspace 704, 2026-09-25):
        both _load_all_tables() and _load_attr_var_mapping_rows() looped
        list_ontology_types() (109 distinct types on this workspace) and
        issued one fetch_entities_by_exact_type() round trip per type to
        find every Data-Table-shaped row -- confirmed live, a single
        resolve_region_allow_value() call took 411s this way. Both callers
        already need every row of every type to classify by shape, so
        there's nothing to filter server-side; only the round-trip count
        was the problem. Replaces up to 109 separate queries with 1.
        """
        result: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT ontology_type, id, attributes FROM aryx_entity "
                        "WHERE workspace_id = %s",
                        (workspace_id,),
                    )
                    for otype, eid, attrs in cur.fetchall():
                        if not otype:
                            continue
                        result.setdefault(otype, []).append((int(eid), _as_attrs(attrs)))
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: fetch_all_entities_grouped_by_type failed", exc_info=True)
            _read_failed("fetch_all_entities_grouped_by_type")
        return result

    def fetch_workspace_table_groups(
        self, workspace_id: int, accept: Any, skip_types: Any = (),
    ) -> dict[str, list[tuple[int, dict[str, Any]]]]:
        """CSV tables the CSV pipeline loaded for this workspace, as Data Table rows. Oracle only: none here."""
        return {}

    def list_ontology_types(self, workspace_id: int) -> list[str]:
        """Every distinct ontology_type ingested into this workspace.

        Used to discover ingested Data Table CSVs by CONTENT (column shape)
        rather than by a hardcoded name — a CSV's ontology_type is whatever
        the ingestion pipeline derived from its filename (see
        aryx.pipeline.doc_discovery.doc_discovery._stem_type), which varies per upload and
        is never assumed here.
        """
        types: list[str] = []
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT DISTINCT ontology_type FROM aryx_entity "
                        "WHERE workspace_id = %s",
                        (workspace_id,),
                    )
                    types = [row[0] for row in cur.fetchall() if row[0]]
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: ontology type listing failed", exc_info=True)
            _read_failed("list_ontology_types")
        return types

    def fetch_rules(
        self, workspace_id: int, rule_type: str, catalog_prefix: str = "",
        active_only: bool = False, with_ref_id: bool = False,
    ) -> list[tuple]:
        """All BmConfigRule entities of one rule_type.

        with_ref_id — when True each tuple gets the rule's BmCatalog node
        ref_id (str, "" if none) APPENDED as a final element (aryxent PR 6
        plumbing). Default False keeps the SQL and tuple shape unchanged.

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
        rows: list[tuple] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigrule")
        status_clause = " AND (attributes->>'status') = '1'" if active_only else ""
        ref_col = ", attributes->>'ref_id'" if with_ref_id else ""
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id,
                               attributes->>'id',
                               attributes->>'name',
                               attributes->>'condition_function_id'""" + ref_col + """
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                          AND (attributes->>'rule_type') = %s
                        """ + status_clause,
                        (workspace_id, type_pattern, rule_type),
                    )
                    for row in cur.fetchall():
                        eid, src_id, name, fn_id = row[:4]
                        out = (int(eid), _as_int(src_id), name or "",
                               _as_int(fn_id) or -1)
                        rows.append(out + (str(row[4] or ""),) if with_ref_id else out)
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: rule fetch failed", exc_info=True)
            _read_failed("fetch_rules")
        return rows

    def fetch_value_rules(
        self, workspace_id: int, catalog_prefix: str = "",
        active_only: bool = False, with_ref_id: bool = False,
    ) -> list[tuple]:
        """All BmConfigRule entities EXCEPT hiding rules (rule_type=11).

        with_ref_id — see fetch_rules(): appends the rule's ref_id ("" if
        none) as a final tuple element; default False is unchanged.

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

        active_only — when True, restricts to status='1' (active) rules,
        same convention/reason as fetch_rules(): BigMachines exports
        routinely carry dead/superseded recommendation/constraint rules
        (status=3) alongside the live one, and without this filter a
        disabled rule is indistinguishable from an active one (see
        docs/CPQ_RULE_STATUS_AND_CONSTRAINT_DISPATCH_ROOT_CAUSE_AND_FIX_
        PLAN_2026-08-14.md). Defaults to False so any other caller is
        byte-for-byte unaffected.
        """
        rows: list[tuple] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigrule")
        status_clause = " AND (attributes->>'status') = '1'" if active_only else ""
        ref_col = ", attributes->>'ref_id'" if with_ref_id else ""
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id,
                               attributes->>'id',
                               attributes->>'name',
                               attributes->>'rule_type',
                               attributes->>'condition_function_id'""" + ref_col + """
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                          AND (attributes->>'rule_type') IS DISTINCT FROM '11'
                        """ + status_clause,
                        (workspace_id, type_pattern),
                    )
                    for row in cur.fetchall():
                        eid, src_id, name, rule_type, fn_id = row[:5]
                        out = (int(eid), _as_int(src_id), name or "",
                               rule_type or "", _as_int(fn_id) or -1)
                        rows.append(out + (str(row[5] or ""),) if with_ref_id else out)
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: value-rule fetch failed", exc_info=True)
            _read_failed("fetch_value_rules")
        return rows

    def fetch_rule_inputs(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[tuple[int, int, str, str]]:
        """All BmConfigRuleInput rows: (rule_id, condition_attr_id, value1,
        operator1).

        operator1 (docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md)
        — the raw BM-native comparison-operator code ("1"/"2"/"3"/"4"/"5"/
        "7"/"8"), returned verbatim as a string; interpretation (=, <>, <,
        <=, >, ...) happens in bml.evaluate_declarative_conditions, not
        here. Confirmed live: previously dropped entirely, silently
        collapsing every condition to "=" regardless of the real operator
        — 25.5% of real rows in one catalog use a non-"4" ("=") operator.
        """
        rows: list[tuple[int, int, str, str]] = []
        type_pattern = _type_pattern(catalog_prefix, "bmconfigruleinput")
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(attributes->>'bm_config_rule_id',
                                        attributes->>'rule_id'),
                               attributes->>'attribute_id',
                               attributes->>'value1',
                               attributes->>'operator1'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, val, op in cur.fetchall():
                        rid_i, aid_i = _as_int(rid), _as_int(aid)
                        if rid_i and aid_i:
                            rows.append((rid_i, aid_i, val or "", (op or "").strip()))
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: rule-input fetch failed", exc_info=True)
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
                        SELECT COALESCE(attributes->>'bm_config_rule_id',
                                        attributes->>'rule_id'),
                               attributes->>'attribute_id',
                               attributes->>'value1',
                               attributes->>'operator1',
                               attributes->>'rule_input_index'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, aid, val, op, idx in cur.fetchall():
                        rid_i, aid_i, idx_i = _as_int(rid), _as_int(aid), _as_int(idx)
                        if rid_i and aid_i and idx_i:
                            rows.append((rid_i, aid_i, val or "", (op or "").strip(), idx_i))
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: rule-input index fetch failed", exc_info=True)
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
                        SELECT attributes->>'id', attributes->>'condition_expression'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE %s
                        """,
                        (workspace_id, type_pattern),
                    )
                    for rid, expr in cur.fetchall():
                        rid_i = _as_int(rid)
                        if rid_i and isinstance(expr, str) and expr.strip():
                            out[rid_i] = expr.strip()
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: rule-expression fetch failed", exc_info=True)
            _read_failed("fetch_rule_condition_expressions")
        return out

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
        rows: list[tuple[int, int, int, str, int, int, str]] = []
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
                               attributes->>'set_type',
                               attributes->>'comments'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND replace(lower(ontology_type), '_', '') LIKE %s
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
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: rule-action fetch failed", exc_info=True)
            _read_failed("fetch_rule_actions")
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
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: marked-attr fetch failed", exc_info=True)
            _read_failed("fetch_marked_attrs")
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
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: rule-chain fetch failed", exc_info=True)
            _read_failed("fetch_rule_chain_links")
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
        except Exception as exc:
            _warn_if_timeout(exc, "pg")
            logger.debug("cpq rdb: layout-attr-assoc fetch failed", exc_info=True)
            _read_failed("fetch_layout_attr_assoc")
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
