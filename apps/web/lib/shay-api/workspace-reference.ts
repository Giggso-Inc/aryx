import type { ShayWorkspace, ShayWorkspaceList } from "../shay-types";
import { requestJSON } from "./http";
import { SHAY_WORKSPACES_BASE } from "./constants";

export type WorkspaceReference = {
  requestedId: string;
  shayWorkspaceId: string;
  workspace?: ShayWorkspace;
};

export async function listBridgedWorkspaces(token: string): Promise<ShayWorkspaceList> {
  return requestJSON<ShayWorkspaceList>(
    SHAY_WORKSPACES_BASE,
    "/",
    undefined,
    token,
  );
}

function matchesWorkspaceReference(workspace: ShayWorkspace, workspaceId: string) {
  if (workspace.id === workspaceId) {
    return true;
  }
  return String(workspace.bridge?.aryx_workspace_id ?? "") === workspaceId;
}

function isLegacyAryxWorkspaceId(workspaceId: string) {
  return /^\d+$/.test(workspaceId);
}

function isWorkspaceLookupError(error: unknown) {
  return error instanceof Error
    && /not found|invalid workspace_id format|invalid workspace id format/i.test(error.message);
}

async function findWorkspaceReference(
  workspaceId: string,
  token: string,
): Promise<WorkspaceReference | null> {
  const list = await listBridgedWorkspaces(token);
  const match = list.workspaces.find((workspace) => matchesWorkspaceReference(workspace, workspaceId));
  if (!match) {
    return null;
  }
  return {
    requestedId: workspaceId,
    shayWorkspaceId: match.id,
    workspace: match,
  };
}

export async function withWorkspaceReference<T>(
  workspaceId: string,
  token: string,
  execute: (reference: WorkspaceReference) => Promise<T>,
): Promise<T> {
  if (isLegacyAryxWorkspaceId(workspaceId)) {
    const resolved = await findWorkspaceReference(workspaceId, token);
    if (resolved) {
      return execute(resolved);
    }
  }

  const directReference: WorkspaceReference = {
    requestedId: workspaceId,
    shayWorkspaceId: workspaceId,
  };

  try {
    return await execute(directReference);
  } catch (error) {
    if (!isWorkspaceLookupError(error)) {
      throw error;
    }

    const resolved = await findWorkspaceReference(workspaceId, token);
    if (!resolved || resolved.shayWorkspaceId === workspaceId) {
      throw error;
    }
    return execute(resolved);
  }
}
