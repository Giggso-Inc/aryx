"""GET /count — count of connected data sources by type (local, cloud, db, app)."""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.channel import Channel
from app.models.datasource import Datasource
from app.schemas.datasource import DatasourceTypeCount, DatasourceTypeCountResponse

from ._helpers import _exclude_thread_level, _parse_channel_uuid

router = APIRouter()


@router.get("/count", response_model=DatasourceTypeCountResponse)
async def get_datasource_type_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    channel_id: Optional[str] = None
) -> DatasourceTypeCountResponse:
    """Get count of connected data sources by type (local, cloud, db, app)"""
    user = await get_current_user_required(request)

    # Build base query - filter by user's company and connected status
    # Get counts grouped by storage_type
    count_query = select(
        Datasource.storage_type,
        func.count(Datasource.id).label('count')
    ).join(Datasource.channel).where(
        and_(
            Channel.company_id == user.company_id,
            Datasource.is_connected == True
        )
    ).group_by(Datasource.storage_type)

    if channel_id:
        channel_uuid = _parse_channel_uuid(channel_id)
        count_query = count_query.where(Datasource.channel_id == channel_uuid)

    # Exclude thread-level datasources (e.g. email attachments) from type count
    # so channel-level count shows only channel-level datasources
    count_query = count_query.where(_exclude_thread_level())

    # Execute query to get counts by type
    result = await db.execute(count_query)
    type_counts = {row.storage_type: row.count for row in result}

    # Define the data source types to include in response
    data_source_types = ["local", "cloud", "app", "db"]

    counts = []
    total_connected = 0

    # Build response with counts for each type (0 if not found)
    for ds_type in data_source_types:
        count = type_counts.get(ds_type, 0)
        total_connected += count
        counts.append(DatasourceTypeCount(type=ds_type, count=count))

    return DatasourceTypeCountResponse(
        counts=counts,
        total_connected=total_connected
    )
