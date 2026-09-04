"""
Golden-master / characterization tests for app/routes/checklists (package).

Written retroactively after a prior split attempt was interrupted mid-way
(missing two endpoints, no tests) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md
Phase 5a item 2. Covers all 8 endpoints of the original 530-line
app/routes/checklists.py, verified against the recovered original source
before being run against the completed split package.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.checklists import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/checklists")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _mock_task(task_id="task-1", workspace_id="ws-1"):
    task = MagicMock()
    task.id = task_id
    task.workspace_id = workspace_id
    return task


def _mock_workspace(company_id="company-001"):
    ws = MagicMock()
    ws.company_id = company_id
    return ws


def _mock_checklist(checklist_id="check-1", task_id="task-1", is_completed=False):
    c = MagicMock()
    c.id = checklist_id
    c.task_id = task_id
    c.text = "Do the thing"
    c.order_index = 0
    c.checklist_metadata = None
    c.is_completed = is_completed
    c.completed_at = None
    c.completed_by = None
    c.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c.mark_completed = MagicMock()
    c.mark_incomplete = MagicMock()
    return c


def _scalar_one_or_none_seq(*values):
    """db.execute(...).scalar_one_or_none() returning consecutive values across calls."""
    results = []
    for v in values:
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=v)
        results.append(r)
    return AsyncMock(side_effect=results)


@pytest.mark.unit
def test_create_task_checklists_happy_path(admin_user):
    mock_db = AsyncMock()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    # execute() sequence: task lookup, workspace lookup, max_order lookup, then the
    # final get_task_checklists call re-does task+workspace lookup, then the ordered select.
    max_order_result = MagicMock()
    max_order_result.scalar = MagicMock(return_value=-1)
    checklists_result = MagicMock()
    checklists_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    call_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
        max_order_result,
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
        checklists_result,
    ]
    mock_db.execute = AsyncMock(side_effect=call_results)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    with patch("app.routes.checklists.task_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/checklists/task/task-1/checklists",
            json={"checklists": [{"text": "Item 1", "order_index": 0, "checklist_metadata": None}]},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0  # ordered-select mock returns empty list, matching current behavior


@pytest.mark.unit
def test_create_task_checklists_order_index_none_is_422(admin_user):
    """Current behavior: ChecklistBase.order_index is a required field (Field(..., ge=0)),
    not Optional, despite the handler's own dead "auto-assign if None" branch — Pydantic
    rejects a null order_index with 422 before the handler code ever runs."""
    mock_db = AsyncMock()
    with patch("app.routes.checklists.task_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/checklists/task/task-1/checklists",
            json={"checklists": [{"text": "Item 1", "order_index": None}]},
        )
    assert resp.status_code == 422


@pytest.mark.unit
def test_create_task_checklists_404_when_task_missing(admin_user):
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    with patch("app.routes.checklists.task_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/checklists/task/missing/checklists",
            json={"checklists": [{"text": "x", "order_index": 0}]},
        )
    assert resp.status_code == 404


@pytest.mark.unit
def test_get_task_checklists_happy_path(admin_user):
    mock_db = AsyncMock()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    checklist = _mock_checklist()
    checklists_result = MagicMock()
    checklists_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[checklist])))
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
        checklists_result,
    ])
    with patch("app.routes.checklists.task_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/checklists/task/task-1/checklists")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["completed_count"] == 0
    assert body["incomplete_count"] == 1


@pytest.mark.unit
def test_get_task_checklists_403_cross_company(admin_user):
    mock_db = AsyncMock()
    task = _mock_task()
    ws = _mock_workspace(company_id="some-other-company")
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
    ])
    with patch("app.routes.checklists.task_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/checklists/task/task-1/checklists")
    assert resp.status_code == 403


@pytest.mark.unit
def test_add_single_checklist_happy_path(admin_user):
    mock_db = AsyncMock()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    max_order_result = MagicMock()
    max_order_result.scalar = MagicMock(return_value=2)
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
        max_order_result,
    ])
    mock_db.commit = AsyncMock()

    def _apply_db_defaults(obj):
        # mock_db.commit() is a no-op AsyncMock — it never flushes, so this simulates the
        # SQLAlchemy Column(default=...) values a real commit/refresh would populate.
        obj.is_completed = False
        obj.completed_at = None
        obj.completed_by = None
        obj.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        obj.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    mock_db.refresh = AsyncMock(side_effect=_apply_db_defaults)
    mock_db.add = MagicMock()
    with patch("app.routes.checklists.task_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/checklists/task/task-1/checklists/add",
            json={"text": "Solo item", "order_index": 0},
        )
    assert resp.status_code == 200


@pytest.mark.unit
def test_get_checklist_happy_path(admin_user):
    mock_db = AsyncMock()
    checklist = _mock_checklist()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=checklist)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
    ])
    with patch("app.routes.checklists.item_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/checklists/checklist/check-1")
    assert resp.status_code == 200


@pytest.mark.unit
def test_get_checklist_404(admin_user):
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    with patch("app.routes.checklists.item_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/checklists/checklist/missing")
    assert resp.status_code == 404


@pytest.mark.unit
def test_update_checklist_happy_path(admin_user):
    mock_db = AsyncMock()
    checklist = _mock_checklist()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=checklist)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
    ])
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    with patch("app.routes.checklists.item_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.put("/api/v1/checklists/checklist/check-1", json={"text": "Updated text"})
    assert resp.status_code == 200


@pytest.mark.unit
def test_delete_checklist_happy_path(admin_user):
    mock_db = AsyncMock()
    checklist = _mock_checklist()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=checklist)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
    ])
    mock_db.delete = AsyncMock()
    mock_db.commit = AsyncMock()
    with patch("app.routes.checklists.item_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.delete("/api/v1/checklists/checklist/check-1")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Checklist deleted successfully"}


@pytest.mark.unit
def test_toggle_checklist_completion_happy_path(admin_user):
    mock_db = AsyncMock()
    checklist = _mock_checklist()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=checklist)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
    ])
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    with patch("app.routes.checklists.item_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/checklists/checklist/check-1/complete",
            json={"is_completed": True, "comments": "done"},
        )
    assert resp.status_code == 200
    checklist.mark_completed.assert_called_once()


@pytest.mark.unit
def test_reorder_checklists_happy_path(admin_user):
    mock_db = AsyncMock()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    checklist = _mock_checklist()
    checklists_result = MagicMock()
    checklists_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=checklist)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
        checklists_result,
    ])
    mock_db.commit = AsyncMock()
    # reorder_checklists calls get_task_checklists (defined in task_ops) at the end of its
    # own body, which independently calls get_current_user_required again — both call sites
    # resolve to different modules' bound names and must both be patched.
    with patch("app.routes.checklists.task_meta.get_current_user_required", new=AsyncMock(return_value=admin_user)), \
         patch("app.routes.checklists.task_ops.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/checklists/task/task-1/checklists/reorder",
            json={"checklist_orders": [{"checklist_id": "check-1", "new_order": 5}]},
        )
    assert resp.status_code == 200
    assert checklist.order_index == 5


@pytest.mark.unit
def test_reorder_checklists_404_when_task_missing(admin_user):
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    with patch("app.routes.checklists.task_meta.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/checklists/task/missing/checklists/reorder",
            json={"checklist_orders": [{"checklist_id": "x", "new_order": 1}]},
        )
    assert resp.status_code == 404


@pytest.mark.unit
def test_get_checklist_stats_happy_path(admin_user):
    mock_db = AsyncMock()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    total_result = MagicMock(scalar=MagicMock(return_value=4))
    completed_result = MagicMock(scalar=MagicMock(return_value=1))
    last_completed_result = MagicMock(scalar=MagicMock(return_value=None))
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
        total_result,
        completed_result,
        last_completed_result,
    ])
    with patch("app.routes.checklists.task_meta.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/checklists/task/task-1/checklists/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_items"] == 4
    assert body["completed_items"] == 1
    assert body["incomplete_items"] == 3
    assert body["completion_percentage"] == 25.0


@pytest.mark.unit
def test_get_checklist_stats_zero_items_no_division_error(admin_user):
    mock_db = AsyncMock()
    task = _mock_task()
    ws = _mock_workspace(company_id=admin_user.company_id)
    total_result = MagicMock(scalar=MagicMock(return_value=0))
    completed_result = MagicMock(scalar=MagicMock(return_value=0))
    last_completed_result = MagicMock(scalar=MagicMock(return_value=None))
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=task)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=ws)),
        total_result,
        completed_result,
        last_completed_result,
    ])
    with patch("app.routes.checklists.task_meta.get_current_user_required", new=AsyncMock(return_value=admin_user)):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/checklists/task/task-1/checklists/stats")
    assert resp.status_code == 200
    assert resp.json()["completion_percentage"] == 0.0
