# Task & Checklist API Reference

**Version:** 1.0.0  
**Author:** Karthick Chandrasekar  
**Date:** 18-08-2025  

## Table of Contents
1. [Task APIs](#task-apis)
2. [Checklist APIs](#checklist-apis)
3. [Common Response Formats](#common-response-formats)
4. [Error Handling](#error-handling)
5. [Authentication](#authentication)

---

## Task APIs

### 1. Create Task
**Endpoint:** `POST /api/v1/tasks/`  
**Description:** Create a new task with optional context resolution from message_id

#### Minimal Request Payload (Mandatory Fields Only)
```json
{
  "title": "Implement User Authentication System",
  "priority": "High",
  "assigned_to": "2fa5b7fc-8216-4456-88af-be07ed5c1191",
  "message_id": "795019c5-feb1-44ef-8c6a-5b171900de38"
}
```

#### Complete Request Payload (All Fields)
```json
{
  "title": "Implement User Authentication System",
  "priority": "High",
  "assigned_to": "2fa5b7fc-8216-4456-88af-be07ed5c1191",
  "description": "Create a comprehensive authentication system with JWT tokens, password hashing, and role-based access control",
  "message_id": "795019c5-feb1-44ef-8c6a-5b171900de38",
  "status": "Open",
  "source": "manual",
  "due_date": "2025-09-15T17:00:00",
  "tags": ["Authentication", "Security", "Backend"],
  "task_metadata": {
    "epic": "User Management",
    "story_points": 8,
    "acceptance_criteria": [
      "User registration with email verification",
      "Secure login with JWT",
      "Password reset functionality"
    ]
  },
  "checklists": [
    {
      "text": "Design database schema for users and roles",
      "order_index": 0
    },
    {
      "text": "Implement password hashing with bcrypt",
      "order_index": 1
    },
    {
      "text": "Create JWT token generation and validation",
      "order_index": 2
    },
    {
      "text": "Add role-based middleware",
      "order_index": 3
    },
    {
      "text": "Write unit tests for all endpoints",
      "order_index": 4
    }
  ]
}
```

#### Field Descriptions
**Mandatory Fields:**
- **title** (required): Task title (1-255 characters)
- **priority** (required): Task priority - `"Low"`, `"Medium"`, `"High"`, `"Critical"`, `"Blocker"`
- **assigned_to** (required): User ID assigned to the task (must be a member of the channel)
- **message_id** (required): Message ID to associate task with (auto-fills workspace_id, channel_id, thread_id)

## Thread-Level Task Limit

**Rule:** Only one active task is allowed per thread at a time.

**Active Task Statuses:**
- `"Open"` - Task is created but not started
- `"In Progress"` - Task is currently being worked on
- `"On Hold"` - Task is temporarily paused

**Completed Task Status:**
- `"Close"` - Task is completed and thread can accept new tasks

**Benefits:**
- Prevents task conflicts within the same conversation
- Ensures focused attention on one task per thread
- Maintains clear workflow progression
- Allows users to work on multiple threads simultaneously

**Example Scenario:**
```
Thread A: Has active task "Bug Fix" (status: In Progress)
Thread B: Can accept new task "Feature Development" (no active tasks)
Thread C: Can accept new task "Code Review" (no active tasks)

User can work on all three threads but only one task per thread.
```

**Optional Fields:**
- **description** (optional): Detailed task description
- **workspace_id** (optional): Workspace ID (auto-filled from message_id)
- **channel_id** (optional): Channel ID (auto-filled from message_id)
- **thread_id** (optional): Thread ID (auto-filled from message_id)
- **status** (optional): Task status - `"Open"`, `"In Progress"`, `"On Hold"`, `"Close"` (default: "Open")
- **source** (optional): Task source - `"ai_generated"`, `"manual"`, `"system"` (default: "manual")
- **due_date** (optional): Task due date and time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
- **tags** (optional): Array of tags for categorization
- **task_metadata** (optional): Additional JSON data for task context
- **checklists** (optional): Initial checklist items with text and order

#### Response
```json
{
  "id": "8cb255bb-18df-456d-aeff-5778a40e07b1",
  "title": "Implement User Authentication System",
  "description": "Create a comprehensive authentication system with JWT tokens, password hashing, and role-based access control",
  "status": "Open",
  "source": "manual",
  "due_date": "2025-09-15",
  "priority": "High",
  "tags": ["Authentication", "Security", "Backend"],
  "task_metadata": {
    "epic": "User Management",
    "story_points": 8,
    "acceptance_criteria": [
      "User registration with email verification",
      "Secure login with JWT",
      "Password reset functionality"
    ]
  },
  "created_at": "2025-08-18T10:30:00Z",
  "updated_at": "2025-08-18T10:30:00Z",
  "completed_at": null,
  "checklists": [
    {
      "id": "40c41c4e-edea-4df2-a184-b7b0fa3b738a",
      "task_id": "8cb255bb-18df-456d-aeff-5778a40e07b1",
      "text": "Design database schema for users and roles",
      "order_index": 0,
      "is_completed": false,
      "completed_at": null,
      "completed_by": null,
      "checklist_metadata": null,
      "created_at": "2025-08-18T10:30:00Z",
      "updated_at": "2025-08-18T10:30:00Z"
    }
  ]
}
```

### 2. List Tasks
**Endpoint:** `GET /api/v1/tasks/`  
**Description:** Get paginated list of tasks with filtering options

#### Query Parameters
- **page** (optional): Page number (default: 1, min: 1)
- **size** (optional): Page size (default: 10, min: 1, max: 100)
- **status** (optional): Filter by status - `"Open"`, `"In Progress"`, `"On Hold"`, `"Close"`
- **priority** (optional): Filter by priority - `"Low"`, `"Medium"`, `"High"`, `"Critical"`, `"Blocker"`
- **assigned_to** (optional): Filter by assigned user ID
- **workspace_id** (optional): Filter by workspace ID
- **channel_id** (optional): Filter by channel ID
- **thread_id** (optional): Filter by thread ID
- **source** (optional): Filter by source - `"ai_generated"`, `"manual"`, `"system"`
- **tags** (optional): Filter by tags (comma-separated)

#### Example Request
```
GET /api/v1/tasks/?page=1&size=20&status=Open&priority=High&tags=Authentication,Security
```

#### Response
```json
{
  "tasks": [
    {
      "id": "8cb255bb-18df-456d-aeff-5778a40e07b1",
      "title": "Implement User Authentication System",
      "description": "Create a comprehensive authentication system with JWT tokens, password hashing, and role-based access control",
      "status": "Open",
      "source": "manual",
      "due_date": "2025-09-15T17:00:00",
      "priority": "High",
      "tags": ["Authentication", "Security", "Backend"],
      "task_metadata": {
        "epic": "User Management",
        "story_points": 8
      },
      "created_at": "2025-08-18T10:30:00Z",
      "updated_at": "2025-08-18T10:30:00Z",
      "completed_at": null,
      "checklists": [...],
      "assigned_user": {
        "id": "2fa5b7fc-8216-4456-88af-be07ed5c1191",
        "name": "John Doe",
        "email_id": "john.doe@company.com",
        "avatar_url": "https://example.com/avatars/john.jpg",
        "role": "developer"
      },
      "created_by_user": {
        "id": "bbc9711f-3834-470e-9913-789fff3becf9",
        "name": "Jane Smith",
        "email_id": "jane.smith@company.com",
        "avatar_url": "https://example.com/avatars/jane.jpg",
        "role": "admin"
      },
      "channel": {
        "id": "33786c03-772b-4466-a5f3-471f0871f85e",
        "name": "Backend Development",
        "description": "Backend development discussions and tasks",
        "type": "public",
        "is_private": false
      },
      "workspace": {
        "id": "d507a753-7f90-4ea1-8239-ca604ec37ee5",
        "name": "Engineering",
        "description": "Engineering team workspace"
      }
    }
  ],
  "total": 1,
  "page": 1,
  "size": 20
}
```

### 3. Get Task by ID
**Endpoint:** `GET /api/v1/tasks/{task_id}`  
**Description:** Get detailed information about a specific task

#### Response
```json
{
  "id": "8cb255bb-18df-456d-aeff-5778a40e07b1",
  "title": "Implement User Authentication System",
  "description": "Create a comprehensive authentication system with JWT tokens, password hashing, and role-based access control",
  "status": "Open",
  "source": "manual",
  "due_date": "2025-09-15T17:00:00",
  "priority": "High",
  "tags": ["Authentication", "Security", "Backend"],
  "task_metadata": {...},
  "created_at": "2025-08-18T10:30:00Z",
  "updated_at": "2025-08-18T10:30:00Z",
  "completed_at": null,
  "checklists": [...]
}
```

### 4. Update Task
**Endpoint:** `PUT /api/v1/tasks/{task_id}`  
**Description:** Update an existing task

#### Request Payload
```json
{
  "title": "Implement User Authentication System - Updated",
  "description": "Create a comprehensive authentication system with JWT tokens, password hashing, role-based access control, and OAuth integration",
  "assigned_to": "3fa5b7fc-8216-4456-88af-be07ed5c1200",
  "status": "In Progress",
  "priority": "Critical",
  "due_date": "2025-09-10T17:00:00",
  "tags": ["Authentication", "Security", "Backend", "OAuth"],
  "task_metadata": {
    "epic": "User Management",
    "story_points": 12,
    "acceptance_criteria": [
      "User registration with email verification",
      "Secure login with JWT",
      "Password reset functionality",
      "OAuth integration with Google and GitHub"
    ],
    "progress": "25%",
    "blockers": ["Waiting for OAuth app credentials"]
  }
}
```

**Note:** `workspace_id`, `channel_id`, `thread_id`, and `message_id` cannot be updated as they define the task's context and are immutable.

**Important:** Only one active task is allowed per thread at a time. If a thread already has an active task (status: Open, In Progress, or On Hold), you cannot create another task in that thread until the existing task is completed or closed.

### 5. Delete Task
**Endpoint:** `DELETE /api/v1/tasks/{task_id}`  
**Description:** Delete a task (also deletes associated checklists)

#### Response
```json
{
  "message": "Task deleted successfully"
}
```

### 6. Assign Task
**Endpoint:** `POST /api/v1/tasks/{task_id}/assign`  
**Description:** Assign a task to a different user

#### Request Payload
```json
{
  "assigned_to": "3fa5b7fc-8216-4456-88af-be07ed5c1200"
}
```

**Note:** The assigned user must be a member of the channel associated with the task.

### 7. Update Task Status
**Endpoint:** `POST /api/v1/tasks/{task_id}/status`  
**Description:** Update task status with optional comments

#### Request Payload
```json
{
  "status": "In Progress",
  "comments": "Started working on database schema design. Will complete by end of week."
}
```

**Available Statuses:** `"Open"`, `"In Progress"`, `"On Hold"`, `"Close"`

### 8. Check Thread Task Status
**Endpoint:** `GET /api/v1/tasks/thread/{thread_id}/status`  
**Description:** Check if a thread can accept new tasks (one active task per thread limit)

#### Response
```json
{
  "thread_id": "thread-uuid",
  "can_create_task": false,
  "existing_task": {
    "id": "task-uuid",
    "title": "Bug Fix - Authentication System",
    "status": "In Progress",
    "assigned_to": "user-uuid",
    "created_at": "2025-01-15T10:30:00Z",
    "due_date": "2025-01-20T17:00:00"
  },
  "message": "Thread already has an active task: Bug Fix - Authentication System"
}
```

**Response Fields:**
- **can_create_task**: Boolean indicating if thread can accept new tasks
- **existing_task**: Details of existing active task (null if none)
- **message**: Human-readable status message

### 9. Get Task Statistics
**Endpoint:** `GET /api/v1/tasks/stats/overview`  
**Description:** Get task statistics overview

#### Query Parameters
- **workspace_id** (optional): Filter by workspace
- **channel_id** (optional): Filter by channel

#### Response
```json
{
  "total_tasks": 25,
  "open_tasks": 8,
  "in_progress_tasks": 12,
  "on_hold_tasks": 3,
  "closed_tasks": 2,
  "overdue_tasks": 1,
  "urgent_tasks": 5
}
```

### 9. Get Thread Task
**Endpoint:** `GET /api/v1/tasks/thread/{thread_id}`  
**Description:** Get task associated with a specific thread

### 10. Create Thread Task
**Endpoint:** `POST /api/v1/tasks/thread/{thread_id}/create`  
**Description:** Create a task for a specific thread

---

## Checklist APIs

### 1. Bulk Create Checklists
**Endpoint:** `POST /api/v1/checklists/bulk`  
**Description:** Create multiple checklist items for a task

#### Request Payload
```json
{
  "task_id": "8cb255bb-18df-456d-aeff-5778a40e07b1",
  "checklists": [
    {
      "text": "Design database schema for users and roles",
      "order_index": 0
    },
    {
      "text": "Implement password hashing with bcrypt",
      "order_index": 1
    },
    {
      "text": "Create JWT token generation and validation",
      "order_index": 2
    },
    {
      "text": "Add role-based middleware",
      "order_index": 3
    },
    {
      "text": "Write unit tests for all endpoints",
      "order_index": 4
    }
  ]
}
```

#### Response
```json
{
  "message": "5 checklist items created successfully",
  "created_count": 5,
  "checklists": [
    {
      "id": "40c41c4e-edea-4df2-a184-b7b0fa3b738a",
      "task_id": "8cb255bb-18df-456d-aeff-5778a40e07b1",
      "text": "Design database schema for users and roles",
      "order_index": 0,
      "is_completed": false,
      "completed_at": null,
      "completed_by": null,
      "checklist_metadata": null,
      "created_at": "2025-08-18T10:30:00Z",
      "updated_at": "2025-08-18T10:30:00Z"
    }
  ]
}
```

### 2. Add Single Checklist Item
**Endpoint:** `POST /api/v1/checklists/`  
**Description:** Add a single checklist item to a task

#### Request Payload
```json
{
  "task_id": "8cb255bb-18df-456d-aeff-5778a40e07b1",
  "text": "Add OAuth integration with Google and GitHub",
  "order_index": 5,
  "checklist_metadata": {
    "complexity": "high",
    "estimated_hours": 8
  }
}
```

### 3. Get All Checklists for Task
**Endpoint:** `GET /api/v1/checklists/task/{task_id}`  
**Description:** Get all checklist items for a specific task

#### Response
```json
[
  {
    "id": "40c41c4e-edea-4df2-a184-b7b0fa3b738a",
    "task_id": "8cb255bb-18df-456d-aeff-5778a40e07b1",
    "text": "Design database schema for users and roles",
    "order_index": 0,
    "is_completed": true,
    "completed_at": "2025-08-19T14:30:00Z",
    "completed_by": "2fa5b7fc-8216-4456-88af-be07ed5c1191",
    "checklist_metadata": null,
    "created_at": "2025-08-18T10:30:00Z",
    "updated_at": "2025-08-19T14:30:00Z"
  },
  {
    "id": "51d52c5f-fefb-5e03-b295-c8c1fb4c849b",
    "task_id": "8cb255bb-18df-456d-aeff-5778a40e07b1",
    "text": "Implement password hashing with bcrypt",
    "order_index": 1,
    "is_completed": false,
    "completed_at": null,
    "completed_by": null,
    "checklist_metadata": null,
    "created_at": "2025-08-18T10:30:00Z",
    "updated_at": "2025-08-18T10:30:00Z"
  }
]
```

### 4. Get Single Checklist Item
**Endpoint:** `GET /api/v1/checklists/{checklist_id}`  
**Description:** Get a specific checklist item

### 5. Update Checklist Item
**Endpoint:** `PUT /api/v1/checklists/{checklist_id}`  
**Description:** Update a checklist item

#### Request Payload
```json
{
  "text": "Implement password hashing with bcrypt and salt",
  "order_index": 1,
  "checklist_metadata": {
    "complexity": "medium",
    "estimated_hours": 4,
    "notes": "Need to research best practices for salt generation"
  }
}
```

### 6. Delete Checklist Item
**Endpoint:** `DELETE /api/v1/checklists/{checklist_id}`  
**Description:** Delete a checklist item

#### Response
```json
{
  "message": "Checklist item deleted successfully"
}
```

### 7. Mark Checklist Complete/Incomplete
**Endpoint:** `POST /api/v1/checklists/{checklist_id}/toggle`  
**Description:** Toggle completion status of a checklist item

#### Request Payload
```json
{
  "completed_by": "2fa5b7fc-8216-4456-88af-be07ed5c1191",
  "notes": "Completed with bcrypt implementation and salt generation"
}
```

### 8. Reorder Checklists
**Endpoint:** `POST /api/v1/checklists/task/{task_id}/checklists/reorder`  
**Description:** Reorder checklist items for a task

#### Request Payload
```json
{
  "checklist_orders": [
    {
      "checklist_id": "40c41c4e-edea-4df2-a184-b7b0fa3b738a",
      "new_order": 2
    },
    {
      "checklist_id": "51d52c5f-fefb-5e03-b295-c8c1fb4c849b",
      "new_order": 0
    },
    {
      "checklist_id": "62e63d70-0f0c-6f14-c3a6-d9d20c5d950c",
      "new_order": 1
    }
  ]
}
```

### 9. Get Checklist Statistics
**Endpoint:** `GET /api/v1/checklists/stats/task/{task_id}`  
**Description:** Get statistics for checklists in a task

#### Response
```json
{
  "total_items": 5,
  "completed_items": 2,
  "pending_items": 3,
  "completion_percentage": 40.0,
  "last_completed": "2025-08-19T14:30:00Z",
  "last_completed_by": "2fa5b7fc-8216-4456-88af-be07ed5c1191"
}
```

---

## Common Response Formats

### Success Response
```json
{
  "data": {...},
  "message": "Operation completed successfully"
}
```

### Error Response
```json
{
  "error": "Bad Request",
  "message": "Validation failed",
  "details": [
    {
      "field": "status",
      "message": "Status must be one of: Open, In Progress, On Hold, Close"
    }
  ],
  "path": "/api/v1/tasks/",
  "timestamp": "2025-08-18T10:30:00Z"
}
```

---

## Error Handling

### Common HTTP Status Codes
- **200**: Success
- **201**: Created
- **400**: Bad Request (validation errors)
- **401**: Unauthorized (missing/invalid token)
- **403**: Forbidden (insufficient permissions)
- **404**: Not Found
- **409**: Conflict (e.g., task already exists for thread)
- **422**: Unprocessable Entity (validation errors)
- **500**: Internal Server Error

### Validation Error Examples
```json
{
  "error": "Validation Error",
  "message": "Invalid status value",
  "details": "Status must be one of: Open, In Progress, On Hold, Close"
}
```

---

## Authentication

All endpoints require authentication via Bearer token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

### Token Format
```json
{
  "sub": "user-uuid",
  "email": "user@company.com",
  "role": "admin",
  "company_id": "company-uuid",
  "type": "access",
  "exp": 1756117054
}
```

---

## Frontend Integration Notes

### 1. Task Status Workflow
- **Open** → **In Progress** → **On Hold** → **In Progress** → **Close**
- Tasks can move between statuses based on business logic
- **Close** status automatically sets `completed_at` timestamp

### 2. Priority Levels
- **Low**: Non-urgent tasks
- **Medium**: Standard priority (default)
- **High**: Important tasks
- **Critical**: Urgent tasks requiring immediate attention
- **Blocker**: Tasks blocking other work

### 3. Checklist Management
- Checklists are ordered by `order_index`
- Reordering updates all affected items
- Completion tracking includes user and timestamp
- Metadata supports custom fields for business logic

### 4. Real-time Updates
- Consider implementing WebSocket connections for real-time task updates
- Use polling for checklist completion status changes
- Implement optimistic updates for better UX

### 5. Pagination
- Default page size: 10
- Maximum page size: 100
- Include total count for pagination controls
- Support sorting by creation date, priority, due date

### 6. Filtering
- Support multiple filter combinations
- Tags support comma-separated values
- Date ranges for due dates and creation dates
- Company and workspace-based access control

---

## Testing Examples

### cURL Commands

#### Create Task
```bash
curl -X POST 'http://localhost:8000/api/v1/tasks/' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <your_token>' \
  -d '{
    "title": "Test Task",
    "description": "Test Description",
    "message_id": "795019c5-feb1-44ef-8c6a-5b171900de38",
    "assigned_to": "2fa5b7fc-8216-4456-88af-be07ed5c1191",
    "status": "Open",
    "priority": "Medium"
  }'
```

#### List Tasks
```bash
curl -X GET 'http://localhost:8000/api/v1/tasks/?page=1&size=10&status=Open' \
  -H 'Authorization: Bearer <your_token>'
```

#### Update Task Status
```bash
curl -X POST 'http://localhost:8000/api/v1/tasks/<task_id>/status' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <your_token>' \
  -d '{
    "status": "In Progress",
    "comments": "Starting work on this task"
  }'
```

---

This API reference provides comprehensive information for frontend developers to integrate with the Task and Checklist system. All endpoints include proper validation, error handling, and access control based on user permissions and company/workspace/channel membership.
