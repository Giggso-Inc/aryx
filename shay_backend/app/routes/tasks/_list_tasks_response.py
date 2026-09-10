"""
Private helper for list_tasks.py (GET /): builds one task's enhanced
response entry, including the endpoint's original per-task error recovery
(a try/except per task so one bad task doesn't break the whole page).
Split out purely to keep list_tasks.py under the 150-line-per-file target;
not reused by any other endpoint.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ._shared import convert_checklists_to_dict, format_due_date_for_response
from ._details_context import build_task_details, build_task_context
from ._history import build_task_history


async def build_enhanced_task_response(task, db: AsyncSession) -> dict:
    """Build one enhanced task-list entry, or a basic fallback entry if any
    step of building the enhanced entry fails. Mirrors the original inline
    per-task try/except recovery exactly."""
    try:
        # Ensure we have a fresh database session
        await db.refresh(task)

        # Load checklists
        try:
            await db.refresh(task, attribute_names=['checklists'])
        except Exception as e:
            print(f"Warning: Could not load checklists for task {task.id}: {e}")
            task.checklists = []

        # Build task details with error handling
        try:
            task_details = await build_task_details(task, db)
        except Exception as e:
            print(f"Error building task details for {task.id}: {e}")
            import traceback
            traceback.print_exc()
            # Fallback task details
            task_details = {
                'task_name': task.title,
                'status': task.status,
                'assignee': None,
                'created_by': None,
                'priority': task.priority,
                'description': task.description,
                'due_date': format_due_date_for_response(task.due_date),
                'created_at': task.created_at.isoformat() if task.created_at else None,
                'updated_at': task.updated_at.isoformat() if task.updated_at else None,
                'source': task.source or 'manual',
                'tags': task.tags,
                'task_metadata': task.task_metadata
            }

        # Build task history with error handling
        try:
            task_history = await build_task_history(task, db)
        except Exception as e:
            print(f"Error building task history for {task.id}: {e}")
            import traceback
            traceback.print_exc()
            task_history = []

        # Build context information with error handling
        try:
            context = await build_task_context(task, db)
        except Exception as e:
            print(f"Error building task context for {task.id}: {e}")
            import traceback
            traceback.print_exc()
            context = {}

        # Build enhanced response
        return {
            'id': str(task.id),
            'task_details': task_details,
            'task_history': task_history,
            'checklists': convert_checklists_to_dict(getattr(task, 'checklists', [])),
            'context': context
        }

    except Exception as e:
        print(f"Error building enhanced response for task (ID: {getattr(task, 'id', 'Unknown')}): {e}")
        import traceback
        traceback.print_exc()

        # Add a basic response if building enhanced response fails
        try:
            return {
                'id': str(getattr(task, 'id', 'unknown')),
                'task_details': {
                    'task_name': getattr(task, 'title', 'Unknown'),
                    'status': getattr(task, 'status', 'Unknown'),
                    'assignee': None,
                    'created_by': None,
                    'priority': getattr(task, 'priority', 'Unknown'),
                    'description': getattr(task, 'description', ''),
                    'due_date': format_due_date_for_response(task.due_date),
                    'created_at': getattr(task, 'created_at', None),
                    'updated_at': getattr(task, 'updated_at', None),
                    'source': getattr(task, 'source', ''),
                    'tags': getattr(task, 'tags', []),
                    'task_metadata': getattr(task, 'task_metadata', {})
                },
                'task_history': [],
                'checklists': [],
                'context': {}
            }
        except Exception as basic_error:
            print(f"Error creating basic response for task: {basic_error}")
            return None
