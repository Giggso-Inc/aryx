"use client";

import type { ShaySession } from "./shay-types";

export const SHAY_SESSION_STORAGE_KEY = "aryx.shay.session";
export const SHAY_SESSION_EVENT_STORAGE_KEY = "aryx.shay.session.event";

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
const SHAY_REFRESH_LOCK_STORAGE_KEY = "aryx.shay.refresh.lock";
const REFRESH_LOCK_TTL_MS = 15_000;
const REFRESH_WAIT_TIMEOUT_MS = 16_000;
const REFRESH_POLL_INTERVAL_MS = 200;
const listeners = new Set<SessionListener>();
let refreshPromise: Promise<ShaySession | null> | null = null;

interface SessionStorageEventPayload {
  type: "stored" | "cleared";
  reason?: SessionClearReason;
  timestamp: number;
}

interface RefreshLockState {
  owner: string;
  refreshToken: string;
  startedAt: number;
}

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

function parseSessionStorageEvent(raw: string | null): SessionStorageEventPayload | null {
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<SessionStorageEventPayload>;
    if (parsed?.type !== "stored" && parsed?.type !== "cleared") {
      return null;
    }
    if (typeof parsed.timestamp !== "number" || !Number.isFinite(parsed.timestamp)) {
      return null;
    }
    if (parsed.reason && parsed.reason !== "logout" && parsed.reason !== "expired") {
      return null;
    }
    return parsed as SessionStorageEventPayload;
  } catch {
    return null;
  }
}

function readRefreshLockState(): RefreshLockState | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(SHAY_REFRESH_LOCK_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<RefreshLockState>;
    if (
      typeof parsed.owner !== "string"
      || typeof parsed.refreshToken !== "string"
      || typeof parsed.startedAt !== "number"
      || !Number.isFinite(parsed.startedAt)
    ) {
      return null;
    }
    return parsed as RefreshLockState;
  } catch {
    return null;
  }
}

function isRefreshLockActive(lock: RefreshLockState | null, refreshToken?: string | null) {
  if (!lock) {
    return false;
  }
  if (refreshToken && lock.refreshToken !== refreshToken) {
    return false;
  }
  return Date.now() - lock.startedAt < REFRESH_LOCK_TTL_MS;
}

function createRefreshLockOwner() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `refresh-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function tryAcquireRefreshLock(refreshToken: string) {
  if (typeof window === "undefined") {
    return null;
  }
  const activeLock = readRefreshLockState();
  if (isRefreshLockActive(activeLock, refreshToken)) {
    return null;
  }
  const owner = createRefreshLockOwner();
  const nextLock: RefreshLockState = {
    owner,
    refreshToken,
    startedAt: Date.now(),
  };
  window.localStorage.setItem(SHAY_REFRESH_LOCK_STORAGE_KEY, JSON.stringify(nextLock));
  const confirmedLock = readRefreshLockState();
  return confirmedLock?.owner === owner ? owner : null;
}

function releaseRefreshLock(owner: string) {
  if (typeof window === "undefined") {
    return;
  }
  const activeLock = readRefreshLockState();
  if (activeLock?.owner === owner) {
    window.localStorage.removeItem(SHAY_REFRESH_LOCK_STORAGE_KEY);
  }
}

function writeSessionStorageEvent(type: "stored" | "cleared", reason?: SessionClearReason) {
  if (typeof window === "undefined") {
    return;
  }
  const payload: SessionStorageEventPayload = {
    type,
    reason,
    timestamp: Date.now(),
  };
  window.localStorage.setItem(SHAY_SESSION_EVENT_STORAGE_KEY, JSON.stringify(payload));
}

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function didSessionChange(previous: ShaySession, current: ShaySession) {
  return previous.access_token !== current.access_token
    || previous.refresh_token !== current.refresh_token;
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

export function getStoredShaySessionEvent() {
  if (typeof window === "undefined") {
    return null;
  }
  return parseSessionStorageEvent(
    window.localStorage.getItem(SHAY_SESSION_EVENT_STORAGE_KEY),
  );
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
  writeSessionStorageEvent("stored");
  notifyListeners(normalized);
}

export function clearStoredShaySession(reason: SessionClearReason = "logout") {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(SHAY_SESSION_STORAGE_KEY);
  writeSessionStorageEvent("cleared", reason);
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

async function waitForCrossTabRefresh(previousSession: ShaySession) {
  const startedAt = Date.now();
  const initialEventTimestamp = getStoredShaySessionEvent()?.timestamp ?? 0;

  while (Date.now() - startedAt < REFRESH_WAIT_TIMEOUT_MS) {
    const currentSession = getStoredShaySession();
    if (!currentSession) {
      const latestEvent = getStoredShaySessionEvent();
      if (latestEvent?.type === "cleared") {
        return null;
      }
    } else if (didSessionChange(previousSession, currentSession)) {
      return currentSession;
    } else {
      const latestEvent = getStoredShaySessionEvent();
      if (latestEvent?.type === "stored" && latestEvent.timestamp > initialEventTimestamp) {
        return currentSession;
      }
    }

    const lock = readRefreshLockState();
    if (!isRefreshLockActive(lock, previousSession.refresh_token)) {
      return undefined;
    }

    await delay(REFRESH_POLL_INTERVAL_MS);
  }

  return undefined;
}

async function refreshAcrossTabs(): Promise<ShaySession | null> {
  const initialSession = getStoredShaySession();
  if (!initialSession?.refresh_token) {
    if (initialSession?.access_token) {
      clearStoredShaySession("expired");
    }
    return null;
  }

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const session = getStoredShaySession();
    if (!session?.refresh_token) {
      return null;
    }

    const lockOwner = tryAcquireRefreshLock(session.refresh_token);
    if (lockOwner) {
      try {
        return await performRefresh();
      } catch {
        return null;
      } finally {
        releaseRefreshLock(lockOwner);
      }
    }

    const refreshedSession = await waitForCrossTabRefresh(session);
    if (refreshedSession !== undefined) {
      return refreshedSession;
    }
  }

  return null;
}

export async function refreshShayAccessToken() {
  if (!refreshPromise) {
    refreshPromise = refreshAcrossTabs().finally(() => {
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
