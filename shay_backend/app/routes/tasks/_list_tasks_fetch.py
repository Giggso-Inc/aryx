"""
Private helper for list_tasks.py (GET /): fetches candidate tasks for the
thread-specific and general query paths. Split out purely to keep
list_tasks.py and _list_tasks_helpers.py under the 150-line-per-file
target; not reused by any other endpoint.
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from app.models.task import Task


async def fetch_candidate_tasks(db: AsyncSession, base_conditions: list, thread_id: Optional[str]) -> list:
    """Fetch tasks matching base_conditions, handling the thread_id-specific
    single-task path and the general multi-task path exactly as before."""
    if thread_id:
        # If thread_id is specified, get the latest task from that specific thread
        print(f"Fetching latest task from specific thread: {thread_id}")
        try:
            task_query = select(Task).where(
                and_(*base_conditions)
            ).order_by(desc(Task.created_at)).limit(1)

            task_result = await db.execute(task_query)
            task = task_result.scalar_one_or_none()
            tasks = [task] if task else []
            if task:
                print(f"Found task in specified thread: {task.title}")
            else:
                print(f"No tasks found in specified thread: {thread_id}")

        except Exception as e:
            print(f"Error fetching task from specific thread {thread_id}: {e}")
            tasks = []

        return tasks

    # Fetch all tasks from visible messages
    print("No thread_id filter - directly fetching tasks from user's channels")

    try:
        direct_task_query = select(Task).where(
            and_(*base_conditions)
        ).order_by(desc(Task.created_at))

        print(f"Direct task query: {direct_task_query}")

        direct_result = await db.execute(direct_task_query)
        tasks = list(direct_result.scalars().all())

        print(f"Direct query found {len(tasks)} tasks from user's channels")

        # Remove duplicates based on task ID
        seen_ids = set()
        unique_tasks = []
        for task in tasks:
            if str(task.id) not in seen_ids:
                seen_ids.add(str(task.id))
                unique_tasks.append(task)

        tasks = unique_tasks
        print(f"Combined total: {len(tasks)} unique tasks")

        # Sort tasks by creation date (latest first) for better UX
        if tasks:
            tasks.sort(key=lambda x: x.created_at, reverse=True)
            print(f"Tasks sorted by creation date (latest first)")

    except Exception as e:
        print(f"Error in direct task query: {e}")
        import traceback
        traceback.print_exc()
        tasks = []

    return tasks
