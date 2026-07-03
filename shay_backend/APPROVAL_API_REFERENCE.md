# Approval API Reference

> **Author:** Karthick Chandrasekar  
> **Date:** 19-08-2025  
> **Version:** 1.0.0  
> **Last Updated:** 19-08-2025

---

## 📋 **Document Information**

This document provides comprehensive API documentation for the Approval System,
a thread-level message approval feature that allows users to request, manage,
and track approvals for messages within threads.

**Features Implemented:**
- ✅ Thread-level approval management
- ✅ Message-specific approval requests
- ✅ User assignment and reassignment
- ✅ Status tracking and audit trails
- ✅ Auto-detection and auto-generation
- ✅ Comprehensive filtering and pagination

## Overview

The Approval API provides thread-level message approval functionality. Users can request approval for messages in threads, assign approvers, and manage the approval workflow. This feature is independent of tasks and provides a streamlined approval process for content moderation and decision-making.

## Features

- **Thread-level approvals**: One active approval per thread
- **Message-specific**: Approvals are tied to specific messages within threads
- **User assignment**: Assign any channel member as an approver
- **Status tracking**: Pending, Approved, Rejected statuses
- **Reassignment**: Approvers can reassign to other channel members
- **Audit trail**: Complete history of approval actions and timestamps

## API Endpoints

### Base URL
```
/api/v1/approvals
```

### 1. Create Approval Request

**POST** `/api/v1/approvals/`

Creates a new approval request for a thread message.

**Request Body:**
```json
{
  "message_id": "65d4db60-f8af-4c81-af29-8d1451e98b40",
  "approver_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a",
  "thread_id": "184c961f-9b15-45ac-b6b0-5f5ff17d6450",  // Optional - auto-detected from message_id
  "title": "Custom approval title",                        // Optional - auto-generated if not provided
  "description": "Custom description"                      // Optional - auto-generated if not provided
}
```

**Response:**
```json
{
  "id": "09dd5250-fda3-4827-b834-436d760eca49",
  "thread_id": "184c961f-9b15-45ac-b6b0-5f5ff17d6450",
  "message_id": "65d4db60-f8af-4c81-af29-8d1451e98b40",
  "channel_id": "c0eb8183-d980-4b9c-9bfb-27d3544ac439",
  "requested_by_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a",
  "approver_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a",
  "status": "pending",
  "title": "Approval for: To test the approval first message",
  "description": "Approval request for message in thread: Approval test thread 01",
  "approval_notes": null,
  "rejection_reason": null,
  "comment": null,
  "is_active": "Y",
  "created_at": "2025-08-19T10:42:16.579491",
  "updated_at": "2025-08-19T10:42:16.579491",
  "approved_at": null,
  "rejected_at": null
}
```

**Validation Rules:**
- Thread must exist and be accessible
- Message must belong to the specified thread
- Approver must be an active channel member
- Only one pending approval per thread allowed
- User must have access to the channel
- `thread_id` is optional - auto-detected from `message_id` if not provided
- `title` is optional - auto-generated from message content if not provided
- `description` is optional - auto-generated from thread title if not provided

### 2. List Approvals

**GET** `/api/v1/approvals/`

Lists approvals with filtering and pagination.

**Query Parameters:**
- `page` (int): Page number (default: 1)
- `size` (int): Page size (default: 10, max: 100)
- `status_filter` (string): Filter by status (pending, approved, rejected)
- `channel_id` (string): Filter by channel ID
- `my_approvals` (bool): Show only approvals assigned to current user
- `my_requests` (bool): Show only approvals requested by current user

**Response:**
```json
{
  "approvals": [
    {
      "id": "09dd5250-fda3-4827-b834-436d760eca49",
      "thread_id": "184c961f-9b15-45ac-b6b0-5f5ff17d6450",
      "message_id": "65d4db60-f8af-4c81-af29-8d1451e98b40",
      "channel_id": "c0eb8183-d980-4b9c-9bfb-27d3544ac439",
      "channel_name": "Test Channel",
      "requested_by_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a",
      "requested_by_user_name": "John Doe",
      "requested_by_user_email": "john@test.com",
      "approver_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a",
      "approver_user_name": "John Doe",
      "approver_user_email": "john@test.com",
      "status": "pending",
      "title": "Approval for: To test the approval first message",
      "description": "Approval request for message in thread: Approval test thread 01",
      "approval_notes": null,
      "rejection_reason": null,
      "comment": null,
      "is_active": "Y",
      "created_at": "2025-08-19T10:42:16.579491",
      "updated_at": "2025-08-19T10:42:16.579491",
      "approved_at": null,
      "rejected_at": null
    }
  ],
  "total": 1,
  "page": 1,
  "size": 10
}
```

### 3. Get Approval Statistics

**GET** `/api/v1/approvals/stats`

Gets approval statistics for the current user's accessible channels.

**Query Parameters:**
- `channel_id` (string, optional): Filter by specific channel

**Response:**
```json
{
  "total_pending": 5,
  "total_approved": 12,
  "total_rejected": 3,
  "total_approvals": 20
}
```

### 4. Get Specific Approval

**GET** `/api/v1/approvals/{approval_id}`

Gets detailed information about a specific approval.

**Response:**
```json
{
  "id": "09dd5250-fda3-4827-b834-436d760eca49",
  "thread_id": "184c961f-9b15-45ac-b6b0-5f5ff17d6450",
  "message_id": "65d4db60-f8af-4c81-af29-8d1451e98b40",
  "channel_id": "c0eb8183-d980-4b9c-9bfb-27d3544ac439",
  "channel_name": "Test Channel",
  "requested_by_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a",
  "requested_by_user_name": "John Doe",
  "requested_by_user_email": "john@test.com",
  "approver_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a",
  "approver_user_name": "John Doe",
  "approver_user_email": "john@test.com",
  "status": "pending",
  "title": "Approval for: To test the approval first message",
  "description": "Approval request for message in thread: Approval test thread 01",
  "approval_notes": null,
  "rejection_reason": null,
  "comment": null,
  "is_active": "Y",
  "created_at": "2025-08-19T10:42:16.579491",
  "updated_at": "2025-08-19T10:42:16.579491",
  "approved_at": null,
  "rejected_at": null
}
```

**Access Control:**
- Only the requester or assigned approver can view the approval

### 5. Update Approval

**PUT** `/api/v1/approvals/{approval_id}`

Updates an approval request (only pending approvals can be updated).

**Request Body:**
```json
{
  "title": "Updated approval title",
  "description": "Updated description",
  "approver_user_id": "new-approver-uuid"
}
```

**Validation Rules:**
- Only pending approvals can be updated
- New approver must be an active channel member
- Only requester or current approver can update

### 6. Take Approval Action

**POST** `/api/v1/approvals/{approval_id}/action`

Takes action on an approval (approve/reject).

**Request Body:**
```json
{
  "action": "approve",           // "approve" or "reject"
  "comment": "Approval comment", // Optional comment
  "rejection_reason": "Reason"   // Required if action is "reject"
}
```

**Validation Rules:**
- Only the assigned approver can take action
- Only pending approvals can have actions taken
- Rejection reason is required for rejections
- Comment field is optional but recommended for audit trail

### 7. Reassign Approval

**POST** `/api/v1/approvals/{approval_id}/reassign`

Reassigns an approval to another user.

**Request Body:**
```json
{
  "new_approver_user_id": "new-approver-uuid",
  "notes": "Reassignment notes"
}
```

**Validation Rules:**
- Only the current approver can reassign
- Only pending approvals can be reassigned
- New approver must be an active channel member

### 8. Delete Approval

**DELETE** `/api/v1/approvals/{approval_id}`

Deletes an approval (soft delete by setting is_active to 'N').

**Validation Rules:**
- Only the requester can delete
- Only pending approvals can be deleted

**Response:**
```json
{
  "message": "Approval deleted successfully"
}
```

## Data Models

### Approval Model

```python
class Approval(Base):
    __tablename__ = "gg_approvals"
    
    id = Column(UUID(as_uuid=True), primary_key=True)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("gg_threads.id"))
    message_id = Column(UUID(as_uuid=True), ForeignKey("gg_messages.id"))
    channel_id = Column(UUID(as_uuid=True), ForeignKey("gg_channels.id"))
    requested_by_user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id"))
    approver_user_id = Column(UUID(as_uuid=True), ForeignKey("gg_users.id"))
    status = Column(String(20), default="pending")  # pending, approved, rejected
    title = Column(String(255))
    description = Column(Text)
    approval_notes = Column(Text)
    rejection_reason = Column(Text)
    comment = Column(Text)  # General comment field for approve/reject actions
    is_active = Column(String(1), default="Y")
    created_at = Column(DateTime, default=func.current_timestamp())
    updated_at = Column(DateTime, default=func.current_timestamp())
    approved_at = Column(DateTime)
    rejected_at = Column(DateTime)
```

## Business Rules

### 1. Approval Creation
- One active approval per thread
- Approver must be an active channel member
- User must have access to the channel

### 2. Approval Actions
- Only assigned approver can approve/reject
- Only pending approvals can have actions taken
- Rejection requires a reason

### 3. Approval Updates
- Only pending approvals can be updated
- New approver must be validated
- Only requester or current approver can update

### 4. Access Control
- Users can only see approvals they're involved in
- Channel access is validated for all operations
- Company-level isolation is maintained

## Error Handling

### Common Error Responses

**400 Bad Request:**
```json
{
  "detail": "Approver must be an active member of the channel"
}
```

**403 Forbidden:**
```json
{
  "detail": "Only the assigned approver can take action on this approval"
}
```

**404 Not Found:**
```json
{
  "detail": "Approval not found"
}
```

**409 Conflict:**
```json
{
  "detail": "There is already a pending approval for this thread"
}
```

## Usage Examples

### 1. Request Approval for a Message

```bash
curl -X POST "http://localhost:8000/api/v1/approvals/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message_id": "65d4db60-f8af-4c81-af29-8d1451e98b40",
    "approver_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a"
    // thread_id, title, and description are optional and will be auto-generated
  }'
```

### 2. Approve a Request

```bash
curl -X POST "http://localhost:8000/api/v1/approvals/approval-uuid/action" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "approve",
    "comment": "Content looks good, approved"
  }'
```

### 3. Reject a Request

```bash
curl -X POST "http://localhost:8000/api/v1/approvals/approval-uuid/action" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "reject",
    "comment": "Content needs revision",
    "rejection_reason": "Violates community guidelines"
  }'
```

### 4. Reassign Approval

```bash
curl -X POST "http://localhost:8000/api/v1/approvals/approval-uuid/reassign" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "new_approver_user_id": "new-approver-uuid",
    "notes": "Reassigned due to workload"
  }'
```

### 5. List My Approvals

```bash
curl -X GET "http://localhost:8000/api/v1/approvals/?my_approvals=true&status_filter=pending" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Database Schema

The approval system uses the following table structure:

```sql
CREATE TABLE gg_approvals (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES gg_threads(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES gg_messages(id) ON DELETE CASCADE,
    channel_id UUID NOT NULL REFERENCES gg_channels(id) ON DELETE CASCADE,
    requested_by_user_id UUID NOT NULL REFERENCES gg_users(id) ON DELETE CASCADE,
    approver_user_id UUID NOT NULL REFERENCES gg_users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    title VARCHAR(255) NOT NULL,
    description TEXT,
    approval_notes TEXT,
    rejection_reason TEXT,
    comment TEXT,
    is_active VARCHAR(1) NOT NULL DEFAULT 'Y',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP,
    rejected_at TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_thread_active_approval ON gg_approvals(thread_id, is_active);
CREATE INDEX idx_channel_status ON gg_approvals(channel_id, status);
CREATE INDEX idx_approver_status ON gg_approvals(approver_user_id, status);
```

## Security Considerations

1. **Authentication**: All endpoints require valid JWT tokens
2. **Authorization**: Users can only access approvals they're involved in
3. **Input Validation**: All input is validated and sanitized
4. **SQL Injection**: Protected through SQLAlchemy ORM
5. **Rate Limiting**: Consider implementing rate limiting for approval creation

## Performance Considerations

1. **Indexing**: Proper indexes on frequently queried columns
2. **Pagination**: Large result sets are paginated
3. **Eager Loading**: User and channel details are loaded in single queries
4. **Soft Deletes**: Uses soft deletes to maintain data integrity

## Frontend Integration Guide

### **Complete API Examples with Real Data**

#### **1. Create Approval (Minimal Request)**
```bash
curl -X 'POST' \
  'http://localhost:8000/api/v1/approvals/' \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "message_id": "65d4db60-f8af-4c81-af29-8d1451e98b40",
    "approver_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a"
  }'
```

#### **2. Create Approval (Full Request)**
```bash
curl -X 'POST' \
  'http://localhost:8000/api/v1/approvals/' \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "message_id": "65d4db60-f8af-4c81-af29-8d1451e98b40",
    "approver_user_id": "6e6a69d0-150b-47b4-a9fe-761f58b0698a",
    "thread_id": "184c961f-9b15-45ac-b6b0-5f5ff17d6450",
    "title": "Custom approval title",
    "description": "Custom description"
  }'
```

#### **3. List Approvals with Filters**
```bash
curl -X 'GET' \
  'http://localhost:8000/api/v1/approvals/?page=1&size=10&status_filter=pending&my_approvals=false&my_requests=false' \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN'
```

#### **4. Get Approval Details**
```bash
curl -X 'GET' \
  'http://localhost:8000/api/v1/approvals/09dd5250-fda3-4827-b834-436d760eca49' \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN'
```

#### **5. Take Approval Action (Approve)**
```bash
curl -X 'POST' \
  'http://localhost:8000/api/v1/approvals/09dd5250-fda3-4827-b834-436d760eca49/action' \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "approve",
    "comment": "Content looks good, approved"
  }'
```

#### **6. Take Approval Action (Reject)**
```bash
curl -X 'POST' \
  'http://localhost:8000/api/v1/approvals/09dd5250-fda3-4827-b834-436d760eca49/action' \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "reject",
    "comment": "Content needs revision",
    "rejection_reason": "Violates community guidelines"
  }'
```

#### **7. Reassign Approval**
```bash
curl -X 'POST' \
  'http://localhost:8000/api/v1/approvals/09dd5250-fda3-4827-b834-436d760eca49/reassign' \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "new_approver_user_id": "new-approver-uuid",
    "notes": "Reassigned due to workload"
  }'
```

#### **8. Get Approval Statistics**
```bash
curl -X 'GET' \
  'http://localhost:8000/api/v1/approvals/stats?channel_id=c0eb8183-d980-4b9c-9bfb-27d3544ac439' \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN'
```

### **Frontend Integration Tips**

#### **1. Auto-detection Features**
- **`thread_id`**: Send only `message_id` - the API will auto-detect the thread
- **`title`**: Send only `message_id` - the API will auto-generate from message content
- **`description`**: Send only `message_id` - the API will auto-generate from thread title

#### **2. Real-time Updates**
- Poll the list endpoint every 30-60 seconds for live updates
- Consider implementing WebSocket for real-time notifications
- Update UI immediately after successful API calls

#### **3. Status Management**
- **`pending`**: Show "Awaiting Approval" with approve/reject buttons
- **`approved`**: Show "Approved" with green checkmark and comment
- **`rejected`**: Show "Rejected" with red X and rejection reason

#### **4. User Permissions**
- **Requester**: Can update, delete, and view their own approvals
- **Approver**: Can approve, reject, reassign, and view assigned approvals
- **Channel Members**: Can view approvals in their channels

#### **5. Error Handling**
- Implement proper error handling for all API responses
- Show user-friendly error messages
- Handle network errors gracefully

#### **6. UI Components**
- **Approval Card**: Display approval details with action buttons
- **Status Badge**: Color-coded status indicators
- **Action Modal**: Forms for approve/reject/reassign actions
- **Filter Panel**: Status, channel, and user filters

#### **7. Data Flow**
```
User Action → API Call → Response → UI Update → State Management
```

## Future Enhancements

1. **Approval Templates**: Predefined approval workflows
2. **Multi-level Approvals**: Chain of approval requirements
3. **Approval Notifications**: Email/SMS notifications for approvers
4. **Approval Analytics**: Dashboard with approval metrics
5. **Approval History**: Complete audit trail of all changes
6. **Bulk Operations**: Approve/reject multiple items at once
