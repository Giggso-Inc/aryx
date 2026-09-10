import type { ShayDatasourceList } from "../shay-types";
import {
  createHttpStatusError,
  getStoredShaySession,
  readErrorDetail,
  refreshShayAccessToken,
} from "../shay-session";

export function resolvePlatformUrl(): string {
  if (typeof window !== "undefined" && window.location.origin) {
    return window.location.origin;
  }
  return "http://localhost:3000";
}

export function withBearerAuth(token?: string, init?: RequestInit): RequestInit | undefined {
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

export async function requestJSON<T>(
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
    const detail = await readErrorDetail(res);
    throw createHttpStatusError(res.status, res.statusText, detail);
  }
  return res.json() as Promise<T>;
}

export function query(params: Record<string, string | number | boolean | undefined | null>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const serialized = search.toString();
  return serialized ? `?${serialized}` : "";
}

type CachedEntry = {
  expiresAt: number;
  value: Promise<unknown>;
};

export const shayGetCache = new Map<string, CachedEntry>();

export function normalizeDatasourceList(list: ShayDatasourceList): ShayDatasourceList {
  const itemCount = Array.isArray(list.items) ? list.items.length : 0;
  const reportedTotal = typeof list.total === "number" && Number.isFinite(list.total)
    ? list.total
    : itemCount;
  return {
    ...list,
    total: Math.max(reportedTotal, itemCount),
  };
}

export function invalidateShayCache(prefix: string) {
  for (const key of shayGetCache.keys()) {
    if (key.startsWith(prefix)) {
      shayGetCache.delete(key);
    }
  }
}

export function cachedRequestJSON<T>(
  cacheKey: string,
  ttlMs: number,
  base: string,
  path: string,
  token?: string,
) {
  const now = Date.now();
  const cached = shayGetCache.get(cacheKey);
  if (cached && cached.expiresAt > now) {
    return cached.value as Promise<T>;
  }

  const nextValue = requestJSON<T>(base, path, undefined, token).catch((error) => {
    shayGetCache.delete(cacheKey);
    throw error;
  });
  shayGetCache.set(cacheKey, {
    expiresAt: now + ttlMs,
    value: nextValue,
  });
  return nextValue;
}
