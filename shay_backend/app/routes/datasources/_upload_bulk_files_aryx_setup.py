"""
Additive Aryx setup for POST /upload/bulk (kind="aryx"), resolved once for
the whole batch. Any failure here becomes a per-file aryx_ingestion.error
in upload_bulk_files.py rather than a hard failure of the upload — which
must still succeed for callers not opting into this feature.

Private module: split out of upload_bulk_files.py (Raven style-compliance,
wave B4) — this per-batch setup step is independent of the per-file upload
loop it feeds.
"""

import uuid
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes.aryx import _resolve_aryx_workspace_id as _resolve_aryx_workspace_id_for_datasources
from app.routes.workspaces import _get_workspace_or_404
from app.utils.permissions import require_active_workspace_role


async def _resolve_aryx_setup_for_bulk_upload(
    db: AsyncSession,
    user,
    kind: Optional[str],
    workspace_id: Optional[str],
) -> Tuple[Optional[int], Optional[str]]:
    """Return (aryx_workspace_id, aryx_setup_error) for this bulk-upload batch."""
    if kind != "aryx":
        return None, None
    if not workspace_id:
        return None, "workspace_id is required when kind='aryx'"
    try:
        target_workspace = await _get_workspace_or_404(db, workspace_id)
        await require_active_workspace_role(db, user.id, uuid.UUID(str(target_workspace.id)))
        aryx_workspace_id = await _resolve_aryx_workspace_id_for_datasources(workspace_id)
        return aryx_workspace_id, None
    except HTTPException as exc:
        return None, str(exc.detail)
