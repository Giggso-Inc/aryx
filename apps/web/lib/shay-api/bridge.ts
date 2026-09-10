import type { ShayBridgeAskResponse, ShayBridgeChatTurn, ShayBridgeThread, ShayBridgeWorkspaceMap } from "../shay-types";
import { requestJSON, withBearerAuth, query } from "./http";
import { ARYX_BASE } from "./constants";

export const bridgeApi = {
  ensureWorkspaceBridge: (payload: {
    shay_workspace_id: string;
    name: string;
    description?: string;
    company_id?: string;
  }, token?: string) =>
    requestJSON<ShayBridgeWorkspaceMap>(
      ARYX_BASE,
      "/admin/shay/workspaces/ensure",
      withBearerAuth(token, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
      token,
    ),

  getWorkspaceBridge: (shayWorkspaceId: string, token?: string) =>
    requestJSON<ShayBridgeWorkspaceMap>(
      ARYX_BASE,
      `/admin/shay/workspaces/${shayWorkspaceId}/mapping`,
      withBearerAuth(token),
      token,
    ),

  syncDatasourceBridge: (payload: {
    shay_workspace_id: string;
    shay_datasource_id: string;
    name: string;
    kind: string;
    config?: Record<string, unknown>;
    secret?: string;
  }) =>
    requestJSON(
      ARYX_BASE,
      "/admin/shay/datasources/sync",
      {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          config: payload.config ?? {},
          secret: payload.secret ?? "",
        }),
      },
    ),

  askBridge: (payload: {
    shay_workspace_id: string;
    shay_thread_id: string;
    question: string;
  }) =>
    requestJSON<ShayBridgeAskResponse>(
      ARYX_BASE,
      "/admin/shay/chats/ask",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  listBridgeThreads: (shayWorkspaceId: string) =>
    requestJSON<ShayBridgeThread[]>(
      ARYX_BASE,
      `/admin/shay/chats/threads${query({ shay_workspace_id: shayWorkspaceId, limit: 100 })}`,
    ),

  getBridgeHistory: (shayThreadId: string) =>
    requestJSON<ShayBridgeChatTurn[]>(
      ARYX_BASE,
      `/admin/shay/chats/history${query({ shay_thread_id: shayThreadId, limit: 100 })}`,
    ),
};
