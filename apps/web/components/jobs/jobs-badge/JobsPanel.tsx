import { AnimatePresence, motion } from "framer-motion";
import { FolderDown, X } from "lucide-react";
import { JobCard } from "./JobCard";
import { useCsvIssueCounts } from "./useCsvIssueCounts";
import type { JobRow } from "./types";

interface PanelProps {
  open: boolean;
  jobs: JobRow[];
  workspaceId: number;
  onClose: () => void;
  onRefresh: () => void;
}

/** Docked side panel. No backdrop — page stays interactive. */
export function JobsPanel({ open, jobs, workspaceId, onClose, onRefresh }: PanelProps) {
  // Re-fetch only when a job really changed (the jobs poll hands over a new array every time).
  const jobsSignature = jobs.map((j) => `${j.job_id}:${j.status}`).join("|");
  const issueCounts = useCsvIssueCounts(workspaceId, open, jobsSignature);
  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          initial={{ x: 480, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 480, opacity: 0 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          className="fixed right-0 top-16 z-30 flex h-[calc(100vh-4rem)] w-[460px] flex-col border-l border-navy-100 bg-white shadow-soft"
        >
          <header className="flex items-center justify-between border-b border-navy-100 px-5 py-3">
            <div className="flex items-center gap-2">
              <FolderDown size={16} className="text-steel-500" />
              <h2 className="font-display text-[1.05rem] text-navy-900">
                Ingest jobs
              </h2>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={onRefresh}
                className="focus-ring rounded-lg px-2 py-1 text-[11px] font-medium text-subtle hover:bg-navy-50"
              >
                Refresh
              </button>
              <button
                onClick={onClose}
                className="focus-ring rounded-lg p-1 text-subtle hover:bg-navy-50"
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>
          </header>
          <p className="border-b border-navy-100 px-5 py-2.5 text-[11px] text-subtle">
            Live status from <code className="rounded bg-navy-50 px-1 py-0.5 font-mono text-[10px] text-steel-600">/admin/jobs</code>{" "}
            · click a job for its event log.
          </p>
          <div className="flex-1 overflow-y-auto px-4 py-3">
            <ul className="space-y-2">
              {jobs.map((j) => (
                <JobCard key={j.job_id} job={j} workspaceId={workspaceId} onChanged={onRefresh}
                         issueCount={issueCounts[j.job_id] ?? 0} />
              ))}
            </ul>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
