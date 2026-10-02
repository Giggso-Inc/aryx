"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useWorkspace } from "@/lib/workspace";
import { api } from "@/lib/api";
import { useJobPoller } from "./useJobPoller";
import { DocsUploadStep } from "./DocsUploadStep";
import { DocsSummaryStep } from "./DocsSummaryStep";
import { ProgressCard } from "./docs-tab/ProgressCard";
import { clearDocsSession, loadDocsSession, saveDocsSession } from "./docs-tab/session-storage";
import type { DocPhase } from "./types";
import type { DiscoverySummary } from "@/lib/types";

interface DocsTabProps {
  restoreId?: string | null;
  restart?: boolean;
  onRestored?: () => void;
}

export function DocsTab({ restoreId, restart = false, onRestored }: DocsTabProps = {}) {
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

  useEffect(() => {
    if (!restoreId) return;
    api.getDiscoverySummary(restoreId, workspaceId)
      .then((s) => {
        setDiscoveryId(restoreId);
        setSummary(s);
        setApproved(new Set((s.types || []).map((t) => t.type)));
        setPhase("summary");
        onRestored?.();
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load discovery"));
  }, [restoreId, workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Rehydrate any in-progress job for this workspace on mount (page reload,
  // tab reopen after the poller's timers were suspended, etc). Skipped when
  // an explicit restoreId was passed in -- that's a deliberate resume of a
  // specific discovery (e.g. picked from a list) and takes priority over
  // whatever session happened to be sitting in localStorage.
  useEffect(() => {
    if (restoreId) return;
    const saved = loadDocsSession(workspaceId);
    if (!saved) return;
    setPhase(saved.phase);
    setReadJobId(saved.readJobId);
    setDiscoveryId(saved.discoveryId);
    setSummary(saved.summary);
    setApproved(new Set(saved.approved));
    setConfirmJobId(saved.confirmJobId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, restoreId]);

  const skipNextPersist = useRef(true);
  useEffect(() => {
    // Skip the render right after rehydration so it doesn't immediately
    // overwrite the just-loaded session with the pre-rehydration defaults.
    if (skipNextPersist.current) { skipNextPersist.current = false; return; }
    // "error" (including a job that turned out to be permanently gone —
    // see useJobPoller's 404 handling) must also clear the session, not
    // just idle/done — otherwise a dead job's stale entry lingers in
    // localStorage indefinitely instead of being cleaned up as soon as its
    // terminal state is known.
    if (phase === "idle" || phase === "done" || phase === "error") {
      clearDocsSession(workspaceId);
      return;
    }
    saveDocsSession(workspaceId, {
      phase, readJobId, discoveryId, summary, approved: [...approved], confirmJobId,
    });
  }, [workspaceId, phase, readJobId, discoveryId, summary, approved, confirmJobId]);

  const onReadDone = useCallback(async (ok: boolean) => {
    if (!ok || !discoveryId) { setPhase("error"); setError("Read job failed"); return; }
    try {
      const s = await api.getDiscoverySummary(discoveryId, workspaceId);
      setSummary(s); setApproved(new Set((s.types || []).map((t) => t.type))); setPhase("summary");
    } catch (e) { setError(e instanceof Error ? e.message : "Summary fetch failed"); setPhase("error"); }
  }, [discoveryId, workspaceId]);

  const onConfirmDone = useCallback((ok: boolean) => {
    if (!ok) { setPhase("error"); setError("Confirm job failed"); return; }
    setPhase("done");
  }, []);

  const readPoller = useJobPoller(phase === "reading" ? readJobId : null, onReadDone, workspaceId);
  const confirmPoller = useJobPoller(phase === "confirming" ? confirmJobId : null, onConfirmDone, workspaceId);

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
      const r = await api.confirmDiscovery(discoveryId, [...approved], approvedFiles, workspaceId, undefined, restart);
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
        <ProgressCard
          step={2}
          title="Reading & discovering entities…"
          pct={readPoller.pct}
          stage={readPoller.stage}
          fallbackStage="Processing…"
          barColor="bg-steel-500"
        />
      )}
      {(phase === "summary" || phase === "confirming") && summary && (
        <DocsSummaryStep summary={summary} approved={approved} onToggle={toggleType}
          confirming={phase === "confirming"} onConfirm={confirm} onReset={reset} />
      )}
      {phase === "confirming" && (
        <ProgressCard
          step={3}
          title="Ingesting to graph…"
          pct={confirmPoller.pct}
          stage={confirmPoller.stage}
          fallbackStage="Writing entities…"
          barColor="bg-emerald-500"
        />
      )}
    </div>
  );
}
