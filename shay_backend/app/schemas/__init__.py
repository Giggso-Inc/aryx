"""
Pydantic schemas for the Log Analyzer Backend.

This module serves as the central import hub for all Pydantic schemas used
throughout the application. It provides a clean interface for importing
validation schemas for authentication, users, workspaces, messages, and more.

Author: Karthick Chandrasekar
Date: 2025-08-14
Version: 1.0.0
"""

from .auth import (
    Token,
    TokenData,
    UserLogin,
    UserCreate,
    UserUpdate,
    OAuthLogin,
    OAuthCallback,
    RefreshToken,
    LogoutRequest
)

from .user import (
    UserResponse,
    UserInviteRequest,
    UserInviteResponse,
    UserRegisterRequest,
    UserLoginRequest,
    UserUpdateRequest,
    UserListResponse,
    BulkUserInviteRequest,
    BulkUserInviteResponse,
    BulkUserInviteItem
)

from .workspace import (
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceResponse,
    WorkspaceList,
    WorkspaceStats
)

from .message import (
    MessageCreate,
    MessageUpdate,
    MessageResponse,
    ThreadCreate,
    ThreadUpdate,
    ThreadResponse,
    ThreadList,
    MessageList,
    ThreadSummary
)

from .attachment import (
    AttachmentCreate,
    AttachmentUpdate,
    AttachmentResponse,
    AttachmentList,
    AttachmentStats
)

from .agent import (
    AICallback,
    AIStatus,
    AIHealth,
    AIStats,
    AITrigger,
    AIWebhookPayload
)

from .channel import (
    ChannelCreate,
    ChannelUpdate,
    ChannelResponse,
    ChannelList,
    WorkspaceTagResponse,
    WorkspaceTagList
)

from .app import (
    AppCreate,
    AppUpdate,
    AppResponse,
    AppList,
    AppStats
)

from .app_account import (
    AppAccountCreate,
    AppAccountUpdate,
    AppAccountResponse,
    AppAccountList,
    AppAccountStats,
    AppConnectionRequest
)

from .task import (
    TaskCreate,
    TaskUpdate,
    TaskResponse,
    TaskList,
    TaskStats,
    TaskAssignmentRequest,
    TaskStatusUpdateRequest,
    TaskFilterRequest
)

from .checklist import (
    ChecklistCreate,
    ChecklistUpdate,
    ChecklistResponse,
    ChecklistList,
    ChecklistBulkCreate,
    ChecklistBulkUpdate,
    ChecklistCompletionRequest,
    ChecklistReorderRequest,
    ChecklistStats
)

from .subscription_plan import (
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
    SubscriptionPlanResponse,
    SubscriptionPlanList,
    SubscriptionPlanFilter
)

from .subscription import (
    SubscriptionCreate,
    SubscriptionUpdate,
    SubscriptionResponse,
    SubscriptionList,
    SubscriptionFilter,
    CompanyCurrentPlanResponse
)