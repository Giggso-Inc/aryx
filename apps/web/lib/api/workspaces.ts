import type { SurvivorshipPolicy, Workspace } from "../types";
import { fetchJSON } from "./core";

export const workspacesApi = {
  listWorkspaces: () =>
    fetchJSON<Workspace[]>("/admin/workspaces"),

  createWorkspace: (name: string, description = "", context = "") =>
    fetchJSON<Workspace>("/admin/workspaces", {
      method: "POST",
      body: JSON.stringify({ name, description, context }),
    }),

  updateWorkspaceContext: (workspaceId: number, context: string) =>
    fetchJSON<Workspace>(`/admin/workspaces/${workspaceId}/context`, {
      method: "PATCH",
      body: JSON.stringify({ context }),
    }),

  purgeWorkspace: (workspaceId: number) =>
    fetchJSON<{ status: string }>(`/admin/workspaces/${workspaceId}/purge`, {
      method: "POST", body: "{}",
    }),

  deleteWorkspace: (workspaceId: number) =>
    fetchJSON<{ status: string }>(`/admin/workspaces/${workspaceId}`, {
      method: "DELETE",
    }),

  nukeAllWorkspaces: () =>
    fetchJSON<{ status: string }>("/admin/workspaces/nuke", {
      method: "POST", body: "{}",
    }),

  autoLinkWorkspace: (workspaceId: number) =>
    fetchJSON<{ links_created: number; specs: Array<Record<string, unknown>> }>(
      `/admin/workspaces/${workspaceId}/auto-link`,
      { method: "POST", body: "{}" },
    ),

  getSurvivorship: (workspaceId: number) =>
    fetchJSON<{ workspace_id: number; survivorship: SurvivorshipPolicy }>(
      `/admin/workspaces/${workspaceId}/survivorship`,
    ).then((d) => d.survivorship || {}),

  setSurvivorship: (workspaceId: number, policy: SurvivorshipPolicy) =>
    fetchJSON<{ id: number; survivorship: SurvivorshipPolicy }>(
      `/admin/workspaces/${workspaceId}/survivorship`,
      { method: "PUT", body: JSON.stringify(policy) },
    ),
};
