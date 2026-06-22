"use client";
import { useCallback, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Zap } from "lucide-react";
import { useWorkspace } from "@/lib/workspace";
import { api } from "@/lib/api";
import { useJobPoller } from "./useJobPoller";
import { RestConfigForm } from "./RestConfigForm";
import type { RestPhase } from "./types";

export function RestTab() {
  const { workspaceId } = useWorkspace();
  const [url, setUrl] = useState("");
  const [authHeader, setAuthHeader] = useState("");
  const [authValue, setAuthValue] = useState("");
  const [recordPath, setRecordPath] = useState("");
  const [pageParam, setPageParam] = useState("");
  const [maxPages, setMaxPages] = useState("20");
  const [context, setContext] = useState("");
  const [phase, setPhase] = useState<RestPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<{ sample: unknown[]; count: number; inferred_type: string } | null>(null);
  const [ontologyType, setOntologyType] = useState("");
  const [ingestJobId, setIngestJobId] = useState<string | null>(null);

  const buildHeaders = () => authHeader && authValue ? { [authHeader]: authValue } : {};

  const preview = async () => {
    if (!url.trim()) return;
    setPhase("previewing"); setError(null);
    try {
      const r = await api.previewRestIngest({
        workspace_id: workspaceId, url: url.trim(), headers: buildHeaders(),
        record_path: recordPath || undefined, page_param: pageParam || undefined, context: context || undefined,
      });
      setPreviewData(r); if (!ontologyType && r.inferred_type) setOntologyType(r.inferred_type); setPhase("preview");
    } catch (e) { setError(e instanceof Error ? e.message : "Preview failed"); setPhase("error"); }
  };

  const onIngestDone = useCallback((ok: boolean) => {
    if (!ok) { setPhase("error"); setError("Ingest job failed"); return; }
    setPhase("done");
  }, []);
  useJobPoller(phase === "ingesting" ? ingestJobId : null, onIngestDone);

  const ingest = async () => {
    setPhase("ingesting"); setError(null);
    try {
      const r = await api.startRestIngest({
        workspace_id: workspaceId, url: url.trim(), headers: buildHeaders(),
        record_path: recordPath || undefined, page_param: pageParam || undefined,
        max_pages: parseInt(maxPages) || 20, ontology_type: ontologyType || undefined, context: context || undefined,
      });
      setIngestJobId(r.job_id);
    } catch (e) { setError(e instanceof Error ? e.message : "Ingest failed"); setPhase("error"); }
  };

  const reset = () => {
    setUrl(""); setPhase("idle"); setError(null); setPreviewData(null); setIngestJobId(null); setOntologyType("");
  };

  if (phase === "done") return (
    <div className="py-12 text-center animate-fade-in">
      <CheckCircle2 size={40} className="mx-auto mb-3 text-emerald-500" />
      <h3 className="text-lg font-semibold text-navy-900">REST API ingest complete</h3>
      <p className="mt-1 text-[13px] text-subtle">Records have been ingested into your knowledge graph.</p>
      <button type="button" onClick={reset}
        className="focus-ring mt-5 rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13px] font-medium text-navy-700 hover:bg-navy-50">
        Ingest another endpoint
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
      <RestConfigForm url={url} setUrl={setUrl} authHeader={authHeader} setAuthHeader={setAuthHeader}
        authValue={authValue} setAuthValue={setAuthValue} recordPath={recordPath} setRecordPath={setRecordPath}
        pageParam={pageParam} setPageParam={setPageParam} maxPages={maxPages} setMaxPages={setMaxPages}
        ontologyType={ontologyType} setOntologyType={setOntologyType} context={context} setContext={setContext}
        previewing={phase === "previewing"} onPreview={preview} />
      {phase === "preview" && previewData && (
        <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-semibold text-navy-900">Preview</h3>
            <span className="text-[11px] text-subtle">
              {previewData.count} record{previewData.count !== 1 ? "s" : ""} — type: <strong>{previewData.inferred_type}</strong>
            </span>
          </div>
          <div className="mb-4 max-h-40 overflow-auto rounded-lg border border-navy-100 bg-navy-950 p-3">
            <pre className="text-[11px] text-navy-200">{JSON.stringify(previewData.sample.slice(0, 3), null, 2)}</pre>
          </div>
          <div className="mb-4">
            <label className="mb-1 block text-[11px] font-medium text-navy-600">Entity type for all records</label>
            <input value={ontologyType} onChange={(e) => setOntologyType(e.target.value)}
              className="focus-ring w-full max-w-xs rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500" />
          </div>
          <button type="button" onClick={ingest}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700">
            <Zap size={13} /> Ingest to graph
          </button>
        </div>
      )}
      {phase === "ingesting" && (
        <div className="flex items-center gap-3 rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
          <Loader2 size={18} className="animate-spin text-steel-500" />
          <div>
            <p className="font-medium text-navy-900">Ingesting records…</p>
            <p className="text-[12px] text-subtle">This may take a minute for large datasets.</p>
          </div>
        </div>
      )}
    </div>
  );
}
