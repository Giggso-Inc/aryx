import type {
  ShayAppList,
  ShayBridgeAskResponse,
  ShayBridgeChatTurn,
  ShayBridgeThread,
  ShayBridgeWorkspaceMap,
  ShayCompany,
  ShayDatasource,
  ShayDatasourceList,
  ShayProfile,
  ShaySession,
  ShayUserList,
  ShayWorkspace,
  ShayWorkspaceAppConnection,
  ShayWorkspaceAppConnectionList,
  ShayWorkspaceList,
  ShayWorkspaceMember,
  ShayWorkspaceMemberList,
} from "./shay-types";

const SHAY_BASE = "/shay/api/v1";
const SHAY_PROXY_BASE = "/api/shay";
const ARYX_BASE = "/api";
const SHAY_SESSION_STORAGE_KEY = "aryx.shay.session";

interface StoredShaySession {
  access_token?: string;
  refresh_token?: string;
  token_type?: string;
  expires_in?: number;
  user_id?: string;
  email_id?: string;
  role?: string;
  company_id?: string;
  name?: string | null;
  avatar_url?: string | null;
  company_name?: string | null;
  default_workspace_id?: string | null;
}

function resolvePlatformUrl(): string {
  if (typeof window !== "undefined" && window.location.origin) {
    return window.location.origin;
  }
  return "http://localhost:3000";
}

function detailFromPayload(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return "Request failed";
  const value = payload as Record<string, unknown>;
  if (typeof value.message === "string") return value.message;
  if (typeof value.detail === "string") return value.detail;
  if (value.detail && typeof value.detail === "object") {
    return detailFromPayload(value.detail);
  }
  return JSON.stringify(payload);
}

function getStoredShaySession(): StoredShaySession | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(SHAY_SESSION_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as StoredShaySession;
  } catch {
    return null;
  }
}

export function getShayAccessToken() {
  return getStoredShaySession()?.access_token ?? null;
}

function withBearerAuth(token?: string, init?: RequestInit): RequestInit | undefined {
  if (!token) {
    return init;
  }
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return {
    ...init,
    headers,
  };
}

function storeShaySession(session: StoredShaySession) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(SHAY_SESSION_STORAGE_KEY, JSON.stringify(session));
}

async function refreshShayAccessToken(): Promise<string | null> {
  const session = getStoredShaySession();
  if (!session?.refresh_token) {
    return null;
  }

  const res = await fetch(`${SHAY_BASE}/auth/refresh`, {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ refresh_token: session.refresh_token }),
  });

  if (!res.ok) {
    return null;
  }

  const refreshed = await res.json() as {
    access_token: string;
    refresh_token: string;
    token_type?: string;
    expires_in?: number;
    user_id?: string;
    email?: string;
    role?: string;
    company_id?: string;
  };

  storeShaySession({
    ...session,
    access_token: refreshed.access_token,
    refresh_token: refreshed.refresh_token,
    token_type: refreshed.token_type ?? session.token_type ?? "bearer",
    expires_in: refreshed.expires_in ?? session.expires_in,
    user_id: refreshed.user_id ?? session.user_id,
    email_id: session.email_id ?? refreshed.email,
    role: refreshed.role ?? session.role,
    company_id: refreshed.company_id ?? session.company_id,
  });

  return refreshed.access_token;
}

async function requestJSON<T>(
  base: string,
  path: string,
  init?: RequestInit,
  token?: string,
  didRetry = false,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type") && init?.body) {
    headers.set("Content-Type", "application/json");
  }
  const authToken = token || getStoredShaySession()?.access_token;
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  const res = await fetch(`${base}${path}`, {
    cache: "no-store",
    ...init,
    headers,
  });
  if (!res.ok) {
    if (res.status === 401 && !didRetry) {
      const refreshedToken = await refreshShayAccessToken();
      if (refreshedToken) {
        return requestJSON<T>(base, path, init, refreshedToken, true);
      }
    }
    const text = await res.text().catch(() => "");
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new Error(text || `${res.status} ${res.statusText}`);
    }
    throw new Error(detailFromPayload(parsed));
  }
  return res.json() as Promise<T>;
}

function query(params: Record<string, string | number | boolean | undefined | null>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const serialized = search.toString();
  return serialized ? `?${serialized}` : "";
}

export const shayApi = {
  login: (email_id: string, password: string) =>
    requestJSON<ShaySession>(SHAY_BASE, "/user-auth/login", {
      method: "POST",
      body: JSON.stringify({ email_id, password, encrypted: false }),
    }),

  forgotPassword: (payload: {
    email_id: string;
    base_url: string;
    app_name?: string;
    template_id?: string;
  }) =>
    requestJSON<{ message: string; email_sent: boolean; reset_link?: string | null }>(
      SHAY_BASE,
      "/user-auth/forgot-password",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  resetPassword: (payload: {
    user_id: string;
    email_id: string;
    new_password: string;
    confirm_new_password: string;
    base_url: string;
    encrypted: boolean;
  }) =>
    requestJSON<{ message: string; success: boolean }>(
      SHAY_BASE,
      "/user-auth/reset-password",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  register: (payload: {
    email_id: string;
    password: string;
    name?: string;
    company_id?: string;
    invite_id?: string;
    role?: string;
  }) =>
    requestJSON<ShaySession>(SHAY_BASE, "/user-auth/register", {
      method: "POST",
      body: JSON.stringify({ ...payload, encrypted: false }),
    }),

  autoLogin: (email: string, password: string) =>
    requestJSON<ShaySession>(
      SHAY_BASE,
      `/public/autoLogin?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`,
      {
        method: "POST",
      },
    ),

  verifyEmail: (token: string) =>
    requestJSON<ShaySession>(SHAY_BASE, "/public/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  companySignup: (payload: {
    name: string;
    domain?: string;
    contactEmail: string;
    userName: string;
    industry?: string;
    password: string;
    planId?: string;
  }) =>
    requestJSON<{ success: boolean; message: string }>(
      SHAY_BASE,
      "/public/companies",
      {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          encrypted: false,
          platformName: "Aryx",
          platformUrl: resolvePlatformUrl(),
        }),
      },
    ),

  initiateSso: (provider: string, redirectUri: string, inviteId?: string) =>
    requestJSON<{ authorization_url: string; state: string }>(
      SHAY_BASE,
      `/sso/${provider}/initiate${query({ redirect_uri: redirectUri, invite_id: inviteId })}`,
    ),

  getProfile: (token: string) =>
    requestJSON<ShayProfile>(SHAY_BASE, "/user-auth/profile", undefined, token),

  getMyCompany: (token: string) =>
    requestJSON<ShayCompany>(SHAY_BASE, "/companies/my", undefined, token),

  listCompanyUsers: (companyId: string, token: string) =>
    requestJSON<ShayUserList>(
      SHAY_BASE,
      `/users/company/${companyId}/users`,
      undefined,
      token,
    ),

  updateCompanyUser: (
    companyId: string,
    userId: string,
    payload: { role?: string; is_active?: boolean; name?: string; avatar_url?: string },
    token: string,
  ) =>
    requestJSON(
      SHAY_BASE,
      `/users/company/${companyId}/users/${userId}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
      token,
    ),

  inviteUser: (
    payload: { email: string; company_id: string; role: string; user_id?: string },
    token: string,
  ) =>
    requestJSON(
      SHAY_BASE,
      "/user-auth/invite",
      {
        method: "POST",
        body: JSON.stringify({ ...payload, platform_name: "Aryx" }),
      },
      token,
    ),

  listWorkspaces: (token: string) =>
    requestJSON<ShayWorkspaceList>(SHAY_PROXY_BASE, "/workspaces/", undefined, token),

  getWorkspace: async (workspaceId: string, token: string) => {
    try {
      return await requestJSON<ShayWorkspace>(
        SHAY_PROXY_BASE,
        `/workspaces/${workspaceId}`,
        undefined,
        token,
      );
    } catch (error) {
      if (!(error instanceof Error) || !/not found/i.test(error.message)) {
        throw error;
      }

      const list = await requestJSON<ShayWorkspaceList>(
        SHAY_PROXY_BASE,
        "/workspaces/",
        undefined,
        token,
      );
      const match = list.workspaces.find((workspace) => workspace.id === workspaceId);
      if (match) {
        return match;
      }
      throw error;
    }
  },

  createWorkspace: (
    payload: { name: string; description?: string; workspace_type?: string },
    token: string,
  ) =>
    requestJSON<ShayWorkspace>(
      SHAY_PROXY_BASE,
      "/workspaces/",
      withBearerAuth(token, {
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
      }),
      token,
    ),

  updateWorkspace: (
    workspaceId: string,
    payload: Partial<Pick<ShayWorkspace, "name" | "description" | "is_public" | "ai_enabled" | "ai_provider" | "ai_model" | "is_active">>,
    token: string,
  ) =>
    requestJSON<ShayWorkspace>(
      SHAY_PROXY_BASE,
      `/workspaces/${workspaceId}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
      token,
    ),

  deleteWorkspace: (workspaceId: string, token: string) =>
    requestJSON<{ success?: boolean; message?: string }>(
      SHAY_PROXY_BASE,
      `/workspaces/${workspaceId}`,
      { method: "DELETE" },
      token,
    ),

  listWorkspaceMembers: (workspaceId: string, token: string) =>
    requestJSON<ShayWorkspaceMemberList>(
      SHAY_BASE,
      `/gg-workspaces/${workspaceId}/members`,
      undefined,
      token,
    ),

  addWorkspaceMember: (
    workspaceId: string,
    payload: { user_id: string; role: string },
    token: string,
  ) =>
    requestJSON<ShayWorkspaceMember>(
      SHAY_BASE,
      `/gg-workspaces/${workspaceId}/members`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      token,
    ),

  updateWorkspaceMember: (
    workspaceId: string,
    userId: string,
    payload: { role?: string; is_active?: boolean },
    token: string,
  ) =>
    requestJSON<ShayWorkspaceMember>(
      SHAY_BASE,
      `/gg-workspaces/${workspaceId}/members/${userId}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
      token,
    ),

  removeWorkspaceMember: (workspaceId: string, userId: string, token: string) =>
    requestJSON(
      SHAY_BASE,
      `/gg-workspaces/${workspaceId}/members/${userId}`,
      { method: "DELETE" },
      token,
    ),

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

  listDatasources: (workspaceId: string, token: string) =>
    requestJSON<ShayDatasourceList>(
      SHAY_BASE,
      `/gg-datasources/${query({ level: "workspace", workspace_id: workspaceId, page_size: 100 })}`,
      undefined,
      token,
    ),

  createDatasource: (
    payload: {
      workspace_id: string;
      name: string;
      storage_type: string;
      provider?: string;
      app_type?: string;
      file_url?: string;
      filename?: string;
      config?: Record<string, unknown>;
      datasource_metadata?: Record<string, unknown>;
    },
    token: string,
  ) =>
    requestJSON<ShayDatasource>(
      SHAY_BASE,
      "/gg-datasources/",
      {
        method: "POST",
        body: JSON.stringify({
          level: "workspace",
          workspace_id: payload.workspace_id,
          name: payload.name,
          storage_type: payload.storage_type,
          provider: payload.provider,
          app_type: payload.app_type,
          filename: payload.filename,
          file_url: payload.file_url,
          config: payload.config ?? {},
          datasource_metadata: payload.datasource_metadata ?? {},
          is_embedding_required: false,
        }),
      },
      token,
    ),

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

  getWorkspaceBridge: (shayWorkspaceId: string) =>
    requestJSON<ShayBridgeWorkspaceMap>(
      ARYX_BASE,
      `/admin/shay/workspaces/${shayWorkspaceId}/mapping`,
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
