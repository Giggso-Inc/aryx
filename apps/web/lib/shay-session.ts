"use client";

import type { ShaySession } from "./shay-types";

export const SHAY_SESSION_STORAGE_KEY = "aryx.shay.session";

export type SessionClearReason = "logout" | "expired";
export type ShayAuthState = "authenticated" | "signed_out" | "expired";

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

type SessionListener = (
  session: ShaySession | null,
  reason?: SessionClearReason,
) => void;

const SHAY_REFRESH_PATH = "/shay/api/v1/auth/refresh";
const listeners = new Set<SessionListener>();
let refreshPromise: Promise<ShaySession | null> | null = null;

export class HttpStatusError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "HttpStatusError";
    this.status = status;
  }
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

function normalizeStoredSession(raw: unknown): ShaySession | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const parsed = raw as Record<string, unknown>;
  const candidate = parsed?.data && typeof parsed.data === "object"
    ? parsed.data as Record<string, unknown>
    : parsed;
  if (typeof candidate.access_token !== "string" || !candidate.access_token) {
    return null;
  }
  return candidate as unknown as ShaySession;
}

function notifyListeners(session: ShaySession | null, reason?: SessionClearReason) {
  listeners.forEach((listener) => listener(session, reason));
}

export function createHttpStatusError(
  status: number,
  statusText: string,
  detail = "",
) {
  return new HttpStatusError(
    status,
    detail ? `${status} ${statusText}: ${detail}` : `${status} ${statusText}`,
  );
}

export function isHttpStatusError(error: unknown, status?: number) {
  return error instanceof HttpStatusError
    && (status === undefined || error.status === status);
}

export async function readErrorDetail(response: Response) {
  const text = await response.text().catch(() => "");
  if (!text) {
    return "";
  }
  try {
    return detailFromPayload(JSON.parse(text));
  } catch {
    return text;
  }
}

export function getStoredShaySession(): ShaySession | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(SHAY_SESSION_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return normalizeStoredSession(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function getShayAccessToken() {
  return getStoredShaySession()?.access_token ?? null;
}

export function storeShaySession(session: StoredShaySession | ShaySession) {
  if (typeof window === "undefined") {
    return;
  }
  const normalized = normalizeStoredSession(session);
  if (!normalized) {
    return;
  }
  window.localStorage.setItem(SHAY_SESSION_STORAGE_KEY, JSON.stringify(normalized));
  notifyListeners(normalized);
}

export function clearStoredShaySession(reason: SessionClearReason = "logout") {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(SHAY_SESSION_STORAGE_KEY);
  notifyListeners(null, reason);
}

export function subscribeToShaySession(listener: SessionListener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

async function performRefresh(): Promise<ShaySession | null> {
  const session = getStoredShaySession();
  if (!session?.refresh_token) {
    if (session?.access_token) {
      clearStoredShaySession("expired");
    }
    return null;
  }

  const res = await fetch(SHAY_REFRESH_PATH, {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ refresh_token: session.refresh_token }),
  });

  if (!res.ok) {
    clearStoredShaySession("expired");
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

  const nextSession: ShaySession = {
    ...session,
    access_token: refreshed.access_token,
    refresh_token: refreshed.refresh_token,
    token_type: refreshed.token_type ?? session.token_type ?? "bearer",
    expires_in: refreshed.expires_in ?? session.expires_in,
    user_id: refreshed.user_id ?? session.user_id,
    email_id: session.email_id ?? refreshed.email ?? "",
    role: refreshed.role ?? session.role,
    company_id: refreshed.company_id ?? session.company_id,
    name: session.name ?? null,
    avatar_url: session.avatar_url ?? null,
    company_name: session.company_name ?? null,
    default_workspace_id: session.default_workspace_id ?? null,
  };

  storeShaySession(nextSession);
  return nextSession;
}

export async function refreshShayAccessToken() {
  if (!refreshPromise) {
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  const session = await refreshPromise;
  return session?.access_token ?? null;
}

export async function fetchWithShayAuth(
  input: RequestInfo | URL,
  init?: RequestInit,
  options?: { token?: string | null },
): Promise<Response> {
  const run = async (token?: string | null) => {
    const headers = new Headers(init?.headers);
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return fetch(input, {
      cache: "no-store",
      ...init,
      headers,
    });
  };

  const session = getStoredShaySession();
  const initialToken = options?.token ?? session?.access_token ?? null;
  const response = await run(initialToken);
  if (response.status !== 401) {
    return response;
  }

  const refreshedToken = await refreshShayAccessToken();
  if (!refreshedToken) {
    return response;
  }

  return run(refreshedToken);
}
