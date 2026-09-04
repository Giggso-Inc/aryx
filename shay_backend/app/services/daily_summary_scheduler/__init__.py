"""
Daily Summary Email Scheduler Service

This module provides a scheduler service that sends daily summary emails
to users based on their notification routine settings.

Author: AI Assistant
Date: 2025-01-XX
Version: 1.0.0

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 929-line app/services/daily_summary_scheduler.py. It is now a
package of mixins by responsibility, combined into one `DailySummaryScheduler`
class below so that `from app.services.daily_summary_scheduler import
DailySummaryScheduler, daily_summary_scheduler` (used by main.py and
app/routes/notifications/email_settings.py) needs zero changes.

  time_utils.py   - ensure_timezone_aware / datetime_for_db (module functions)
  lifecycle.py    - __init__ / start / stop (the AsyncIOScheduler wiring)
  eligibility.py  - process_daily_summaries (the scheduled job) + get_users_to_notify
  sender.py       - send_daily_summary_email (per-user assemble + SMTP send)
  counts.py       - collect_notification_counts (stated exception, see its docstring)
  top_channels.py - get_top_channels (stated exception, see its docstring)
  cards.py        - generate_enabled_cards
  content.py      - generate_email_content + generate_channels_rows

All mixins share the same `self` (one DailySummaryScheduler instance); no
two mixins define the same method name, so MRO order does not matter here.
"""

from .time_utils import ensure_timezone_aware, datetime_for_db
from .lifecycle import LifecycleMixin
from .eligibility import EligibilityMixin
from .sender import SenderMixin
from .counts import CountsMixin
from .top_channels import TopChannelsMixin
from .cards import CardsMixin
from .content import ContentMixin


class DailySummaryScheduler(
    LifecycleMixin,
    EligibilityMixin,
    SenderMixin,
    CountsMixin,
    TopChannelsMixin,
    CardsMixin,
    ContentMixin,
):
    """Scheduler service for sending daily summary emails (see module docstring for the split map)."""


# Create singleton instance
daily_summary_scheduler = DailySummaryScheduler()

__all__ = [
    "DailySummaryScheduler",
    "daily_summary_scheduler",
    "ensure_timezone_aware",
    "datetime_for_db",
]
