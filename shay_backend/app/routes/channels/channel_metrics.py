"""
Shared per-channel metrics computation used by the three channel-listing
endpoints (list_my, list_company, list_memberships).

Extracted during the Raven style-compliance line-count pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B2). The three listing
endpoints each used to carry their own ~110-line copy of this block, differing
only in (a) whether app/datasource info is collected as a list of all matches
or just the first match, and (b) whether channel_type/provider is computed at
all. Rather than accept that as a genuine stated exception, this module
parameterizes those two differences so the logic lives in exactly one place.

The channel_type/provider resolution itself was further split out to
channel_metrics_provider.py in wave B3, to bring this file under 150 lines.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import and_, func, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import literal

from app.models.app import App
from app.models.app_account import AppAccount
from app.models.approval import Approval
from app.models.channel_member import ChannelMember
from app.models.datasource import Datasource
from app.models.task import Task
from .channel_metrics_provider import resolve_channel_type_and_provider


@dataclass
class ChannelMetrics:
    total_apps_connected: int
    total_users: int
    total_datasources: int
    app: Union[List[Dict[str, Any]], Optional[Dict[str, Any]]]
    datasource: Union[List[Dict[str, Any]], Optional[Dict[str, Any]]]
    task_count: int
    approval_count: int
    channel_type: Optional[str] = None
    provider: Optional[str] = None


async def compute_channel_metrics(
    db: AsyncSession,
    channel: Any,
    *,
    collect_all: bool = False,
    include_provider: bool = False,
) -> ChannelMetrics:
    """Compute the apps/users/datasources/tasks/approvals metrics block for
    a single channel, as shared by list_my, list_company and
    list_memberships.

    collect_all=True reproduces list_my's behavior of returning every
    matching app/datasource as a list; collect_all=False (the default)
    reproduces list_company/list_memberships's behavior of returning only
    the first match (or None).

    include_provider=True additionally computes channel_type/provider, as
    done by list_my and list_company (but not list_memberships).
    """
    apps_count_query = select(func.count(AppAccount.id)).where(
        and_(
            AppAccount.channel_id == channel.id,
            AppAccount.is_active == True,
            or_(AppAccount.api_key.is_(None), AppAccount.api_key != "email"),
        )
    )
    total_apps_connected = (await db.execute(apps_count_query)).scalar() or 0

    users_count_query = select(func.count(ChannelMember.id)).where(
        and_(ChannelMember.channel_id == channel.id, ChannelMember.is_active == True)
    )
    total_users = (await db.execute(users_count_query)).scalar() or 0

    ds_not_thread = or_(
        Datasource.datasource_metadata.is_(None),
        ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String())),
    )
    datasources_count_query = select(func.count(Datasource.id)).where(
        and_(Datasource.channel_id == channel.id, ds_not_thread)
    )
    total_datasources = (await db.execute(datasources_count_query)).scalar() or 0

    app_info: Union[List[Dict[str, Any]], Optional[Dict[str, Any]]] = [] if collect_all else None
    if total_apps_connected > 0:
        app_query = select(App.app_name, App.app_image).join(AppAccount, App.id == AppAccount.app_id).where(
            and_(AppAccount.channel_id == channel.id, AppAccount.is_active == True)
        )
        if not collect_all:
            app_query = app_query.limit(1)
        app_rows = (await db.execute(app_query)).all()
        if collect_all:
            app_info = [{"app_name": row.app_name, "icon_url": row.app_image} for row in app_rows]
        elif app_rows:
            row = app_rows[0]
            app_info = {"app_name": row.app_name, "icon_url": row.app_image}

    datasource_info: Union[List[Dict[str, Any]], Optional[Dict[str, Any]]] = [] if collect_all else None
    if total_datasources > 0:
        datasource_query = select(
            Datasource.name, Datasource.filename, Datasource.file_type
        ).where(and_(Datasource.channel_id == channel.id, ds_not_thread))
        if not collect_all:
            datasource_query = datasource_query.limit(1)
        ds_rows = (await db.execute(datasource_query)).all()
        if collect_all:
            datasource_info = [
                {"datasource_name": row.name, "file_name": row.filename, "file_type": row.file_type}
                for row in ds_rows
            ]
        elif ds_rows:
            row = ds_rows[0]
            datasource_info = {"datasource_name": row.name, "file_name": row.filename, "file_type": row.file_type}

    task_count = (await db.execute(select(func.count(Task.id)).where(Task.channel_id == channel.id))).scalar() or 0

    approval_count = (
        await db.execute(
            select(func.count(Approval.id)).where(
                and_(Approval.channel_id == channel.id, Approval.is_active == "Y")
            )
        )
    ).scalar() or 0

    channel_type: Optional[str] = None
    provider: Optional[str] = None
    if include_provider:
        channel_type, provider = await resolve_channel_type_and_provider(db, channel)

    return ChannelMetrics(
        total_apps_connected=total_apps_connected,
        total_users=total_users,
        total_datasources=total_datasources,
        app=app_info,
        datasource=datasource_info,
        task_count=task_count,
        approval_count=approval_count,
        channel_type=channel_type,
        provider=provider,
    )
