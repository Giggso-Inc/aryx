"""
Single database template-record by template_id or template_name:

  GET    /{identifier}

Must be registered after db_list's GET / and after every /files/* and
/content/* submodule — its single dynamic path segment would otherwise
swallow literal single-segment siblings if any existed at this level (there
are none today, since /files and /content are their own literal first
segments, but the registration order is kept identical to the source file
for safety and readability, matching the channels/ and gg_datasources/
package precedent).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.template import Template
from app.schemas.template import TemplateResponse

router = APIRouter()


@router.get("/{identifier}", response_model=TemplateResponse)
async def get_template(
    identifier: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> TemplateResponse:
    """
    Get a specific template database record by template_id or template_name.

    Args:
        identifier: Template ID or template name to retrieve
        request: FastAPI request object
        db: Database session

    Returns:
        Template record
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request, db)

    try:
        # Try to find by template_id first, then by template_name
        result = await db.execute(
            select(Template).where(
                or_(
                    Template.template_id == identifier,
                    Template.template_name == identifier
                )
            )
        )
        template = result.scalar_one_or_none()

        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template not found: {identifier}"
            )

        return TemplateResponse.model_validate(template)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving template: {str(e)}"
        )
