"use client";

import type { ShaySession } from "./shay-types";
import {
  isRefreshLockActive,
  readRefreshLockState,
  releaseRefreshLock,
  tryAcquireRefreshLock,
} from "./shay-session/refresh-lock";
import {
  clearStoredShaySession,
  didSessionChange,
  getStoredShaySession,
  getStoredShaySessionEvent,
  storeShaySession,
} from "./shay-session/store";

export {
  HttpStatusError,
  createHttpStatusError,
  isHttpStatusError,
  readErrorDetail,
} from "./shay-session/errors";
export {
  SHAY_SESSION_STORAGE_KEY,
  SHAY_SESSION_EVENT_STORAGE_KEY,
  clearStoredShaySession,
  getShayAccessToken,
  getStoredShaySession,
  getStoredShaySessionEvent,
  storeShaySession,
  subscribeToShaySession,
  type SessionClearReason,
  type ShayAuthState,
} from "./shay-session/store";

const SHAY_REFRESH_PATH = "/shay/api/v1/auth/refresh";
const REFRESH_WAIT_TIMEOUT_MS = 16_000;
const REFRESH_POLL_INTERVAL_MS = 200;
let refreshPromise: Promise<ShaySession | null> | null = null;

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
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
