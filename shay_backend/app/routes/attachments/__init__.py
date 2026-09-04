"""
Attachment routes for file upload and management.

Prefix: /api/v1/attachments

Endpoints
─────────
  POST   /upload                              upload a channel attachment
  GET    /                                     list attachments in a channel
  GET    /{attachment_id}                      get attachment by ID
  GET    /{attachment_id}/download             download attachment file
  DELETE /{attachment_id}                      delete attachment
  GET    /stats/{channel_id}                   attachment statistics for a channel
  POST   /task/{task_id}/upload                upload a task attachment
  GET    /task/{task_id}/attachments           list attachments for a task
  GET    /task/{task_id}/attachments/stats     attachment statistics for a task
  DELETE /task/{task_id}/attachments/{attachment_id}  delete a task attachment
  PUT    /task/{task_id}/attachments/{attachment_id}  update a task attachment
  POST   /task/{task_id}/bulk-upload           bulk-upload attachments to a task

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 1,096-line app/routes/attachments.py. It is now a package of
submodules by resource/sub-area, combined into one `router` below so that
`from .attachments import router as attachments_router` (used by
app/routes/__init__.py) needs zero changes.

Route registration order matches the original file's endpoint declaration
order exactly. No path-collision reordering is required here (unlike
channels/ and gg_datasources/): the channel-scoped routes' single dynamic
segment (GET/DELETE /{attachment_id}) and the task-scoped routes (always
under the literal "/task/..." prefix, 3+ segments) never overlap in path
shape, so registration order between the two groups is not load-bearing —
it is kept identical to the source file purely for readability.
"""

from fastapi import APIRouter

from . import detail
from . import list as list_
from . import stats
from . import task_bulk
from . import task_detail
from . import task_list
from . import task_stats
from . import task_upload
from . import upload

router = APIRouter()
router.include_router(upload.router)
router.include_router(list_.router)
router.include_router(detail.router)
router.include_router(stats.router)
router.include_router(task_upload.router)
router.include_router(task_list.router)
router.include_router(task_stats.router)
router.include_router(task_detail.router)
router.include_router(task_bulk.router)

__all__ = ["router"]
