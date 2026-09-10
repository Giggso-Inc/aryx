"""
Shared task-attachment access-control helpers: fetch a task by id (404 if
missing), verify the requesting user can access its workspace (403 if not),
and fetch the requesting user's company (404 if missing). Originally
duplicated across upload_task_attachment / bulk_upload_task_attachments /
delete_task_attachment / update_task_attachment in the pre-split
attachments.py.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company


async def _get_task_or_404(db: AsyncSession, task_id: str):
    from app.models.task import Task
    task_stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(task_stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    return task


async def _check_task_access(db: AsyncSession, task, user) -> None:
    if task.workspace_id:
        from app.models.workspace import Workspace
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()

        if workspace and not workspace.is_accessible_by_user(user.company_id, user.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task workspace"
            )


async def _get_company_or_404(db: AsyncSession, company_id: str) -> Company:
    company_stmt = select(Company).where(Company.id == company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    return company
