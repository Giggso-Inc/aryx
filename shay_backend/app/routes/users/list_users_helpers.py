"""
Helpers for list_company_users (list_users.py): the company-wide
user-count queries. Split out purely to keep the endpoint itself under the
150-line limit; no behavior change.

These are genuinely separable from the endpoint's filtered/sorted/paginated
query building: they don't depend on `base_query`/`data_query` local state,
they only need `db`/`company_id`.

NOTE: the sort_by/sort_order/status validation stays inline in
list_users.py rather than living here. That code raises
`HTTPException(status_code=status.HTTP_400_BAD_REQUEST, ...)` inside a
function scope where `status` is *also* the name of one of the endpoint's
own query parameters (`status: Optional[str] = Query(...)`) -- Python
resolves the bare name `status` to that local parameter for the whole
function body, shadowing the `from fastapi import status` module import, so
`status.HTTP_400_BAD_REQUEST` raises AttributeError -> uncaught -> FastAPI
turns it into a 500. This is a pre-existing bug, characterized by
tests/test_users_characterization.py::TestListCompanyUsers's
`*_hits_status_shadowing_bug_500` tests. It only reproduces in a scope that
also has a `status` parameter, so moving the validation into this
shadowing-free helper module would silently fix it -- a behavior change the
split must not make. Only the `ALLOWED_SORT_FIELDS` constant (no `status`
usage) is shared here.
"""

from typing import Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

ALLOWED_SORT_FIELDS = ["name", "email_id", "role", "created_datetime", "updated_datetime"]


async def _get_company_user_counts(db: AsyncSession, company_id: str) -> Tuple[int, int, int, int]:
    """Total, total_active, total_inactive, total_admin counts for a company.

    Based on company_id only, not affected by search/role/status filters."""
    count_query = select(func.count(User.id)).where(User.company_id == company_id)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    total_active_query = select(func.count(User.id)).where(
        and_(User.company_id == company_id, User.is_active == True)
    )
    total_active_result = await db.execute(total_active_query)
    total_active = total_active_result.scalar() or 0

    total_inactive_query = select(func.count(User.id)).where(
        and_(User.company_id == company_id, User.is_active == False)
    )
    total_inactive_result = await db.execute(total_inactive_query)
    total_inactive = total_inactive_result.scalar() or 0

    total_admin_query = select(func.count(User.id)).where(
        and_(User.company_id == company_id, User.role == "admin")
    )
    total_admin_result = await db.execute(total_admin_query)
    total_admin = total_admin_result.scalar() or 0

    return total, total_active, total_inactive, total_admin
