import type { ShaySession } from "../shay-types";

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

export type SessionListener = (
  session: ShaySession | null,
  reason?: SessionClearReason,
) => void;

export interface SessionStorageEventPayload {
  type: "stored" | "cleared";
  reason?: SessionClearReason;
  timestamp: number;
}

const listeners = new Set<SessionListener>();

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

function notifyListeners(session: ShaySession | null, reason?: SessionClearReason) {
  listeners.forEach((listener) => listener(session, reason));
}

export function didSessionChange(previous: ShaySession, current: ShaySession) {
  return previous.access_token !== current.access_token
    || previous.refresh_token !== current.refresh_token;
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
