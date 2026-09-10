import type { ShayAppList, ShayWorkspaceAppConnection, ShayWorkspaceAppConnectionList } from "../shay-types";
import { requestJSON } from "./http";
import { SHAY_BASE } from "./constants";

export const workspaceAppsApi = {
  listApps: (token: string) =>
    requestJSON<ShayAppList>(SHAY_BASE, "/apps/?size=100", undefined, token),

  listWorkspaceAppConnections: (workspaceId: string, token: string) =>
    requestJSON<ShayWorkspaceAppConnectionList>(
      SHAY_BASE,
      `/gg-workspaces/${workspaceId}/app-connections?size=100`,
      undefined,
      token,
    ),

  createWorkspaceAppConnection: (
    workspaceId: string,
    payload: {
      app_id: string;
      connection_name?: string;
      provider?: string;
      auth_type?: string;
      connection_settings?: Record<string, unknown>;
    },
    token: string,
  ) =>
    requestJSON<ShayWorkspaceAppConnection>(
      SHAY_BASE,
      `/gg-workspaces/${workspaceId}/app-connections`,
      {
        method: "POST",
        body: JSON.stringify({
          app_id: payload.app_id,
          connection_name: payload.connection_name,
          provider: payload.provider,
          auth_type: payload.auth_type ?? "oauth2",
          connection_status: "active",
          connection_settings: payload.connection_settings ?? {},
          auto_sync: false,
          sync_interval: 3600,
        }),
      },
      token,
    ),

  updateWorkspaceAppConnection: (
    workspaceId: string,
    connectionId: string,
    payload: {
      connection_name?: string;
      connection_status?: string;
      is_active?: boolean;
      provider?: string;
      auth_type?: string;
    },
    token: string,
  ) =>
    requestJSON<ShayWorkspaceAppConnection>(
      SHAY_BASE,
      `/gg-workspaces/${workspaceId}/app-connections/${connectionId}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
      token,
    ),

  deleteWorkspaceAppConnection: (workspaceId: string, connectionId: string, token: string) =>
    requestJSON(
      SHAY_BASE,
      `/gg-workspaces/${workspaceId}/app-connections/${connectionId}`,
      { method: "DELETE" },
      token,
    ),
};
