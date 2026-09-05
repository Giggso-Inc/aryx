"""
Shared WHERE-clause builders for the datasource list endpoint.

Private module: used only by list_datasources.py. The list endpoint builds
an identical set of filters for both its main (paginated) query and its
COUNT query; these were previously duplicated inline. Extracting them here
means each filter is written once and applied to both queries via
``query.where(*build_common_datasource_filters(...))``.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import String, and_, or_
from sqlalchemy.sql.expression import literal

from app.models.datasource import Datasource


def exclude_incomplete_database_datasources():
    """Exclude database datasources without a tableName in config or metadata."""
    return or_(
        Datasource.storage_type != "database",
        and_(
            Datasource.storage_type == "database",
            or_(
                and_(
                    Datasource.config.op("?")(literal("tableName", type_=String())),
                    Datasource.config.op("->>")(literal("tableName", type_=String())).isnot(None),
                    Datasource.config.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                ),
                and_(
                    Datasource.datasource_metadata.op("?")(literal("tableName", type_=String())),
                    Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())).isnot(None),
                    Datasource.datasource_metadata.op("->>")(literal("tableName", type_=String())) != literal("", type_=String())
                )
            )
        )
    )


def thread_scope_filter(thread_uuid: UUID):
    """Filter to datasources belonging to this specific thread (thread-level scope)."""
    return and_(
        Datasource.datasource_metadata.isnot(None),
        Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
        Datasource.datasource_metadata.op("->>")(literal("thread_id", type_=String())) == literal(str(thread_uuid), type_=String())
    )


def channel_scope_filter():
    """Filter to exclude thread-level datasources (e.g. email attachments) from a channel-level list."""
    return or_(
        Datasource.datasource_metadata.is_(None),
        ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
    )


def build_common_datasource_filters(
    *,
    thread_uuid: Optional[UUID],
    channel_uuid: Optional[UUID],
    type_filter: Optional[str],
    provider: Optional[str],
    app_type: Optional[str],
    processing_status: Optional[str],
    is_connected: Optional[bool],
    search: Optional[str],
) -> List:
    """Build the list of WHERE conditions shared by the main and COUNT queries."""
    conditions = [exclude_incomplete_database_datasources()]

    conditions.append(thread_scope_filter(thread_uuid) if thread_uuid else channel_scope_filter())

    if channel_uuid:
        conditions.append(Datasource.channel_id == channel_uuid)
    if type_filter:
        conditions.append(Datasource.storage_type == type_filter)
    if provider:
        conditions.append(Datasource.provider == provider)
    if app_type:
        conditions.append(Datasource.app_type == app_type)
    if processing_status:
        conditions.append(Datasource.processing_status == processing_status)
    if is_connected is not None:
        conditions.append(Datasource.is_connected == is_connected)
    if search:
        conditions.append(or_(
            Datasource.name.ilike(f"%{search}%"),
            Datasource.filename.ilike(f"%{search}%")
        ))

    return conditions
