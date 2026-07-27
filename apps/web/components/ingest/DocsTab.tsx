"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { useWorkspace } from "@/lib/workspace";
import { api } from "@/lib/api";
import { useJobPoller } from "./useJobPoller";
import { DocsUploadStep } from "./DocsUploadStep";
import { DocsSummaryStep } from "./DocsSummaryStep";
import type { DocPhase } from "./types";
import type { DiscoverySummary } from "@/lib/types";

const RESUMABLE_PHASES: DocPhase[] = ["reading", "summary", "confirming"];

type PersistedDocsSession = {
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
function _storageKey(workspaceId: number): string {
  return `aryx.docs.session.${workspaceId}`;
}

function _loadSession(workspaceId: number): PersistedDocsSession | null {
  try {
    const raw = localStorage.getItem(_storageKey(workspaceId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedDocsSession;
    if (!RESUMABLE_PHASES.includes(parsed.phase)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function _saveSession(workspaceId: number, session: PersistedDocsSession): void {
  try {
    localStorage.setItem(_storageKey(workspaceId), JSON.stringify(session));
  } catch { /* storage unavailable/full — resuming is best-effort */ }
}

function _clearSession(workspaceId: number): void {
  try {
    localStorage.removeItem(_storageKey(workspaceId));
  } catch { /* ignore */ }
}

export function DocsTab() {
  const { workspaceId } = useWorkspace();
  const [files, setFiles] = useState<File[]>([]);
  const [context, setContext] = useState("");
  const [phase, setPhase] = useState<DocPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [readJobId, setReadJobId] = useState<string | null>(null);
  const [discoveryId, setDiscoveryId] = useState<string | null>(null);
  const [summary, setSummary] = useState<DiscoverySummary | null>(null);
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [confirmJobId, setConfirmJobId] = useState<string | null>(null);

  // Rehydrate any in-progress job for this workspace on mount (page reload,
  // tab reopen after the poller's timers were suspended, etc).
  useEffect(() => {
    const saved = _loadSession(workspaceId);
    if (!saved) return;
    setPhase(saved.phase);
    setReadJobId(saved.readJobId);
    setDiscoveryId(saved.discoveryId);
    setSummary(saved.summary);
    setApproved(new Set(saved.approved));
    setConfirmJobId(saved.confirmJobId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  const skipNextPersist = useRef(true);
  useEffect(() => {
    // Skip the render right after rehydration so it doesn't immediately
    // overwrite the just-loaded session with the pre-rehydration defaults.
    if (skipNextPersist.current) { skipNextPersist.current = false; return; }
    if (phase === "idle" || phase === "done") { _clearSession(workspaceId); return; }
    _saveSession(workspaceId, {
      phase, readJobId, discoveryId, summary, approved: [...approved], confirmJobId,
    });
  }, [workspaceId, phase, readJobId, discoveryId, summary, approved, confirmJobId]);

  const onReadDone = useCallback(async (ok: boolean) => {
    if (!ok || !discoveryId) { setPhase("error"); setError("Read job failed"); return; }
    try {
      const s = await api.getDiscoverySummary(discoveryId);
      setSummary(s); setApproved(new Set((s.types || []).map((t) => t.type))); setPhase("summary");
    } catch (e) { setError(e instanceof Error ? e.message : "Summary fetch failed"); setPhase("error"); }
  }, [discoveryId]);

  const onConfirmDone = useCallback((ok: boolean) => {
    if (!ok) { setPhase("error"); setError("Confirm job failed"); return; }
    setPhase("done");
  }, []);

  const readPoller = useJobPoller(phase === "reading" ? readJobId : null, onReadDone);
  const confirmPoller = useJobPoller(phase === "confirming" ? confirmJobId : null, onConfirmDone);

  const start = async () => {
    if (!files.length) return;
    setPhase("reading"); setError(null);
    try {
      const r = await api.readDocs(workspaceId, files, context);
      setDiscoveryId(r.discovery_id); setReadJobId(r.discovery_id);
    } catch (e) { setError(e instanceof Error ? e.message : "Upload failed"); setPhase("error"); }
  };

  const confirm = async () => {
    if (!discoveryId) return;
    const approvedFiles = (summary?.files ?? []).map((f) => f.filename);
    if (approved.size === 0 && approvedFiles.length === 0) return;
    setPhase("confirming"); setError(null);
    try {
      const r = await api.confirmDiscovery(discoveryId, [...approved], approvedFiles);
      setConfirmJobId(r.job_id);
    } catch (e) { setError(e instanceof Error ? e.message : "Confirm failed"); setPhase("error"); }
  };

  const reset = () => {
    setFiles([]); setContext(""); setPhase("idle"); setError(null);
    setReadJobId(null); setDiscoveryId(null); setSummary(null);
    setApproved(new Set()); setConfirmJobId(null);
  };

  const toggleType = (type: string) => {
    setApproved((prev) => { const next = new Set(prev); if (next.has(type)) next.delete(type); else next.add(type); return next; });
  };

  if (phase === "done") return (
    <div className="py-12 text-center animate-fade-in">
      <CheckCircle2 size={40} className="mx-auto mb-3 text-emerald-500" />
      <h3 className="text-lg font-semibold text-navy-900">Ingest complete</h3>
      <p className="mt-1 text-[13px] text-subtle">Entities are now in your knowledge graph.</p>
      <button type="button" onClick={reset}
        className="focus-ring mt-5 rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13px] font-medium text-navy-700 hover:bg-navy-50">
        Ingest more documents
      </button>
    </div>
  );

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
          <button type="button" onClick={reset} className="ml-auto underline">Reset</button>
        </div>
      )}
      <DocsUploadStep files={files} setFiles={setFiles} context={context} setContext={setContext}
        started={phase !== "idle"} onStart={start} />
      {phase === "reading" && (
        <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
          <div className="mb-3 flex items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-full bg-navy-800 text-[11px] font-bold text-white">2</span>
            <h3 className="font-semibold text-navy-900">Reading &amp; discovering entities…</h3>
            <Loader2 size={14} className="animate-spin text-steel-500 ml-auto" />
          </div>
          {readPoller.pct != null && (
            <div className="mb-2 h-2 w-full overflow-hidden rounded-full bg-navy-100">
              <div className="h-full rounded-full bg-steel-500 transition-all duration-500" style={{ width: `${readPoller.pct}%` }} />
            </div>
          )}
          <p className="text-[12px] text-subtle">{readPoller.stage || "Processing…"}</p>
        </div>
      )}
      {(phase === "summary" || phase === "confirming") && summary && (
        <DocsSummaryStep summary={summary} approved={approved} onToggle={toggleType}
          confirming={phase === "confirming"} onConfirm={confirm} onReset={reset} />
      )}
      {phase === "confirming" && (
        <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
          <div className="mb-3 flex items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-full bg-navy-800 text-[11px] font-bold text-white">3</span>
            <h3 className="font-semibold text-navy-900">Ingesting to graph…</h3>
            <Loader2 size={14} className="animate-spin text-steel-500 ml-auto" />
          </div>
          {confirmPoller.pct != null && (
            <div className="mb-2 h-2 w-full overflow-hidden rounded-full bg-navy-100">
              <div className="h-full rounded-full bg-emerald-500 transition-all duration-500" style={{ width: `${confirmPoller.pct}%` }} />
            </div>
          )}
          <p className="text-[12px] text-subtle">{confirmPoller.stage || "Writing entities…"}</p>
        </div>
      )}
    </div>
  );
}
