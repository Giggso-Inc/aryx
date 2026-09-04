import type { DiscoverySummary } from "@/lib/types";
import type { DocPhase } from "../types";

export const RESUMABLE_PHASES: DocPhase[] = ["reading", "summary", "confirming"];

export type PersistedDocsSession = {
  phase: DocPhase;
  readJobId: string | null;
  discoveryId: string | null;
  summary: DiscoverySummary | null;
  approved: string[];
  confirmJobId: string | null;
};

// A read/confirm job on a large (1000+ page) document can run for hours —
// far longer than a single browser tab is reliably alive for (reloads,
// crashes, accidental closes). Without this, phase/discoveryId/job ids were
// pure in-memory React state: any interruption lost track of an
// in-progress job that was still running server-side, and the only way
// back in was to re-upload from scratch. Persisting to localStorage and
// rehydrating on mount lets a reload pick the same job back up.
function storageKey(workspaceId: number): string {
  return `aryx.docs.session.${workspaceId}`;
}

export function loadDocsSession(workspaceId: number): PersistedDocsSession | null {
  try {
    const raw = localStorage.getItem(storageKey(workspaceId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedDocsSession;
    if (!RESUMABLE_PHASES.includes(parsed.phase)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveDocsSession(workspaceId: number, session: PersistedDocsSession): void {
  try {
    localStorage.setItem(storageKey(workspaceId), JSON.stringify(session));
  } catch { /* storage unavailable/full — resuming is best-effort */ }
}

export function clearDocsSession(workspaceId: number): void {
  try {
    localStorage.removeItem(storageKey(workspaceId));
  } catch { /* ignore */ }
}
