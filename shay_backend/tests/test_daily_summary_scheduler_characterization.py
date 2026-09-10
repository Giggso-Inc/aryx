"""
Golden-master / characterization tests for
app/services/daily_summary_scheduler.py.

Purpose: daily_summary_scheduler.py is 929 lines (two module-level datetime
helpers + one DailySummaryScheduler class) with ZERO prior test coverage. It
is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2). Before the
split, we capture the CURRENT observable behavior of the scheduler
lifecycle, the eligibility/query logic, the per-user send flow, and the
HTML-content builders, so the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today. No pytest-asyncio is installed, so async
methods are driven with asyncio.run() (matches
tests/test_channels_characterization.py).

Boundary mocking:
- The AsyncSession (`db`) is a MagicMock whose `.execute` is an AsyncMock
  returning a MagicMock result object with `.scalars().all()` /
  `.scalar_one_or_none()` / `.scalar()` / `.all()` stubbed per call, matching
  how SQLAlchemy Core result objects are used in the real code — no real DB.
- `email_service` (imported directly into this module) is patched so no SMTP
  call is made.
- `AsyncIOScheduler` / `apscheduler` internals are exercised for real in the
  constructor (matches production) but `start`/`stop` tests patch
  `self.scheduler` directly to avoid a real background thread.

Documented pre-existing bug (found while reading the ground-truth code,
characterized as-is, NOT fixed):
- collect_notification_counts and get_top_channels both build
  `select(Message.channel_id)...` to find "email channel IDs", but the
  Message model (app/models/message.py) has NO channel_id column (only
  thread_id) -- this raises AttributeError the moment a user has ANY
  channel memberships. In other words these two methods only complete
  successfully for a user with zero channels; for any real user with
  channels, send_daily_summary_email's own try/except re-raises it and
  process_daily_summaries's per-user try/except swallows and logs it. See
  TestCollectNotificationCounts.test_channels_present_hits_message_channel_id_bug.

Skipped (not characterized), with reason:
- collect_notification_counts / get_top_channels: beyond the bug above,
  only a representative subset of the ten near-identical
  "if <type>_enabled == 1: count X" blocks is characterized per method
  (mentions and the "no channels" short-circuit) — the remaining blocks
  (posts, replies, tasks, approvals, blockers, meetings, apps, chats,
  friends) follow the exact same enabled-flag-gated count-or-zero pattern,
  and all of them are unreachable anyway once user_channel_ids is non-empty
  (per the bug above), so exhaustively re-testing each would not add
  confidence for a split that does not touch this logic's shape.
- generate_email_content's `user_name` line
  (`user.name or user.email_id.split('@')[0] if user.email_id else 'User'`)
  is characterized as-is including its actual operator-precedence behavior
  (it parses as `user.name or (user.email_id.split('@')[0] if user.email_id
  else 'User')`, NOT `(user.name or user.email_id.split('@')[0]) if
  user.email_id else 'User'` — a common misreading of this line). See
  TestGenerateEmailContent.test_user_name_precedence_documents_current_behavior.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _svc():
    from app.services.daily_summary_scheduler import DailySummaryScheduler
    return DailySummaryScheduler()


_UNSET = object()


def _exec_result(*, scalars_all=None, scalar_one_or_none=_UNSET, scalar=None, all_rows=None):
    """Build a MagicMock standing in for the result of `await db.execute(stmt)`."""
    result = MagicMock()
    if scalars_all is not None:
        result.scalars.return_value.all.return_value = scalars_all
    if scalar_one_or_none is not _UNSET:
        result.scalar_one_or_none.return_value = scalar_one_or_none
    if scalar is not None:
        result.scalar.return_value = scalar
    if all_rows is not None:
        result.all.return_value = all_rows
    return result


# ---------------------------------------------------------------------------
# Module-level datetime helpers
# ---------------------------------------------------------------------------

class TestDatetimeHelpers:
    def test_ensure_timezone_aware_none_passthrough(self):
        from app.services.daily_summary_scheduler import ensure_timezone_aware
        assert ensure_timezone_aware(None) is None

    def test_ensure_timezone_aware_naive_assumed_utc(self):
        from app.services.daily_summary_scheduler import ensure_timezone_aware
        naive = datetime(2026, 1, 1, 12, 0, 0)
        result = ensure_timezone_aware(naive)
        assert result.tzinfo == timezone.utc

    def test_ensure_timezone_aware_aware_converted_to_utc(self):
        from app.services.daily_summary_scheduler import ensure_timezone_aware
        from datetime import timedelta as td
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone(td(hours=5)))
        result = ensure_timezone_aware(aware)
        assert result.tzinfo == timezone.utc
        assert result.hour == 7

    def test_datetime_for_db_none_passthrough(self):
        from app.services.daily_summary_scheduler import datetime_for_db
        assert datetime_for_db(None) is None

    def test_datetime_for_db_strips_tzinfo(self):
        from app.services.daily_summary_scheduler import datetime_for_db
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = datetime_for_db(aware)
        assert result.tzinfo is None
        assert result == datetime(2026, 1, 1, 12, 0, 0)


# ---------------------------------------------------------------------------
# Lifecycle: __init__ / start / stop
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_init_not_running(self):
        svc = _svc()
        assert svc.is_running is False
        assert svc.scheduler is not None

    def test_start_sets_is_running_and_adds_job(self):
        svc = _svc()
        svc.scheduler = MagicMock()
        svc.scheduler.get_job.return_value = None
        svc.start()
        assert svc.is_running is True
        svc.scheduler.add_job.assert_called_once()
        svc.scheduler.start.assert_called_once()

    def test_start_is_noop_when_already_running(self):
        svc = _svc()
        svc.scheduler = MagicMock()
        svc.is_running = True
        svc.start()
        svc.scheduler.add_job.assert_not_called()

    def test_stop_shuts_down_and_clears_running(self):
        svc = _svc()
        svc.scheduler = MagicMock()
        svc.is_running = True
        svc.stop()
        assert svc.is_running is False
        svc.scheduler.shutdown.assert_called_once()

    def test_stop_is_noop_when_not_running(self):
        svc = _svc()
        svc.scheduler = MagicMock()
        svc.is_running = False
        svc.stop()
        svc.scheduler.shutdown.assert_not_called()


# ---------------------------------------------------------------------------
# get_users_to_notify
# ---------------------------------------------------------------------------

class TestGetUsersToNotify:
    def test_null_last_notify_time_always_notifies(self):
        svc = _svc()
        setting = MagicMock(resource_id="u1", last_email_notify_time=None, routine=15)
        db = MagicMock()
        db.execute = AsyncMock(return_value=_exec_result(scalars_all=[setting]))
        result = asyncio.run(svc.get_users_to_notify(db))
        assert result == [setting]

    def test_enough_time_passed_notifies(self):
        svc = _svc()
        old_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        setting = MagicMock(resource_id="u1", last_email_notify_time=old_time, routine=15)
        db = MagicMock()
        db.execute = AsyncMock(return_value=_exec_result(scalars_all=[setting]))
        result = asyncio.run(svc.get_users_to_notify(db))
        assert result == [setting]

    def test_not_enough_time_passed_skips(self):
        svc = _svc()
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        setting = MagicMock(resource_id="u1", last_email_notify_time=recent_time, routine=15)
        db = MagicMock()
        db.execute = AsyncMock(return_value=_exec_result(scalars_all=[setting]))
        result = asyncio.run(svc.get_users_to_notify(db))
        assert result == []


# ---------------------------------------------------------------------------
# process_daily_summaries
# ---------------------------------------------------------------------------

class TestProcessDailySummaries:
    def test_processes_each_user_and_continues_on_error(self):
        svc = _svc()
        setting1 = MagicMock(resource_id="u1")
        setting2 = MagicMock(resource_id="u2")

        async def fake_send(settings_obj, db):
            if settings_obj is setting1:
                raise RuntimeError("boom")
            return None

        mock_db_cm = MagicMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(svc, "get_users_to_notify", new=AsyncMock(return_value=[setting1, setting2])), \
             patch.object(svc, "send_daily_summary_email", new=AsyncMock(side_effect=fake_send)) as mock_send, \
             patch("app.services.daily_summary_scheduler.eligibility.AsyncSessionLocal", return_value=mock_db_cm):
            asyncio.run(svc.process_daily_summaries())

        assert mock_send.call_count == 2

    def test_outer_exception_is_swallowed(self):
        # get_users_to_notify itself raising should not propagate.
        svc = _svc()
        mock_db_cm = MagicMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)
        with patch.object(svc, "get_users_to_notify", new=AsyncMock(side_effect=RuntimeError("db down"))), \
             patch("app.services.daily_summary_scheduler.eligibility.AsyncSessionLocal", return_value=mock_db_cm):
            asyncio.run(svc.process_daily_summaries())  # must not raise


# ---------------------------------------------------------------------------
# send_daily_summary_email
# ---------------------------------------------------------------------------

class TestSendDailySummaryEmail:
    def test_skips_when_notifications_disabled(self):
        svc = _svc()
        settings_obj = MagicMock(is_notification_enabled=0, resource_id="u1")
        db = MagicMock()
        db.refresh = AsyncMock()
        asyncio.run(svc.send_daily_summary_email(settings_obj, db))
        db.refresh.assert_awaited_once()

    def test_skips_when_no_notification_types_enabled(self):
        svc = _svc()
        settings_obj = MagicMock(
            is_notification_enabled=1, resource_id="u1",
            mention_enabled=0, post_enabled=0, reply_enabled=0, task_enabled=0,
            approval_pending_enabled=0, meeting_enabled=0, blocker_enabled=0,
            app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        db = MagicMock()
        db.refresh = AsyncMock()
        asyncio.run(svc.send_daily_summary_email(settings_obj, db))
        # Should return early without querying for the user.
        db.execute.assert_not_called()

    def test_skips_when_user_not_found(self):
        svc = _svc()
        settings_obj = MagicMock(
            is_notification_enabled=1, resource_id="u1", mention_enabled=1,
            post_enabled=0, reply_enabled=0, task_enabled=0,
            approval_pending_enabled=0, meeting_enabled=0, blocker_enabled=0,
            app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        db = MagicMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(return_value=_exec_result(scalar_one_or_none=None))
        asyncio.run(svc.send_daily_summary_email(settings_obj, db))
        # Only the user lookup should have executed.
        assert db.execute.await_count == 1

    def test_full_happy_path_sends_and_updates_notify_time(self):
        svc = _svc()
        settings_obj = MagicMock(
            is_notification_enabled=1, resource_id="u1", mention_enabled=1,
            post_enabled=0, reply_enabled=0, task_enabled=0,
            approval_pending_enabled=0, meeting_enabled=0, blocker_enabled=0,
            app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        user = MagicMock(id="u1", email_id="user@example.com", name="Jane")
        db = MagicMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(return_value=_exec_result(scalar_one_or_none=user))
        db.commit = AsyncMock()

        with patch.object(svc, "collect_notification_counts", new=AsyncMock(return_value={"mentions": 3})), \
             patch.object(svc, "generate_enabled_cards", return_value="<td>card</td>"), \
             patch.object(svc, "get_top_channels", new=AsyncMock(return_value=[])), \
             patch.object(svc, "generate_email_content", return_value="<html>body</html>"), \
             patch("app.services.daily_summary_scheduler.sender.email_service") as mock_email_service:
            mock_email_service.from_email = "noreply@example.com"
            mock_email_service._send_email.return_value = True
            asyncio.run(svc.send_daily_summary_email(settings_obj, db))

        db.commit.assert_awaited_once()
        assert settings_obj.last_email_notify_time is not None

    def test_no_cards_and_no_channels_skips_send(self):
        svc = _svc()
        settings_obj = MagicMock(
            is_notification_enabled=1, resource_id="u1", mention_enabled=1,
            post_enabled=0, reply_enabled=0, task_enabled=0,
            approval_pending_enabled=0, meeting_enabled=0, blocker_enabled=0,
            app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        user = MagicMock(id="u1", email_id="user@example.com", name="Jane")
        db = MagicMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(return_value=_exec_result(scalar_one_or_none=user))
        db.commit = AsyncMock()

        with patch.object(svc, "collect_notification_counts", new=AsyncMock(return_value={"mentions": 0})), \
             patch.object(svc, "generate_enabled_cards", return_value=""), \
             patch.object(svc, "get_top_channels", new=AsyncMock(return_value=[])), \
             patch("app.services.daily_summary_scheduler.sender.email_service") as mock_email_service:
            asyncio.run(svc.send_daily_summary_email(settings_obj, db))

        db.commit.assert_not_awaited()
        mock_email_service._send_email.assert_not_called()

    def test_send_failure_does_not_update_notify_time(self):
        svc = _svc()
        settings_obj = MagicMock(
            is_notification_enabled=1, resource_id="u1", mention_enabled=1,
            post_enabled=0, reply_enabled=0, task_enabled=0,
            approval_pending_enabled=0, meeting_enabled=0, blocker_enabled=0,
            app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        user = MagicMock(id="u1", email_id="user@example.com", name="Jane")
        db = MagicMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(return_value=_exec_result(scalar_one_or_none=user))
        db.commit = AsyncMock()

        with patch.object(svc, "collect_notification_counts", new=AsyncMock(return_value={"mentions": 3})), \
             patch.object(svc, "generate_enabled_cards", return_value="<td>card</td>"), \
             patch.object(svc, "get_top_channels", new=AsyncMock(return_value=[])), \
             patch.object(svc, "generate_email_content", return_value="<html>body</html>"), \
             patch("app.services.daily_summary_scheduler.sender.email_service") as mock_email_service:
            mock_email_service.from_email = "noreply@example.com"
            mock_email_service._send_email.return_value = False
            asyncio.run(svc.send_daily_summary_email(settings_obj, db))

        db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# collect_notification_counts (representative subset)
# ---------------------------------------------------------------------------

class TestCollectNotificationCounts:
    def test_no_channels_returns_all_zero_counts(self):
        svc = _svc()
        settings_obj = MagicMock(routine=15)
        db = MagicMock()

        async def fake_execute(stmt):
            # First call: user lookup. Second call: channel memberships (empty).
            if fake_execute.calls == 0:
                fake_execute.calls += 1
                return _exec_result(scalar_one_or_none=MagicMock(name="Jane"))
            return _exec_result(all_rows=[])
        fake_execute.calls = 0
        db.execute = AsyncMock(side_effect=fake_execute)

        result = asyncio.run(svc.collect_notification_counts(uuid.uuid4(), settings_obj, db))
        assert result["mentions"] == 0
        assert result["tasks"] == 0
        assert result["email_conversations"] == 0

    def test_channels_present_hits_message_channel_id_bug(self):
        # Pre-existing bug: the Message model (app/models/message.py) has NO
        # channel_id column (only thread_id) -- the query at
        # `select(Message.channel_id)...` (used to find "email channel IDs")
        # raises AttributeError as soon as user_channel_ids is non-empty.
        # This means collect_notification_counts (and get_top_channels,
        # which has the identical query) can only ever succeed for a user
        # with ZERO channel memberships; for any real user with channels it
        # always raises, which send_daily_summary_email's own try/except
        # then re-raises, and process_daily_summaries's per-user try/except
        # swallows and logs. Characterizing this as current behavior, not
        # fixing the model/query mismatch.
        svc = _svc()
        settings_obj = MagicMock(
            routine=15, mention_enabled=1, post_enabled=0, reply_enabled=0,
            task_enabled=0, approval_pending_enabled=0, blocker_enabled=0,
            meeting_enabled=0, app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        user = MagicMock()
        user.name = "Jane"
        db = MagicMock()
        call_order = []

        async def fake_execute(stmt):
            call_order.append(1)
            if len(call_order) == 1:
                return _exec_result(scalar_one_or_none=user)
            # Second call: channel memberships -> non-empty, so the buggy
            # Message.channel_id query is reached next and raises before
            # db.execute is even called a third time.
            return _exec_result(all_rows=[(uuid.uuid4(),)])
        db.execute = AsyncMock(side_effect=fake_execute)

        with pytest.raises(AttributeError, match="channel_id"):
            asyncio.run(svc.collect_notification_counts(uuid.uuid4(), settings_obj, db))


# ---------------------------------------------------------------------------
# get_top_channels (representative subset)
# ---------------------------------------------------------------------------

class TestGetTopChannels:
    def test_no_channels_returns_empty_list(self):
        svc = _svc()
        settings_obj = MagicMock(routine=15)
        db = MagicMock()

        async def fake_execute(stmt):
            if fake_execute.calls == 0:
                fake_execute.calls += 1
                return _exec_result(scalar_one_or_none=MagicMock())
            return _exec_result(all_rows=[])
        fake_execute.calls = 0
        db.execute = AsyncMock(side_effect=fake_execute)

        result = asyncio.run(svc.get_top_channels(uuid.uuid4(), settings_obj, db))
        assert result == []


# ---------------------------------------------------------------------------
# generate_enabled_cards
# ---------------------------------------------------------------------------

class TestGenerateEnabledCards:
    def test_no_enabled_types_returns_empty_string(self):
        svc = _svc()
        settings_obj = MagicMock(
            mention_enabled=0, post_enabled=0, reply_enabled=0, task_enabled=0,
            approval_pending_enabled=0, meeting_enabled=0, blocker_enabled=0,
            app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        result = svc.generate_enabled_cards(settings_obj, {})
        assert result == ""

    def test_enabled_type_with_zero_count_produces_no_card(self):
        svc = _svc()
        settings_obj = MagicMock(
            mention_enabled=1, post_enabled=0, reply_enabled=0, task_enabled=0,
            approval_pending_enabled=0, meeting_enabled=0, blocker_enabled=0,
            app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        result = svc.generate_enabled_cards(settings_obj, {"mentions": 0})
        assert result == ""

    def test_enabled_type_with_positive_count_produces_card(self):
        svc = _svc()
        settings_obj = MagicMock(
            mention_enabled=1, post_enabled=0, reply_enabled=0, task_enabled=0,
            approval_pending_enabled=0, meeting_enabled=0, blocker_enabled=0,
            app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        result = svc.generate_enabled_cards(settings_obj, {"mentions": 5})
        assert "5" in result
        assert "Mentions" in result

    def test_post_enabled_adds_email_conversations_card_too(self):
        svc = _svc()
        settings_obj = MagicMock(
            mention_enabled=0, post_enabled=1, reply_enabled=0, task_enabled=0,
            approval_pending_enabled=0, meeting_enabled=0, blocker_enabled=0,
            app_enabled=0, chat_enabled=0, friend_enabled=0,
        )
        result = svc.generate_enabled_cards(settings_obj, {"posts": 2, "email_conversations": 4})
        assert "Posts" in result
        assert "Email Conversations" in result


# ---------------------------------------------------------------------------
# generate_channels_rows
# ---------------------------------------------------------------------------

class TestGenerateChannelsRows:
    def test_empty_channels_returns_placeholder_row(self):
        svc = _svc()
        result = svc.generate_channels_rows([])
        assert "No channels with notifications found" in result

    def test_channels_produce_rows(self):
        svc = _svc()
        result = svc.generate_channels_rows([
            {"channel_name": "general", "channel_url": "https://x.test/c1", "notification_count": 3}
        ])
        assert "general" in result
        assert "https://x.test/c1" in result
        assert "3" in result


# ---------------------------------------------------------------------------
# generate_email_content
# ---------------------------------------------------------------------------

class TestGenerateEmailContent:
    def test_generates_content_using_template(self):
        svc = _svc()
        user = MagicMock(name="Jane", email_id="jane@example.com")
        user.name = "Jane"
        settings_obj = MagicMock()

        with patch("app.services.daily_summary_scheduler.content.email_service") as mock_email_service:
            mock_email_service._load_template.return_value = (
                "{platform_name}-{user_name}-{domain_url}-{domain_name}-"
                "{notification_settings_url}-{enabled_cards}-{groups_rows}-"
                "{current_year}-{logo_html}"
            )
            mock_email_service._get_embedded_logo_html.return_value = "<img>"
            result = svc.generate_email_content(user, settings_obj, {}, [], "<td>card</td>")

        assert "Jane" in result
        assert "<td>card</td>" in result

    def test_user_name_precedence_documents_current_behavior(self):
        # user.name truthy -> user.name wins regardless of email_id, due to
        # `user.name or (user.email_id.split('@')[0] if user.email_id else
        # 'User')` operator precedence (or binds looser than the ternary).
        svc = _svc()
        user = MagicMock(email_id="jane.doe@example.com")
        user.name = "Explicit Name"
        settings_obj = MagicMock()
        with patch("app.services.daily_summary_scheduler.content.email_service") as mock_email_service:
            mock_email_service._load_template.return_value = "{user_name}"
            mock_email_service._get_embedded_logo_html.return_value = ""
            result = svc.generate_email_content(user, settings_obj, {}, [], "")
        assert result == "Explicit Name"

    def test_missing_template_raises(self):
        svc = _svc()
        user = MagicMock(email_id="jane@example.com")
        user.name = "Jane"
        settings_obj = MagicMock()
        with patch("app.services.daily_summary_scheduler.content.email_service") as mock_email_service:
            mock_email_service._load_template.side_effect = FileNotFoundError("missing")
            with pytest.raises(FileNotFoundError):
                svc.generate_email_content(user, settings_obj, {}, [], "")
