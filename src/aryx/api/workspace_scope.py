"""Warn-mode `workspace_id` resolution for destructive endpoints.

CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T9/T11: `workspace_id: int = 1`
is a dangerous default on delete/mutation endpoints -- a caller that omits
it silently acts on workspace 1's data. The original audit's own
recommendation is a warn-mode first release (log every site that would
have defaulted, before making the parameter required), since flipping
straight to required could break a real caller nobody has audited yet.

This is that warn-mode step, applied to the handful of directly-
destructive endpoints named in the audit's T11 finding (deletes and the
workspace-wipe endpoint) -- not all ~95 `workspace_id: int = 1` sites
repo-wide, which is separate, larger follow-up work.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DEFAULT_WORKSPACE_ID = 1


def resolve_workspace_id_warn(workspace_id: int | None, endpoint: str) -> int:
    """Return `workspace_id`, defaulting to 1 and logging a warning when
    the caller omitted it entirely -- so a real audit of "who's actually
    relying on the default" is possible before a later change makes the
    parameter required outright. Never blocks the request; this is
    observation, not enforcement.
    """
    if workspace_id is None:
        logger.warning(
            "workspace_id omitted on %s -- defaulting to %d (T9/T11 warn-mode; "
            "this call site may need to become workspace_id-required)",
            endpoint, _DEFAULT_WORKSPACE_ID,
        )
        return _DEFAULT_WORKSPACE_ID
    return workspace_id
