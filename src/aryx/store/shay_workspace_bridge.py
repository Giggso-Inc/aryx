"""ShayBridgeStore's workspace-mapping methods (mixin).

Split out of `store/shay_bridge_store.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03). No test patches these methods individually
(confirmed via grep — `test_shay_bridge_store.py`'s only patches are on
`get_pool`, used by `__init__`, and `DatasourceStore`, used only by
`sync_datasource`), so this mixin carries no patch-retargeting risk.
"""
from __future__ import annotations

import logging
from typing import Any

from psycopg.types.json import Json

from aryx.config import get_settings
from aryx.store.shay_bridge_helpers import _aryx_workspace_name
from aryx.workspaces import make_workspace_store

logger = logging.getLogger(__name__)


class _ShayWorkspaceBridgeMixin:
    """get/ensure workspace-mapping methods for ShayBridgeStore."""

    def get_workspace_mapping(self, shay_workspace_id: str) -> dict[str, Any] | None:
        # No JOIN to gg_workspace — that table is owned by shay-api (cross-service).
        # An INNER JOIN would return None for any mapping whose shay workspace was
        # deleted or not yet visible, causing an unnecessary re-create attempt.
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.shay_workspace_id::text,
                    m.aryx_workspace_id,
                    m.company_id::text,
                    m.sync_state
                FROM aryx_shay_workspace_map m
                WHERE m.shay_workspace_id = %s::uuid
                """,
                (shay_workspace_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "shay_workspace_id": row[0],
            "aryx_workspace_id": row[1],
            "company_id": row[2],
            "sync_state": row[3] or {},
        }

    def ensure_workspace_mapping(
        self,
        *,
        shay_workspace_id: str,
        name: str,
        description: str = "",
        company_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or update the bridge row linking a Shay workspace to Aryx.

        Idempotent: safe to call on every Shay workspace touch. Creates a
        new Aryx workspace (via `make_workspace_store`) and bridge row on
        first call for a given `shay_workspace_id`; on subsequent calls,
        updates `company_id` (only when a non-null value is given) and
        merges `sync_state` without disturbing the existing
        `aryx_workspace_id` link.

        Args:
            shay_workspace_id: Shay's UUID for the workspace.
            name: Human-readable workspace name, used to derive the Aryx
                workspace's own name and merged into `sync_state`.
            description: Optional description for a newly created Aryx
                workspace. Ignored when the mapping already exists.
            company_id: Shay's company UUID for this workspace, or None to
                leave any existing value untouched.

        Returns:
            The bridge row as a dict with `shay_workspace_id`,
            `aryx_workspace_id`, `company_id`, `sync_state`, and `created`
            (True only when this call created a brand-new mapping).

        Raises:
            RuntimeError: If a concurrent insert or update leaves no row
                behind to read back (should not happen in normal operation).
        """
        existing = self.get_workspace_mapping(shay_workspace_id)
        if existing:
            if get_settings().effective_db_backend() == "oci":
                # Postgres's `sync_state || %s::jsonb` is a jsonb shallow-merge
                # (right side wins on key conflicts). _translate_sql() only
                # strips the ::jsonb cast, leaving `||` as Oracle's STRING
                # CONCAT operator -- silently doubling sync_state as text on
                # every repeat call instead of merging it. JSON_MERGEPATCH
                # reproduces the same "patch wins" semantics on Oracle.
                #
                # sync_state is a plain CLOB/VARCHAR2 column here (unlike
                # Postgres's jsonb, Oracle enforces no JSON validity on
                # write), so rows touched by the bug above before this fix
                # existed can already hold garbage like the same object
                # concatenated as text N times over. JSON_MERGEPATCH()
                # against a non-JSON target returns NULL (not an error),
                # which then fails NOT NULL with ORA-01407 -- found via a
                # real pre-existing workspace when regression-testing this
                # exact fix. The `CASE WHEN sync_state IS JSON` guard
                # self-heals any such row on its next touch instead of
                # requiring a one-off data-repair migration.
                with self._pool.connection() as conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE aryx_shay_workspace_map
                        SET company_id = COALESCE(%(company_id)s, company_id),
                            sync_state = JSON_MERGEPATCH(
                                CASE WHEN sync_state IS JSON THEN sync_state ELSE TO_CLOB('{}') END,
                                %(patch)s
                            ),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE shay_workspace_id = %(shay_workspace_id)s
                        """,
                        {
                            "company_id": company_id,
                            "patch": Json({"workspace_name": name}),
                            "shay_workspace_id": shay_workspace_id,
                        },
                    )
                updated = self.get_workspace_mapping(shay_workspace_id)
                if not updated:
                    raise RuntimeError(
                        f"bridge UPDATE for {shay_workspace_id!r} left no row behind"
                    )
                updated["created"] = False
                return updated

            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE aryx_shay_workspace_map
                    SET company_id = COALESCE(%s::uuid, company_id),
                        sync_state = sync_state || %s::jsonb,
                        updated_at = NOW()
                    WHERE shay_workspace_id = %s::uuid
                    RETURNING shay_workspace_id::text, aryx_workspace_id, company_id::text, sync_state
                    """,
                    (
                        company_id,
                        Json({"workspace_name": name}),
                        shay_workspace_id,
                    ),
                )
                row = cur.fetchone()
            return {
                "shay_workspace_id": row[0],
                "aryx_workspace_id": row[1],
                "company_id": row[2],
                "sync_state": row[3] or {},
                "created": False,
            }

        ws_name = _aryx_workspace_name(name, shay_workspace_id)
        workspace_store = make_workspace_store(self._dsn)
        try:
            aryx_workspace = workspace_store.create(
                ws_name,
                description or f"Bridge for Shay workspace {name}",
                f"shay_workspace_id={shay_workspace_id}",
            )
        except Exception as exc:
            # ORA-00001 / Postgres 23505: workspace was created by a prior attempt
            # that succeeded here but failed on the bridge INSERT (e.g. FK violation).
            # Recover by looking up the orphaned aryx_workspace row by name.
            _is_dup = "ORA-00001" in str(exc) or getattr(exc, "pgcode", None) == "23505"
            if not _is_dup:
                raise
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM aryx_workspace WHERE name = %s",
                    (ws_name,),
                )
                ws_row = cur.fetchone()
            if not ws_row:
                raise
            aryx_workspace = {"id": ws_row[0]}
            logger.info("ensure_workspace_mapping: reusing orphaned workspace id=%s name=%s",
                        ws_row[0], ws_name)
        finally:
            workspace_store.close()

        if get_settings().effective_db_backend() == "oci":
            # Oracle has no ON CONFLICT ... DO UPDATE; _translate_sql() raises
            # loudly on that construct rather than silently degrading (post-merge
            # review fix), so this caller needs an Oracle-specific path instead
            # of the Postgres upsert below.
            #
            # An earlier version of this fix used an Oracle MERGE, which hit a
            # second Oracle quirk: MERGE's force=True CLOB coercion (needed to
            # avoid ORA-03146 when a bind is genuinely CLOB-bound in one branch)
            # coerces EVERY non-excluded string bind to CLOB, including
            # company_id here -- but company_id targets a plain CHAR/UUID
            # column, not CLOB, so Oracle raised ORA-00932 ("... is of data
            # type CHAR, which is incompatible with expected data type CLOB")
            # while reconciling the MATCHED/NOT MATCHED branches internally.
            #
            # This function already confirmed (via get_workspace_mapping() at
            # the top) that no row exists yet for this shay_workspace_id, so a
            # MERGE's conflict-handling is unnecessary here -- a plain INSERT
            # with a duplicate-key fallback (the same pattern already used a
            # few lines up for the aryx_workspace race) is simpler and avoids
            # MERGE's CLOB-typing rules entirely.
            import oracledb  # noqa: PLC0415

            lost_insert_race = False
            with self._pool.connection() as conn, conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO aryx_shay_workspace_map (
                            shay_workspace_id, aryx_workspace_id, company_id, sync_state
                        ) VALUES (%s, %s, %s, %s)
                        """,
                        (
                            shay_workspace_id,
                            int(aryx_workspace["id"]),
                            company_id,
                            Json({"workspace_name": name}),
                        ),
                    )
                except oracledb.IntegrityError as exc:
                    if "ORA-00001" not in str(exc):
                        raise
                    lost_insert_race = True
                    logger.info(
                        "ensure_workspace_mapping: concurrent insert race for "
                        "shay_workspace_id=%s, reusing existing row",
                        shay_workspace_id,
                    )
            created_row = self.get_workspace_mapping(shay_workspace_id)
            if created_row:
                # get_workspace_mapping() found no row for this id at function
                # entry (line 67 above). If the INSERT above succeeded, this
                # request genuinely created the row. If it hit ORA-00001
                # instead, a concurrent request won the race and created it
                # first -- report created=False so the caller doesn't believe
                # it was the one that created this mapping.
                created_row["created"] = not lost_insert_race
                return created_row
            raise RuntimeError(
                f"bridge MERGE for {shay_workspace_id!r} left no row behind"
            )

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO aryx_shay_workspace_map (
                    shay_workspace_id, aryx_workspace_id, company_id, sync_state
                )
                VALUES (%s::uuid, %s, %s::uuid, %s)
                ON CONFLICT (shay_workspace_id) DO UPDATE
                SET company_id = COALESCE(EXCLUDED.company_id, aryx_shay_workspace_map.company_id),
                    updated_at = NOW()
                RETURNING shay_workspace_id::text, aryx_workspace_id, company_id::text, sync_state
                """,
                (
                    shay_workspace_id,
                    int(aryx_workspace["id"]),
                    company_id,
                    Json({"workspace_name": name}),
                ),
            )
            row = cur.fetchone()

        if row is None:
            # Should not happen on Postgres (RETURNING always yields a row on
            # both INSERT and DO UPDATE) -- defensive fallback only.
            existing = self.get_workspace_mapping(shay_workspace_id)
            if existing:
                existing["created"] = False
                return existing
            raise RuntimeError(
                f"bridge INSERT for {shay_workspace_id!r} silently failed and no row found"
            )
        return {
            "shay_workspace_id": row[0],
            "aryx_workspace_id": row[1],
            "company_id": row[2],
            "sync_state": row[3] or {},
            "created": True,
        }
