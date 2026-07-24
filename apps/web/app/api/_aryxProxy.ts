import { createHash } from "node:crypto";

import { NextRequest, NextResponse } from "next/server";

const SHAY_PROFILE_PATH = "/api/v1/user-auth/profile";
const SHAY_AUTH_CACHE_TTL_MS = 30_000;
const SHAY_WORKSPACE_AUTH_CACHE_TTL_MS = 30_000;
const shayAuthCache = new Map<string, number>();
const shayWorkspaceAuthCache = new Map<string, number>();

export function aryxTarget() {
  return process.env.NODE_ENV === "development"
    ? "http://localhost:8088"
    : process.env.ARYX_API_URL_INTERNAL ?? "http://api:8000";
}

export function shayTarget() {
  return process.env.NODE_ENV === "development"
    ? "http://localhost:8090"
    : process.env.SHAY_API_URL_INTERNAL ?? "http://shay-api:8000";
}

export function requireInternalApiKey(): string | NextResponse {
  const internalApiKey = process.env.ARYX_INTERNAL_API_KEY;
  if (!internalApiKey) {
    return NextResponse.json(
      { detail: "ARYX_INTERNAL_API_KEY is not configured" },
      { status: 500 },
    );
  }
  return internalApiKey;
}

function cacheKeyForAuthorization(authorization: string) {
  return createHash("sha256").update(authorization).digest("hex");
}

function cacheKeyForWorkspaceAuthorization(
  authorization: string,
  shayWorkspaceId: string,
) {
  return createHash("sha256")
    .update(`${authorization}:${shayWorkspaceId}`)
    .digest("hex");
}

function isBearerAuthorizationHeader(value: string | null): value is string {
  return !!value && /^Bearer\s+\S+$/i.test(value.trim());
}

export async function requireShayBearerAuth(
  req: NextRequest,
): Promise<string | NextResponse> {
  const authorization = req.headers.get("authorization");
  if (!isBearerAuthorizationHeader(authorization)) {
    return NextResponse.json(
      { detail: "missing or invalid bearer token" },
      { status: 401 },
    );
  }

  const normalizedAuthorization = authorization.trim();
  const cacheKey = cacheKeyForAuthorization(normalizedAuthorization);
  const now = Date.now();
  const cachedUntil = shayAuthCache.get(cacheKey);
  if (cachedUntil && cachedUntil > now) {
    return normalizedAuthorization;
  }

  try {
    const response = await fetch(`${shayTarget()}${SHAY_PROFILE_PATH}`, {
      method: "GET",
      headers: {
        Authorization: normalizedAuthorization,
      },
      cache: "no-store",
    });
    if (!response.ok) {
      shayAuthCache.delete(cacheKey);
      return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
    }
    shayAuthCache.set(cacheKey, now + SHAY_AUTH_CACHE_TTL_MS);
    return normalizedAuthorization;
  } catch {
    return NextResponse.json(
      { detail: "Unable to validate Shay session" },
      { status: 502 },
    );
  }
}

export async function requireShayWorkspaceAccess(
  req: NextRequest,
  shayWorkspaceId: string | null | undefined,
): Promise<string | NextResponse> {
  if (!shayWorkspaceId) {
    return NextResponse.json(
      { detail: "shay_workspace_id is required" },
      { status: 422 },
    );
  }

  const auth = await requireShayBearerAuth(req);
  if (auth instanceof NextResponse) {
    return auth;
  }

  const cacheKey = cacheKeyForWorkspaceAuthorization(auth, shayWorkspaceId);
  const now = Date.now();
  const cachedUntil = shayWorkspaceAuthCache.get(cacheKey);
  if (cachedUntil && cachedUntil > now) {
    return auth;
  }

  try {
    const response = await fetch(
      `${shayTarget()}/api/v1/workspaces/${encodeURIComponent(shayWorkspaceId)}`,
      {
        method: "GET",
        headers: { Authorization: auth },
        cache: "no-store",
      },
    );
    if (!response.ok) {
      shayWorkspaceAuthCache.delete(cacheKey);
      return NextResponse.json(
        { detail: "Forbidden for this Shay workspace" },
        { status: response.status === 401 ? 401 : 403 },
      );
    }
    shayWorkspaceAuthCache.set(
      cacheKey,
      now + SHAY_WORKSPACE_AUTH_CACHE_TTL_MS,
    );
    return auth;
  } catch {
    return NextResponse.json(
      { detail: "Unable to validate Shay workspace access" },
      { status: 502 },
    );
  }
}

export function buildAryxForwardHeaders(
  req: NextRequest,
  internalApiKey: string,
) {
  const headers = new Headers({
    "x-aryx-api-key": internalApiKey,
  });
  const contentType = req.headers.get("Content-Type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  return headers;
}
