"""
Shared access-control helpers for the checklists routes.

Both task-scoped and checklist-scoped endpoints repeat the same "fetch
the parent, then verify the requesting user's company matches the
parent task's workspace company" pattern. Extracted here verbatim (no
behavior change) so it is defined once instead of nine times.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checklist import Checklist
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace


async def get_task_with_workspace_access(task_id: str, db: AsyncSession, user: User) -> Task:
    """Fetch a task and verify the user's company matches its workspace's company."""
    task_stmt = select(Task).where(Task.id == task_id)
    result = await db.execute(task_stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    if task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()

        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to task"
            )

    return task


async def get_checklist_with_access(checklist_id: str, db: AsyncSession, user: User) -> Checklist:
    """Fetch a checklist and verify access through its parent task's workspace."""
    checklist_stmt = select(Checklist).where(Checklist.id == checklist_id)
    result = await db.execute(checklist_stmt)
    checklist = result.scalar_one_or_none()

    if not checklist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checklist not found"
        )

    task_stmt = select(Task).where(Task.id == checklist.task_id)
    task_result = await db.execute(task_stmt)
    task = task_result.scalar_one_or_none()

    if task and task.workspace_id:
        workspace_stmt = select(Workspace).where(Workspace.id == task.workspace_id)
        workspace_result = await db.execute(workspace_stmt)
        workspace = workspace_result.scalar_one_or_none()

        if not workspace or workspace.company_id != user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to checklist"
            )

    return checklist
