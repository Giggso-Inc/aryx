"""
Email senders for task assignment/reassignment notifications. Used by
notifications_dispatch.py (via _notifications_dispatch_assign.py /
_notifications_dispatch_reassign.py).

This used to be a single 169-line module. Raven style-compliance pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) split it by concern:
  - _notifications_email_assign.py: send_task_assignment_notification_email
  - _notifications_email_reassign.py: send_task_reassignment_notification_email
This module re-exports both so every existing
`from .notifications_email import send_task_..._notification_email` import
elsewhere in this package keeps working unchanged.
"""

from ._notifications_email_assign import send_task_assignment_notification_email
from ._notifications_email_reassign import send_task_reassignment_notification_email

__all__ = [
    "send_task_assignment_notification_email",
    "send_task_reassignment_notification_email",
]
