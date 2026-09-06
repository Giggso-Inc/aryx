"""
Background-task entry points for task assignment/reassignment notifications
(scheduled via FastAPI's BackgroundTasks from create.py, assign.py, and
update.py).

This used to be a single 267-line module. Raven style-compliance pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) split it by concern:
  - _notifications_membership.py: the shared channel-membership lookup
  - _notifications_dispatch_assign.py: process_task_assignment_notifications
  - _notifications_dispatch_reassign.py: process_task_reassignment_notifications
This module re-exports both process_* functions so every existing
`from .notifications_dispatch import process_task_...` import elsewhere in
this package keeps working unchanged.
"""

from ._notifications_dispatch_assign import process_task_assignment_notifications
from ._notifications_dispatch_reassign import process_task_reassignment_notifications
from ._notifications_membership import get_channel_members_with_task_notifications_enabled

__all__ = [
    "process_task_assignment_notifications",
    "process_task_reassignment_notifications",
    "get_channel_members_with_task_notifications_enabled",
]
