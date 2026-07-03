/** Format workspace names for display.
 *
 * The Shay bridge often stores names like "shay::My Workspace::2cac120e".
 * Users should see the friendly middle portion instead of the bridge prefix
 * and suffix.
 */
export function formatWorkspaceName(name?: string | null) {
  const raw = (name || "").trim();
  if (!raw) {
    return "Workspace";
  }

  const parts = raw.split("::").filter(Boolean);
  if (parts.length >= 3 && parts[0]?.toLowerCase() === "shay") {
    const suffix = parts[parts.length - 1];
    if (/^[a-f0-9]{6,}$/i.test(suffix)) {
      const friendly = parts.slice(1, -1).join("::").trim();
      if (friendly) {
        return friendly;
      }
    }
    return parts.slice(1).join("::").trim() || raw;
  }

  return raw;
}
