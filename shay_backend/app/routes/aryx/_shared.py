"""Aryx bridge: shared timeouts, error mapping, and workspace-access helpers.

Split out of the original app/routes/aryx.py so each endpoint module can stay
under the 150-line style limit. See app/routes/aryx/__init__.py for the full
module-level docstring describing the bridge architecture.
"""

from uuid import UUID

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.routes.workspaces import _aryx_headers, _get_workspace_or_404
from app.utils.permissions import require_active_workspace_role

_TIMEOUT_ASK = httpx.Timeout(60.0)      # LLM-backed; slower than a plain CRUD call
_TIMEOUT_BRIDGE = httpx.Timeout(30.0)   # matches workspaces.py's bridge calls
_TIMEOUT_UPLOAD = httpx.Timeout(120.0)  # file upload can be larger; read itself is async server-side


def _raise_for_bridge_error(exc: Exception, action: str) -> None:
    """Map an httpx/bridge failure to the same HTTPException shape workspaces.py uses."""
    if isinstance(exc, httpx.HTTPStatusError):
        detail = exc.response.text or str(exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Aryx {action} failed: {detail}") from exc
    if isinstance(exc, httpx.RequestError):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Aryx service unavailable: {exc}") from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    raise exc


async def _resolve_aryx_workspace_id(shay_workspace_id: str) -> int:
    """Look up the Aryx workspace bridged to this Shay workspace.

    Reuses the same GET /admin/shay/workspaces/{id}/mapping lookup already
    used by workspaces.py's delete/purge routes — it does not create a
    mapping, so the workspace must already have gone through
    POST /admin/shay/workspaces/ensure (i.e. it was created via Shay's
    normal workspace-create flow).
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_BRIDGE) as client:
        try:
            resp = await client.get(
                f"{settings.ARYX_API_URL_INTERNAL}/admin/shay/workspaces/{shay_workspace_id}/mapping",
                headers=_aryx_headers(),
            )
            if resp.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    f"no Aryx mapping for Shay workspace {shay_workspace_id} — "
                    "create it via the workspace-create flow first",
                )
            resp.raise_for_status()
        except HTTPException:
            raise
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as exc:
            _raise_for_bridge_error(exc, "workspace lookup")
    mapping = resp.json()
    return int(mapping["aryx_workspace_id"])


async def _require_workspace_access(
    request: Request, db: AsyncSession, workspace_id: str,
) -> None:
    """Same auth gate as the existing workspace routes: authenticated user,
    active membership in this specific Shay workspace."""
    user = await get_current_user_required(request)
    workspace = await _get_workspace_or_404(db, workspace_id)
    await require_active_workspace_role(db, user.id, UUID(str(workspace.id)))
