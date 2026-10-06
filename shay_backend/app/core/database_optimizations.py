"""
Post-connect optimization/repair helpers for app/core/database.py.

Both functions here operate purely on a passed-in `conn` (no module-level
engine/session state), so they're a safe extraction from database.py —
called from init_db() there. Extracted verbatim, no behavior change.
"""

from app.core.config import settings

# (index_name_uppercase, table_name_uppercase, column_list) -- shared by both
# the async and sync repair functions below, so there is exactly one list to
# keep in sync with the actual schema, not two.
_ARC_INDEXES = [
    ("UK_GG_MEMBERS_WORKSPACE",         "GG_MEMBERS",         "WORKSPACE_ID, USER_ID"),
    ("UK_GG_MEMBERS_CHANNEL",           "GG_MEMBERS",         "CHANNEL_ID, USER_ID"),
    ("UK_GG_MEMBERS_THREAD",            "GG_MEMBERS",         "THREAD_ID, USER_ID"),
    ("UK_GG_APP_CONNECTIONS_WORKSPACE", "GG_APP_CONNECTIONS", "WORKSPACE_ID, APP_ID"),
    ("UK_GG_APP_CONNECTIONS_CHANNEL",   "GG_APP_CONNECTIONS", "CHANNEL_ID, APP_ID"),
    ("UK_GG_APP_CONNECTIONS_THREAD",    "GG_APP_CONNECTIONS", "THREAD_ID, APP_ID"),
    ("UK_GG_DATASOURCES_WORKSPACE",     "DATASOURCES",        "WORKSPACE_ID, NAME"),
    ("UK_GG_DATASOURCES_CHANNEL",       "DATASOURCES",        "CHANNEL_ID, NAME"),
    ("UK_GG_DATASOURCES_THREAD",        "DATASOURCES",        "THREAD_ID, NAME"),
    ("UK_GG_DATASOURCES_MESSAGE",       "DATASOURCES",        "MESSAGE_ID, NAME"),
]


async def _oracle_repair_partial_unique_indexes(conn) -> None:
    """
    Drop global unique indexes that were incorrectly created on exclusive-arc tables.

    SQLAlchemy partial unique indexes (unique=True, postgresql_where=...) silently
    drop the WHERE clause on Oracle, producing global unique constraints that violate
    when NULL columns are shared across scope levels — e.g. all workspace-level members
    share channel_id=NULL, so UK_GG_MEMBERS_CHANNEL fires on the second insert.

    This repair runs before create_all so that an existing Oracle schema created by a
    previous boot gets fixed in-place without dropping any tables or losing data.
    Safe to call repeatedly: queries user_indexes first, no-ops if already non-unique.

    Not called by the live Oracle path anymore (init_db() now runs the sync
    engine branch, which calls _oracle_repair_partial_unique_indexes_sync
    instead) -- kept, and still exported from database.py, because
    tests/test_database_characterization.py exercises this exact function
    directly as its characterization of the repair SQL.
    """
    from sqlalchemy import text

    for idx_name, table_name, cols in _ARC_INDEXES:
        result = await conn.execute(
            text("SELECT uniqueness FROM user_indexes WHERE index_name = :n"),
            {"n": idx_name},
        )
        row = result.fetchone()
        if row and row[0] == "UNIQUE":
            try:
                await conn.execute(text(f'DROP INDEX "{idx_name}"'))
                await conn.execute(text(f'CREATE INDEX "{idx_name}" ON "{table_name}" ({cols})'))
                print(f"  repaired: {idx_name} (unique → non-unique)")
            except Exception as e:
                print(f"  warning: could not repair {idx_name}: {e}")


def _oracle_repair_partial_unique_indexes_sync(conn) -> None:
    """Sync counterpart of `_oracle_repair_partial_unique_indexes` --
    same SQL, same _ARC_INDEXES list, no `await` -- for init_db()'s Oracle
    branch now that engine is a sync Engine (python-oracledb thick mode,
    see docs/oci-oracle/ORACLE_THICK_MODE_MIGRATION_PLAN_2026-10-06.md
    "shay-api" section). This is the one actually called by the live
    Oracle path."""
    from sqlalchemy import text

    for idx_name, table_name, cols in _ARC_INDEXES:
        result = conn.execute(
            text("SELECT uniqueness FROM user_indexes WHERE index_name = :n"),
            {"n": idx_name},
        )
        row = result.fetchone()
        if row and row[0] == "UNIQUE":
            try:
                conn.execute(text(f'DROP INDEX "{idx_name}"'))
                conn.execute(text(f'CREATE INDEX "{idx_name}" ON "{table_name}" ({cols})'))
                print(f"  repaired: {idx_name} (unique → non-unique)")
            except Exception as e:
                print(f"  warning: could not repair {idx_name}: {e}")


async def create_postgresql_optimizations(conn) -> None:
    """Create PostgreSQL-specific optimizations"""
    try:
        # Create hash indexes for UUID primary keys
        if settings.POSTGRES_USE_HASH_INDEXES:
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_hash ON gg_users USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_companies_hash ON gg_company USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workspaces_hash ON gg_workspace USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_hash ON gg_tasks USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_approvals_hash ON gg_approvals USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_datasources_hash ON gg_datasources USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_channel_members_id_hash ON gg_channel_members USING HASH(id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gg_templates_id_hash ON gg_templates USING HASH(id);"
            )

        # Create composite indexes for common queries
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_thread_time ON gg_messages(thread_id, created_at);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user_time ON gg_messages(user_id, created_at);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_ai_processed ON gg_messages(is_ai_processed, created_at);"
        )

        # Create indexes for company-based queries
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_company ON gg_users(company_id);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspaces_company ON gg_workspace(company_id);"
        )
        # Create indexes for workspace hierarchy
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_channels_workspace ON gg_channels(workspace_id);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_threads_channel ON gg_threads(channel_id);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_channel ON gg_messages(channel_id);"
        )

        # Create indexes for new models
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status_time ON gg_tasks(status, created_at);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON gg_tasks(assigned_to, status);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_approvals_task_status ON gg_approvals(task_id, status);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_datasources_workspace ON gg_datasources(workspace_id);"
        )

        print("✅ PostgreSQL optimizations applied")

    except Exception as e:
        print(f"⚠️ Warning: Could not apply PostgreSQL optimizations: {e}")
