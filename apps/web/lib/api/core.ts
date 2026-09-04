import { createHttpStatusError, fetchWithShayAuth, readErrorDetail } from "../shay-session";

// Same-origin relative path. Next.js rewrites /api/* → FastAPI internally
// (see next.config.mjs). Works in dev (proxies to localhost:8088) and in
// production (proxies to api:8000) without any client-side knowledge.
export const BASE = "/api";

export type DataSourceDeleteResult = {
  status: string;
  source_key: string;
  asset_key?: string;
  catalog_rows_deleted: number;
  graph_sync: "complete" | "repair_required";
};

/** Throw on non-2xx; return parsed JSON otherwise. */
export async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetchWithShayAuth(`${BASE}${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw createHttpStatusError(res.status, res.statusText, detail);
  }
  return res.json() as Promise<T>;
}

export async function fetchBlob(path: string, init?: RequestInit): Promise<Blob> {
  const res = await fetchWithShayAuth(`${BASE}${path}`, init);
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw createHttpStatusError(res.status, res.statusText, detail);
  }
  return res.blob();
}
