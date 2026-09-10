import type { ShayWorkspaceMember, ShayWorkspaceMemberList } from "../shay-types";
import { requestJSON, cachedRequestJSON, invalidateShayCache, shayGetCache } from "./http";
import { SHAY_GG_WORKSPACES_BASE } from "./constants";
import { withWorkspaceReference } from "./workspace-reference";

export const workspaceMembersApi = {
  listWorkspaceMembers: (workspaceId: string, token: string) =>
    withWorkspaceReference(workspaceId, token, (reference) => {
      const cacheKey = `workspace-members:${reference.shayWorkspaceId}`;
      const request = cachedRequestJSON<ShayWorkspaceMemberList>(
        cacheKey,
        10_000,
        SHAY_GG_WORKSPACES_BASE,
        `/${reference.shayWorkspaceId}/members`,
        token,
      );
      if (reference.shayWorkspaceId !== workspaceId) {
        shayGetCache.set(`workspace-members:${workspaceId}`, {
          expiresAt: Date.now() + 10_000,
          value: request,
        });
      }
      return request;
    }),

  addWorkspaceMember: (
    workspaceId: string,
    payload: { user_id: string; role: string },
    token: string,
  ) =>
    withWorkspaceReference(workspaceId, token, (reference) =>
      requestJSON<ShayWorkspaceMember>(
        SHAY_GG_WORKSPACES_BASE,
        `/${reference.shayWorkspaceId}/members`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
        token,
      ),
    ).then((result) => {
      invalidateShayCache("workspace:");
      invalidateShayCache(`workspace-members:${workspaceId}`);
      invalidateShayCache(`workspace-members:${result.workspace_id}`);
      return result;
    }),

  updateWorkspaceMember: (
    workspaceId: string,
    userId: string,
    payload: { role?: string; is_active?: boolean },
    token: string,
  ) =>
    withWorkspaceReference(workspaceId, token, (reference) =>
      requestJSON<ShayWorkspaceMember>(
        SHAY_GG_WORKSPACES_BASE,
        `/${reference.shayWorkspaceId}/members/${userId}`,
        {
          method: "PUT",
          body: JSON.stringify(payload),
        },
        token,
      ),
    ).then((result) => {
      invalidateShayCache("workspace:");
      invalidateShayCache(`workspace-members:${workspaceId}`);
      invalidateShayCache(`workspace-members:${result.workspace_id}`);
      return result;
    }),

  removeWorkspaceMember: (workspaceId: string, userId: string, token: string) =>
    withWorkspaceReference(workspaceId, token, (reference) =>
      requestJSON(
        SHAY_GG_WORKSPACES_BASE,
        `/${reference.shayWorkspaceId}/members/${userId}`,
        { method: "DELETE" },
        token,
      ),
    ).then((result) => {
      invalidateShayCache("workspace:");
      invalidateShayCache(`workspace-members:${workspaceId}`);
      return result;
    }),
};
