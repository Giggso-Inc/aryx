"""
Integration tests for shay-suite-backend against the Docker test PostgreSQL DB.

Requirements:
  - Docker test DB must be running:
      cd docker/test-db
      docker compose -f docker-compose.test.yml --env-file .env.test up -d
  - TEST_DATABASE_URL env var (defaults to localhost:5433)

Run only these tests:
  pytest tests/test_integration_db.py -m db -v

Run all tests including integration:
  pytest -v
"""

import uuid
import asyncio
import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helper: run an async coroutine in the current event loop
# ---------------------------------------------------------------------------
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. Schema verification — all expected tables must exist
# ---------------------------------------------------------------------------

SUITE_TABLES = [
    "gg_company", "gg_users", "gg_workspace", "gg_channels",
    "gg_threads", "gg_messages", "gg_tasks", "gg_checklists",
    "gg_approvals", "gg_attachments", "gg_ai_responses",
    "gg_app_accounts", "gg_apps", "gg_members", "gg_datasources",
    "gg_vault", "gg_invitations", "gg_realtime_notification",
    "gg_email_notify_settings", "gg_shortened_urls",
    "gg_support_requests", "gg_email_verification_tokens",
    "gg_channel_members", "gg_emails", "gg_email_attachments",
    "subscription_plans", "subscriptions",
]


@pytest.mark.db
class TestSchemaExists:
    @pytest.mark.parametrize("table", SUITE_TABLES)
    def test_table_exists(self, real_db, table):
        async def _check():
            result = await real_db.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name=:t"
                ),
                {"t": table},
            )
            return result.scalar()

        count = _run(_check())
        assert count == 1, f"Table '{table}' not found in test DB"


# ---------------------------------------------------------------------------
# 2. Company CRUD
# ---------------------------------------------------------------------------

@pytest.mark.db
class TestCompanyCRUD:
    def _new_company_id(self):
        return str(uuid.uuid4())

    def test_insert_and_select_company(self, real_db):
        cid = self._new_company_id()

        async def _go():
            await real_db.execute(
                text(
                    "INSERT INTO gg_company (id, name, domain) "
                    "VALUES (:id, :name, :domain)"
                ),
                {"id": cid, "name": "Test Co", "domain": f"{cid[:8]}.test"},
            )
            row = await real_db.execute(
                text("SELECT name FROM gg_company WHERE id=:id"),
                {"id": cid},
            )
            return row.scalar_one_or_none()

        name = _run(_go())
        assert name == "Test Co"

    def test_update_company(self, real_db):
        cid = self._new_company_id()

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_company (id, name) VALUES (:id, :name)"),
                {"id": cid, "name": "Original"},
            )
            await real_db.execute(
                text("UPDATE gg_company SET name=:n WHERE id=:id"),
                {"id": cid, "n": "Updated"},
            )
            row = await real_db.execute(
                text("SELECT name FROM gg_company WHERE id=:id"),
                {"id": cid},
            )
            return row.scalar_one_or_none()

        assert _run(_go()) == "Updated"

    def test_delete_company(self, real_db):
        cid = self._new_company_id()

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_company (id, name) VALUES (:id, 'Delete Me')"),
                {"id": cid},
            )
            await real_db.execute(
                text("DELETE FROM gg_company WHERE id=:id"),
                {"id": cid},
            )
            row = await real_db.execute(
                text("SELECT id FROM gg_company WHERE id=:id"),
                {"id": cid},
            )
            return row.scalar_one_or_none()

        assert _run(_go()) is None

    def test_domain_unique_constraint(self, real_db):
        domain = f"{uuid.uuid4().hex[:8]}.unique-test"

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_company (id, name, domain) VALUES (:id, 'Co1', :d)"),
                {"id": str(uuid.uuid4()), "d": domain},
            )
            try:
                await real_db.execute(
                    text("INSERT INTO gg_company (id, name, domain) VALUES (:id, 'Co2', :d)"),
                    {"id": str(uuid.uuid4()), "d": domain},
                )
                await real_db.flush()
                return False  # Should not reach here
            except Exception:
                return True

        assert _run(_go()) is True


# ---------------------------------------------------------------------------
# 3. User CRUD
# ---------------------------------------------------------------------------

@pytest.mark.db
class TestUserCRUD:
    def _insert_company(self, real_db):
        cid = str(uuid.uuid4())
        _run(real_db.execute(
            text("INSERT INTO gg_company (id, name) VALUES (:id, 'UserTestCo')"),
            {"id": cid},
        ))
        return cid

    def test_insert_and_select_user(self, real_db):
        cid = self._insert_company(real_db)
        uid = str(uuid.uuid4())
        email = f"{uid[:8]}@test.com"

        async def _go():
            await real_db.execute(
                text(
                    "INSERT INTO gg_users (id, name, email_id, company_id) "
                    "VALUES (:id, :name, :email, :cid)"
                ),
                {"id": uid, "name": "Alice", "email": email, "cid": cid},
            )
            row = await real_db.execute(
                text("SELECT name, email_id FROM gg_users WHERE id=:id"),
                {"id": uid},
            )
            return row.fetchone()

        row = _run(_go())
        assert row.name == "Alice"
        assert row.email_id == email

    def test_email_unique_constraint(self, real_db):
        email = f"{uuid.uuid4().hex[:8]}@unique.com"

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_users (id, email_id) VALUES (:id, :e)"),
                {"id": str(uuid.uuid4()), "e": email},
            )
            try:
                await real_db.execute(
                    text("INSERT INTO gg_users (id, email_id) VALUES (:id, :e)"),
                    {"id": str(uuid.uuid4()), "e": email},
                )
                await real_db.flush()
                return False
            except Exception:
                return True

        assert _run(_go()) is True


# ---------------------------------------------------------------------------
# 4. Workspace + Channel + Thread hierarchy
# ---------------------------------------------------------------------------

@pytest.mark.db
class TestHierarchyCRUD:
    def _setup_company_and_user(self, real_db):
        cid = str(uuid.uuid4())
        uid = str(uuid.uuid4())
        _run(real_db.execute(
            text("INSERT INTO gg_company (id, name) VALUES (:id, 'HierCo')"),
            {"id": cid},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_users (id, email_id, company_id) VALUES (:id, :e, :cid)"),
            {"id": uid, "e": f"{uid[:8]}@h.com", "cid": cid},
        ))
        return cid, uid

    def test_workspace_channel_thread_message_chain(self, real_db):
        cid, uid = self._setup_company_and_user(real_db)
        ws_id = str(uuid.uuid4())
        ch_id = str(uuid.uuid4())
        th_id = str(uuid.uuid4())
        msg_id = str(uuid.uuid4())

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_workspace (id, name, company_id, created_at, updated_at) "
                     "VALUES (:id, 'ws', :cid, NOW(), NOW())"),
                {"id": ws_id, "cid": cid},
            )
            await real_db.execute(
                text("INSERT INTO gg_channels (id, name, workspace_id, company_id, created_at, updated_at) "
                     "VALUES (:id, 'general', :wid, :cid, NOW(), NOW())"),
                {"id": ch_id, "wid": ws_id, "cid": cid},
            )
            await real_db.execute(
                text("INSERT INTO gg_threads (id, channel_id, workspace_id) "
                     "VALUES (:id, :cid, :wid)"),
                {"id": th_id, "cid": ch_id, "wid": ws_id},
            )
            await real_db.execute(
                text("INSERT INTO gg_messages (id, content, thread_id, channel_id, workspace_id) "
                     "VALUES (:id, 'Hello', :tid, :chid, :wid)"),
                {"id": msg_id, "tid": th_id, "chid": ch_id, "wid": ws_id},
            )
            row = await real_db.execute(
                text("SELECT content FROM gg_messages WHERE id=:id"),
                {"id": msg_id},
            )
            return row.scalar_one_or_none()

        assert _run(_go()) == "Hello"

    def test_channel_name_unique_within_workspace(self, real_db):
        cid, _ = self._setup_company_and_user(real_db)
        ws_id = str(uuid.uuid4())

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_workspace (id, name, company_id, created_at, updated_at) "
                     "VALUES (:id, 'ws2', :cid, NOW(), NOW())"),
                {"id": ws_id, "cid": cid},
            )
            await real_db.execute(
                text("INSERT INTO gg_channels (id, name, workspace_id, company_id, created_at, updated_at) "
                     "VALUES (:id, 'dup-name', :wid, :cid, NOW(), NOW())"),
                {"id": str(uuid.uuid4()), "wid": ws_id, "cid": cid},
            )
            try:
                await real_db.execute(
                    text("INSERT INTO gg_channels (id, name, workspace_id, company_id, created_at, updated_at) "
                         "VALUES (:id, 'dup-name', :wid, :cid, NOW(), NOW())"),
                    {"id": str(uuid.uuid4()), "wid": ws_id, "cid": cid},
                )
                await real_db.flush()
                return False
            except Exception:
                return True

        assert _run(_go()) is True


# ---------------------------------------------------------------------------
# 5. gg_members exclusive arc constraint
# ---------------------------------------------------------------------------

@pytest.mark.db
class TestGGMembersExclusiveArc:
    def _setup(self, real_db):
        cid = str(uuid.uuid4())
        uid = str(uuid.uuid4())
        ws_id = str(uuid.uuid4())
        ch_id = str(uuid.uuid4())
        th_id = str(uuid.uuid4())

        _run(real_db.execute(
            text("INSERT INTO gg_company (id, name) VALUES (:id, 'MemberCo')"),
            {"id": cid},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_users (id, email_id, company_id) VALUES (:id, :e, :cid)"),
            {"id": uid, "e": f"{uid[:8]}@m.com", "cid": cid},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_workspace (id, name, company_id, created_at, updated_at) "
                 "VALUES (:id, 'ws', :cid, NOW(), NOW())"),
            {"id": ws_id, "cid": cid},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_channels (id, name, workspace_id, company_id, created_at, updated_at) "
                 "VALUES (:id, 'ch', :wid, :cid, NOW(), NOW())"),
            {"id": ch_id, "wid": ws_id, "cid": cid},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_threads (id, channel_id, workspace_id) VALUES (:id, :cid, :wid)"),
            {"id": th_id, "cid": ch_id, "wid": ws_id},
        ))
        return uid, ws_id, ch_id, th_id

    def test_workspace_member_insert(self, real_db):
        uid, ws_id, ch_id, th_id = self._setup(real_db)

        async def _go():
            await real_db.execute(
                text(
                    "INSERT INTO gg_members (id, user_id, workspace_id, level) "
                    "VALUES (:id, :uid, :wid, 'workspace')"
                ),
                {"id": str(uuid.uuid4()), "uid": uid, "wid": ws_id},
            )
            row = await real_db.execute(
                text("SELECT level FROM gg_members WHERE user_id=:uid AND workspace_id=:wid"),
                {"uid": uid, "wid": ws_id},
            )
            return row.scalar_one_or_none()

        assert _run(_go()) == "workspace"

    def test_channel_member_insert(self, real_db):
        uid, ws_id, ch_id, th_id = self._setup(real_db)

        async def _go():
            await real_db.execute(
                text(
                    "INSERT INTO gg_members (id, user_id, channel_id, level) "
                    "VALUES (:id, :uid, :chid, 'channel')"
                ),
                {"id": str(uuid.uuid4()), "uid": uid, "chid": ch_id},
            )
            row = await real_db.execute(
                text("SELECT level FROM gg_members WHERE user_id=:uid AND channel_id=:chid"),
                {"uid": uid, "chid": ch_id},
            )
            return row.scalar_one_or_none()

        assert _run(_go()) == "channel"

    def test_arc_violation_rejects_both_workspace_and_channel(self, real_db):
        uid, ws_id, ch_id, th_id = self._setup(real_db)

        async def _go():
            try:
                await real_db.execute(
                    text(
                        "INSERT INTO gg_members (id, user_id, workspace_id, channel_id, level) "
                        "VALUES (:id, :uid, :wid, :chid, 'workspace')"
                    ),
                    {"id": str(uuid.uuid4()), "uid": uid, "wid": ws_id, "chid": ch_id},
                )
                await real_db.flush()
                return False
            except Exception:
                return True

        assert _run(_go()) is True

    def test_duplicate_workspace_member_rejected(self, real_db):
        uid, ws_id, ch_id, th_id = self._setup(real_db)

        async def _go():
            await real_db.execute(
                text(
                    "INSERT INTO gg_members (id, user_id, workspace_id, level) "
                    "VALUES (:id, :uid, :wid, 'workspace')"
                ),
                {"id": str(uuid.uuid4()), "uid": uid, "wid": ws_id},
            )
            try:
                await real_db.execute(
                    text(
                        "INSERT INTO gg_members (id, user_id, workspace_id, level) "
                        "VALUES (:id, :uid, :wid, 'workspace')"
                    ),
                    {"id": str(uuid.uuid4()), "uid": uid, "wid": ws_id},
                )
                await real_db.flush()
                return False
            except Exception:
                return True

        assert _run(_go()) is True


# ---------------------------------------------------------------------------
# 6. gg_datasources exclusive arc (4 levels)
# ---------------------------------------------------------------------------

@pytest.mark.db
class TestGGDatasourcesExclusiveArc:
    def _setup(self, real_db):
        cid = str(uuid.uuid4())
        uid = str(uuid.uuid4())
        ws_id = str(uuid.uuid4())
        ch_id = str(uuid.uuid4())
        th_id = str(uuid.uuid4())
        msg_id = str(uuid.uuid4())

        _run(real_db.execute(
            text("INSERT INTO gg_company (id, name) VALUES (:id, 'DSCo')"),
            {"id": cid},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_users (id, email_id, company_id) VALUES (:id, :e, :cid)"),
            {"id": uid, "e": f"{uid[:8]}@ds.com", "cid": cid},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_workspace (id, name, company_id, created_at, updated_at) "
                 "VALUES (:id, 'ws', :cid, NOW(), NOW())"),
            {"id": ws_id, "cid": cid},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_channels (id, name, workspace_id, company_id, created_at, updated_at) "
                 "VALUES (:id, 'ch', :wid, :cid, NOW(), NOW())"),
            {"id": ch_id, "wid": ws_id, "cid": cid},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_threads (id, channel_id, workspace_id) VALUES (:id, :cid, :wid)"),
            {"id": th_id, "cid": ch_id, "wid": ws_id},
        ))
        _run(real_db.execute(
            text("INSERT INTO gg_messages (id, content, thread_id, channel_id, workspace_id) "
                 "VALUES (:id, 'msg', :tid, :chid, :wid)"),
            {"id": msg_id, "tid": th_id, "chid": ch_id, "wid": ws_id},
        ))
        return uid, ws_id, ch_id, th_id, msg_id

    def _insert_ds(self, real_db, *, level, workspace_id=None, channel_id=None,
                   thread_id=None, message_id=None, name="ds-test"):
        return _run(real_db.execute(
            text(
                "INSERT INTO gg_datasources "
                "(id, level, workspace_id, channel_id, thread_id, message_id, name, storage_type) "
                "VALUES (:id, :lv, :wid, :chid, :tid, :mid, :nm, 'local')"
            ),
            {
                "id": str(uuid.uuid4()), "lv": level, "nm": name,
                "wid": workspace_id, "chid": channel_id,
                "tid": thread_id, "mid": message_id,
            },
        ))

    def test_workspace_level_insert(self, real_db):
        _, ws_id, ch_id, th_id, msg_id = self._setup(real_db)
        self._insert_ds(real_db, level="workspace", workspace_id=ws_id, name="ws-ds")

        async def _check():
            r = await real_db.execute(
                text("SELECT level FROM gg_datasources WHERE workspace_id=:wid AND name='ws-ds'"),
                {"wid": ws_id},
            )
            return r.scalar_one_or_none()

        assert _run(_check()) == "workspace"

    def test_channel_level_insert(self, real_db):
        _, ws_id, ch_id, th_id, msg_id = self._setup(real_db)
        self._insert_ds(real_db, level="channel", channel_id=ch_id, name="ch-ds")

        async def _check():
            r = await real_db.execute(
                text("SELECT level FROM gg_datasources WHERE channel_id=:chid AND name='ch-ds'"),
                {"chid": ch_id},
            )
            return r.scalar_one_or_none()

        assert _run(_check()) == "channel"

    def test_thread_level_insert(self, real_db):
        _, ws_id, ch_id, th_id, msg_id = self._setup(real_db)
        self._insert_ds(real_db, level="thread", thread_id=th_id, name="th-ds")

        async def _check():
            r = await real_db.execute(
                text("SELECT level FROM gg_datasources WHERE thread_id=:tid AND name='th-ds'"),
                {"tid": th_id},
            )
            return r.scalar_one_or_none()

        assert _run(_check()) == "thread"

    def test_message_level_insert(self, real_db):
        _, ws_id, ch_id, th_id, msg_id = self._setup(real_db)
        self._insert_ds(real_db, level="message", message_id=msg_id, name="msg-ds")

        async def _check():
            r = await real_db.execute(
                text("SELECT level FROM gg_datasources WHERE message_id=:mid AND name='msg-ds'"),
                {"mid": msg_id},
            )
            return r.scalar_one_or_none()

        assert _run(_check()) == "message"

    def test_arc_violation_two_fks_rejected(self, real_db):
        _, ws_id, ch_id, th_id, msg_id = self._setup(real_db)

        async def _go():
            try:
                await real_db.execute(
                    text(
                        "INSERT INTO gg_datasources "
                        "(id, level, workspace_id, channel_id, name, storage_type) "
                        "VALUES (:id, 'workspace', :wid, :chid, 'bad-ds', 'local')"
                    ),
                    {"id": str(uuid.uuid4()), "wid": ws_id, "chid": ch_id},
                )
                await real_db.flush()
                return False
            except Exception:
                return True

        assert _run(_go()) is True

    def test_duplicate_name_in_same_scope_rejected(self, real_db):
        _, ws_id, ch_id, th_id, msg_id = self._setup(real_db)
        self._insert_ds(real_db, level="workspace", workspace_id=ws_id, name="dup-ds")

        async def _go():
            try:
                self._insert_ds(real_db, level="workspace", workspace_id=ws_id, name="dup-ds")
                await real_db.flush()
                return False
            except Exception:
                return True

        assert _run(_go()) is True

    def test_same_name_allowed_in_different_scopes(self, real_db):
        _, ws_id, ch_id, th_id, msg_id = self._setup(real_db)
        # Same name 'cross-ds' at workspace and channel level — both must succeed
        self._insert_ds(real_db, level="workspace", workspace_id=ws_id, name="cross-ds")
        self._insert_ds(real_db, level="channel", channel_id=ch_id, name="cross-ds")

        async def _count():
            r = await real_db.execute(
                text("SELECT COUNT(*) FROM gg_datasources WHERE name='cross-ds'"),
            )
            return r.scalar()

        assert _run(_count()) == 2


# ---------------------------------------------------------------------------
# 7. Tasks + Checklists
# ---------------------------------------------------------------------------

@pytest.mark.db
class TestTasksAndChecklists:
    def test_task_with_checklists(self, real_db):
        task_id = str(uuid.uuid4())

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_tasks (id, title) VALUES (:id, 'My Task')"),
                {"id": task_id},
            )
            for i in range(3):
                await real_db.execute(
                    text(
                        "INSERT INTO gg_checklists (id, task_id, text, order_index) "
                        "VALUES (:id, :tid, :txt, :oi)"
                    ),
                    {"id": str(uuid.uuid4()), "tid": task_id, "txt": f"Step {i+1}", "oi": i},
                )
            row = await real_db.execute(
                text("SELECT COUNT(*) FROM gg_checklists WHERE task_id=:tid"),
                {"tid": task_id},
            )
            return row.scalar()

        assert _run(_go()) == 3

    def test_checklist_cascade_delete_with_task(self, real_db):
        task_id = str(uuid.uuid4())

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_tasks (id, title) VALUES (:id, 'Del Task')"),
                {"id": task_id},
            )
            await real_db.execute(
                text("INSERT INTO gg_checklists (id, task_id, text, order_index) "
                     "VALUES (:id, :tid, 'item', 0)"),
                {"id": str(uuid.uuid4()), "tid": task_id},
            )
            await real_db.execute(
                text("DELETE FROM gg_tasks WHERE id=:id"), {"id": task_id}
            )
            row = await real_db.execute(
                text("SELECT COUNT(*) FROM gg_checklists WHERE task_id=:tid"),
                {"tid": task_id},
            )
            return row.scalar()

        assert _run(_go()) == 0


# ---------------------------------------------------------------------------
# 8. Subscription plans + subscriptions
# ---------------------------------------------------------------------------

@pytest.mark.db
class TestSubscriptions:
    def test_subscription_plan_and_subscription(self, real_db):
        plan_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        sub_id = str(uuid.uuid4())

        async def _go():
            await real_db.execute(
                text(
                    "INSERT INTO subscription_plans (id, name, plan_code, monthly_price) "
                    "VALUES (:id, 'Pro', :code, 49.00)"
                ),
                {"id": plan_id, "code": f"pro-{plan_id[:8]}"},
            )
            await real_db.execute(
                text("INSERT INTO gg_company (id, name) VALUES (:id, 'SubCo')"),
                {"id": cid},
            )
            await real_db.execute(
                text(
                    "INSERT INTO subscriptions "
                    "(id, company_id, plan_id, amount, billing_cycle, current_period_start, current_period_end) "
                    "VALUES (:id, :cid, :pid, 49.00, 'monthly', NOW(), NOW() + INTERVAL '30 days')"
                ),
                {"id": sub_id, "cid": cid, "pid": plan_id},
            )
            row = await real_db.execute(
                text("SELECT status FROM subscriptions WHERE id=:id"), {"id": sub_id}
            )
            return row.scalar_one_or_none()

        assert _run(_go()) == "active"


# ---------------------------------------------------------------------------
# 9. Shortened URLs
# ---------------------------------------------------------------------------

@pytest.mark.db
class TestShortenedUrls:
    def test_insert_and_lookup_short_link(self, real_db):
        code = uuid.uuid4().hex[:7]

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_shortened_urls (short_link, original_url) VALUES (:c, :u)"),
                {"c": code, "u": "https://example.com/very/long/path"},
            )
            row = await real_db.execute(
                text("SELECT original_url FROM gg_shortened_urls WHERE short_link=:c"),
                {"c": code},
            )
            return row.scalar_one_or_none()

        assert _run(_go()) == "https://example.com/very/long/path"

    def test_short_link_primary_key_unique(self, real_db):
        code = uuid.uuid4().hex[:7]

        async def _go():
            await real_db.execute(
                text("INSERT INTO gg_shortened_urls (short_link, original_url) VALUES (:c, :u)"),
                {"c": code, "u": "https://a.com"},
            )
            try:
                await real_db.execute(
                    text("INSERT INTO gg_shortened_urls (short_link, original_url) VALUES (:c, :u)"),
                    {"c": code, "u": "https://b.com"},
                )
                await real_db.flush()
                return False
            except Exception:
                return True

        assert _run(_go()) is True
