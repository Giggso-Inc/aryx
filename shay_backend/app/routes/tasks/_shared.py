"""
Small, dependency-free response/serialization helpers shared by every task
endpoint submodule (crud, listing, assignment, thread_tasks).
"""

from typing import Any, Dict, List, Optional

from app.models.task import Task


def format_due_date_for_response(due_date) -> Optional[str]:
    """Helper function to format due_date for API responses"""
    if not due_date:
        return None

    if hasattr(due_date, 'isoformat'):
        # If it's a datetime object, use isoformat
        return due_date.isoformat()
    else:
        # If it's a date object, convert to datetime first
        from datetime import datetime
        return datetime.combine(due_date, datetime.min.time()).isoformat()


def convert_checklists_to_dict(checklists) -> List[dict]:
    """Convert checklist objects to dictionary format safely"""
    if not checklists:
        return []

    result = []
    for checklist in checklists:
        if hasattr(checklist, 'to_dict'):
            result.append(checklist.to_dict())
        else:
            # Fallback: create dict manually if to_dict method is not available
            result.append({
                'id': str(checklist.id) if hasattr(checklist, 'id') else None,
                'task_id': str(checklist.task_id) if hasattr(checklist, 'task_id') else None,
                'text': checklist.text if hasattr(checklist, 'text') else '',
                'order_index': checklist.order_index if hasattr(checklist, 'order_index') else 0,
                'is_completed': checklist.is_completed if hasattr(checklist, 'is_completed') else False,
                'completed_at': checklist.completed_at.isoformat() if hasattr(checklist, 'completed_at') and checklist.completed_at else None,
                'completed_by': str(checklist.completed_by) if hasattr(checklist, 'completed_by') and checklist.completed_by else None,
                'checklist_metadata': checklist.checklist_metadata if hasattr(checklist, 'checklist_metadata') else None,
                'created_at': checklist.created_at.isoformat() if hasattr(checklist, 'created_at') and checklist.created_at else None,
                'updated_at': checklist.updated_at.isoformat() if hasattr(checklist, 'updated_at') and checklist.updated_at else None
            })
    return result


def build_task_response(task: Task, include_details: bool = False) -> Dict[str, Any]:
    """Build a safe serializable response for a Task without mutating ORM relationships"""
    response = {
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'status': task.status,
        'source': task.source,
        'due_date': format_due_date_for_response(task.due_date),
        'priority': task.priority,
        'tags': task.tags,
        'task_metadata': task.task_metadata,
        'created_at': task.created_at,
        'updated_at': task.updated_at,
        'completed_at': getattr(task, 'completed_at', None),
        'checklists': [],  # Initialize as empty to avoid lazy loading issues
    }

    # Note: channel/workspace details are no longer available as ORM relationships on Task.
    # They are resolved via message_id in load_task_details() and build_task_context().

    return response
