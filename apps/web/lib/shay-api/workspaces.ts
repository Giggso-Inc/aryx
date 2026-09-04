import type { ShayWorkspace } from "../shay-types";
import { requestJSON, cachedRequestJSON, invalidateShayCache, shayGetCache } from "./http";
import { SHAY_WORKSPACES_BASE } from "./constants";
import { listBridgedWorkspaces, withWorkspaceReference } from "./workspace-reference";

export const workspacesApi = {
  listWorkspaces: (token: string) => listBridgedWorkspaces(token),

  getWorkspace: (workspaceId: string, token: string) =>
    withWorkspaceReference(workspaceId, token, async (reference) => {
      if (reference.workspace) {
        shayGetCache.set(`workspace:${workspaceId}`, {
          expiresAt: Date.now() + 10_000,
          value: Promise.resolve(reference.workspace),
        });
        shayGetCache.set(`workspace:${reference.shayWorkspaceId}`, {
          expiresAt: Date.now() + 10_000,
          value: Promise.resolve(reference.workspace),
        });
        return reference.workspace;
      }

      const workspace = await cachedRequestJSON<ShayWorkspace>(
        `workspace:${reference.shayWorkspaceId}`,
        10_000,
        SHAY_WORKSPACES_BASE,
        `/${reference.shayWorkspaceId}`,
        token,
      );
      if (reference.shayWorkspaceId !== workspaceId) {
        shayGetCache.set(`workspace:${workspaceId}`, {
          expiresAt: Date.now() + 10_000,
          value: Promise.resolve(workspace),
        });
      }
      return workspace;
    }),

  getWorkspaceDirect: (workspaceId: string, token: string) =>
    requestJSON<ShayWorkspace>(
      SHAY_WORKSPACES_BASE,
      `/${workspaceId}`,
      undefined,
      token,
    ),

  createWorkspace: (
    payload: { name: string; description?: string; workspace_type?: string },
    token: string,
  ) =>
    requestJSON<ShayWorkspace>(
      SHAY_WORKSPACES_BASE,
      "/",
      {
        method: "POST",
        body: JSON.stringify({
          name: payload.name,
          description: payload.description ?? "",
          workspace_type: payload.workspace_type ?? "aryx",
          is_public: false,
          ai_enabled: true,
          ai_provider: "openai",
          ai_model: "gpt-4",
        }),
      },
      token,
    ).then((result) => {
      invalidateShayCache("workspace:");
      return result;
    }),

  updateWorkspace: (
    workspaceId: string,
    payload: Partial<Pick<ShayWorkspace, "name" | "description" | "is_public" | "ai_enabled" | "ai_provider" | "ai_model" | "is_active">>,
    token: string,
  ) => withWorkspaceReference(workspaceId, token, (reference) =>
    requestJSON<ShayWorkspace>(SHAY_WORKSPACES_BASE, `/${reference.shayWorkspaceId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }, token),
  ).then((result) => {
    invalidateShayCache(`workspace:${workspaceId}`);
    invalidateShayCache(`workspace:${result.id}`);
    return result;
  }),

  deleteWorkspace: (workspaceId: string, token: string) =>
    withWorkspaceReference(workspaceId, token, (reference) =>
      requestJSON<{ success?: boolean; message?: string }>(
        SHAY_WORKSPACES_BASE,
        `/${reference.shayWorkspaceId}`,
        { method: "DELETE" },
        token,
      ),
    ).then((result) => {
      invalidateShayCache(`workspace:${workspaceId}`);
      invalidateShayCache(`workspace-members:${workspaceId}`);
      invalidateShayCache(`datasources:${workspaceId}`);
      return result;
    }),

  purgeWorkspace: (workspaceId: string, token: string) =>
    withWorkspaceReference(workspaceId, token, (reference) =>
      requestJSON<{ status: string }>(
        SHAY_WORKSPACES_BASE,
        `/${reference.shayWorkspaceId}/purge`,
        { method: "POST", body: "{}" },
        token,
      ),
    ),
};
