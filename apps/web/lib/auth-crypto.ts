export function normalizeUrlSafeToken(token: string) {
  const normalized = token.replace(/-/g, "+").replace(/_/g, "/");
  const padding = "=".repeat((4 - (normalized.length % 4)) % 4);
  return normalized + padding;
}
