import { useState } from "react";
import {
  AlertTriangle, Ban, CheckCircle2, ChevronDown, ChevronRight, FolderDown, Loader2, RotateCcw,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { CsvIssues } from "./CsvIssues";
import { EventLog } from "./EventLog";
import { RUNNING, type JobRow } from "./types";

export function JobCard(
  { job, workspaceId, onChanged, issueCount = 0 }:
  { job: JobRow; workspaceId: number; onChanged: () => void; issueCount?: number },
) {
  const [open, setOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const isRunning = RUNNING.has(job.status);
  const isFailed = job.status === "failed" || job.status === "cancelled"
    || !!job.error;
  const isDone = job.status === "complete";

  const cancel = async () => {
    setCancelling(true);
    try {
      await api.cancelJob(job.job_id, workspaceId);
      onChanged();
    } finally {
      setCancelling(false);
    }
  };
  return (
    <li className={cn(
      "rounded-xl border bg-white shadow-soft",
      isFailed ? "border-rose-200" :
      isDone ? "border-emerald-200" : "border-navy-100",
    )}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full p-3.5 text-left focus-ring rounded-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {open ? <ChevronDown size={12} className="text-subtle" />
                    : <ChevronRight size={12} className="text-subtle" />}
              <StatusIcon running={isRunning} done={isDone} failed={isFailed} />
              <span className="truncate text-[13px] font-semibold text-navy-900">
                {job.source_dataset || "upload"}
              </span>
            </div>
            <div className="mt-1 ml-5 font-mono text-[10px] text-subtle">
              {job.source_system} · {job.job_id.slice(0, 12)}…
            </div>
          </div>
          <span className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            isRunning && "bg-steel-500/15 text-steel-600",
            isDone && "bg-emerald-50 text-emerald-700",
            isFailed && "bg-rose-50 text-rose-700",
            !isRunning && !isDone && !isFailed && "bg-navy-50 text-navy-700",
          )}>
            {job.status}
          </span>
        </div>
        {(job.stage || job.pct !== null) && (
          <div className="ml-5 mt-2.5">
            <div className="flex items-center justify-between text-[11px] text-subtle">
              <span className="font-mono">{job.stage || "queued"}</span>
              <span className="font-mono">{job.pct ?? 0}%</span>
            </div>
            <div className="mt-1 h-1.5 w-full rounded-full bg-navy-100">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  isFailed ? "bg-rose-400" : "bg-steel-500",
                )}
                style={{ width: `${Math.min(job.pct ?? 0, 100)}%` }}
              />
            </div>
          </div>
        )}
        {issueCount > 0 && (
          <div className="ml-5 mt-1.5 inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[10.5px] font-medium text-amber-800">
            <AlertTriangle size={10} /> {issueCount} CSV issue{issueCount === 1 ? "" : "s"} — open for details
          </div>
        )}
        {job.detail && (
          <div className="ml-5 mt-1.5 truncate text-[11px] text-navy-700">
            {job.detail}
          </div>
        )}
        {job.error && (
          <div className="ml-5 mt-2 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-700">
            {job.error}
          </div>
        )}
      </button>

      {(isRunning || isFailed) && (
        <div className="flex items-center gap-2 border-t border-navy-100 px-3.5 py-2">
          {isRunning && (
            <button
              type="button"
              onClick={cancel}
              disabled={cancelling}
              className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-2.5 py-1 text-[11px] font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50"
            >
              {cancelling ? <Loader2 size={11} className="animate-spin" />
                           : <Ban size={11} />}
              Cancel job
            </button>
          )}
          {isFailed && (
            <a
              href="/start"
              className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-navy-700"
            >
              <RotateCcw size={11} /> Retry — re-onboard
            </a>
          )}
          <span className="text-[10px] text-subtle">
            {isRunning
              ? "Stuck? Cancel frees the workspace; re-upload to retry."
              : "Re-run the wizard to re-ingest. Smaller batches help."}
          </span>
        </div>
      )}

      {open && <EventLog jobId={job.job_id} workspaceId={workspaceId} live={isRunning} />}
      {open && !isRunning && (
        <CsvIssues jobId={job.job_id} workspaceId={workspaceId} onChanged={onChanged} />
      )}
    </li>
  );
}

function StatusIcon({
  running, done, failed,
}: { running: boolean; done: boolean; failed: boolean }) {
  if (failed) return <AlertTriangle size={13} className="text-rose-500" />;
  if (done) return <CheckCircle2 size={13} className="text-emerald-500" />;
  if (running) return <Loader2 size={13} className="animate-spin text-steel-500" />;
  return <FolderDown size={13} className="text-subtle" />;
}
