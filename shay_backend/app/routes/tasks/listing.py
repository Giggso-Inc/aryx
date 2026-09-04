"""
Task listing/counting/stats endpoints (mounted at /api/v1/tasks):
  GET /              list_tasks
  GET /count         get_task_count
  GET /stats/overview  get_task_stats

Stated exception (list_tasks alone is ~280 lines, well over the 150-line
target): the endpoint builds one paginated response with inline per-task
error recovery (a try/except per task so one bad task doesn't break the
whole page) — that recovery logic is only meaningful inline, next to the
loop it guards.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from sqlalchemy.sql.expression import literal
from sqlalchemy.dialects.postgresql import JSONB as PgJSONB

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.utils.channel_access import check_channel_access_by_thread
from app.models.task import Task
from app.models.channel import Channel
from app.models.channel_member import ChannelMember
from app.models.message import Message
from app.schemas.task import TaskListResponse, TaskCountResponse, TaskStats

from ._shared import convert_checklists_to_dict, format_due_date_for_response
from ._details import build_task_details, build_task_context
from ._history import build_task_history

router = APIRouter()


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(10, ge=1, le=100, description="Page size"),
    status: Optional[str] = Query(None, description="Filter by status (comma-separated for multiple values, e.g., 'Open,In Progress,On Hold')"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned user"),
    workspace_id: Optional[str] = Query(None, description="Filter by workspace (resolved via message)"),
    channel_id: Optional[str] = Query(None, description="Filter by channel (resolved via message)"),
    thread_id: Optional[str] = Query(None, description="Filter by thread (resolved via message)"),
    source: Optional[str] = Query(None, description="Filter by source"),
    tags: Optional[str] = Query(None, description="Filter by tags (comma-separated)"),
    created_by: Optional[str] = Query(None, description="Filter by task creator")
) -> TaskListResponse:
    """List tasks with enhanced details, history, and first task per thread limit"""
    user = await get_current_user_required(request, db)

    # Get channels where the user is a member (active channels only)
    user_channels_query = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )

    user_channels_result = await db.execute(user_channels_query)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]

    print(f"User {user.id} is a member of {len(user_channel_ids)} active channels")
    print(f"Channel IDs: {user_channel_ids}")

    if not user_channel_ids:
        return TaskListResponse(
            tasks=[],
            total=0,
            page=page,
            size=size,
            has_more=False
        )

    # Task model no longer has channel_id/thread_id/workspace_id columns.
    # Access control: get message IDs in user's channels, then find tasks by message_id.
    # Collect message IDs visible to the user (messages in their channels).
    user_messages_query = select(Message.id).where(
        Message.channel_id.in_(user_channel_ids)
    )
    if thread_id:
        # Check channel access via thread_id before filtering
        await check_channel_access_by_thread(db, user, thread_id)
        user_messages_query = user_messages_query.where(Message.thread_id == thread_id)
    if channel_id:
        user_messages_query = user_messages_query.where(Message.channel_id == channel_id)

    user_messages_result = await db.execute(user_messages_query)
    visible_message_ids = [row[0] for row in user_messages_result.all()]

    if not visible_message_ids:
        return TaskListResponse(
            tasks=[],
            total=0,
            page=page,
            size=size,
            has_more=False
        )

    # Build base query restricted to tasks linked to visible messages
    base_conditions = [Task.message_id.in_(visible_message_ids)]

    # Apply simple column filters
    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            base_conditions.append(Task.status.in_(status_list))

    if priority:
        base_conditions.append(Task.priority == priority)

    if assigned_to:
        base_conditions.append(Task.assigned_to == assigned_to)

    if source:
        base_conditions.append(Task.source == source)

    if created_by:
        base_conditions.append(Task.created_by == created_by)

    if tags:
        tag_list = [tag.strip() for tag in tags.split(",")]
        base_conditions.append(Task.tags.op("@>")(literal(tag_list, type_=PgJSONB())))

    # Handle task fetching
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

    else:
        # Fetch all tasks from visible messages
        print("No thread_id filter - directly fetching tasks from user's channels")
        print(f"User ID: {user.id}")
        print(f"User channel count: {len(user_channel_ids)}")

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

    # Apply post-fetch filters
    filtered_tasks = []
    for task in tasks:
        # Exclude tasks with no message_id (orphans)
        if task.message_id is None:
            continue
        # Note: status/priority/assigned_to/source/created_by/tags filters already applied above
        filtered_tasks.append(task)

    # Apply pagination
    total = len(filtered_tasks)
    start_idx = (page - 1) * size
    end_idx = start_idx + size
    paginated_tasks = filtered_tasks[start_idx:end_idx]

    # Build enhanced responses
    enhanced_responses = []

    for i, task in enumerate(paginated_tasks):
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
            enhanced_response = {
                'id': str(task.id),
                'task_details': task_details,
                'task_history': task_history,
                'checklists': convert_checklists_to_dict(getattr(task, 'checklists', [])),
                'context': context
            }

            enhanced_responses.append(enhanced_response)

        except Exception as e:
            print(f"Error building enhanced response for task {i+1} (ID: {getattr(task, 'id', 'Unknown')}): {e}")
            import traceback
            traceback.print_exc()

            # Add a basic response if building enhanced response fails
            try:
                basic_response = {
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
                enhanced_responses.append(basic_response)
            except Exception as basic_error:
                print(f"Error creating basic response for task {i+1}: {basic_error}")
                continue

    has_more = end_idx < total

    return TaskListResponse(
        tasks=enhanced_responses,
        total=total,
        page=page,
        size=size,
        has_more=has_more
    )


@router.get("/count", response_model=TaskCountResponse)
async def get_task_count(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> TaskCountResponse:
    """Get total count of tasks for the current user - uses same logic as list endpoint"""
    user = await get_current_user_required(request, db)

    # Get channels where the user is a member (active channels only)
    user_channels_query = select(ChannelMember.channel_id).where(
        and_(
            ChannelMember.user_id == user.id,
            ChannelMember.is_active == True
        )
    )

    user_channels_result = await db.execute(user_channels_query)
    user_channel_ids = [str(c) for c in user_channels_result.scalars().all()]

    if not user_channel_ids:
        return TaskCountResponse(task_count=0)

    # Use the same logic as list_tasks endpoint:
    # Count tasks linked to messages in user's channels.
    visible_message_ids_query = select(Message.id).where(
        Message.channel_id.in_(user_channel_ids)
    )
    visible_msg_result = await db.execute(visible_message_ids_query)
    visible_message_ids = [row[0] for row in visible_msg_result.all()]

    if not visible_message_ids:
        return TaskCountResponse(task_count=0)

    count_query = select(func.count(Task.id)).where(
        Task.message_id.in_(visible_message_ids)
    )
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    return TaskCountResponse(task_count=total_count)


@router.get("/stats/overview", response_model=TaskStats)
async def get_task_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    workspace_id: Optional[str] = Query(None, description="Filter by workspace"),
    channel_id: Optional[str] = Query(None, description="Filter by channel")
) -> TaskStats:
    """Get task statistics"""
    from app.models.workspace import Workspace

    user = await get_current_user_required(request, db)

    # Build base query for accessible channels (via company workspaces)
    workspace_query = select(Workspace.id).where(Workspace.company_id == user.company_id)
    if workspace_id:
        workspace_query = workspace_query.where(Workspace.id == workspace_id)

    workspace_result = await db.execute(workspace_query)
    accessible_workspaces = [str(w) for w in workspace_result.scalars().all()]

    if not accessible_workspaces:
        return TaskStats(
            total_tasks=0,
            open_tasks=0,
            in_progress_tasks=0,
            on_hold_tasks=0,
            closed_tasks=0,
            urgent_tasks=0
        )

    # Find channels in those workspaces
    channels_query = select(Channel.id).where(Channel.workspace_id.in_(accessible_workspaces))
    if channel_id:
        channels_query = channels_query.where(Channel.id == channel_id)
    channels_result = await db.execute(channels_query)
    accessible_channel_ids = [row[0] for row in channels_result.all()]

    if not accessible_channel_ids:
        return TaskStats(
            total_tasks=0,
            open_tasks=0,
            in_progress_tasks=0,
            on_hold_tasks=0,
            closed_tasks=0,
            urgent_tasks=0
        )

    # Find message IDs in those channels
    msg_ids_query = select(Message.id).where(Message.channel_id.in_(accessible_channel_ids))
    msg_ids_result = await db.execute(msg_ids_query)
    accessible_message_ids = [row[0] for row in msg_ids_result.all()]

    if not accessible_message_ids:
        return TaskStats(
            total_tasks=0,
            open_tasks=0,
            in_progress_tasks=0,
            on_hold_tasks=0,
            closed_tasks=0,
            urgent_tasks=0
        )

    # Build task query
    task_query = select(Task).where(Task.message_id.in_(accessible_message_ids))

    # Get all tasks for stats
    result = await db.execute(task_query)
    tasks = result.scalars().all()

    # Calculate stats
    total_tasks = len(tasks)
    open_tasks = len([t for t in tasks if t.status == 'Open'])
    in_progress_tasks = len([t for t in tasks if t.status == 'In Progress'])
    on_hold_tasks = len([t for t in tasks if t.status == 'On Hold'])
    closed_tasks = len([t for t in tasks if t.status == 'Close'])
    overdue_tasks = len([t for t in tasks if t.is_overdue])
    urgent_tasks = len([t for t in tasks if t.is_urgent])

    return TaskStats(
        total_tasks=total_tasks,
        open_tasks=open_tasks,
        in_progress_tasks=in_progress_tasks,
        on_hold_tasks=on_hold_tasks,
        closed_tasks=closed_tasks,
        overdue_tasks=overdue_tasks,
        urgent_tasks=urgent_tasks
    )
