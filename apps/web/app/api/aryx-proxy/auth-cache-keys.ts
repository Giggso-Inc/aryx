import { createHash } from "node:crypto";

export function cacheKeyForAuthorization(authorization: string) {
  return createHash("sha256").update(authorization).digest("hex");
}

export function cacheKeyForWorkspaceAuthorization(
  authorization: string,
  shayWorkspaceId: string,
) {
  return createHash("sha256")
    .update(`${authorization}:${shayWorkspaceId}`)
    .digest("hex");
}

export function isBearerAuthorizationHeader(value: string | null): value is string {
  return !!value && /^Bearer\s+\S+$/i.test(value.trim());
}
