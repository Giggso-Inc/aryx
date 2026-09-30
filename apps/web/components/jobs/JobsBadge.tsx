"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { FolderDown, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { parseWorkspaceScope } from "@/lib/workspace-route";
import { JobsPanel } from "./jobs-badge/JobsPanel";
import { POLL_MS, RUNNING, type JobRow } from "./jobs-badge/types";

/** Header chip + dockable side panel for ingest jobs.
 *  Auto-opens on / and /model whenever any job is running so the user
 *  doesn't have to know to click. No backdrop — the panel coexists with
 *  the page so they can keep working. */
export function JobsBadge() {
  const { workspaceId, workspaces } = useWorkspace();
  const pathname = usePathname();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const refresh = useCallback(async () => {
    if (workspaceId <= 0 || workspaces.length === 0) {
      setJobs([]);
      return;
    }
    try {
      setJobs(await api.listJobs(workspaceId));
    } catch {
      setJobs([]);
    }
  }, [workspaceId, workspaces.length]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  // Auto-open on Ask + Model when something is running and user hasn't
  // dismissed the panel for this session.
  const running = jobs.filter((j) => RUNNING.has(j.status)).length;
  const workspaceScope = parseWorkspaceScope(pathname);
  const onAskOrModel = pathname === "/"
    || pathname?.startsWith("/model")
    || workspaceScope.section === "ask"
    || workspaceScope.section === "ontology";
  useEffect(() => {
    if (running > 0 && onAskOrModel && !dismissed) setOpen(true);
    if (running === 0) setDismissed(false);
  }, [running, onAskOrModel, dismissed]);

  if (jobs.length === 0) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={running > 0
          ? `${running} ingest job${running === 1 ? "" : "s"} running`
          : "Recent ingest jobs"}
        className="focus-ring relative inline-flex size-9 items-center justify-center rounded-lg text-navy-600 transition-colors hover:bg-navy-50 hover:text-navy-900"
      >
        {running > 0
          ? <Loader2 size={16} className="animate-spin text-steel-500" />
          : <FolderDown size={16} />}
        {running > 0 && (
          <span className="absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-steel-500 px-1 text-[10px] font-semibold text-white shadow-sm">
            {running}
          </span>
        )}
      </button>
      <JobsPanel
        open={open}
        jobs={jobs}
        workspaceId={workspaceId}
        onClose={() => { setOpen(false); setDismissed(true); }}
        onRefresh={refresh}
      />
    </>
  );
}
