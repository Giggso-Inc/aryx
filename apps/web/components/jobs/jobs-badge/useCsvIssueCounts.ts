import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * Open CSV issues per upload job (a skipped/failed file counts 1, a partly loaded file counts its open
 * rejected rows), so the collapsed job card can say "N CSV issues". One request for the whole panel.
 * `refreshKey` changes whenever the jobs list refreshes.
 */
export function useCsvIssueCounts(workspaceId: number, active: boolean, refreshKey: unknown): Record<string, number> {
  const [counts, setCounts] = useState<Record<string, number>>({});
  useEffect(() => {
    if (!active) return;
    let live = true;
    api.listCsvRuns(workspaceId)
      .then((runs) => {
        if (!live) return;
        const next: Record<string, number> = {};
        for (const r of runs) {
          if (r.state !== "open" || !r.job_id) continue;
          next[r.job_id] = (next[r.job_id] ?? 0) + (r.status !== "loaded" ? 1 : r.open_rejects);
        }
        setCounts(next);
      })
      // The endpoint is Oracle-only (501 elsewhere) — no counts is the right answer, not an error.
      .catch(() => { if (live) setCounts({}); });
    return () => { live = false; };
  }, [workspaceId, active, refreshKey]);
  return counts;
}
