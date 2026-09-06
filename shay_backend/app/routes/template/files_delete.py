"""
Delete a template file + its DB record, looked up by
template_id-or-template_name ("identifier"):

  DELETE /files/{identifier}
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.template import Template

router = APIRouter()


@router.delete("/files/{identifier}")
async def delete_template_file(
    identifier: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    """
    Delete a template file and its database record by template_id or filename.

    Args:
        identifier: Template ID or filename to delete
        request: FastAPI request object
        db: Database session

    Returns:
        Success message
    """
    # Authentication removed for testing
    # user = await get_current_user_required(request, db)

    try:
        # Find database record first (by template_id or template_name)
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
                detail=f"Template record not found: {identifier}"
            )

        # Use the file_path from database record
        template_dir = settings.TEMPLATE_DIR
        file_path = template.file_path or os.path.join(template_dir, template.template_name)

        # Check if file exists
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template file not found: {file_path}"
            )

        # Delete file from disk
        os.remove(file_path)

        # Delete database record
        await db.delete(template)
        await db.commit()

        return JSONResponse(
            content={"message": f"Template file '{identifier}' and its record deleted successfully"},
            status_code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting template file: {str(e)}"
        )
