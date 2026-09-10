"""Fetch template content (DB metadata + on-disk file) by template_id."""

import os
from typing import Any, Dict

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.template import Template


class FetchMixin:
    """Look up a Template row and read its backing file from disk."""

    async def get_template_content(
        self,
        template_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Fetch template content by template_id

        Args:
            template_id: Template ID to fetch
            db: Database session

        Returns:
            Dict containing template content and metadata

        Raises:
            HTTPException: If template not found or file read error
        """
        try:
            # Find template record by template_id
            result = await db.execute(
                select(Template).where(Template.template_id == template_id)
            )
            template = result.scalar_one_or_none()

            if not template:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Template not found: {template_id}"
                )

            # Get file path from database record
            file_path = template.file_path
            if not file_path:
                # Fallback to template directory + template_name
                file_path = os.path.join(self.template_dir, template.template_name)

            # Check if file exists
            if not os.path.exists(file_path):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Template file not found: {file_path}"
                )

            # Security check - ensure file is within template directory
            if not os.path.abspath(file_path).startswith(os.path.abspath(self.template_dir)):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: File path outside template directory"
                )

            # Read file content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            return {
                'template_id': template.template_id,
                'template_name': template.template_name,
                'content': content,
                'file_path': file_path,
                'additional_config': template.additional_config or {}
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error fetching template content: {str(e)}"
            )
