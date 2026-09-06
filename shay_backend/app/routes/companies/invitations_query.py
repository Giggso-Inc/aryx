"""
Query-building helpers for list_invitations (invitations.py): sort-param
validation, the dedup-by-most-recent-email query builder, sort application,
and the total-count query. Split out purely to keep the endpoint itself
under the 150-line limit; no behavior change -- same queries, same order.
"""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models.invitation import Invitation

ALLOWED_SORT_FIELDS = ["email", "created_at"]


def _validate_invitation_sort(sort_by: str, sort_order: str) -> None:
    if sort_by not in ALLOWED_SORT_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sort_by field. Allowed values: {', '.join(ALLOWED_SORT_FIELDS)}"
        )

    if sort_order.lower() not in ["asc", "desc"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sort_order. Allowed values: asc or desc"
        )


def _build_distinct_invitation_query(company_id: str, search: Optional[str], role: Optional[str]) -> Select:
    """Deduplicate by email first (most recent invitation per email), then
    apply the role filter to the deduplicated results."""
    dedup_conditions = [
        Invitation.company_id == company_id,
        Invitation.status == "pending"
    ]

    if search:
        dedup_conditions.append(Invitation.email.ilike(f"%{search}%"))

    dedup_subquery = (
        select(
            Invitation.id,
            Invitation.role,
            func.row_number()
            .over(
                partition_by=Invitation.email,
                order_by=Invitation.created_at.desc()
            )
            .label("rn")
        )
        .where(and_(*dedup_conditions))
    ).subquery()

    distinct_invitation_ids_query = select(dedup_subquery.c.id).where(dedup_subquery.c.rn == 1)

    if role:
        distinct_invitation_ids_query = distinct_invitation_ids_query.where(dedup_subquery.c.role == role)

    return select(Invitation).where(Invitation.id.in_(distinct_invitation_ids_query))


def _apply_invitation_sort(base_query: Select, sort_by: str, sort_order: str) -> Select:
    if sort_by == "email":
        sort_field = Invitation.email
    else:  # Default: sort by created_at
        sort_field = Invitation.created_at

    if sort_order.lower() == "desc":
        return base_query.order_by(sort_field.desc())
    return base_query.order_by(sort_field.asc())


async def _count_pending_invitations(db: AsyncSession, company_id: str) -> int:
    """ALWAYS counts overall distinct emails (without role filter); this
    should not change based on filters."""
    total_count_subquery = (
        select(
            Invitation.email,
            func.row_number()
            .over(
                partition_by=Invitation.email,
                order_by=Invitation.created_at.desc()
            )
            .label("rn")
        )
        .where(
            and_(
                Invitation.company_id == company_id,
                Invitation.status == "pending"
            )
        )
    ).subquery()

    count_query = select(func.count()).select_from(
        total_count_subquery
    ).where(total_count_subquery.c.rn == 1)

    total_result = await db.execute(count_query)
    return total_result.scalar() or 0
