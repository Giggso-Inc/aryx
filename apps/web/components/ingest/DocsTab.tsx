"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, FileText, Loader2, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { DocsUploadStep } from "./DocsUploadStep";
import { DocsSummaryStep, fileKey, typeKey } from "./DocsSummaryStep";
import { useJobPoller } from "./useJobPoller";
import type { DiscoverySummary, DocPhase, DocsSessionState } from "./types";

const storageKeyFor = (workspaceId: number) => `aryx.docs.session.${workspaceId}`;

/** The one functional ingest tab: upload → read (discover) → approve →
 *  confirm (ingest) → done. Session state survives reload/navigation because
 *  a 1000+-page PDF read can take a long time. */
export function DocsTab() {
  const { workspaceId } = useWorkspace();
  const storageKey = storageKeyFor(workspaceId);

  const [phase, setPhase] = useState<DocPhase>("idle");
  const [files, setFiles] = useState<File[]>([]);
  const [context, setContext] = useState("");
  const [discoveryId, setDiscoveryId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [summary, setSummary] = useState<DiscoverySummary | null>(null);
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // ── Rehydrate an in-progress session on mount / workspace switch ──────
  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = localStorage.getItem(storageKeyFor(workspaceId));
    if (!raw) return;
    try {
      const saved = JSON.parse(raw) as DocsSessionState;
      const approvedSet = new Set(saved.approved || []);
      if (saved.phase === "reading" && saved.discoveryId) {
        setDiscoveryId(saved.discoveryId);
        setApproved(approvedSet);
        setPhase("reading");
      } else if (saved.phase === "summary" && saved.discoveryId) {
        setDiscoveryId(saved.discoveryId);
        setApproved(approvedSet);
        api.getDiscoverySummary(saved.discoveryId)
          .then((s) => { setSummary(s); setPhase("summary"); })
          .catch(() => {
            setErrorMsg("Couldn't reload the discovery summary.");
            setPhase("error");
          });
      } else if (saved.phase === "confirming" && saved.jobId) {
        setDiscoveryId(saved.discoveryId);
        setJobId(saved.jobId);
        setApproved(approvedSet);
        setPhase("confirming");
      }
    } catch {
      // Corrupt/old shape — ignore and start fresh.
    }
    // Only on mount / workspace switch, not on every local state change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  // ── Persist in-progress state; clear on terminal states ───────────────
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (phase === "idle" || phase === "done" || phase === "error") {
      localStorage.removeItem(storageKey);
      return;
    }
    const state: DocsSessionState = {
      phase, discoveryId, jobId, approved: Array.from(approved),
    };
    localStorage.setItem(storageKey, JSON.stringify(state));
  }, [phase, discoveryId, jobId, approved, storageKey]);

  const handleReadDone = async (ok: boolean) => {
    if (!discoveryId) return;
    if (!ok) {
      setErrorMsg("Reading the uploaded files failed.");
      setPhase("error");
      return;
    }
    try {
      const s = await api.getDiscoverySummary(discoveryId);
      setSummary(s);
      setPhase("summary");
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Failed to load the summary.");
      setPhase("error");
    }
  };

  const handleConfirmDone = (ok: boolean) => {
    if (!ok) setErrorMsg("Ingest failed — the job did not complete.");
    setPhase(ok ? "done" : "error");
  };

  const readPoller = useJobPoller(
    phase === "reading" ? discoveryId : null, handleReadDone,
  );
  const confirmPoller = useJobPoller(
    phase === "confirming" ? jobId : null, handleConfirmDone,
  );

  const startRead = async () => {
    setPhase("uploading");
    setErrorMsg(null);
    try {
      const r = await api.readDocs(files, context, workspaceId);
      setDiscoveryId(r.discovery_id);
      setPhase("reading");
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Upload failed.");
      setPhase("error");
    }
  };

  const toggleApproved = (key: string) => {
    setApproved((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const confirm = async () => {
    if (!discoveryId) return;
    setPhase("confirming");
    setErrorMsg(null);
    const approvedTypes = Array.from(approved)
      .filter((k) => k.startsWith("t:")).map((k) => k.slice(2));
    const approvedFiles = Array.from(approved)
      .filter((k) => k.startsWith("f:")).map((k) => k.slice(2));
    try {
      const r = await api.confirmDiscovery(discoveryId, approvedTypes, approvedFiles);
      setJobId(r.job_id);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Confirm failed.");
      setPhase("error");
    }
  };

  const resetAll = () => {
    setPhase("idle");
    setFiles([]);
    setContext("");
    setDiscoveryId(null);
    setJobId(null);
    setSummary(null);
    setApproved(new Set());
    setErrorMsg(null);
    if (typeof window !== "undefined") localStorage.removeItem(storageKey);
  };

  return (
    <div className="flex flex-col items-center px-6 py-10">
      {(phase === "idle" || phase === "uploading") && (
        <DocsUploadStep
          files={files} setFiles={setFiles}
          context={context} setContext={setContext}
          started={phase === "uploading"}
          onStart={startRead}
        />
      )}

      {phase === "reading" && (
        <ProgressPanel
          icon={<FileText size={20} className="text-steel-600" />}
          title="Reading your documents…"
          detail={readPoller.stage || "Queued"}
          pct={readPoller.pct}
        />
      )}

      {phase === "summary" && summary && (
        <DocsSummaryStep
          summary={summary}
          approved={approved}
          onToggle={toggleApproved}
          confirming={false}
          onConfirm={confirm}
          onReset={resetAll}
        />
      )}

      {phase === "confirming" && (
        <ProgressPanel
          icon={<Loader2 size={20} className="animate-spin text-steel-600" />}
          title="Ingesting approved data…"
          detail={confirmPoller.stage || "Queued"}
          pct={confirmPoller.pct}
        />
      )}

      {phase === "done" && (
        <div className="w-full max-w-2xl rounded-2xl border border-emerald-200 bg-emerald-50/60 p-6 text-center">
          <CheckCircle2 size={28} className="mx-auto text-emerald-600" />
          <div className="mt-2 text-[15px] font-semibold text-navy-900">
            Ingest complete
          </div>
          <p className="mt-1 text-[13px] text-subtle">
            Your approved documents have been added to the graph.
          </p>
          <button
            type="button"
            onClick={resetAll}
            className="focus-ring mt-4 inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-3.5 py-1.5 text-[12px] font-medium text-navy-700 hover:bg-navy-50"
          >
            <RotateCcw size={12} /> Ingest more documents
          </button>
        </div>
      )}

      {phase === "error" && (
        <div className="w-full max-w-2xl rounded-2xl border border-rose-200 bg-rose-50/60 p-6 text-center">
          <AlertTriangle size={28} className="mx-auto text-rose-600" />
          <div className="mt-2 text-[15px] font-semibold text-navy-900">
            Something went wrong
          </div>
          <p className="mt-1 text-[13px] text-rose-700">
            {errorMsg || "The job did not complete."}
          </p>
          <button
            type="button"
            onClick={resetAll}
            className="focus-ring mt-4 inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-3.5 py-1.5 text-[12px] font-medium text-navy-700 hover:bg-navy-50"
          >
            <RotateCcw size={12} /> Start over
          </button>
        </div>
      )}
    </div>
  );
}

function ProgressPanel({
  icon, title, detail, pct,
}: { icon: React.ReactNode; title: string; detail: string; pct: number | null }) {
  return (
    <div className="w-full max-w-2xl rounded-2xl border border-navy-100 bg-white p-6">
      <div className="flex items-center gap-2.5">
        {icon}
        <span className="text-[14px] font-semibold text-navy-900">{title}</span>
      </div>
      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-navy-50">
        <div
          className="h-full rounded-full bg-steel-500 transition-all"
          style={{ width: `${pct ?? 8}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] uppercase tracking-wider text-subtle">
        <span>{detail}</span>
        {pct !== null && <span className="font-mono text-navy-700">{pct}%</span>}
      </div>
      <p className="mt-3 text-[12px] text-subtle">
        You can leave this page and come back — progress is saved.
      </p>
    </div>
  );
}

// Re-exported for tests / potential external key building.
export { typeKey, fileKey };
